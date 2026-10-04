"""Small durable local audit store; each operation owns its SQLite connection."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS diagnoses (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    request TEXT NOT NULL, response TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY, diagnosis_id TEXT NOT NULL REFERENCES diagnoses(id),
                    rating TEXT NOT NULL CHECK(rating IN ('helpful','incorrect')),
                    comment TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save(self, request: dict, response: dict):
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO diagnoses VALUES (?,?,?,?)",
                (
                    response["id"],
                    response["created_at"],
                    json.dumps(request, ensure_ascii=False),
                    json.dumps(response, ensure_ascii=False),
                ),
            )

    def get(self, diagnosis_id: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT request,response FROM diagnoses WHERE id=?", (diagnosis_id,)
            ).fetchone()
            if not row:
                return None
            feedback = [
                dict(x)
                for x in conn.execute(
                    "SELECT rating,comment,created_at FROM feedback WHERE diagnosis_id=? ORDER BY id",
                    (diagnosis_id,),
                )
            ]
        result = json.loads(row["response"])
        request = json.loads(row["request"])
        # Recover the original snapshot even for records created by earlier releases.
        result.update(
            {key: request.get(key) for key in ("question", "at", "is_new_customer", "cart")}
        )
        result["feedback"] = feedback
        return {"request": request, "response": result}

    def list(self, limit: int = 50):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT request,response FROM diagnoses ORDER BY created_at DESC,id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": d["id"],
                "status": d["status"],
                "created_at": d["created_at"],
                "answer": d["answer"],
                "question": json.loads(row["request"])["question"],
            }
            for row in rows
            for d in [json.loads(row["response"])]
        ]

    def feedback(self, diagnosis_id: str, rating: str, comment: str):
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM diagnoses WHERE id=?", (diagnosis_id,)).fetchone():
                raise KeyError(diagnosis_id)
            conn.execute(
                "INSERT INTO feedback(diagnosis_id,rating,comment,created_at) VALUES(?,?,?,?)",
                (diagnosis_id, rating, comment, datetime.now(timezone.utc).isoformat()),
            )
