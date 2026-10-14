import sys

import uvicorn

from src.backend.config import BackendConfig
from src.backend.services.parent_watchdog import start_parent_watchdog


def main() -> None:
    if sys.argv[1:] == ["--check-local-retrieval"]:
        import sqlite3
        import sqlite_vec
        from src.backend.services.embedding import E5Encoder

        vector = E5Encoder().encode(["本地资源验证 local resource check"], query=True)[0]
        with sqlite3.connect(":memory:") as connection:
            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            distance = connection.execute("SELECT vec_distance_cosine(?,?)", (vector.tobytes(), vector.tobytes())).fetchone()[0]
            if len(vector) != 384 or abs(distance) > 0.00001:
                raise RuntimeError("本地模型或向量扩展检查失败")
        print("E5 tokenizer / ONNX CPU / sqlite-vec: OK (384 dimensions)")
        return
    from src.backend.main import app

    config = BackendConfig.from_env()
    start_parent_watchdog()
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )


if __name__ == "__main__":
    main()
