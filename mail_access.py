"""
mail_access.py — Windows Outlook Mail (read-only) via PowerShell COM
Falls back gracefully if Outlook is not installed.
"""

import subprocess


def _run_powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=20
    )
    return result.stdout.strip()


def get_unread_count() -> int:
    script = """
    try {
        $ol = New-Object -ComObject Outlook.Application
        $ns = $ol.GetNamespace("MAPI")
        $inbox = $ns.GetDefaultFolder(6)
        Write-Output $inbox.UnReadItemCount
    } catch { Write-Output "0" }
    """
    try:
        return int(_run_powershell(script).strip())
    except Exception:
        return 0


def get_recent_messages(limit: int = 5) -> list[dict]:
    script = f"""
    try {{
        $ol = New-Object -ComObject Outlook.Application
        $ns = $ol.GetNamespace("MAPI")
        $inbox = $ns.GetDefaultFolder(6)
        $items = $inbox.Items
        $items.Sort("[ReceivedTime]", $true)
        $count = 0
        foreach ($item in $items) {{
            if ($count -ge {limit}) {{ break }}
            $read = if ($item.UnRead) {{ "false" }} else {{ "true" }}
            Write-Output "$($item.Subject)|$($item.SenderName)|$($item.ReceivedTime)|$read"
            $count++
        }}
    }} catch {{ Write-Output "ERROR: $_" }}
    """
    try:
        raw = _run_powershell(script)
        results = []
        for line in raw.splitlines():
            if line.startswith("ERROR") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                results.append({
                    "subject": parts[0].strip(),
                    "sender": parts[1].strip(),
                    "date": parts[2].strip(),
                    "read": parts[3].strip() == "true",
                })
        return results
    except Exception:
        return []


def search_mail(query: str, limit: int = 5) -> list[dict]:
    script = f"""
    try {{
        $ol = New-Object -ComObject Outlook.Application
        $ns = $ol.GetNamespace("MAPI")
        $inbox = $ns.GetDefaultFolder(6)
        $filter = "@SQL=urn:schemas:httpmail:subject LIKE '%{query}%' OR urn:schemas:httpmail:fromname LIKE '%{query}%'"
        $items = $inbox.Items.Restrict($filter)
        $count = 0
        foreach ($item in $items) {{
            if ($count -ge {limit}) {{ break }}
            Write-Output "$($item.Subject)|$($item.SenderName)|$($item.ReceivedTime)"
            $count++
        }}
    }} catch {{ Write-Output "ERROR: $_" }}
    """
    try:
        raw = _run_powershell(script)
        results = []
        for line in raw.splitlines():
            if line.startswith("ERROR") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                results.append({
                    "subject": parts[0].strip(),
                    "sender": parts[1].strip(),
                    "date": parts[2].strip(),
                })
        return results
    except Exception:
        return []


def format_messages_for_voice(messages: list[dict]) -> str:
    if not messages:
        return "No messages found."
    lines = []
    for msg in messages:
        status = "" if msg.get("read") else " [UNREAD]"
        lines.append(f"• {msg['subject']}{status} — from {msg['sender']}")
    return "\n".join(lines)
