"""
server.py — SIA Backend
FastAPI + WebSocket voice pipeline.

Brain priority:
  1. Claude (Anthropic) — if ANTHROPIC_API_KEY is set in .env
  2. Ollama local models  — otherwise, or when user switches

New in this version:
  - Auto-detect Claude vs Ollama per session
  - /api/models — discovers all local Ollama models
  - set_model WS message — live model switching with context continuity
  - Session context files + permanent memory (via session_manager)
  - Per-session panel data (no more global list)
  - Parallel action dispatch
  - Kokoro init lock (thread-safe)
  - Prompt cache with 60s TTL
  - History trimmed in-place
  - pick_model uses word-boundary matching
  - prewarm runs on startup
"""

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import soundfile as sf
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Env ───────────────────────────────────────────────────────────────────────
load_dotenv()

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "").strip()
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "hpp4J3VqNfWAUOO0d1Us")
USER_NAME           = os.getenv("USER_NAME", "")
OLLAMA_BASE         = os.getenv("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_MODEL_MAIN   = os.getenv("OLLAMA_MODEL_MAIN", "qwen3:4b")
OLLAMA_MODEL_FAST   = os.getenv("OLLAMA_MODEL_FAST", "qwen3:1.7b")
KOKORO_VOICE        = os.getenv("KOKORO_VOICE", "af_sarah")
EDGE_TTS_VOICE      = os.getenv("EDGE_TTS_VOICE", "en-IN-NeerjaNeural")

USE_CLAUDE = bool(ANTHROPIC_API_KEY)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SIA")

# ── Anthropic client (optional) ───────────────────────────────────────────────
_anthropic_async = None
if USE_CLAUDE:
    try:
        import anthropic as _ant
        _anthropic_async = _ant.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        log.info("Claude (Anthropic) configured as primary brain ✓")
    except ImportError:
        log.warning("anthropic package not installed — falling back to Ollama")
        USE_CLAUDE = False
else:
    log.info("No ANTHROPIC_API_KEY — using Ollama as brain")

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="SIA", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Session state ─────────────────────────────────────────────────────────────
sessions: dict[str, dict] = {}


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        default_model = "claude" if USE_CLAUDE else OLLAMA_MODEL_MAIN
        sessions[session_id] = {
            "id": session_id,
            "history": [],
            "created_at": time.time(),
            "model": default_model,           # active model for this session
            "panel_queue": [],                 # per-session, not global
        }
    return sessions[session_id]


# ── System prompt (cached, 60s TTL) ──────────────────────────────────────────
_prompt_cache: dict[str, Any] = {"text": "", "built_at": 0.0}


def build_system_prompt() -> str:
    from datetime import datetime
    now_ts = time.time()
    if now_ts - _prompt_cache["built_at"] < 60:
        return _prompt_cache["text"]

    # Import here to avoid circular at module load
    from session_manager import build_memory_block

    now = datetime.now()
    hour = now.hour
    tod = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    day_str  = now.strftime("%A, %d %B %Y")
    time_str = now.strftime("%I:%M %p")
    name_line = (
        f"You are speaking with {USER_NAME}. Address them by name occasionally."
        if USER_NAME else ""
    )
    memory_block = build_memory_block()

    prompt = f"""/no_think

You are SIA — Structured Intent Agent.
You are a voice-first AI assistant running on Windows 11.
Personality: calm, precise, witty, warm, impeccably helpful.
You are NOT a British butler — you are a sharp modern AI assistant.

{name_line}

CURRENT TIME CONTEXT:
- It is {tod} — {time_str} on {day_str}

WINDOWS ENVIRONMENT:
- Windows 11. Use Windows terminology (File Explorer not Finder, PowerShell not Terminal).
- File paths use backslashes: C:\\Users\\Kaavya\\Desktop
- Keyboard shortcuts: Win+D desktop, Win+E Explorer.

{memory_block}

RESPONSE RULES:
- Keep responses SHORT — 2-4 sentences max. You are speaking aloud.
- No markdown, no bullet points, no headers. Plain spoken English only.
- Never say "Certainly!", "Of course!", "Great!" — be natural.
- Do not start every response with a greeting. Just answer.

AVAILABLE ACTIONS — embed tags in your reply when needed:
[ACTION:OPEN:<AppName>]            open any Windows app
[ACTION:WINDOW:<App>|<verb>]       maximize/minimize/close/focus a window
[ACTION:LIST_APPS:<filter>]        list installed apps
[ACTION:TERMINAL:<command>]        run PowerShell command
[ACTION:SHORTCUT:<keys>]           send keyboard shortcut (win+d, alt+tab)
[ACTION:SEARCH:<query>]            web search, shows panel
[ACTION:NEWS:<topic>]              latest news, shows panel
[ACTION:STOCK:<symbol>]            stock price (AAPL, RELIANCE.NS, TCS.NS)
[ACTION:FETCH:<url>]               fetch and read a webpage
[ACTION:SYSINFO]                   CPU / RAM / disk / battery / uptime
[ACTION:PROCESS:list]              running processes
[ACTION:PROCESS:kill:<name>]       kill a process
[ACTION:FILE:open:<path>]          open a file
[ACTION:FILE:list:<dir>]           list files
[ACTION:FILE:search:<name>]        search files by name
[ACTION:VOLUME:<0-100>]            set system volume
[ACTION:CLIPBOARD:get]             read clipboard
[ACTION:CLIPBOARD:set:<text>]      write to clipboard
[ACTION:NOTIFY:<title>|<msg>]      Windows notification
[ACTION:CALENDAR]                  Outlook calendar
[ACTION:MAIL]                      Outlook unread emails
[ACTION:NOTES:list]                list notes
[ACTION:NOTES:create:<title>|<body>]  create a note
[ACTION:REMEMBER:<key>|<value>]    store to memory
[ACTION:RECALL:<query>]            search memory
[ACTION:TASKS:add:<title>]         add task
[ACTION:TASKS:list]                list tasks
[ACTION:TASKS:done:<id>]           mark task done

For Indian stocks add .NS: RELIANCE.NS, TCS.NS, INFY.NS
Action tags are processed silently. Embed and continue naturally.
When you don't know something, say so briefly and honestly."""

    _prompt_cache["text"] = prompt
    _prompt_cache["built_at"] = now_ts
    return prompt


# ── Action dispatcher ─────────────────────────────────────────────────────────
ACTION_RE = re.compile(r'\[ACTION:([^\]]+)\]')

# Actions that produce their own spoken response — skip second AI pass
SELF_VOICED_ACTIONS = {
    "OPEN", "WINDOW", "VOLUME", "SHORTCUT", "CLIPBOARD",
    "NOTIFY", "TERMINAL", "FILE", "PROCESS", "REMEMBER",
}

# Simple task keywords — route to lightweight model (word-boundary aware)
_SIMPLE_KW_RE = re.compile(
    r'\b(time|date|weather|stock|open|close|volume|'
    r'search|news|hello|hi|thanks|play|remind|'
    r'note|task|clipboard|mute)\b',
    re.IGNORECASE,
)


def pick_model(user_text: str, session_model: str) -> str:
    """
    Returns the Ollama model to use. Respects the session-level model override.
    Never called when session model is 'claude'.
    """
    if len(user_text) < 80 and _SIMPLE_KW_RE.search(user_text):
        return OLLAMA_MODEL_FAST
    return session_model if session_model != "claude" else OLLAMA_MODEL_MAIN


async def dispatch_action(tag: str, session_id: str) -> str:
    """Process a single [ACTION:...] tag and return the result string."""
    parts = tag.split(":", 1)
    action = parts[0].upper()
    arg    = parts[1] if len(parts) > 1 else ""

    try:
        if action == "CALENDAR":
            from calendar_access import get_events, format_events_for_voice
            events = get_events()
            return format_events_for_voice(events)

        elif action == "MAIL":
            from mail_access import get_recent_messages, get_unread_count, format_messages_for_voice
            count = get_unread_count()
            msgs  = get_recent_messages(5)
            return f"You have {count} unread messages.\n" + format_messages_for_voice(msgs)

        elif action == "NOTES":
            sub = arg.split(":", 1)
            if sub[0] == "list":
                from notes_access import get_recent_notes
                notes = get_recent_notes(5)
                if not notes:
                    return "No notes found."
                return "\n".join(f"• {n['title'] or 'Untitled'}: {n['body'][:80]}" for n in notes)
            elif sub[0] == "create" and len(sub) > 1:
                title_body = sub[1].split("|", 1)
                from notes_access import create_note
                ok = create_note(
                    title_body[0] if title_body else "SIA Note",
                    title_body[1] if len(title_body) > 1 else "",
                )
                return "Note created." if ok else "Could not create note."

        elif action == "OPEN":
            from actions import open_app
            return open_app(arg)

        elif action == "WINDOW":
            from actions import control_window
            p2 = arg.split("|", 1)
            return control_window(p2[0].strip(), p2[1].strip() if len(p2) > 1 else "focus")

        elif action == "LIST_APPS":
            from actions import list_installed_apps
            apps = list_installed_apps(arg)
            return ("No matching apps found." if not apps
                    else "Installed: " + ", ".join(apps[:20]))

        elif action == "OPEN_URL":
            from actions import open_url_in_chrome
            return open_url_in_chrome(arg)

        elif action == "TERMINAL":
            from actions import run_terminal_command
            return run_terminal_command(arg)

        elif action == "SEARCH":
            from browser import search_web, format_search_results_for_voice
            results = await asyncio.get_event_loop().run_in_executor(None, search_web, arg)
            sessions[session_id]["panel_queue"].append({
                "title": f"Search: {arg}", "type": "search", "items": results[:6],
            })
            return format_search_results_for_voice(results)

        elif action == "NEWS":
            from browser import get_news, format_news_for_voice
            topic = arg or "top news today"
            items = await asyncio.get_event_loop().run_in_executor(None, get_news, topic)
            sessions[session_id]["panel_queue"].append({
                "title": f"News: {topic}", "type": "search",
                "items": [{"title": n["title"], "url": n["url"],
                           "snippet": f"{n['source']}  {n['time']}"} for n in items],
            })
            return format_news_for_voice(items)

        elif action == "STOCK":
            from browser import get_stock, format_stock_for_voice
            symbol = arg.upper().strip()
            data = await asyncio.get_event_loop().run_in_executor(None, get_stock, symbol)
            if "error" not in data:
                sessions[session_id]["panel_queue"].append({
                    "title": f"{data.get('name', symbol)} ({symbol})",
                    "type": "stock",
                    "fields": {
                        "Price":   data["price"],
                        "Change":  f"{data['change']} ({data['percent']})",
                        "High":    data["high"], "Low": data["low"],
                        "Volume":  data["volume"], "Mkt Cap": data["mkt_cap"],
                    },
                })
            return format_stock_for_voice(data)

        elif action == "SYSINFO":
            from actions import get_system_info
            info = get_system_info()
            if "error" in info:
                return f"System info error: {info['error']}"
            sessions[session_id]["panel_queue"].append({
                "title": "System Info", "type": "stock",
                "fields": {
                    "CPU":       info.get("cpu", "N/A"),
                    "RAM Used":  info.get("ram_used", "N/A"),
                    "RAM Total": info.get("ram_total", "N/A"),
                    "Disk Free": info.get("disk_free", "N/A"),
                    "Battery":   f"{info.get('battery','N/A')} {info.get('batt_status','')}".strip(),
                    "Uptime":    info.get("uptime", "N/A"),
                },
            })
            return (f"CPU at {info.get('cpu','N/A')}, RAM {info.get('ram_used','N/A')} "
                    f"of {info.get('ram_total','N/A')} used, "
                    f"disk {info.get('disk_free','N/A')} free, "
                    f"up {info.get('uptime','N/A')}.")

        elif action == "PROCESS":
            sub = arg.split(":", 1)
            if sub[0] == "list":
                from actions import get_running_processes
                procs = get_running_processes(sub[1] if len(sub) > 1 else "", top=8)
                sessions[session_id]["panel_queue"].append({
                    "title": "Running Processes", "type": "search",
                    "items": [{"title": p["name"], "url": "",
                               "snippet": f"CPU: {p['cpu']}s  RAM: {p['mem_mb']} MB"} for p in procs],
                })
                return "Top processes: " + ", ".join(f"{p['name']} ({p['mem_mb']}MB)" for p in procs[:5])
            elif sub[0] == "kill" and len(sub) > 1:
                from actions import kill_process
                return kill_process(sub[1].strip())

        elif action == "FILE":
            sub = arg.split(":", 1)
            if sub[0] == "open" and len(sub) > 1:
                from actions import open_file
                return open_file(sub[1].strip())
            elif sub[0] == "list":
                from actions import list_files
                p2 = sub[1].split("|") if len(sub) > 1 else []
                directory = p2[0].strip() if p2 else ""
                files = list_files(directory)
                sessions[session_id]["panel_queue"].append({
                    "title": f"Files: {directory or 'Desktop'}", "type": "search",
                    "items": [{"title": f, "url": "", "snippet": ""} for f in files],
                })
                return f"Found {len(files)} files: " + ", ".join(files[:5])
            elif sub[0] == "search" and len(sub) > 1:
                from actions import search_files
                results = search_files(sub[1].strip())
                sessions[session_id]["panel_queue"].append({
                    "title": f"File search: {sub[1]}", "type": "search",
                    "items": [{"title": r.split("\\")[-1], "url": "", "snippet": r} for r in results],
                })
                return (f"Found {len(results)} files matching '{sub[1]}'."
                        if results else f"No files matching '{sub[1]}'.")

        elif action == "SHORTCUT":
            from actions import send_keyboard_shortcut
            return send_keyboard_shortcut(arg)

        elif action == "VOLUME":
            from actions import set_volume
            try:
                return set_volume(int(arg))
            except ValueError:
                return "Invalid volume level."

        elif action == "CLIPBOARD":
            from actions import get_clipboard, set_clipboard
            if arg == "get":
                return get_clipboard() or "Clipboard is empty."
            elif arg.startswith("set:"):
                return set_clipboard(arg[4:])

        elif action == "NOTIFY":
            from actions import show_notification
            p2 = arg.split("|", 1)
            return show_notification(p2[0], p2[1] if len(p2) > 1 else "")

        elif action == "REMEMBER":
            from memory import upsert_fact
            kv = arg.split("|", 1)
            if len(kv) == 2:
                upsert_fact(kv[0].strip(), kv[1].strip())
                return f"Remembered: {kv[0]}."
            return "Could not store fact."

        elif action == "RECALL":
            from memory import search_facts
            facts = search_facts(arg)
            if not facts:
                return "Nothing found in memory."
            return "\n".join(f"{f['key']}: {f['value']}" for f in facts)

        elif action == "TASKS":
            sub = arg.split(":", 1)
            if sub[0] == "list":
                from memory import get_tasks
                tasks = get_tasks(limit=10)
                if not tasks:
                    return "No tasks."
                return "\n".join(f"[{t['id']}] {t['title']} ({t['status']})" for t in tasks)
            elif sub[0] == "add" and len(sub) > 1:
                from memory import add_task
                return f"Task added (id {add_task(sub[1].strip())})."
            elif sub[0] == "done" and len(sub) > 1:
                from memory import update_task_status
                update_task_status(int(sub[1]), "done")
                return "Task marked complete."

    except Exception as e:
        log.error(f"Action {action} error: {e}")
        return f"Action failed: {e}"

    return f"Unknown action: {action}"


async def process_actions(text: str, session_id: str) -> tuple[str, list[str]]:
    """
    Strip [ACTION:...] tags, run them in parallel where possible,
    return (clean_text, [result_strings]).
    """
    tags  = ACTION_RE.findall(text)
    clean = ACTION_RE.sub("", text).strip()
    clean = re.sub(r'\s+', ' ', clean)

    if not tags:
        return clean, []

    # Run all action tags concurrently
    results = await asyncio.gather(
        *[dispatch_action(t, session_id) for t in tags],
        return_exceptions=True,
    )
    valid = [r for r in results if isinstance(r, str) and r]
    return clean, valid


# ── TTS — Kokoro → Edge → SAPI ───────────────────────────────────────────────
_kokoro_pipeline = None
_kokoro_lock = asyncio.Lock()     # prevents double-init


async def _get_kokoro():
    global _kokoro_pipeline
    if _kokoro_pipeline is not None:
        return _kokoro_pipeline
    async with _kokoro_lock:
        if _kokoro_pipeline is not None:        # double-check after acquiring
            return _kokoro_pipeline
        def _load():
            from kokoro import KPipeline
            return KPipeline(lang_code='a')
        try:
            _kokoro_pipeline = await asyncio.get_event_loop().run_in_executor(None, _load)
            log.info("Kokoro TTS pipeline loaded.")
        except Exception as e:
            log.warning(f"Kokoro load failed: {e}")
    return _kokoro_pipeline


async def tts_kokoro(text: str) -> bytes | None:
    pipeline = await _get_kokoro()
    if not pipeline:
        return None
    try:
        def _gen():
            chunks = [audio for _, _, audio in pipeline(text, voice=KOKORO_VOICE, speed=1.05)]
            return np.concatenate(chunks) if chunks else None

        audio = await asyncio.get_event_loop().run_in_executor(None, _gen)
        if audio is None:
            return None
        buf = io.BytesIO()
        sf.write(buf, audio, 24000, format="WAV")
        return buf.getvalue()
    except Exception as e:
        log.warning(f"Kokoro TTS error: {e}")
        return None


async def tts_edge(text: str) -> bytes | None:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks) if chunks else None
    except Exception as e:
        log.warning(f"Edge TTS failed: {e}")
        return None


async def synthesize_and_send(ws: WebSocket, text: str) -> None:
    audio = await tts_kokoro(text)
    if audio:
        await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "format": "wav"})
        log.info("TTS: Kokoro")
        return
    audio = await tts_edge(text)
    if audio:
        await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "format": "mp3"})
        log.info("TTS: Edge fallback")
        return
    log.warning("TTS: all engines failed")
    await ws.send_json({"type": "audio_local", "text": text})


# ── Echo filter ───────────────────────────────────────────────────────────────
_recent_sia_phrases: list[str] = []
MAX_ECHO_CACHE = 5


def is_echo(text: str) -> bool:
    t = text.lower().strip()
    return any(t in p or p[:40] in t for p in _recent_sia_phrases)


def cache_sia_phrase(text: str) -> None:
    _recent_sia_phrases.append(text.lower().strip())
    if len(_recent_sia_phrases) > MAX_ECHO_CACHE:
        _recent_sia_phrases.pop(0)


# ── AI response ───────────────────────────────────────────────────────────────
TRIVIAL = {
    "one moment.", "one moment", "just a moment.", "sure!", "of course!",
    "certainly!", "okay.", "ok.", "alright.", "sure thing.", "",
}


def clean_llm(text: str) -> str:
    text = re.sub(r'<think>[\s\S]*?</think>', '', text)
    text = re.sub(r'<think>[\s\S]*', '', text)
    return text.strip()


async def _get_claude_response(session_id: str, user_text: str) -> str:
    if not _anthropic_async:
        return "Claude is not configured. Add ANTHROPIC_API_KEY to .env."
    import anthropic as _ant
    session = get_session(session_id)
    history = session["history"]
    history.append({"role": "user", "content": user_text})
    # Trim history in-place (prevent unbounded growth)
    if len(history) > 40:
        session["history"] = history[-40:]
        history = session["history"]

    try:
        resp = await _anthropic_async.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=build_system_prompt(),
            messages=history[-20:],
        )
        reply = resp.content[0].text
        history.append({"role": "assistant", "content": reply})
        log.info(f"[claude] used for: {user_text[:40]}")
        return reply
    except _ant.AuthenticationError:
        return "Claude authentication failed. Check ANTHROPIC_API_KEY."
    except _ant.RateLimitError:
        return "Claude rate limit hit. Try again shortly."
    except Exception as e:
        log.error(f"Claude error: {e}")
        return f"Claude error — check console."


async def _get_ollama_response(session_id: str, user_text: str, model: str) -> str:
    session = get_session(session_id)
    history = session["history"]

    # Trim in-place
    if len(history) > 40:
        session["history"] = history[-40:]
        history = session["history"]

    actual_model = pick_model(user_text, model)
    payload = {
        "model": actual_model,
        "messages": [{"role": "system", "content": build_system_prompt()}] + history[-20:] +
                    [{"role": "user", "content": user_text}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 300, "temperature": 0.7},
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=80.0) as client:
                r = await client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
                r.raise_for_status()

            raw   = r.json()["message"]["content"]
            reply = clean_llm(raw)
            log.info(f"RAW [{actual_model}]: {repr(raw[:160])}")

            if reply.lower().strip().rstrip('.') in TRIVIAL or len(reply) < 8:
                log.warning(f"Trivial on attempt {attempt+1}: {repr(reply)}")
                if attempt < 2:
                    payload["messages"][-1]["content"] = (
                        f"{user_text}. Respond directly in plain English."
                    )
                    await asyncio.sleep(0.5)
                    continue
                reply = "I'm SIA, your local AI assistant. How can I help?"

            history.append({"role": "user",      "content": user_text})
            history.append({"role": "assistant", "content": reply})
            log.info(f"[{actual_model}] → {user_text[:40]}")
            return reply

        except httpx.ConnectError:
            if attempt < 2:
                await asyncio.sleep(3)
                continue
            return "Ollama isn't responding. Run: ollama serve"
        except Exception as e:
            log.error(f"Ollama error: {type(e).__name__}: {e}")
            return "Model error — check backend console."

    return "I had trouble processing that. Try again."


async def get_ai_response(session_id: str, user_text: str) -> str:
    """Route to Claude or Ollama based on session model preference."""
    session = get_session(session_id)
    model   = session.get("model", "claude" if USE_CLAUDE else OLLAMA_MODEL_MAIN)

    if model == "claude":
        return await _get_claude_response(session_id, user_text)
    else:
        return await _get_ollama_response(session_id, user_text, model)


# ── Model discovery ───────────────────────────────────────────────────────────
async def discover_models() -> list[dict]:
    """
    Returns all available models: Claude (if key set) + all Ollama models found.
    """
    models: list[dict] = []

    if USE_CLAUDE:
        models.append({
            "id": "claude",
            "name": "Claude (Anthropic)",
            "provider": "anthropic",
            "size_gb": None,
            "available": True,
        })

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    size_bytes = m.get("size", 0)
                    models.append({
                        "id":        m["name"],
                        "name":      m["name"],
                        "provider":  "ollama",
                        "size_gb":   round(size_bytes / 1e9, 1) if size_bytes else None,
                        "available": True,
                    })
    except Exception as e:
        log.warning(f"Ollama model discovery failed: {e}")
        # Fallback: show configured defaults so UI isn't empty
        for mid in [OLLAMA_MODEL_MAIN, OLLAMA_MODEL_FAST]:
            if not any(m["id"] == mid for m in models):
                models.append({"id": mid, "name": mid, "provider": "ollama",
                               "size_gb": None, "available": False})

    return models


# ── Startup / prewarm ─────────────────────────────────────────────────────────
async def prewarm_ollama() -> None:
    log.info(f"Pre-warming {OLLAMA_MODEL_MAIN}…")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": OLLAMA_MODEL_MAIN,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 3},
                },
            )
        log.info(f"Ollama pre-warm done ✓ ({OLLAMA_MODEL_MAIN})")
    except Exception as e:
        log.warning(f"Pre-warm skipped: {e}")


_main_loop: asyncio.AbstractEventLoop | None = None


@app.on_event("startup")
async def on_startup():
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    from memory import init_db
    init_db()
    # Pre-warm only if not using Claude as primary
    if not USE_CLAUDE:
        asyncio.create_task(prewarm_ollama())
    log.info("SIA backend ready ✓")


# ── WebSocket voice handler ───────────────────────────────────────────────────
@app.websocket("/ws/voice")
async def voice_ws(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid.uuid4())
    log.info(f"New voice session: {session_id}")

    # Create session context file
    from session_manager import create_session_context, append_message, update_session_model

    session = get_session(session_id)
    create_session_context(session_id, session["model"])

    try:
        while True:
            data     = await ws.receive_json()
            msg_type = data.get("type")

            # ── Model switch ──────────────────────────────────────────────────
            if msg_type == "set_model":
                new_model = data.get("model", "").strip()
                if not new_model:
                    continue
                old_model = session["model"]
                session["model"] = new_model

                # Restore history from context file so new model has continuity
                from session_manager import get_history_for_model_switch
                ctx_history = get_history_for_model_switch(session_id, n=12)
                if ctx_history:
                    session["history"] = ctx_history

                update_session_model(session_id, new_model)
                log.info(f"[{session_id[:8]}] Model switched: {old_model} → {new_model}")
                await ws.send_json({
                    "type": "model_switched",
                    "from": old_model,
                    "to":   new_model,
                })
                continue

            # ── Ping ─────────────────────────────────────────────────────────
            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
                continue

            # ── Reset ────────────────────────────────────────────────────────
            if msg_type == "reset":
                session["history"] = []
                await ws.send_json({"type": "status", "state": "reset"})
                continue

            # ── Transcript ───────────────────────────────────────────────────
            if msg_type != "transcript":
                continue

            user_text = data.get("text", "").strip()
            if not user_text or len(user_text) < 2:
                continue
            if is_echo(user_text):
                log.debug(f"Echo filtered: {user_text[:50]}")
                continue

            log.info(f"[{session_id[:8]}] User: {user_text}")
            append_message(session_id, "user", user_text)
            await ws.send_json({"type": "status", "state": "thinking"})

            try:
                raw_reply = await asyncio.wait_for(
                    get_ai_response(session_id, user_text),
                    timeout=100.0,
                )

                clean_reply, action_results = await process_actions(raw_reply, session_id)

                if action_results:
                    action_type = ACTION_RE.findall(raw_reply)
                    is_simple   = all(
                        t.split(":")[0].upper() in SELF_VOICED_ACTIONS
                        for t in action_type
                    )
                    if is_simple:
                        # Don't waste an Ollama call — use the action result directly
                        clean_reply = clean_reply or " ".join(action_results)
                    else:
                        # Data-returning action — ask AI to voice it naturally
                        followup = (
                            f"Data retrieved:\n{chr(10).join(action_results)}\n\n"
                            "Summarise this in 1-2 spoken sentences as SIA."
                        )
                        try:
                            final = await asyncio.wait_for(
                                get_ai_response(session_id, followup),
                                timeout=60.0,
                            )
                            final_clean, _ = await process_actions(final, session_id)
                            clean_reply = final_clean or " ".join(action_results)
                        except asyncio.TimeoutError:
                            clean_reply = " ".join(action_results)

                if not clean_reply:
                    clean_reply = "Done."

                log.info(f"[{session_id[:8]}] SIA: {clean_reply[:80]}")
                cache_sia_phrase(clean_reply)
                append_message(session_id, "assistant", clean_reply)

                await ws.send_json({"type": "response", "text": clean_reply})

                # Flush per-session panel queue
                for panel in session.get("panel_queue", []):
                    await ws.send_json({"type": "panel_data", "panel": panel})
                session["panel_queue"].clear()

                await synthesize_and_send(ws, clean_reply)

            except asyncio.TimeoutError:
                log.error(f"[{session_id[:8]}] AI response timed out")
                msg = "That took too long. Please try again."
                await ws.send_json({"type": "response", "text": msg})
                await ws.send_json({"type": "audio_local", "text": msg})
            except Exception as e:
                log.error(f"[{session_id[:8]}] Handler error: {type(e).__name__}: {e}")
                await ws.send_json({"type": "response", "text": f"Error — check the console."})

            await ws.send_json({"type": "status", "state": "listening"})

    except WebSocketDisconnect:
        log.info(f"Session disconnected: {session_id}")
    except Exception as e:
        log.error(f"WS fatal error: {e}")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # Finalize session (extract facts → permanent memory) — background task
        final_model = sessions.get(session_id, {}).get("model", OLLAMA_MODEL_MAIN)
        asyncio.create_task(
            _finalize(session_id, final_model)
        )


async def _finalize(session_id: str, model: str) -> None:
    from session_manager import finalize_session
    await finalize_session(session_id, OLLAMA_BASE, model, ANTHROPIC_API_KEY)


# ── Live log streaming ────────────────────────────────────────────────────────
_log_buffer: list[dict]       = []
_log_subscribers: list[WebSocket] = []
MAX_LOG_BUFFER = 200


class WSLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        try:
            entry = {"ts": record.created, "level": record.levelname,
                     "msg": self.format(record)}
            _log_buffer.append(entry)
            if len(_log_buffer) > MAX_LOG_BUFFER:
                _log_buffer.pop(0)
            if _main_loop and _main_loop.is_running():
                for sub in list(_log_subscribers):
                    _main_loop.call_soon_threadsafe(
                        asyncio.ensure_future, _safe_log_send(sub, entry)
                    )
        except Exception:
            pass


async def _safe_log_send(ws: WebSocket, entry: dict):
    try:
        await ws.send_json(entry)
    except Exception:
        _log_subscribers.discard(ws) if hasattr(_log_subscribers, 'discard') else None


_ws_log_handler = WSLogHandler()
_ws_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_ws_log_handler)
for _n in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    logging.getLogger(_n).addHandler(_ws_log_handler)


@app.websocket("/ws/logs")
async def logs_ws(ws: WebSocket):
    await ws.accept()
    _log_subscribers.append(ws)
    try:
        for entry in list(_log_buffer[-150:]):
            await ws.send_json(entry)
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=25)
            except asyncio.TimeoutError:
                await ws.send_json({"level": "PING", "msg": "", "ts": time.time()})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if ws in _log_subscribers:
            _log_subscribers.remove(ws)


# ── REST API ──────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    return {
        "status": "ok",
        "version": "2.0.0",
        "brain": "claude" if USE_CLAUDE else "ollama",
        "claude_configured": USE_CLAUDE,
        "active_sessions": len(sessions),
    }


@app.get("/api/models")
async def list_models():
    """Return all available models (Claude + local Ollama models)."""
    models = await discover_models()
    return {"models": models}


@app.get("/api/memory/permanent")
async def get_permanent_memory():
    from session_manager import load_permanent_memory
    return load_permanent_memory()


@app.get("/api/sessions")
async def list_sessions():
    from session_manager import list_recent_sessions
    return {"sessions": list_recent_sessions(20)}


@app.get("/api/memory/facts")
async def list_facts():
    from memory import all_facts
    return {"facts": all_facts()}


@app.post("/api/memory/facts")
async def add_fact(payload: dict):
    from memory import upsert_fact
    key   = payload.get("key", "")
    value = payload.get("value", "")
    if not key or not value:
        raise HTTPException(400, "key and value required")
    upsert_fact(key, value)
    return {"status": "saved"}


@app.get("/api/tasks")
async def list_tasks():
    from memory import get_tasks
    return {"tasks": get_tasks()}


@app.post("/api/tasks")
async def create_task(payload: dict):
    from memory import add_task
    title = payload.get("title", "")
    if not title:
        raise HTTPException(400, "title required")
    return {"id": add_task(title, payload.get("description", ""))}


@app.get("/api/calendar")
async def get_calendar():
    from calendar_access import get_events
    return {"events": get_events()}


@app.get("/api/mail")
async def get_mail():
    from mail_access import get_unread_count, get_recent_messages
    return {"unread": get_unread_count(), "messages": get_recent_messages(5)}


# ── Serve frontend dist ───────────────────────────────────────────────────────
dist_path = Path(__file__).parent / "frontend" / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        from calendar_access import start_background_refresh
        start_background_refresh()
    except Exception:
        pass

    log.info("Starting SIA backend on http://localhost:8340")
    uvicorn.run("server:app", host="127.0.0.1", port=8340, reload=False, log_level="info")
