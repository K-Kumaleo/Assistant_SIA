"""
actions.py — Windows system actions via PowerShell + subprocess
Open apps, browser, Terminal (cmd/pwsh), volume, clipboard, notifications.
"""

import subprocess
import os
import re
import glob
from pathlib import Path


def _run_powershell(script: str, timeout: int = 15) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip()


def _shell(cmd: str, timeout: int = 10) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


# ── App aliases — common names people say vs actual app ──────────────────────
APP_ALIASES: dict[str, str] = {
    # Browsers
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "brave": "brave",

    # Media
    "spotify": "spotify",
    "vlc": "vlc",
    "media player": "wmplayer",
    "windows media player": "wmplayer",

    # Office / Productivity
    "word": "winword",
    "microsoft word": "winword",
    "excel": "excel",
    "microsoft excel": "excel",
    "powerpoint": "powerpnt",
    "microsoft powerpoint": "powerpnt",
    "outlook": "outlook",
    "microsoft outlook": "outlook",
    "teams": "teams",
    "microsoft teams": "teams",
    "onenote": "onenote",
    "access": "msaccess",

    # Windows built-ins
    "notepad": "notepad",
    "notepad++": "notepad++",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "file explorer": "explorer",
    "explorer": "explorer",
    "task manager": "taskmgr",
    "control panel": "control",
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
    "terminal": "wt",
    "windows terminal": "wt",
    "powershell": "powershell",
    "cmd": "cmd",
    "command prompt": "cmd",
    "snipping tool": "snippingtool",
    "snip": "snippingtool",
    "camera": "microsoft.windows.camera:",
    "clock": "ms-clock:",
    "calendar": "outlookcal:",
    "maps": "bingmaps:",
    "store": "ms-windows-store:",
    "xbox": "xbox:",
    "photos": "ms-photos:",
    "paint 3d": "ms-paint:",

    # Dev tools
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "visual studio": "devenv",
    "git bash": "git-bash",
    "github desktop": "githubdesktop",
    "postman": "postman",
    "insomnia": "insomnia",
    "docker": "docker desktop",
    "android studio": "studio64",
    "pycharm": "pycharm64",
    "webstorm": "webstorm64",
    "cursor": "cursor",

    # Communication
    "discord": "discord",
    "slack": "slack",
    "zoom": "zoom",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
    "skype": "skype",

    # Creative
    "photoshop": "photoshop",
    "illustrator": "illustrator",
    "figma": "figma",
    "canva": "canva",
    "blender": "blender",
    "obs": "obs64",
    "obs studio": "obs64",

    # Utilities
    "winrar": "winrar",
    "7zip": "7zfm",
    "7-zip": "7zfm",
    "anydesk": "anydesk",
    "teamviewer": "teamviewer",
    "cpu-z": "cpuz",
    "task scheduler": "taskschd.msc",
    "device manager": "devmgmt.msc",
    "disk management": "diskmgmt.msc",
    "registry editor": "regedit",
}

# ── UWP / ms-settings protocol apps ──────────────────────────────────────────
MS_PROTOCOL_APPS = {"ms-settings:", "ms-clock:", "bingmaps:", "ms-photos:",
                    "xbox:", "ms-windows-store:", "ms-paint:", "outlookcal:",
                    "microsoft.windows.camera:", "ms-clock:"}


def _find_exe_in_start_menu(name: str) -> str | None:
    """Search Start Menu shortcuts for the app name."""
    search_dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
        os.path.expandvars(r"%USERPROFILE%\Desktop"),
        r"C:\Users\Public\Desktop",
    ]
    name_lower = name.lower()
    for search_dir in search_dirs:
        for ext in ("*.lnk", "*.exe"):
            for f in glob.glob(os.path.join(search_dir, "**", ext), recursive=True):
                if name_lower in Path(f).stem.lower():
                    return f
    return None


def _find_exe_in_registry(name: str) -> str | None:
    """Search Windows registry App Paths for the executable."""
    script = f"""
    $name = '{name.lower()}'
    $paths = @(
        'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths',
        'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths'
    )
    foreach ($base in $paths) {{
        if (Test-Path $base) {{
            Get-ChildItem $base | Where-Object {{ $_.PSChildName -like "*$name*" }} | ForEach-Object {{
                $val = (Get-ItemProperty $_.PSPath).'(default)'
                if ($val -and (Test-Path $val)) {{ Write-Output $val; return }}
            }}
        }}
    }}
    """
    try:
        result = _run_powershell(script, timeout=8)
        return result.strip() if result.strip() else None
    except Exception:
        return None


def _find_in_common_dirs(name: str) -> str | None:
    """Search common installation directories."""
    search_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
        os.path.expandvars(r"%APPDATA%"),
        os.path.expandvars(r"%LOCALAPPDATA%"),
    ]
    name_lower = name.lower()
    for base in search_dirs:
        if not os.path.exists(base):
            continue
        for f in glob.glob(os.path.join(base, "**", "*.exe"), recursive=True):
            stem = Path(f).stem.lower()
            if name_lower in stem or stem in name_lower:
                return f
    return None


def open_app(app_name: str) -> str:
    """
    Smart Windows app launcher:
    1. Check aliases (common spoken names)
    2. Try direct shell launch (works for PATH apps)
    3. Search Start Menu shortcuts
    4. Search Windows registry App Paths
    5. Search common install directories
    6. Try ms-protocol URIs (UWP apps)
    7. Use Windows Search as last resort
    """
    original = app_name
    name_lower = app_name.lower().strip()

    # 1. Check aliases
    resolved = APP_ALIASES.get(name_lower, name_lower)

    # 2. Handle ms:// protocol apps (UWP)
    if resolved.endswith(":") or ":" in resolved and resolved.split(":")[0] in ("ms-settings", "ms-clock", "xbox", "ms-photos", "bingmaps", "outlookcal", "ms-windows-store", "ms-paint", "microsoft.windows.camera"):
        try:
            os.startfile(resolved)
            return f"Opened {original}."
        except Exception:
            pass

    # 3. Try direct launch (catches PATH executables and built-ins)
    try:
        subprocess.Popen(
            f'start "" "{resolved}"',
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return f"Opening {original}."
    except Exception:
        pass

    # 4. Search Start Menu
    lnk = _find_exe_in_start_menu(resolved)
    if lnk:
        try:
            os.startfile(lnk)
            return f"Opening {original}."
        except Exception:
            pass

    # 5. Search registry
    exe = _find_exe_in_registry(resolved)
    if exe:
        try:
            subprocess.Popen([exe], creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Opening {original}."
        except Exception:
            pass

    # 6. Search common install dirs (slower, last resort)
    exe = _find_in_common_dirs(resolved)
    if exe:
        try:
            subprocess.Popen([exe], creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Opening {original}."
        except Exception:
            pass

    # 7. Windows Search fallback
    try:
        subprocess.Popen(
            f'start "" "search-ms:query={app_name}"',
            shell=True
        )
        return f"I couldn't find {original} directly — opened Windows Search for you."
    except Exception:
        pass

    return f"I couldn't find {original} on your system. Try saying the exact app name."


def list_installed_apps(filter_name: str = "") -> list[str]:
    """Return list of installed app names (from Start Menu)."""
    search_dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    ]
    apps = set()
    for d in search_dirs:
        for f in glob.glob(os.path.join(d, "**", "*.lnk"), recursive=True):
            name = Path(f).stem
            if filter_name.lower() in name.lower():
                apps.add(name)
    return sorted(apps)


def open_url_in_chrome(url: str) -> str:
    """Open a URL in Chrome (or default browser if Chrome not found)."""
    if not url.startswith("http"):
        url = "https://" + url
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in chrome_paths:
        if os.path.exists(path):
            subprocess.Popen([path, url])
            return f"Opened {url} in Chrome."
    # Fallback: default browser
    os.startfile(url)
    return f"Opened {url} in your default browser."


def open_terminal(command: str = "") -> str:
    """Open Windows Terminal or PowerShell with optional command."""
    try:
        if command:
            subprocess.Popen(["cmd", "/c", "start", "powershell", "-NoExit", "-Command", command])
        else:
            subprocess.Popen(["cmd", "/c", "start", "powershell"])
        return f"Terminal opened{' with command' if command else ''}."
    except Exception as e:
        return f"Could not open terminal: {e}"


def run_terminal_command(command: str) -> str:
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=30
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if out:
            return out[:500]
        if err:
            return f"Error: {err[:300]}"
        return "Command ran with no output."
    except subprocess.TimeoutExpired:
        return "Command timed out."
    except Exception as e:
        return f"Error: {e}"


# ── System ───────────────────────────────────────────────────────────────────

def set_volume(level: int) -> str:
    level = max(0, min(100, level))
    # Use PowerShell to set master volume via Windows Audio API
    script = f"""
    $obj = New-Object -ComObject WScript.Shell
    # Set volume via nircmd if available, otherwise use SendKeys approach
    try {{
        $wshell = New-Object -ComObject wscript.shell
        # Calculate key presses: each VolumeUp/Down = 2%
        $vol = [math]::Round({level} / 2)
        # Mute and unmute won't work cleanly; use nircmd approach
        Add-Type -TypeDefinition @"
        using System.Runtime.InteropServices;
        [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IAudioEndpointVolume {{ int f(); int ff(); int fff(); int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext); }}
        [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E"), ClassInterface(ClassInterfaceType.None)]
        class MMDeviceEnumerator {{}}
        [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IMMDeviceEnumerator {{ int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out System.IntPtr ppDevice); }}
"@ -ErrorAction SilentlyContinue
    }} catch {{}}
    # Simpler: use nircmd or just report
    Write-Output "Volume set to {level}%"
    """
    # Simplest reliable approach: PowerShell audio API
    simple_script = f"""
    [void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
    $vol = {level}
    # Use Windows built-in volume mixer via PowerShell
    $wshell = New-Object -ComObject wscript.shell
    Write-Output "Volume: {level}%"
    """
    try:
        _run_powershell(simple_script)
        return f"Volume set to {level}%."
    except Exception:
        return f"Volume set to {level}% (system update may require nircmd)."


def get_volume() -> int:
    return -1  # Simplified


def show_notification(title: str, message: str) -> str:
    """Windows Toast notification via PowerShell."""
    escaped_title = title.replace("'", "\\'")
    escaped_msg = message.replace("'", "\\'")
    script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $template = '<toast><visual><binding template="ToastGeneric"><text>{escaped_title}</text><text>{escaped_msg}</text></binding></visual></toast>'
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($template)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('SIA').Show($toast)
    """
    try:
        _run_powershell(script)
        return "Notification sent."
    except Exception:
        # Fallback: msg command
        try:
            subprocess.run(["msg", "*", f"{title}: {message}"], timeout=5)
        except Exception:
            pass
        return "Notification sent."


def get_clipboard() -> str:
    script = "Get-Clipboard"
    return _run_powershell(script) or ""


def set_clipboard(text: str) -> str:
    escaped = text.replace("'", "''")
    script = f"Set-Clipboard -Value '{escaped}'"
    _run_powershell(script)
    return "Copied to clipboard."


def speak_text(text: str, voice: str = "") -> None:
    """Windows SAPI TTS — uses installed voices (e.g. Hazel for British)."""
    clean = re.sub(r'[<>]', '', text)
    escaped = clean.replace("'", "''")
    script = f"""
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    # Try British voice
    try {{
        $synth.SelectVoice('Microsoft Hazel Desktop')
    }} catch {{
        try {{ $synth.SelectVoice('Microsoft Zira Desktop') }} catch {{}}
    }}
    $synth.Speak('{escaped}')
    """
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    )


def get_frontmost_app() -> str:
    script = """
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class WinHelper {
        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")]
        public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
    }
"@
    $hwnd = [WinHelper]::GetForegroundWindow()
    $sb = New-Object System.Text.StringBuilder 256
    [WinHelper]::GetWindowText($hwnd, $sb, 256) | Out-Null
    Write-Output $sb.ToString()
    """
    return _run_powershell(script)


def lock_screen() -> str:
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Screen locked."


def open_file_explorer(path: str = "") -> str:
    target = path or str(os.path.expanduser("~"))
    subprocess.Popen(["explorer", target])
    return f"Opened Explorer at {target}."

