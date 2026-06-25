"""
session_manager.py — SIA Session Context + Permanent Memory
─────────────────────────────────────────────────────────────
Two-tier memory architecture:

  1. SESSION CONTEXT FILE  data/sessions/<id>.json
     Created when a session starts. Stores every message in full.
     Survives model switches — new model picks up exactly where the
     previous one left off by loading the file.

  2. PERMANENT MEMORY      data/memory/permanent.json
     Long-term persona memory. At session end the LLM reads the
     full conversation and extracts facts / a summary. These are
     merged in here and injected into every future system prompt.
"""

import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR             = Path(__file__).parent / "data"
SESSIONS_DIR         = DATA_DIR / "sessions"
PERMANENT_MEMORY_PATH = DATA_DIR / "memory" / "permanent.json"

SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
PERMANENT_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# PERMANENT MEMORY
# ══════════════════════════════════════════════════════════════════════════════

def load_permanent_memory() -> dict:
    if PERMANENT_MEMORY_PATH.exists():
        try:
            return json.loads(PERMANENT_MEMORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _empty_permanent_memory()


def save_permanent_memory(mem: dict) -> None:
    PERMANENT_MEMORY_PATH.write_text(
        json.dumps(mem, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _empty_permanent_memory() -> dict:
    return {
        "persona": {
            "user_name": "",
            "preferences": {},
            "facts": [],           # [{key, value, ts, source_session}]
        },
        "knowledge": [],           # miscellaneous long-term facts
        "session_summaries": [],   # [{session_id, date, summary, key_points}]
    }


def add_permanent_fact(key: str, value: str, source_session: str = "") -> None:
    """Upsert a fact into permanent memory (case-insensitive key match)."""
    mem = load_permanent_memory()
    facts: list[dict] = mem["persona"]["facts"]
    for f in facts:
        if f["key"].lower() == key.lower():
            f["value"] = value
            f["updated_at"] = time.time()
            save_permanent_memory(mem)
            return
    facts.append({
        "key": key,
        "value": value,
        "ts": time.time(),
        "source_session": source_session,
    })
    save_permanent_memory(mem)


def add_session_summary(
    session_id: str, summary: str, key_points: list[str]
) -> None:
    mem = load_permanent_memory()
    mem["session_summaries"].append({
        "session_id": session_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": summary,
        "key_points": key_points,
    })
    # Keep only the last 30 session summaries
    mem["session_summaries"] = mem["session_summaries"][-30:]
    save_permanent_memory(mem)


def build_memory_block() -> str:
    """
    Returns a compact string suitable for injection into the system prompt.
    Empty string if no permanent memory exists yet.
    """
    mem = load_permanent_memory()
    lines: list[str] = []

    facts = mem.get("persona", {}).get("facts", [])
    if facts:
        lines.append("PERMANENT MEMORY — KNOWN FACTS:")
        for f in facts[-15:]:
            lines.append(f"  {f['key']}: {f['value']}")

    summaries = mem.get("session_summaries", [])
    if summaries:
        lines.append("RECENT SESSION CONTEXT:")
        for s in summaries[-3:]:
            points = "  ".join(s.get("key_points", [])[:3])
            lines.append(f"  [{s['date']}] {s['summary']}  {points}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION CONTEXT FILES
# ══════════════════════════════════════════════════════════════════════════════

def create_session_context(session_id: str, model: str) -> dict:
    ctx: dict = {
        "session_id": session_id,
        "started_at": time.time(),
        "ended_at": None,
        "model_used": model,
        "model_history": [],
        "messages": [],          # [{role, content, ts}]
        "context_summary": "",
        "facts_extracted": [],
    }
    _write_context(session_id, ctx)
    return ctx


def _ctx_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def _write_context(session_id: str, ctx: dict) -> None:
    _ctx_path(session_id).write_text(
        json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_session_context(session_id: str) -> dict | None:
    p = _ctx_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def append_message(session_id: str, role: str, content: str) -> None:
    """Append one message to the session context file (non-blocking write)."""
    ctx = load_session_context(session_id)
    if not ctx:
        return
    ctx["messages"].append({"role": role, "content": content, "ts": time.time()})
    _write_context(session_id, ctx)


def update_session_model(session_id: str, new_model: str) -> None:
    ctx = load_session_context(session_id)
    if not ctx:
        return
    ctx["model_history"].append({"model": ctx["model_used"], "switched_at": time.time()})
    ctx["model_used"] = new_model
    _write_context(session_id, ctx)


def get_history_for_model_switch(session_id: str, n: int = 12) -> list[dict]:
    """
    Returns the last N messages from the context file as plain
    {role, content} dicts — used to seed a new model's history
    so conversation continuity is preserved across model switches.
    """
    ctx = load_session_context(session_id)
    if not ctx:
        return []
    msgs = ctx.get("messages", [])
    return [{"role": m["role"], "content": m["content"]} for m in msgs[-n:]]


def list_recent_sessions(limit: int = 20) -> list[dict]:
    files = sorted(
        SESSIONS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out = []
    for f in files[:limit]:
        try:
            ctx = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "session_id": ctx["session_id"],
                "started_at": ctx["started_at"],
                "ended_at": ctx.get("ended_at"),
                "model_used": ctx.get("model_used", "unknown"),
                "message_count": len(ctx.get("messages", [])),
                "summary": ctx.get("context_summary", ""),
            })
        except Exception:
            pass
    return out


# ══════════════════════════════════════════════════════════════════════════════
# SESSION FINALIZATION  (called on disconnect)
# ══════════════════════════════════════════════════════════════════════════════

async def finalize_session(
    session_id: str,
    ollama_base: str,
    model: str,
    anthropic_key: str = "",
) -> None:
    """
    Summarize the session and extract persona facts into permanent memory.
    Runs after the WebSocket disconnects — failures are silent (non-critical).
    """
    ctx = load_session_context(session_id)
    if not ctx or len(ctx.get("messages", [])) < 3:
        # Too short to bother
        if ctx:
            ctx["ended_at"] = time.time()
            _write_context(session_id, ctx)
        return

    messages = ctx["messages"]
    convo = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages[-40:]
    )

    extraction_prompt = (
        "Analyse this conversation and return ONLY a JSON object — no markdown, "
        "no preamble:\n"
        '{\n'
        '  "summary": "2-sentence summary of what was discussed",\n'
        '  "key_points": ["point1", "point2"],\n'
        '  "user_facts": [{"key": "fact name", "value": "fact value"}],\n'
        '  "tasks_mentioned": ["task1"]\n'
        '}\n\n'
        f"Conversation:\n{convo}"
    )

    try:
        extracted: dict = {}

        if anthropic_key:
            import anthropic as ant
            client = ant.Anthropic(api_key=anthropic_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": extraction_prompt}],
            )
            raw = resp.content[0].text
        else:
            async with httpx.AsyncClient(timeout=90.0) as client:
                r = await client.post(
                    f"{ollama_base}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": extraction_prompt}],
                        "stream": False,
                        "think": False,
                        "options": {"num_predict": 500, "temperature": 0.2},
                    },
                )
                raw = r.json()["message"]["content"]

        # Extract JSON — model may add ```json fences
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            extracted = json.loads(match.group())

        # Write to permanent memory
        for fact in extracted.get("user_facts", []):
            if fact.get("key") and fact.get("value"):
                add_permanent_fact(fact["key"], fact["value"], session_id)

        if extracted.get("summary"):
            add_session_summary(
                session_id,
                extracted["summary"],
                extracted.get("key_points", []),
            )

        # Update context file
        ctx["context_summary"] = extracted.get("summary", "")
        ctx["facts_extracted"] = extracted.get("user_facts", [])

    except Exception:
        pass  # finalization is best-effort

    ctx["ended_at"] = time.time()
    _write_context(session_id, ctx)
