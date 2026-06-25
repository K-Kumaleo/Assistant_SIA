"""
notes_access.py — Windows Notes via plain text files in %USERPROFILE%\SIA_Notes
No edit/delete by design. Falls back to OneNote COM if available.
"""

import os
import subprocess
from pathlib import Path
from datetime import datetime

NOTES_DIR = Path.home() / "SIA_Notes"


def _ensure_dir():
    NOTES_DIR.mkdir(parents=True, exist_ok=True)


def get_recent_notes(limit: int = 5) -> list[dict]:
    _ensure_dir()
    files = sorted(NOTES_DIR.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
    results = []
    for f in files[:limit]:
        try:
            body = f.read_text(encoding="utf-8")[:200]
            results.append({"title": f.stem, "body": body})
        except Exception:
            pass
    return results


def create_note(title: str, body: str) -> bool:
    _ensure_dir()
    try:
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:60]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = NOTES_DIR / f"{safe_title or timestamp}.txt"
        filename.write_text(f"{title}\n{'='*len(title)}\n\n{body}", encoding="utf-8")
        return True
    except Exception:
        return False


def search_notes_apple(query: str, limit: int = 5) -> list[dict]:
    """Search local SIA_Notes folder (named for API compatibility)."""
    _ensure_dir()
    query_lower = query.lower()
    results = []
    for f in NOTES_DIR.glob("*.txt"):
        try:
            body = f.read_text(encoding="utf-8")
            if query_lower in f.stem.lower() or query_lower in body.lower():
                results.append({"title": f.stem, "body": body[:200]})
                if len(results) >= limit:
                    break
        except Exception:
            pass
    return results


def open_notes_folder() -> str:
    _ensure_dir()
    subprocess.Popen(["explorer", str(NOTES_DIR)])
    return f"Opened notes folder at {NOTES_DIR}"
