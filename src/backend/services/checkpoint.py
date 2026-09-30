import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from src.backend.paths import DATA_DIRECTORY


DATABASE_PATH = DATA_DIRECTORY / "documate.sqlite3"

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

connection = sqlite3.connect(
    DATABASE_PATH,
    check_same_thread=False,
)

checkpointer = SqliteSaver(connection)
