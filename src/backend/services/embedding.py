import os
import sys
import threading
from pathlib import Path
from typing import Callable

from src.backend.paths import DATA_DIRECTORY
from src.backend.services.cancellation import cancellable_lock
from src.backend.services.document_parser import TextBlock


EMBEDDING_DIMENSION = 384


class E5Encoder:
    """惰性加载本地未量化 E5；不使用 Hub、不联网下载模型。"""

    def __init__(self, model_directory: Path | None = None) -> None:
        self.directory = model_directory or Path(os.getenv(
            "DOCUMATE_EMBEDDING_DIR", str(DATA_DIRECTORY / "models" / "multilingual-e5-small")
        ))
        if model_directory is None and not os.getenv("DOCUMATE_EMBEDDING_DIR") and not self.directory.exists():
            if getattr(sys, "frozen", False):
                self.directory = Path(sys._MEIPASS) / "models" / "multilingual-e5-small"
            else:
                self.directory = Path(__file__).resolve().parents[1] / "data" / "models" / "multilingual-e5-small"
        self._lock = threading.RLock()
        self._session = self._tokenizer = None

    def _load(self) -> None:
        if self._session is not None:
            return
        for name in ("model.onnx", "tokenizer.json"):
            if not (self.directory / name).is_file():
                raise FileNotFoundError(f"本地 E5 资源缺失：{self.directory / name}")
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        tokenizer = Tokenizer.from_file(str(self.directory / "tokenizer.json"))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        session = ort.InferenceSession(str(self.directory / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        self._tokenizer, self._session = tokenizer, session

    @property
    def fingerprint(self) -> str:
        import hashlib

        with self._lock:
            if not hasattr(self, "_fingerprint"):
                digest = hashlib.sha256()
                for name in ("model.onnx", "tokenizer.json"):
                    with (self.directory / name).open("rb") as stream:
                        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                            digest.update(block)
                self._fingerprint = digest.hexdigest() + ":mean-l2:320-40:parser1"
            return self._fingerprint

    def split(self, blocks: list[TextBlock]) -> list[TextBlock]:
        with self._lock:
            self._load()
            chunks = []
            for block in blocks:
                encoded = self._tokenizer.encode(block.text, add_special_tokens=False)
                for start in range(0, len(encoded.ids), 280):
                    offsets = encoded.offsets[start:start + 320]
                    left, right = offsets[0][0], offsets[-1][1]
                    chunks.append(TextBlock(block.text[left:right], {**block.location, "char_start": left, "char_end": right}))
            return chunks

    def encode(self, texts: list[str], *, query: bool = False, cancel_check: Callable[[], None] = lambda: None):
        import numpy as np

        with cancellable_lock(self._lock, cancel_check):
            self._load()
            output = []
            for start in range(0, len(texts), 4):
                cancel_check()
                encoded = [self._tokenizer.encode(("query: " if query else "passage: ") + text) for text in texts[start:start + 4]]
                length = max(len(item.ids) for item in encoded)
                if length > 512:
                    raise ValueError("E5 输入超过 512 tokens，请缩短检索需求或文本块")
                ids = np.asarray([item.ids + [1] * (length - len(item.ids)) for item in encoded], dtype=np.int64)
                mask = np.asarray([[1] * len(item.ids) + [0] * (length - len(item.ids)) for item in encoded], dtype=np.int64)
                hidden = self._session.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0]
                pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1)[:, None]
                norms = np.linalg.norm(pooled, axis=1, keepdims=True)
                if pooled.shape[1] != EMBEDDING_DIMENSION or not np.isfinite(pooled).all() or (norms == 0).any():
                    raise RuntimeError("E5 输出无效向量")
                output.append((pooled / norms).astype(np.float32))
            cancel_check()
            return np.concatenate(output) if output else np.empty((0, EMBEDDING_DIMENSION), dtype=np.float32)
