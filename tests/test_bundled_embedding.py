import sys
from pathlib import Path

from src.backend.services import embedding


def test_frozen_encoder_uses_bundled_resources_for_fresh_user(tmp_path, monkeypatch):
    resource_root = Path(embedding.__file__).resolve().parents[1] / "data"
    monkeypatch.delenv("DOCUMATE_EMBEDDING_DIR", raising=False)
    monkeypatch.setattr(embedding, "DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resource_root), raising=False)
    encoder = embedding.E5Encoder()
    vector = encoder.encode(["本地资料查询 local documents"], query=True)
    assert vector.shape == (1, 384)
    assert encoder.directory == resource_root / "models" / "multilingual-e5-small"
    assert not (tmp_path / "models").exists()


def test_explicit_model_override_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMATE_EMBEDDING_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/unused", raising=False)
    assert embedding.E5Encoder().directory == tmp_path
