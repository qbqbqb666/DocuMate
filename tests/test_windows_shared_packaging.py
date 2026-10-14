import base64
from pathlib import Path

import pytest

from scripts import package_windows_shared as shared


def source_fixture(root: Path) -> Path:
    for filename in shared.FILES:
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('source', encoding='utf-8')
    for filename in ('src/frontend/App.tsx', 'src/backend/main.py', 'src/electron/main.cjs', 'scripts/package_windows.py', 'build/icons/windows/icon.ico'):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('needed', encoding='utf-8')
    for filename in ('model.onnx', 'tokenizer.json', 'MODEL_CARD.md'):
        path = root / shared.MODEL / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('model resource', encoding='utf-8')
    for filename in ('node_modules/mac.node', '.venv/bin/python', '.env', 'src/backend/data/local_accounts.sqlite3', 'src/backend/data/rag-validation/test.txt', 'src/backend/data/models/multilingual-e5-small/dependencies/mac.whl', 'src/backend/__pycache__/main.pyc'):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('must not copy', encoding='utf-8')
    return root


def artifacts_fixture(root: Path) -> Path:
    root.mkdir(parents=True)
    installer = root / 'DocuMate-Setup-v0.6.0-windows-x64.exe'
    installer.write_bytes(b'new installer')
    (root / (installer.name + '.blockmap')).write_bytes(b'blockmap')
    digest = base64.b64encode(shared.file_hash(installer, 'sha512')).decode()
    (root / 'latest.yml').write_text(f'version: 0.6.0\npath: {installer.name}\nsha512: {digest}\n', encoding='utf-8')
    return root


def test_sync_isolated_sources_models_reused_and_stale_files_removed(tmp_path):
    source = source_fixture(tmp_path / '共享项目 (new)')
    destination = shared.build_directory(source, tmp_path / 'Windows Desktop')
    count = shared.sync_source(source, destination)
    assert count > 0
    assert (destination / shared.MODEL / 'model.onnx').read_text() == 'model resource'
    assert (destination / 'build/icons/windows/icon.ico').exists()
    assert not (destination / 'src/backend/data/local_accounts.sqlite3').exists()
    assert not (destination / shared.MODEL / 'dependencies').exists()
    assert not (destination / '.env').exists()
    assert not (destination / '.venv').exists()
    assert not (destination / 'node_modules').exists()
    dependencies = destination / 'node_modules'
    dependencies.mkdir()
    (dependencies / 'windows.node').write_bytes(b'cache')
    assert shared.sync_source(source, destination) == 0
    (source / 'src/frontend/App.tsx').write_text('changed content', encoding='utf-8')
    assert shared.sync_source(source, destination) == 1
    (source / 'src/frontend/App.tsx').unlink()
    shared.sync_source(source, destination)
    assert not (destination / 'src/frontend/App.tsx').exists()
    assert (dependencies / 'windows.node').read_bytes() == b'cache'
    assert (source / '.env').read_text() == 'must not copy'


def test_missing_model_stops_sync_before_touching_cache(tmp_path):
    source = source_fixture(tmp_path / 'source')
    (source / shared.MODEL / 'model.onnx').unlink()
    cache = tmp_path / 'cache'
    with pytest.raises(FileNotFoundError, match='模型资源'):
        shared.sync_source(source, cache)
    assert not cache.exists()


def test_publish_three_files_and_keep_previous_output_backup(tmp_path):
    local = artifacts_fixture(tmp_path / 'local')
    output = tmp_path / 'shared/release/windows-x64'
    output.mkdir(parents=True)
    (output / 'old.exe').write_bytes(b'old')
    backup = shared.publish_artifacts(local, output, '0.6.0')
    assert backup is not None
    assert (backup / 'old.exe').read_bytes() == b'old'
    assert len(list(output.iterdir())) == 3
    for path in local.iterdir():
        assert shared.file_hash(path) == shared.file_hash(output / path.name)


@pytest.mark.parametrize('failure', ['missing', 'metadata', 'transfer'])
def test_failed_publish_preserves_old_output(tmp_path, monkeypatch, failure):
    local = artifacts_fixture(tmp_path / 'local')
    output = tmp_path / 'shared/release/windows-x64'
    output.mkdir(parents=True)
    (output / 'old.exe').write_bytes(b'old')
    if failure == 'missing':
        (local / 'latest.yml').unlink()
    elif failure == 'metadata':
        (local / 'latest.yml').write_text('version: 0.5.1\n', encoding='utf-8')
    else:
        monkeypatch.setattr(shared.shutil, 'copy2', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('share unavailable')))
    with pytest.raises((FileNotFoundError, ValueError, OSError)):
        shared.publish_artifacts(local, output, '0.6.0')
    assert (output / 'old.exe').read_bytes() == b'old'
    assert len(list(output.iterdir())) == 1


def test_failed_final_rename_restores_old_output(tmp_path, monkeypatch):
    local = artifacts_fixture(tmp_path / 'local')
    output = tmp_path / 'shared/release/windows-x64'
    output.mkdir(parents=True)
    (output / 'old.exe').write_bytes(b'old')
    rename = Path.rename
    def fail_stage(path, target):
        if path.name.startswith('.windows-x64-incoming-'):
            raise OSError('share interrupted')
        return rename(path, target)
    monkeypatch.setattr(Path, 'rename', fail_stage)
    with pytest.raises(OSError, match='interrupted'):
        shared.publish_artifacts(local, output, '0.6.0')
    assert (output / 'old.exe').read_bytes() == b'old'
    assert not list(output.parent.glob('.windows-x64-incoming-*'))
