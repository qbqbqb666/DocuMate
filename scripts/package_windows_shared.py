"""从共享项目启动，在 Windows 桌面的独立目录构建，再回传发布文件。"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4


FILES = (
    "package.json", "package-lock.json", "pyproject.toml", "uv.lock",
    "documate-backend.spec", "index.html", "vite.config.ts", "tsconfig.json",
    "tailwind.config.cjs", "postcss.config.cjs",
)
DIRECTORIES = ("src/frontend", "src/backend", "src/electron", "scripts", "build/icons")
MODEL = Path("src/backend/data/models/multilingual-e5-small")
EXCLUDED = { "__pycache__", "node_modules", ".venv", ".git", ".DS_Store"}


def desktop_directory() -> Path:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
        desktop, _ = winreg.QueryValueEx(key, "Desktop")
    return Path(os.path.expandvars(desktop))


def build_directory(source: Path, desktop: Path) -> Path:
    identity = hashlib.sha256(str(source).casefold().encode("utf-8")).hexdigest()[:12]
    return desktop / "DocuMate-Windows-build" / identity


def source_files(source: Path) -> dict[str, Path]:
    result = {name: source / name for name in FILES}
    for name in DIRECTORIES:
        directory = source / name
        if not directory.is_dir():
            raise FileNotFoundError(f"缺少源码目录：{directory}")
        for folder, directories, files in os.walk(directory, followlinks=False):
            directories[:] = [d for d in directories if d not in EXCLUDED and not d.startswith(".") and not (Path(folder) / d).is_symlink() and Path(folder) / d != source / "src/backend/data"]
            for filename in files:
                path = Path(folder) / filename
                if path.is_symlink() or filename.startswith(".") or path.suffix in {".pyc", ".log"}:
                    continue
                result[path.relative_to(source).as_posix()] = path
    model = source / MODEL
    for required in ("model.onnx", "tokenizer.json"):
        if not (model / required).is_file():
            raise FileNotFoundError(f"共享项目缺少模型资源：{model / required}")
    for path in model.iterdir():
        if path.is_file() and not path.is_symlink() and not path.name.startswith("."):
            result[path.relative_to(source).as_posix()] = path
    for path in result.values():
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"缺少构建文件：{path}")
    return result


def sync_source(source: Path, destination: Path) -> int:
    files = source_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = destination / ".source-files.json"
    previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    current = {}
    copied = 0
    for name, source_file in files.items():
        target = destination / name
        if not target.resolve().is_relative_to(destination.resolve()):
            raise ValueError("本地构建目录包含不支持的符号链接")
        info = source_file.stat()
        signature = [info.st_size, info.st_mtime_ns]
        old = previous.get(name, {})
        if old.get("source") != signature or not target.is_file() or old.get("target") != [target.stat().st_size, target.stat().st_mtime_ns]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
            after = source_file.stat()
            if signature != [after.st_size, after.st_mtime_ns]:
                raise RuntimeError(f"源码正在修改，请保存后重新打包：{source_file}")
            copied += 1
        current[name] = {"source": signature, "target": [target.stat().st_size, target.stat().st_mtime_ns]}
    # 只清理本脚本先前同步的文件，依赖和构建缓存继续复用。
    for name in previous.keys() - current.keys():
        target = destination / name
        if not Path(name).is_absolute() and ".." not in Path(name).parts and target.resolve().is_relative_to(destination.resolve()):
            target.unlink(missing_ok=True)
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    temporary.replace(manifest)
    return copied


def file_hash(path: Path, algorithm: str = "sha256") -> bytes:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.digest()


def publish_artifacts(local_output: Path, shared_output: Path, version: str) -> Path | None:
    name = f"DocuMate-Setup-v{version}-windows-x64.exe"
    names = (name, name + ".blockmap", "latest.yml")
    for filename in names:
        if not (local_output / filename).is_file() or not (local_output / filename).stat().st_size:
            raise FileNotFoundError(f"缺少完整发布文件：{filename}")
    metadata = (local_output / "latest.yml").read_text(encoding="utf-8")
    expected_hash = base64.b64encode(file_hash(local_output / name, "sha512")).decode()
    if not re.search(r"(?m)^version:\s*['\"]?" + re.escape(version) + r"['\"]?\s*$", metadata) or name not in metadata or expected_hash not in metadata:
        raise ValueError("latest.yml 的版本、安装包路径或哈希与产物不一致")
    shared_output.parent.mkdir(parents=True, exist_ok=True)
    stage = shared_output.with_name(f".windows-x64-incoming-{uuid4().hex}")
    stage.mkdir()
    backup = None
    try:
        for filename in names:
            shutil.copy2(local_output / filename, stage / filename)
            if file_hash(stage / filename) != file_hash(local_output / filename):
                raise RuntimeError(f"回传校验失败：{filename}")
        if shared_output.exists():
            backup = shared_output.with_name(f"windows-x64-before-{version}-{uuid4().hex[:8]}")
            shared_output.rename(backup)
        try:
            stage.rename(shared_output)
        except OSError:
            if backup is not None:
                backup.rename(shared_output)
            raise
        return backup
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    source = parser.parse_args().source.resolve()
    if sys.platform != "win32":
        raise RuntimeError("请在 Windows 虚拟机中双击 package-windows-x64.bat")
    node = shutil.which("node")
    if node is None or shutil.which("npm.cmd") is None:
        raise RuntimeError("请先安装 Node.js/npm，并加入 PATH")
    destination = build_directory(source, desktop_directory()).resolve()
    if str(destination).startswith("\\\\"):
        raise RuntimeError("Windows 桌面位于网络路径，请先使用 Windows 本地桌面")
    destination.mkdir(parents=True, exist_ok=True)
    import msvcrt

    with (destination / ".build.lock").open("a+b") as lock:
        lock.write(b"\0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("此项目已在打包，请等待另一个打包窗口结束") from error
        try:
            print(f"共享源码：{source}\nWindows 桌面构建目录：{destination}", flush=True)
            print(f"同步完成，本次复制 {sync_source(source, destination)} 个文件（未变模型和源码复用）", flush=True)
            fingerprint = hashlib.sha256((destination / "package-lock.json").read_bytes() + subprocess.check_output([node, "-p", "process.version + '/' + process.arch"], cwd=destination)).hexdigest()
            marker = destination / ".node-dependencies.sha256"
            command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "npm.cmd"]
            if not (destination / "node_modules").is_dir() or not marker.is_file() or marker.read_text().strip() != fingerprint:
                subprocess.run([*command, "ci", "--include=dev"], cwd=destination, check=True)
                marker.write_text(fingerprint, encoding="utf-8")
            subprocess.run([*command, "run", "package:win:x64"], cwd=destination, check=True)
            version = json.loads((destination / "package.json").read_text(encoding="utf-8"))["version"]
            shared_output = source / "release" / "windows-x64"
            backup = publish_artifacts(destination / "release" / "windows-x64", shared_output, version)
            print(f"\n打包并回传成功：{shared_output}", flush=True)
            if backup is not None:
                print(f"旧产物备份：{backup}", flush=True)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"打包失败：{error}", file=sys.stderr, flush=True)
        sys.exit(1)
