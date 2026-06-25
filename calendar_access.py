"""
calendar_access.py — Windows Calendar via PowerShell + Outlook COM
Reads events from Outlook calendar with background cache refresh.
Falls back gracefully if Outlook is not installed.
"""

import subprocess
import threading
import time

_cache: dict = {"events": [], "ts": 0}
_lock = threading.Lock()
CACHE_TTL = 300


def _run_powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=20
    )
    return result.stdout.strip()


def _fetch_events_raw(days_ahead: int = 7) -> list[dict]:
    script = f"""
    try {{
        $outlook = New-Object -ComObject Outlook.Application
        $ns = $outlook.GetNamespace("MAPI")
        $cal = $ns.GetDefaultFolder(9)
        $items = $cal.Items
        $items.IncludeRecurrences = $true
        $items.Sort("[Start]")
        $start = Get-Date
        $end = $start.AddDays({days_ahead})
        $filter = "[Start] >= '$($start.ToString('MM/dd/yyyy HH:mm'))' AND [Start] <= '$($end.ToString('MM/dd/yyyy HH:mm'))'"
        $filtered = $items.Restrict($filter)
        foreach ($item in $filtered) {{
            $loc = if ($item.Location) {{ $item.Location }} else {{ "" }}
            Write-Output "$($item.Subject)|$($item.Start)|$($item.End)|$loc"
        }}
    }} catch {{
        Write-Output "ERROR: $_"
    }}
    """
    try:
        raw = _run_powershell(script)
        events = []
        for line in raw.splitlines():
            if line.startswith("ERROR") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                events.append({
                    "title": parts[0].strip(),
                    "start": parts[1].strip(),
                    "end": parts[2].strip(),
                    "location": parts[3].strip() if len(parts) > 3 else "",
                    "calendar": "Outlook",
                })
        return events
    except Exception:
        return []


def _refresh_cache():
    events = _fetch_events_raw()
    with _lock:
        _cache["events"] = events
        _cache["ts"] = time.time()


def get_events(days_ahead: int = 7, force_refresh: bool = False) -> list[dict]:
    with _lock:
        age = time.time() - _cache["ts"]
        cached = _cache["events"]
    if force_refresh or age > CACHE_TTL or not cached:
        _refresh_cache()
        with _lock:
            return _cache["events"]
    return cached


def get_today_events() -> list[dict]:
    return get_events()[:5]


def format_events_for_voice(events: list[dict]) -> str:
    if not events:
        return "No upcoming events found."
    lines = []
    for ev in events[:8]:
        loc = f" at {ev['location']}" if ev.get("location") else ""
        lines.append(f"• {ev['title']} — {ev['start']}{loc}")
    return "\n".join(lines)


def start_background_refresh():
    def loop():
        while True:
            try:
                _refresh_cache()
            except Exception:
                pass
            time.sleep(CACHE_TTL)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
