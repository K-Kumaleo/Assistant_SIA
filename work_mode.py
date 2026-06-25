"""
work_mode.py — Persistent Claude Code sessions via `claude -p --continue`
Lets SIA kick off background coding/build tasks.
"""

import subprocess
import threading
import os
import time
from pathlib import Path


_active_sessions: dict[str, dict] = {}
_lock = threading.Lock()


def start_task(task_id: str, prompt: str, working_dir: str | None = None) -> str:
    """
    Start a Claude Code task in a background thread.
    Returns immediately with task_id for status polling.
    """
    cwd = working_dir or str(Path.home() / "Desktop" / "SIA")
    # Windows: ensure path exists
    Path(cwd).mkdir(parents=True, exist_ok=True)

    def run():
        with _lock:
            _active_sessions[task_id] = {
                "status": "running",
                "output": "",
                "started_at": time.time(),
            }
        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True, text=True,
                timeout=300, cwd=cwd
            )
            output = result.stdout.strip() or result.stderr.strip()
            with _lock:
                _active_sessions[task_id]["status"] = "done"
                _active_sessions[task_id]["output"] = output[:2000]
        except subprocess.TimeoutExpired:
            with _lock:
                _active_sessions[task_id]["status"] = "timeout"
                _active_sessions[task_id]["output"] = "Task timed out after 5 minutes."
        except FileNotFoundError:
            with _lock:
                _active_sessions[task_id]["status"] = "error"
                _active_sessions[task_id]["output"] = (
                    "Claude Code not found. Install with: npm install -g @anthropic-ai/claude-code"
                )
        except Exception as e:
            with _lock:
                _active_sessions[task_id]["status"] = "error"
                _active_sessions[task_id]["output"] = str(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return task_id


def get_task_status(task_id: str) -> dict:
    with _lock:
        return dict(_active_sessions.get(task_id, {"status": "not_found", "output": ""}))


def list_tasks() -> list[dict]:
    with _lock:
        return [
            {"id": tid, **info}
            for tid, info in _active_sessions.items()
        ]


def cancel_task(task_id: str) -> bool:
    # Background threads can't be force-killed easily; mark as cancelled
    with _lock:
        if task_id in _active_sessions:
            _active_sessions[task_id]["status"] = "cancelled"
            return True
    return False
