"""
memory.py — SIA Memory System
SQLite with FTS5: facts, tasks, conversation history (three-tier).
"""

import sqlite3
import json
import time
import os
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data" / "sia.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at REAL DEFAULT (unixepoch('now', 'subsec')),
        updated_at REAL DEFAULT (unixepoch('now', 'subsec'))
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'pending',
        created_at REAL DEFAULT (unixepoch('now', 'subsec')),
        updated_at REAL DEFAULT (unixepoch('now', 'subsec'))
    );

    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        body TEXT NOT NULL,
        tags TEXT,
        created_at REAL DEFAULT (unixepoch('now', 'subsec'))
    );

    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        ts REAL DEFAULT (unixepoch('now', 'subsec'))
    );

    CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, ts);
    CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);

    -- FTS5 for semantic search
    CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
        title, body, tags,
        content='notes', content_rowid='id'
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
        key, value,
        content='facts', content_rowid='id'
    );
    """)
    conn.commit()
    conn.close()


# ── Facts ───────────────────────────────────────────────────────────────────

def upsert_fact(key: str, value: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM facts WHERE key = ?", (key,))
    row = c.fetchone()
    now = time.time()
    if row:
        c.execute(
            "UPDATE facts SET value=?, updated_at=? WHERE key=?",
            (value, now, key)
        )
    else:
        c.execute(
            "INSERT INTO facts (key, value, created_at, updated_at) VALUES (?,?,?,?)",
            (key, value, now, now)
        )
    conn.commit()
    conn.close()


def get_fact(key: str) -> str | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM facts WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else None


def search_facts(query: str, limit: int = 5) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT f.key, f.value FROM facts_fts fts JOIN facts f ON fts.rowid=f.id WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        )
        rows = [dict(r) for r in c.fetchall()]
    except Exception:
        rows = []
    conn.close()
    return rows


def all_facts(limit: int = 20) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT key, value FROM facts ORDER BY updated_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Tasks ────────────────────────────────────────────────────────────────────

def add_task(title: str, description: str = "") -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO tasks (title, description) VALUES (?,?)",
        (title, description)
    )
    task_id = c.lastrowid
    conn.commit()
    conn.close()
    return task_id


def update_task_status(task_id: int, status: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
        (status, time.time(), task_id)
    )
    conn.commit()
    conn.close()


def get_tasks(status: str | None = None, limit: int = 20) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    if status:
        c.execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, limit)
        )
    else:
        c.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Notes ────────────────────────────────────────────────────────────────────

def save_note(body: str, title: str = "", tags: str = "") -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO notes (title, body, tags) VALUES (?,?,?)",
        (title, body, tags)
    )
    note_id = c.lastrowid
    # update FTS
    c.execute(
        "INSERT INTO notes_fts(rowid, title, body, tags) VALUES (?,?,?,?)",
        (note_id, title, body, tags)
    )
    conn.commit()
    conn.close()
    return note_id


def search_notes(query: str, limit: int = 5) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT n.* FROM notes_fts fts JOIN notes n ON fts.rowid=n.id WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        )
        rows = [dict(r) for r in c.fetchall()]
    except Exception:
        rows = []
    conn.close()
    return rows


# ── Conversation (three-tier) ────────────────────────────────────────────────

def add_message(session_id: str, role: str, content: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO conversations (session_id, role, content) VALUES (?,?,?)",
        (session_id, role, content)
    )
    conn.commit()
    conn.close()


def get_recent_messages(session_id: str, limit: int = 20) -> list[dict]:
    """Tier 1: last N turns of current session."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT role, content FROM conversations WHERE session_id=? ORDER BY ts DESC LIMIT ?",
        (session_id, limit)
    )
    rows = [dict(r) for r in reversed(c.fetchall())]
    conn.close()
    return rows


def summarize_old_sessions(current_session: str, max_sessions: int = 5) -> str:
    """Tier 2: compressed summary of older sessions."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT DISTINCT session_id FROM conversations
           WHERE session_id != ?
           ORDER BY MAX(ts) DESC LIMIT ?""",
        (current_session, max_sessions)
    )
    sessions = [r["session_id"] for r in c.fetchall()]
    summaries = []
    for sid in sessions:
        c.execute(
            "SELECT role, content FROM conversations WHERE session_id=? ORDER BY ts LIMIT 10",
            (sid,)
        )
        msgs = c.fetchall()
        if msgs:
            snippet = " | ".join(f"{m['role']}: {m['content'][:80]}" for m in msgs[:3])
            summaries.append(f"[{sid[:8]}] {snippet}")
    conn.close()
    return "\n".join(summaries) if summaries else ""


# ── Init ─────────────────────────────────────────────────────────────────────

init_db()
