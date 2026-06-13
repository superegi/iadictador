from __future__ import annotations

from pathlib import Path
from datetime import datetime
import json
import os
import sqlite3
from typing import Any


DB_PATH = Path(os.getenv("IAD_WORK_STORE_DB", "data/iad_work_store.sqlite3"))


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def as_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"raw": str(value)}, ensure_ascii=False)


def from_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iad_work_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            username TEXT,
            template_name TEXT,
            confidence TEXT,
            method TEXT,
            source_text TEXT,
            base_report TEXT,
            final_report TEXT,
            analysis_json TEXT,
            generated_json TEXT,
            clinical_json TEXT,
            review_json TEXT,
            cards_json TEXT,
            status TEXT DEFAULT 'saved',
            saved_to_history INTEGER DEFAULT 1,
            saved_to_training INTEGER DEFAULT 1
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iad_training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            work_record_id INTEGER,
            username TEXT,
            sample_type TEXT,
            input_text TEXT,
            output_text TEXT,
            metadata_json TEXT,
            FOREIGN KEY(work_record_id) REFERENCES iad_work_records(id)
        )
        """
    )

    conn.commit()


def save_work_record(payload: dict[str, Any], username: str = "") -> dict[str, Any]:
    created = now_iso()

    template_name = str(payload.get("template_name") or "")
    confidence = str(payload.get("confidence") or "")
    method = str(payload.get("method") or "")
    source_text = str(payload.get("source_text") or "")
    base_report = str(payload.get("base_report") or "")
    final_report = str(payload.get("final_report") or "")

    analysis_json = as_json(payload.get("analysis"))
    generated_json = as_json(payload.get("generated"))
    clinical_json = as_json(payload.get("clinical_json"))
    review_json = as_json(payload.get("review"))
    cards_json = as_json(payload.get("cards"))

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO iad_work_records (
                created_at, updated_at, username,
                template_name, confidence, method,
                source_text, base_report, final_report,
                analysis_json, generated_json, clinical_json, review_json, cards_json,
                status, saved_to_history, saved_to_training
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
            """,
            (
                created, created, username,
                template_name, confidence, method,
                source_text, base_report, final_report,
                analysis_json, generated_json, clinical_json, review_json, cards_json,
                "saved",
            ),
        )

        record_id = int(cur.lastrowid)

        conn.execute(
            """
            INSERT INTO iad_training_samples (
                created_at, work_record_id, username, sample_type,
                input_text, output_text, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created,
                record_id,
                username,
                "work_review_final",
                source_text,
                final_report,
                as_json(
                    {
                        "template_name": template_name,
                        "confidence": confidence,
                        "method": method,
                        "base_report": base_report,
                        "clinical_json": payload.get("clinical_json"),
                        "review": payload.get("review"),
                        "cards": payload.get("cards"),
                    }
                ),
            ),
        )

        conn.commit()

    return {
        "ok": True,
        "id": record_id,
        "created_at": created,
        "saved_to_history": True,
        "saved_to_training": True,
    }


def row_to_work(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "username": row["username"],
        "template_name": row["template_name"],
        "confidence": row["confidence"],
        "method": row["method"],
        "source_text": row["source_text"],
        "base_report": row["base_report"],
        "final_report": row["final_report"],
        "analysis": from_json(row["analysis_json"]),
        "generated": from_json(row["generated_json"]),
        "clinical_json": from_json(row["clinical_json"]),
        "review": from_json(row["review_json"]),
        "cards": from_json(row["cards_json"]),
        "status": row["status"],
    }


def list_work_records(limit: int = 50, username: str = "", all_users: bool = False) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))

    with connect() as conn:
        if username and not all_users:
            rows = conn.execute(
                """
                SELECT * FROM iad_work_records
                WHERE username = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (username, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM iad_work_records
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return [row_to_work(row) for row in rows]


def row_to_training(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "work_record_id": row["work_record_id"],
        "username": row["username"],
        "sample_type": row["sample_type"],
        "input_text": row["input_text"],
        "output_text": row["output_text"],
        "metadata": from_json(row["metadata_json"]),
    }


def list_training_samples(limit: int = 50, username: str = "", all_users: bool = False) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))

    with connect() as conn:
        if username and not all_users:
            rows = conn.execute(
                """
                SELECT * FROM iad_training_samples
                WHERE username = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (username, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM iad_training_samples
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return [row_to_training(row) for row in rows]
