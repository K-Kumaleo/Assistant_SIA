# SIA — Structured Intent Agent

A voice-first AI assistant for Windows 11. Speak naturally, and SIA executes actions on your machine, searches the web, manages tasks and memory, and responds with synthesized speech — all running locally with no mandatory cloud dependencies.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [System Requirements](#system-requirements)
- [Dependencies](#dependencies)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running SIA](#running-sia)
- [Usage](#usage)
- [Voice Commands and Actions](#voice-commands-and-actions)
- [Model Selection](#model-selection)
- [Memory System](#memory-system)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Known Limitations](#known-limitations)

---

## Overview

SIA processes voice input through the browser's Web Speech API, sends transcriptions to a FastAPI backend over WebSocket, routes them through a local or cloud language model, executes any embedded action tags in parallel, synthesizes a spoken response via Kokoro TTS, and streams the audio back to the browser.

The assistant has no always-on microphone daemon. It activates within the browser tab and deactivates when the tab is closed or the session ends.

---

## Architecture

```
Browser (Chrome)
  |-- Web Speech API          voice capture / STT
  |-- Three.js orb            visual state indicator
  |-- Vite + TypeScript       frontend shell
  |
  WebSocket /ws/voice
  |
FastAPI Backend (Python)
  |-- session_manager.py      session context files + permanent memory
  |-- server.py               request routing, action dispatch, TTS pipeline
  |-- actions.py              Windows system actions via PowerShell
  |-- browser.py              Playwright web search and browsing
  |-- memory.py               SQLite FTS5 (facts, tasks, notes)
  |
  AI Brain (one of the following, per session)
  |-- Anthropic Claude        cloud, if ANTHROPIC_API_KEY is set
  |-- Ollama (local)          qwen3:4b (primary) / qwen3:1.7b (fast)
  |
  TTS Pipeline
  |-- Kokoro TTS              local neural voices (primary)
  |-- Edge TTS                Microsoft neural voices (fallback)
```

---

## System Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Operating System | Windows 11 | Actions use Win32 APIs and PowerShell |
| Python | 3.11 or newer | 3.12 recommended |
| Node.js | 18 or newer | For the Vite frontend dev server |
| RAM | 8 GB | 16 GB recommended when running 4B models |
| VRAM | 4 GB | For qwen3:4b. 1.7b model runs on CPU |
| Browser | Google Chrome | Required for Web Speech API and microphone access |
| Ollama | Latest | For local LLM inference |

---

## Dependencies

### System-level (install before anything else)

**Ollama**
Local LLM runtime. Download from https://ollama.com/download/windows and run the installer. After installation, open PowerShell and pull the required models:

```powershell
ollama pull qwen3:4b
ollama pull qwen3:1.7b
```

`qwen3:4b` is the primary model (~2.5 GB download). `qwen3:1.7b` is the fast routing model for simple queries (~1 GB).

**espeak-ng**
Phoneme engine required by Kokoro TTS. Install via winget:

```powershell
winget install espeak-ng
```

If winget is unavailable, download the `.msi` installer directly from:
https://github.com/espeak-ng/espeak-ng/releases/latest

After installation, restart your terminal so the `espeak-ng` binary is on `PATH`.

**Playwright browser binaries**
After Python dependencies are installed, run:

```powershell
.venv\Scripts\activate
playwright install chromium
```

This downloads the headless Chromium binary used for web search.

---

### Python packages

All packages are installed automatically by `setup.bat` or via pip. The full list:

| Package | Version | Purpose |
|---|---|---|
| fastapi | >=0.115.0 | Backend web framework |
| uvicorn[standard] | >=0.32.0 | ASGI server |
| httpx | >=0.27.0 | Async HTTP client for Ollama API |
| pydantic | >=2.0.0 | Data validation |
| websockets | >=13.0 | WebSocket support |
| python-dotenv | >=1.0.0 | .env file loading |
| numpy | >=1.26.0 | Audio array processing |
| soundfile | latest | WAV encoding for Kokoro audio |
| kokoro | latest | Local neural TTS engine |
| edge-tts | >=6.1.12 | Microsoft Edge TTS fallback |
| playwright | >=1.40.0 | Headless browser for web search |
| pyyaml | >=6.0 | Config parsing |
| anthropic | >=0.39.0 | Anthropic Claude API (optional) |

To install manually:

```powershell
pip install fastapi "uvicorn[standard]" httpx pydantic websockets python-dotenv numpy soundfile kokoro edge-tts playwright pyyaml
# Optional, for Claude support:
pip install anthropic
```

---

### Frontend packages

Managed by npm. Installed automatically by `setup.bat`.

| Package | Purpose |
|---|---|
| vite | Frontend build tool and dev server |
| typescript | Type checking |
| three | Three.js for the orb visualizer |

---

## Installation

**Step 1 — Clone the repository**

```powershell
git clone https://github.com/your-username/SIA.git
cd SIA
```

**Step 2 — Install system dependencies**

Install Ollama and espeak-ng as described in the [Dependencies](#dependencies) section above. Pull the Ollama models before proceeding.

**Step 3 — Run the setup script**

```powershell
setup.bat
```

This script will:
- Verify Python and Node.js are installed
- Create a Python virtual environment at `.venv`
- Install all Python packages from `requirements.txt`
- Install frontend packages via npm
- Create a `.env` file from the template
- Create the `data/` directory structure

**Step 4 — Install Playwright browsers**

```powershell
.venv\Scripts\activate
playwright install chromium
```

**Step 5 — Configure `.env`**

Open `.env` in a text editor and fill in your values. See [Configuration](#configuration) below.

---

## Configuration

All configuration lives in the `.env` file at the project root.

```env
# Optional: Anthropic Claude API key
# If set, SIA uses Claude as the AI brain by default.
# If not set, SIA uses local Ollama models instead.
ANTHROPIC_API_KEY=

# Optional: ElevenLabs TTS (premium voice synthesis)
# If not set, SIA uses Kokoro TTS (local) with Edge TTS as fallback.
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=hpp4J3VqNfWAUOO0d1Us

# Optional: Your name — SIA will address you by name
USER_NAME=

# Ollama configuration
# Change OLLAMA_BASE if Ollama is running on a different host or port
OLLAMA_BASE=http://localhost:11434
OLLAMA_MODEL_MAIN=qwen3:4b
OLLAMA_MODEL_FAST=qwen3:1.7b

# TTS voice selection
KOKORO_VOICE=af_sarah
EDGE_TTS_VOICE=en-IN-NeerjaNeural
```

**Claude vs Ollama**

SIA automatically selects the AI backend:
- If `ANTHROPIC_API_KEY` is present and valid, Claude is used by default
- If the key is absent or empty, Ollama is used
- The user can override this per-session from the settings panel in the UI

---

## Running SIA

**Option A — Start everything at once**

```powershell
start.bat
```

This opens two terminal windows (backend and frontend) and launches Chrome at `http://localhost:5173`.

**Option B — Start manually in separate terminals**

Terminal 1 (backend):
```powershell
call .venv\Scripts\activate
python server.py
```

Terminal 2 (frontend):
```powershell
cd frontend
npm run dev
```

Then open Chrome at `http://localhost:5173`.

Both terminal windows must remain open while SIA is in use.

---

## Usage

1. Open `http://localhost:5173` in Chrome
2. Click anywhere on the page to initialize the microphone and WebSocket connection
3. The orb and status indicator in the top-left will change to **Listening**
4. Speak your query or command naturally
5. SIA will process the request (status changes to **Thinking**), then respond aloud (status changes to **Speaking**)
6. After speaking, SIA returns to **Listening** automatically

**Keyboard shortcuts**

| Shortcut | Action |
|---|---|
| Ctrl+R | Reset the current conversation |
| Escape | Close the settings panel |

**UI panels**

The interface has two draggable panels:
- **Error Log** — top-right, shows runtime errors
- **SIA Terminal** — bottom-left, shows backend and frontend logs in split view

Panels can be minimised using the yellow dot, closed using the red dot, and restored from the taskbar strip at the bottom. Drag the panel header to reposition.

**Display windows**

When SIA retrieves rich data (search results, stock prices, system info, file lists), it opens a separate popup window for the data. Each data type opens in its own window; the same window is reused if you repeat a similar query. Ensure your browser allows popups from `localhost`.

---

## Voice Commands and Actions

SIA understands natural language. The examples below show the intent — you do not need to use this exact phrasing.

### Application control

| Example phrase | What happens |
|---|---|
| "Open Notepad" | Launches Notepad |
| "Open VS Code" | Launches Visual Studio Code |
| "Open YouTube" | Opens youtube.com in the browser |
| "Minimize Spotify" | Minimizes the Spotify window |
| "Close Chrome" | Closes the Chrome window |
| "List installed apps" | Shows installed apps in a display window |

### System

| Example phrase | What happens |
|---|---|
| "Set volume to 60" | Sets system volume to 60% |
| "What is my system status" | Shows CPU, RAM, disk, battery, uptime |
| "Show running processes" | Lists top processes in a display window |
| "Kill process named notepad" | Terminates the named process |
| "Run ipconfig in terminal" | Executes the command in PowerShell |
| "Press Win + D" | Sends the keyboard shortcut |

### Web and information

| Example phrase | What happens |
|---|---|
| "Search for Python async tutorials" | DuckDuckGo search, results in display window |
| "Latest news on AI" | News results in display window |
| "What is the stock price of TCS" | Fetches TCS.NS, shows panel with price data |
| "What is the price of Apple" | Fetches AAPL |
| "Fetch the page at example.com" | Reads and summarises the webpage |

For Indian stocks, the `.NS` suffix is added automatically (e.g. RELIANCE, TCS, INFY, HDFC).

### Files

| Example phrase | What happens |
|---|---|
| "Open the file at C:\Users\me\notes.txt" | Opens the file with its default app |
| "List files on my Desktop" | Shows Desktop contents in display window |
| "Find files named report" | Searches for matching filenames |

### Memory and tasks

| Example phrase | What happens |
|---|---|
| "Remember that my laptop password is abc123" | Stores to persistent SQLite memory |
| "What do you remember about my password" | Retrieves from memory |
| "Add a task: finish the report" | Creates a task |
| "List my tasks" | Shows all pending tasks |
| "Mark task 3 as done" | Completes task 3 |

### Productivity

| Example phrase | What happens |
|---|---|
| "What is on my calendar today" | Reads Outlook calendar (requires Outlook) |
| "Show my unread emails" | Reads Outlook inbox (requires Outlook) |
| "Create a note titled Meeting — discussed Q3 targets" | Creates a note |
| "Show my notes" | Lists recent notes |
| "Copy hello world to clipboard" | Writes to clipboard |
| "What is in my clipboard" | Reads from clipboard |
| "Send a notification: Build complete" | Windows toast notification |

---

## Model Selection

Open the settings panel using the gear button (bottom-right corner). The **AI Brain** section at the top shows a dropdown listing every model available on your system.

The list is populated by querying the Ollama API at startup. Click the refresh button next to the dropdown to rescan if you have pulled new models since starting SIA.

**Switching models mid-conversation**

Selecting a different model from the dropdown sends a `set_model` message to the backend. The backend loads the last 12 messages from the current session context file and injects them into the new model's history. Conversation continuity is preserved across switches.

The active model is shown in the top-left HUD beneath the status indicator. Cloud models (Claude) show a cloud icon; local models show a hexagon icon.

**Routing logic**

For simple, short queries (greetings, time, single-word commands), SIA automatically routes to the fast lightweight model (`qwen3:1.7b`) to reduce latency. Longer or more complex queries go to the primary model (`qwen3:4b`). This routing is invisible to the user and does not affect the model shown in the dropdown.

---

## Memory System

SIA has three layers of memory:

### 1. In-session history

The last 40 conversation turns are kept in RAM for the active session and passed to the model as context on each request. This layer is lost if the backend is restarted.

### 2. Session context files

Every session creates a JSON file at `data/sessions/<session-id>.json` when the WebSocket connection opens. Every user and assistant message is appended to this file in real time.

Purpose: model switching and crash recovery. If the backend restarts, the file remains and can be used to resume context.

### 3. Permanent memory

When a session ends (WebSocket disconnects), SIA runs a background extraction pass over the full conversation. The model identifies:
- Facts about the user worth retaining (preferences, names, recurring topics)
- A 2-sentence session summary
- Key points from the conversation

These are written to `data/memory/permanent.json`. On every subsequent session, this file's contents are injected into the system prompt so SIA retains long-term knowledge about the user without requiring the user to repeat themselves.

The permanent memory file is human-readable JSON and can be edited or cleared manually if needed.

### SQLite memory

Facts, tasks, and notes stored explicitly via voice commands (`Remember that...`, `Add a task...`, `Create a note...`) are saved to `data/sia.db` with full-text search (FTS5). This database persists independently of sessions and permanent memory.

---

## Project Structure

```
SIA/
|
|-- server.py               FastAPI backend: WebSocket pipeline, AI routing,
|                           action dispatch, TTS, session lifecycle
|-- session_manager.py      Session context files and permanent memory system
|-- actions.py              Windows system actions (app launch, volume,
|                           clipboard, notifications, file ops, shortcuts)
|-- browser.py              Playwright: web search, news, stock prices,
|                           webpage fetching
|-- memory.py               SQLite with FTS5: facts, tasks, notes,
|                           conversation history
|-- calendar_access.py      Outlook calendar integration via COM
|-- mail_access.py          Outlook email integration via COM
|-- notes_access.py         Note creation and retrieval
|-- planner.py              Task planning utilities
|-- work_mode.py            Work session mode features
|
|-- requirements.txt        Python package list
|-- setup.bat               One-time setup script
|-- start.bat               Launch backend + frontend + Chrome
|-- start_backend.bat       Launch backend only
|-- start_frontend.bat      Launch frontend only
|-- .env                    API keys and runtime configuration
|
|-- data/
|   |-- sessions/           Per-session context files (JSON, one per session)
|   |-- memory/
|   |   `-- permanent.json  Long-term persona memory
|   `-- sia.db              SQLite database (facts, tasks, notes)
|
`-- frontend/
    |-- index.html          App shell
    |-- vite.config.ts      Dev server config with WebSocket proxy
    |-- package.json
    `-- src/
        |-- main.ts         App entrypoint, state machine, panel system
        |-- ws.ts           WebSocket client with auto-reconnect
        |-- voice.ts        Web Speech API capture and audio playback
        |-- orb.ts          Three.js animated orb visualizer
        |-- settings.ts     Settings panel and model selector
        |-- style.css       All styles
        `-- public/
            `-- display.html    Popup window for rich data display
```

---

## Troubleshooting

**SIA responds with "One moment." to every query**

The LLM's thinking mode is active despite the `think: false` flag. The system prompt includes `/no_think` to suppress this on Ollama-compatible models. If the problem persists, check that your Ollama version supports qwen3 and is up to date:

```powershell
ollama --version
```

Update Ollama from https://ollama.com/download/windows if needed.

**First query after startup times out**

The model takes 30-70 seconds to load into VRAM on first use. SIA runs a background prewarm on startup, but if the query is sent before the prewarm completes, it may time out. Wait a few seconds after the terminal shows `SIA backend ready` before speaking.

**Voice recognition is not working**

- Chrome must be allowed microphone access for localhost. Check the site settings in Chrome: `chrome://settings/content/microphone`
- Web Speech API requires a non-silent audio environment. Check that your microphone is not muted in Windows sound settings
- The page must be clicked at least once before the microphone activates

**"Ollama isn't responding"**

Ollama must be running before starting the backend. Verify it is active:

```powershell
ollama list
```

If the command fails, start Ollama from the system tray or run:

```powershell
ollama serve
```

**YouTube or web apps are not opening**

YouTube is a website, not a Windows application. SIA opens it via the browser. If it does not open, check that Chrome is installed and is the default browser, or that the website alias resolves correctly in `actions.py`.

**VS Code is triggering a UAC prompt instead of opening**

This occurs if Python's subprocess cannot find `code.exe` in its `PATH`. SIA searches known installation paths. If VS Code was installed to a non-standard location, add the path to `VSCODE_PATH` in `.env` or update the `APP_ALIASES` dictionary in `actions.py`.

**Kokoro TTS warnings about word count mismatch**

These are non-fatal. They indicate that `espeak-ng` is either not installed or not on `PATH`. Install it and restart the backend. Audio will still generate in the meantime using a fallback phoneme method.

**Popup display windows are blocked**

Chrome blocks popups by default. When SIA attempts to open a display window, Chrome will show a blocked popup notification in the address bar. Click it and allow popups from `localhost`. This only needs to be done once.

---

## Known Limitations

- **Windows only.** The action system depends on PowerShell, the Windows registry, Win32 notification APIs, and COM automation for Outlook. It will not function on macOS or Linux.

- **Chrome only.** Web Speech API support is not consistent across browsers. Firefox and Safari do not implement it reliably at the time of writing.

- **Ollama must be running before the backend starts.** There is no automatic restart of Ollama if it crashes mid-session.

- **Outlook integration requires a local Outlook installation.** Web-only Office 365 accounts are not supported.

- **The browser microphone requires user gesture to activate.** Clicking the page once on first load satisfies this requirement.

- **Popup display windows require Chrome popups to be allowed for localhost.** This is a one-time permission.

- **Local models have a cold-start delay.** The first response after launching the backend takes longer while the model loads into memory. Subsequent responses are faster.

- **Session permanent memory extraction runs on disconnect.** If the backend process is killed (not gracefully stopped), the session finalization step will not run and that session's facts will not be extracted into permanent memory.

---

## License

This project is for personal and educational use. Dependencies are subject to their respective licenses. Kokoro TTS is licensed under Apache 2.0. Three.js is licensed under MIT. Ollama and model weights are subject to the terms of their respective providers.
