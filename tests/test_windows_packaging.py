import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile

import pytest

from scripts.package_windows import (
    MACHINES, ROOT, builder_config, check_pe, make_arm_wheel, patch_arm_popcount,
)


def test_patch_preserves_64_bit_hamming_input():
    source = "static unsigned int __builtin_popcountl(unsigned int x) { return 0; }"
    assert "__builtin_popcountl(u64 x)" in patch_arm_popcount(source)
    with pytest.raises(RuntimeError, match="不匹配"):
        patch_arm_popcount("unexpected upstream revision")


def test_arm_wheel_replaces_dll_and_recalculates_record(tmp_path):
    original = io.BytesIO()
    info = "sqlite_vec-0.1.9.dist-info"
    with zipfile.ZipFile(original, "w") as wheel:
        wheel.writestr("sqlite_vec/vec0.dll", b"old x64 binary")
        wheel.writestr("sqlite_vec/__init__.py", "# upstream wrapper")
        wheel.writestr(f"{info}/METADATA", "Name: sqlite-vec\nVersion: 0.1.9\n")
        wheel.writestr(f"{info}/LICENSE", "upstream license")
        wheel.writestr(f"{info}/WHEEL", "Tag: py3-none-win_amd64\n")
        wheel.writestr(f"{info}/RECORD", "old record")
    target = tmp_path / "sqlite_vec-0.1.9-py3-none-win_arm64.whl"
    make_arm_wheel(original.getvalue(), b"new arm64 binary", target)
    with zipfile.ZipFile(target) as wheel:
        assert wheel.read("sqlite_vec/vec0.dll") == b"new arm64 binary"
        assert wheel.read("sqlite_vec/__init__.py") == b"# upstream wrapper"
        assert wheel.read(f"{info}/LICENSE") == b"upstream license"
        assert b"py3-none-win_arm64" in wheel.read(f"{info}/WHEEL")
        rows = list(csv.reader(io.StringIO(wheel.read(f"{info}/RECORD").decode())))
        assert {row[0] for row in rows} == set(wheel.namelist())
        for name, digest, size in rows:
            if name.endswith("/RECORD"):
                assert digest == size == ""
            else:
                data = wheel.read(name)
                expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                assert digest == "sha256=" + expected
                assert int(size) == len(data)


@pytest.mark.parametrize("arch", ["arm64", "x64"])
def test_pe_rejects_mixed_architectures(tmp_path, arch):
    binary = bytearray(134)
    binary[:2] = b"MZ"
    struct.pack_into("<I", binary, 0x3C, 128)
    binary[128:132] = b"PE\0\0"
    struct.pack_into("<H", binary, 132, MACHINES[arch])
    target = tmp_path / "backend.exe"
    target.write_bytes(binary)
    check_pe(target, arch)
    other = "x64" if arch == "arm64" else "arm64"
    with pytest.raises(RuntimeError, match="架构不匹配"):
        check_pe(target, other)


@pytest.mark.parametrize("arch", ["arm64", "x64"])
def test_packager_selects_matching_backend_and_output(arch):
    package = json.loads((ROOT / "package.json").read_text())
    before = json.dumps(package, sort_keys=True)
    backend = Path("build/backend") / f"windows-{arch}/dist/documate-backend"
    config = builder_config(package, arch, backend)
    assert config["win"]["target"] == [{"target": "nsis", "arch": [arch]}]
    assert config["directories"]["output"] == f"release/windows-{arch}"
    assert config["win"]["publish"] == [{
        "provider": "generic",
        "url": f"http://1.14.67.230/documate-updates/windows-{arch}/",
    }]
    assert config["extraResources"] == [{"from": str(backend), "to": "backend/documate-backend"}]
    assert json.dumps(package, sort_keys=True) == before
