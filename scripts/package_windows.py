"""Windows packaging: npm run package:win:x64 / package:win:arm64.

ARM64 requires native Python 3.14 and Visual Studio C++ ARM64 tools + Windows SDK.
sqlite-vec 0.1.9 is rebuilt from its pinned upstream source, retaining its Python
wrapper/license from the hash-verified upstream wheel. No dependency is skipped.
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VEC_COMMIT = "e9f598abfa0c06b328d8fe5da9c3760cce74be10"  # upstream v0.1.9
MACHINES = {"arm64": 0xAA64, "x64": 0x8664}


def run(args, *, cwd=ROOT, capture=False, env=None):
    print("\n> " + subprocess.list2cmdline([str(arg) for arg in args]), flush=True)
    return subprocess.run(
        [str(arg) for arg in args], cwd=cwd, env=env, check=True,
        text=True, encoding="utf-8", errors="replace", capture_output=capture,
    ).stdout


def download(url):
    print(f"下载 {url}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DocuMate-build"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def upstream_file(name):
    url = f"https://api.github.com/repos/asg017/sqlite-vec/contents/{name}?ref={VEC_COMMIT}"
    entry = json.loads(download(url))
    data = base64.b64decode(entry["content"])
    digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if digest != entry["sha"]:
        raise RuntimeError(f"源码校验失败：{name}")
    return data


def patch_arm_popcount(source):
    # Same correctness fix as upstream PR #271: preserve the upper 32 bits.
    old = "static unsigned int __builtin_popcountl(unsigned int x)"
    if source.count(old) != 1:
        raise RuntimeError("sqlite-vec 源码与已审核的 ARM64 补丁不匹配")
    return source.replace(old, "static unsigned int __builtin_popcountl(u64 x)")


def check_pe(filename, arch):
    with Path(filename).open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError(f"不是 Windows 二进制：{filename}")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError(f"无效 PE 文件：{filename}")
        machine = struct.unpack("<H", stream.read(2))[0]
    if machine != MACHINES[arch]:
        raise RuntimeError(f"{filename} 架构不匹配，要求 {arch}，实际 0x{machine:04x}")


def arm_compiler_environment():
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise RuntimeError("请先安装 Visual Studio Build Tools：C++ ARM64/ARM64EC 工具和 Windows SDK。")
    installation = run(
        [vswhere, "-latest", "-products", "*", "-requires",
         "Microsoft.VisualStudio.Component.VC.Tools.ARM64", "-property", "installationPath"],
        capture=True,
    ).strip()
    if not installation:
        raise RuntimeError("未找到 MSVC ARM64 工具。请在 Visual Studio Installer 中添加 C++ ARM64/ARM64EC 工具和 Windows SDK。")
    vcvars = Path(installation) / "VC/Auxiliary/Build/vcvarsall.bat"
    # x64-hosted compiler also runs under Windows ARM emulation.
    # cmd.exe needs shell quoting, not list2cmdline's C-runtime quote escaping.
    command = f'cmd.exe /d /s /c "call "{vcvars}" amd64_arm64 && set"'
    print("\n> " + command, flush=True)
    completed = subprocess.run(
        command, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = "\n".join(filter(None, [completed.stdout.strip(), completed.stderr.strip()]))
        raise RuntimeError(f"ARM64 编译环境初始化失败：\n{detail or completed.returncode}")
    output = completed.stdout
    env = os.environ.copy()
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            env[key.upper()] = value
    return env


def make_arm_wheel(original, dll, destination):
    with zipfile.ZipFile(io.BytesIO(original)) as wheel:
        files = {name: wheel.read(name) for name in wheel.namelist() if not name.endswith("/")}
    dist_info = "sqlite_vec-0.1.9.dist-info"
    files["sqlite_vec/vec0.dll"] = dll
    files[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: documate-arm64-build\n"
        "Root-Is-Purelib: false\nTag: py3-none-win_arm64\n"
    ).encode()
    record = f"{dist_info}/RECORD"
    files.pop(record, None)
    rows = io.StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    for name, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow([name, f"sha256={digest}", len(data)])
    writer.writerow([record, "", ""])
    files[record] = rows.getvalue().encode()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as wheel:
        for name, data in files.items():
            wheel.writestr(name, data)


def build_sqlite_vec(work, env):
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(p for p in lock["package"] if p["name"] == "sqlite-vec")
    if package["version"] != "0.1.9":
        raise RuntimeError("sqlite-vec 版本已变化，需重新审核 ARM64 源码适配")
    upstream_wheel = next(w for w in package["wheels"] if w["url"].endswith("win_amd64.whl"))
    original = download(upstream_wheel["url"])
    if "sha256:" + hashlib.sha256(original).hexdigest() != upstream_wheel["hash"]:
        raise RuntimeError("sqlite-vec 上游 wheel 校验失败")
    work.mkdir(parents=True, exist_ok=True)
    source = patch_arm_popcount(upstream_file("sqlite-vec.c").decode())
    (work / "sqlite-vec.c").write_text(source, encoding="utf-8")
    header = upstream_file("sqlite-vec.h.tmpl").decode()
    for key, value in {"VERSION": "0.1.9", "VERSION_MAJOR": "0", "VERSION_MINOR": "1",
                       "VERSION_PATCH": "9", "DATE": "2026-03-31", "SOURCE": VEC_COMMIT}.items():
        header = header.replace("${" + key + "}", value)
    if "${" in header:
        raise RuntimeError("sqlite-vec 头文件存在未替换的变量")
    (work / "sqlite-vec.h").write_text(header, encoding="utf-8")
    # Header version used by the upstream v0.1.9 release workflow.
    archive = download("https://www.sqlite.org/2024/sqlite-amalgamation-3450300.zip")
    with zipfile.ZipFile(io.BytesIO(archive)) as files:
        for name in ("sqlite3.h", "sqlite3ext.h"):
            (work / name).write_bytes(files.read(f"sqlite-amalgamation-3450300/{name}"))
    compiler = shutil.which("cl.exe", path=env.get("PATH"))
    if not compiler:
        raise RuntimeError("ARM64 编译环境中找不到 cl.exe")
    run([compiler, "/nologo", "/O2", "/LD", "/I.", "sqlite-vec.c", "/Fevec0.dll"], cwd=work, env=env)
    check_pe(work / "vec0.dll", "arm64")
    destination = work / "sqlite_vec-0.1.9-py3-none-win_arm64.whl"
    make_arm_wheel(original, (work / "vec0.dll").read_bytes(), destination)
    return destination


SMOKE_TEST = """
import sqlite3, sqlite_vec
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.base import empty_checkpoint
conn = sqlite3.connect(':memory:')
conn.enable_load_extension(True)
sqlite_vec.load(conn)
assert conn.execute('select vec_version()').fetchone()[0] == 'v0.1.9'
assert conn.execute('select vec_distance_hamming(vec_bit(?), vec_bit(?))',
                    (bytes(8), bytes([0,0,0,0,255,255,255,255]))).fetchone()[0] == 32
saver = SqliteSaver(conn)
checkpoint = empty_checkpoint()
config = saver.put({'configurable': {'thread_id': 'build-smoke', 'checkpoint_ns': ''}},
                   checkpoint, {'source': 'input', 'step': -1, 'parents': {}}, {})
assert saver.get_tuple(config).checkpoint['id'] == checkpoint['id']
print('SQLite extension and checkpoint smoke tests passed')
"""


def builder_config(package, arch, backend):
    config = dict(package["build"])
    config["extends"] = None
    config["directories"] = {"output": f"release/windows-{arch}"}
    config["extraResources"] = [{"from": str(backend), "to": "backend/documate-backend"}]
    config["win"] = {**config["win"], "target": [{"target": "nsis", "arch": [arch]}]}
    config["win"]["publish"] = [
        {**provider, "url": provider["url"].replace("${arch}", arch)}
        for provider in config["win"]["publish"]
    ]
    return config


def check_backend(executable):
    with tempfile.TemporaryDirectory(prefix="documate-build-smoke-") as directory:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {**os.environ, "DOCUMATE_BACKEND_HOST": "127.0.0.1",
               "DOCUMATE_BACKEND_PORT": str(port), "DOCUMATE_DATA_DIR": directory,
               "DOCUMATE_DEFAULT_WORKSPACE": directory,
               "DOCUMATE_APP_ENV": str(Path(directory) / ".env"),
               "PYTHON_DOTENV_DISABLED": "1"}
        env.pop("DOCUMATE_PARENT_PID", None)
        log_path = Path(directory) / "backend.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen([str(executable)], cwd=directory, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(120):
                    if process.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ready", timeout=1) as response:
                            if json.load(response).get("status") == "ready":
                                print("Windows 后端启动检查通过", flush=True)
                                return
                    except OSError:
                        pass
                    time.sleep(0.5)
                raise RuntimeError("打包后的后端未就绪：\n" + log_path.read_text(encoding="utf-8", errors="replace")[-6000:])
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arch", choices=("x64", "arm64"))
    args = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("请在 Windows 虚拟机中执行此命令")
    if args.arch == "arm64" and sysconfig.get_platform() != "win-arm64":
        raise RuntimeError("ARM64 打包需要原生 ARM64 Python 3.14；请检查 py -3.14 的架构")
    node = os.environ.get("npm_node_execpath") or shutil.which("node")
    npm = os.environ.get("npm_execpath")
    if not node or not npm:
        raise RuntimeError("请通过 npm.cmd run package:win:" + args.arch + " 执行")
    env = arm_compiler_environment() if args.arch == "arm64" else os.environ.copy()
    uv = [sys.executable, "-m", "uv"]
    run([*uv, "--version"])
    work = ROOT / "build/backend" / ("windows-" + args.arch)
    work.mkdir(parents=True, exist_ok=True)
    wheel = build_sqlite_vec(work / "sqlite-vec", env) if args.arch == "arm64" else None
    interpreter = sys.executable if args.arch == "arm64" else "cpython-3.14-windows-x86_64-none"
    venv = work / "venv"
    python = venv / "Scripts/python.exe"
    if not python.exists():
        run([*uv, "venv", "--python", interpreter, venv])
    check_pe(python, args.arch)
    requirements = work / "requirements.txt"
    export = [*uv, "export", "--frozen", "--no-emit-project", "--no-hashes", "--output-file", requirements]
    if wheel:
        export += ["--no-emit-package", "sqlite-vec"]
    run(export, capture=True)
    install = [*uv, "pip", "install", "--python", python, "--no-deps", "-r", requirements]
    if wheel:
        install.append(wheel)
    run(install, env=env)
    run([*uv, "pip", "check", "--python", python])
    run([python, "-c", SMOKE_TEST])
    run([node, npm, "run", "build"])
    dist = work / "dist"
    # Keep the shared spec unchanged; collect the extension DLL in Windows packages.
    spec = (ROOT / "documate-backend.spec").read_text(encoding="utf-8")
    if "ROOT = Path(SPECPATH)" not in spec or '    "docx",' not in spec:
        raise RuntimeError("PyInstaller spec 已变化，请更新 Windows 构建脚本")
    spec = spec.replace("ROOT = Path(SPECPATH)", f"ROOT = Path({str(ROOT)!r})")
    spec = spec.replace('    "docx",', '    "sqlite_vec",\n    "docx",')
    spec_path = work / "documate-backend.spec"
    spec_path.write_text(spec, encoding="utf-8")
    run([python, "-m", "PyInstaller", "--clean", "--noconfirm", "--distpath", dist,
         "--workpath", ROOT / "build/pyinstaller" / args.arch, spec_path], env=env)
    backend = dist / "documate-backend"
    check_pe(backend / "documate-backend.exe", args.arch)
    for binary in backend.rglob("*"):
        if binary.suffix.lower() in (".dll", ".pyd"):
            check_pe(binary, args.arch)
    if not list(backend.rglob("vec0.dll")):
        raise RuntimeError("PyInstaller 未收集 sqlite-vec 扩展 DLL")
    check_backend(backend / "documate-backend.exe")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    config_file = work / "electron-builder.json"
    config_file.write_text(json.dumps(builder_config(package, args.arch, backend)), encoding="utf-8")
    run([node, ROOT / "node_modules/electron-builder/cli.js", "--config", config_file,
         "--win", "nsis", "--" + args.arch, "--publish", "never"])
    output = ROOT / "release" / ("windows-" + args.arch)
    installer = output / f"DocuMate-Setup-v{package['version']}-windows-{args.arch}.exe"
    if not installer.is_file():
        raise RuntimeError(f"未找到预期安装包：{installer}")
    for artifact in (output / "latest.yml", Path(str(installer) + ".blockmap")):
        if not artifact.is_file():
            raise RuntimeError(f"缺少服务器更新文件：{artifact}")
    unpacked = output / ("win-unpacked" if args.arch == "x64" else "win-arm64-unpacked")
    update_config = unpacked / "resources/app-update.yml"
    expected_feed = builder_config(package, args.arch, backend)["win"]["publish"][0]["url"]
    if not update_config.is_file() or expected_feed not in update_config.read_text(encoding="utf-8"):
        raise RuntimeError("安装包内的更新地址缺失或架构不匹配")
    print(f"\n打包完成：{installer}\n请安装并验证启动、登录和会话恢复。")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"\n打包停止：{error}", file=sys.stderr)
        sys.exit(1)
