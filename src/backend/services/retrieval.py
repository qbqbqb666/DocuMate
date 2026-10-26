import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from src.backend.paths import DATA_DIRECTORY
from src.backend.services.cancellation import RunCancelledError, cancellable_lock
from src.backend.services.document_parser import SUPPORTED_SUFFIXES, parse_document
from src.backend.services.embedding import E5Encoder
from src.backend.services.workspace import EXCLUDED_SEARCH_DIRECTORIES


logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 50 * 1024 * 1024


def _signature(path: Path) -> str:
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError("资料必须是普通文件，不能是符号链接")
    stat = path.stat()
    return f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"


def _readable_error(error: str | None) -> str | None:
    if error and ("codec can't decode byte" in error or "invalid start byte" in error):
        return "无法按 UTF-8 解码文本：文件可能是二进制缓存，或使用了其他文本编码。"
    return error


class RetrievalService:
    """本地基础语义检索，按文件版本原子发布，不修改或备份原文件。"""

    def __init__(self, database: Path | None = None, encoder: E5Encoder | None = None,
                 debounce_seconds: float = 5, poll_seconds: float = 2) -> None:
        self.database = database or DATA_DIRECTORY / "retrieval.sqlite3"
        self.encoder = encoder or E5Encoder()
        self.debounce_seconds, self.poll_seconds = debounce_seconds, poll_seconds
        self._lock = threading.RLock()
        self._roots: set[Path] = set()
        self._file_roots: set[Path] = set()
        self._requests: set[Path] = set()
        self._queue_lock = threading.RLock()
        self._wake = threading.Event()
        self._last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._root_provider: Callable[[], list[str]] = lambda: []
        self.retain_path: Callable[[Path], bool] = lambda path: True
        self.visible_path: Callable[[Path, list[Path]], bool] = lambda path, roots: True

    def prune_removed(self) -> None:
        with self._lock:
            if not self.database.exists():
                return
            db = self._connect()
            try:
                with db:
                    for row in db.execute("SELECT path FROM files").fetchall():
                        if not self.retain_path(Path(row["path"])):
                            db.execute("DELETE FROM files WHERE path=?", (row["path"],))
            finally:
                db.close()

    def _connect(self) -> sqlite3.Connection:
        import sqlite_vec

        self.database.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files(
                path TEXT PRIMARY KEY, signature TEXT NOT NULL, sha256 TEXT,
                status TEXT NOT NULL, changed_at REAL NOT NULL, error TEXT, encoder TEXT);
            CREATE TABLE IF NOT EXISTS chunks(
                id INTEGER PRIMARY KEY, path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
                text TEXT NOT NULL, location TEXT NOT NULL, embedding BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
        """)
        return db

    def start(self, root_provider: Callable[[], list[str]] | None = None) -> None:
        with self._queue_lock:
            if root_provider is not None:
                self._root_provider = root_provider
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._watch, name="documate-index", daemon=True)
            self._thread.start()

    def request_index(self, roots: list[str | Path]) -> None:
        with self._queue_lock:
            self._requests.update(Path(root).expanduser().absolute() for root in roots)
        self.start()
        self._wake.set()

    def index_status(self, paths: list[Path]) -> dict:
        records = {}
        if self.database.exists():
            with sqlite3.connect(self.database) as db:
                db.row_factory = sqlite3.Row
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='files'").fetchone():
                    records = {row["path"]: dict(row) for row in db.execute("SELECT path,status,error,signature FROM files")}
        files = []
        for path in sorted(set(paths)):
            record = records.get(str(path))
            state, error = "pending", None
            try:
                signature = _signature(path)
                if record and record["signature"] == signature:
                    state, error = record["status"], record["error"]
            except (OSError, ValueError):
                state, error = "missing", "原文件已移除或路径已改变"
            files.append({"path": str(path), "status": state, "error": _readable_error(error)})
        return {"files": files, "ready": sum(f["status"] == "ready" for f in files),
                "pending": sum(f["status"] == "pending" for f in files),
                "indexing": sum(f["status"] == "indexing" for f in files),
                "errors": [f for f in files if f["status"] in {"error", "missing"}],
                "worker_error": self._last_error}

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _watch(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                with self._queue_lock:
                    requested = list(self._requests)
                    self._requests.clear()
                roots = [root for root in [*self._root_provider(), *requested] if self.retain_path(Path(root))]
                with self._lock:
                    registered = [root for root in self._roots if self.retain_path(root)]
                if roots or registered:
                    self.synchronize([*roots, *registered], self._check_running)
                self._last_error = None
            except RunCancelledError:
                return
            except Exception as error:
                self._last_error = str(error)[:500]
                logger.exception("本地资料索引扫描失败")

    def _check_running(self) -> None:
        if self._stop.is_set():
            raise RunCancelledError("资料索引已停止")

    def synchronize(self, roots: list[str | Path], cancel_check: Callable[[], None] = lambda: None) -> None:
        roots = sorted({Path(root).expanduser().absolute() for root in roots})
        with cancellable_lock(self._lock, cancel_check):
            self._roots.update(roots)
            self._file_roots.update(root for root in roots if root.is_file() and root.resolve() == root)
            paths: set[Path] = set()
            scan_roots = set(roots)
            for root in roots:
                legacy = root / ".documate" / "documents"
                if legacy.is_dir() and legacy.resolve() == legacy:
                    scan_roots.add(legacy)
            for root in sorted(scan_roots):
                cancel_check()
                if not self.retain_path(root) or not root.exists() or root.is_symlink() or root.resolve() != root:
                    continue
                if root in self._file_roots:
                    if root.is_file() and not root.is_symlink() and root.suffix.lower() in SUPPORTED_SUFFIXES:
                        paths.add(root)
                    continue
                if not root.is_dir():
                    raise ValueError(f"检索范围不是文件或文件夹：{root}")
                def walk_error(error: OSError) -> None:
                    raise error
                for folder, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
                    cancel_check()
                    directories[:] = [d for d in directories if not d.startswith(".") and d not in EXCLUDED_SEARCH_DIRECTORIES and not (Path(folder) / d).is_symlink()]
                    for name in files:
                        path = Path(folder) / name
                        if not name.startswith(".") and path.suffix.lower() in SUPPORTED_SUFFIXES and not path.is_symlink():
                            paths.add(path)
                            if len(paths) > 20_000:
                                raise ValueError("资料文件超过单次扫描的 20000 份上限")
            paths = {path for path in paths if self.retain_path(path)}
            db = self._connect()
            try:
                for row in db.execute("SELECT path FROM files").fetchall():
                    path = Path(row["path"])
                    if not self.retain_path(path) or (any(path.is_relative_to(root) for root in roots) and path not in paths):
                        with db:
                            db.execute("DELETE FROM files WHERE path=?", (str(path),))
                if not paths:
                    return
                fingerprint = self.encoder.fingerprint
                previous = db.execute("SELECT value FROM metadata WHERE key='encoder'").fetchone()
                if previous is None or previous[0] != fingerprint:
                    with db:
                        db.execute("UPDATE files SET status='pending',changed_at=?", (time.time() - self.debounce_seconds,))
                        db.execute("INSERT OR REPLACE INTO metadata VALUES('encoder',?)", (fingerprint,))
                for path in sorted(paths):
                    cancel_check()
                    try:
                        signature = _signature(path)
                    except (OSError, ValueError):
                        with db:
                            db.execute("DELETE FROM files WHERE path=?", (str(path),))
                        continue
                    row = db.execute("SELECT * FROM files WHERE path=?", (str(path),)).fetchone()
                    if row is None:
                        with db:
                            db.execute("INSERT INTO files(path,signature,status,changed_at) VALUES(?,?,'pending',?)", (str(path), signature, time.time() - self.debounce_seconds))
                    elif row["signature"] != signature:
                        with db:
                            db.execute("UPDATE files SET signature=?,status='pending',changed_at=?,error=NULL WHERE path=?", (signature, time.time(), str(path)))
                        continue
                    elif row["status"] == "ready":
                        continue
                    elif time.time() - row["changed_at"] < self.debounce_seconds:
                        continue
                    try:
                        with db:
                            db.execute("UPDATE files SET status='indexing',error=NULL WHERE path=?", (str(path),))
                        if path.stat().st_size > MAX_FILE_BYTES:
                            raise ValueError("单份资料不能超过 50 MB")
                        content = path.read_bytes()
                        if len(content) > MAX_FILE_BYTES:
                            raise ValueError("单份资料不能超过 50 MB")
                        digest = hashlib.sha256(content).hexdigest()
                        if row is not None and row["sha256"] == digest and row["encoder"] == fingerprint:
                            if _signature(path) == signature:
                                with db:
                                    db.execute("UPDATE files SET status='ready',error=NULL WHERE path=?", (str(path),))
                                continue
                        blocks = self.encoder.split(parse_document(path, content))
                        if not blocks:
                            raise ValueError("没有可检索文字（扫描 PDF 暂不支持 OCR）")
                        vectors = self.encoder.encode([block.text for block in blocks], cancel_check=cancel_check)
                        cancel_check()
                        if not self.retain_path(path):
                            with db:
                                db.execute("DELETE FROM files WHERE path=?", (str(path),))
                            continue
                        if _signature(path) != signature:
                            with db:
                                db.execute("UPDATE files SET status='pending',changed_at=? WHERE path=?", (time.time(), str(path)))
                            continue
                        with db:
                            db.execute("DELETE FROM chunks WHERE path=?", (str(path),))
                            db.executemany("INSERT INTO chunks(path,text,location,embedding) VALUES(?,?,?,?)", [(str(path), block.text, json.dumps(block.location, ensure_ascii=False), vector.tobytes()) for block, vector in zip(blocks, vectors)])
                            db.execute("UPDATE files SET sha256=?,encoder=?,status='ready',error=NULL WHERE path=?", (digest, fingerprint, str(path)))
                    except RunCancelledError:
                        with db:
                            db.execute("UPDATE files SET status='pending' WHERE path=?", (str(path),))
                        raise
                    except Exception as error:
                        with db:
                            db.execute("UPDATE files SET status='error',error=?,changed_at=? WHERE path=?", (_readable_error(str(error))[:500], time.time(), str(path)))
            finally:
                db.close()

    def search(self, query: str, roots: list[str | Path], top_k: int = 5,
               cancel_check: Callable[[], None] = lambda: None) -> dict:
        if not query.strip() or len(query) > 2000 or not 1 <= top_k <= 20:
            raise ValueError("检索需求须为 1～2000 字符，top_k 须为 1～20")
        roots = sorted({Path(root).expanduser().absolute() for root in roots})
        if not roots:
            raise ValueError("请指定检索文件夹")
        self.synchronize(roots, cancel_check)
        self.start()
        cancel_check()
        vector = self.encoder.encode([query.strip()], query=True, cancel_check=cancel_check)[0].tobytes()
        with cancellable_lock(self._lock, cancel_check):
            db = self._connect()
            try:
                # 路径范围在距离排序前过滤；基础版采用 sqlite-vec 精确距离计算。
                conditions = " OR ".join("f.path=?" if root in self._file_roots else "(f.path=? OR instr(f.path,?)=1)" for root in roots)
                parameters = []
                for root in roots:
                    parameters.append(str(root))
                    if root not in self._file_roots:
                        parameters.append(str(root).rstrip(os.sep) + os.sep)
                rows = db.execute(f"SELECT f.path,f.signature,f.sha256,MIN(vec_distance_cosine(c.embedding,?)) distance FROM chunks c JOIN files f ON f.path=c.path WHERE f.status='ready' AND ({conditions}) GROUP BY f.path ORDER BY distance,f.path", [vector, *parameters]).fetchall()
                hits = []
                for row in rows:
                    cancel_check()
                    path = Path(row["path"])
                    if not self.visible_path(path, roots):
                        continue
                    try:
                        if _signature(path) != row["signature"]:
                            with db:
                                db.execute("UPDATE files SET status='pending',changed_at=? WHERE path=?", (time.time(), str(path)))
                            continue
                    except (OSError, ValueError):
                        with db:
                            db.execute("DELETE FROM files WHERE path=?", (str(path),))
                        continue
                    matches = db.execute("SELECT id,text,location,vec_distance_cosine(embedding,?) distance FROM chunks WHERE path=? ORDER BY distance,id LIMIT 3", (vector, str(path))).fetchall()
                    hits.append({"path": str(path), "filename": path.name, "sha256": row["sha256"], "similarity": 1 - row["distance"], "matches": [{"chunk_id": item["id"], "text": item["text"][:800], "truncated": len(item["text"]) > 800, "location": json.loads(item["location"]), "similarity": 1 - item["distance"]} for item in matches]})
                    if len(hits) == top_k:
                        break
                statuses = [dict(row) for row in db.execute(f"SELECT f.path,f.status,f.error FROM files f WHERE {conditions}", parameters) if self.visible_path(Path(row["path"]), roots)]
                return {"query": query, "roots": [str(root) for root in roots], "files": hits,
                        "index": {"ready": sum(r["status"] == "ready" for r in statuses), "pending": sum(r["status"] == "pending" for r in statuses), "errors": [r for r in statuses if r["status"] == "error"]},
                        "note": "基础语义候选，分数不是正确率；需按原文件核对。待更新和失败文件不参与检索。"}
            finally:
                db.close()


_service: RetrievalService | None = None
_service_lock = threading.Lock()


def get_retrieval_service() -> RetrievalService:
    global _service
    with _service_lock:
        if _service is None:
            _service = RetrievalService()
        return _service
