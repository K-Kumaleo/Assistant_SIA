// main.ts — SIA v5: model switching, session context, permanent memory

import { SiaWebSocket }                     from "./ws.ts";
import { SpeechRecognizer, AudioPlayer }    from "./voice.ts";
import { OrbVisualizer, OrbState }          from "./orb.ts";
import { initSettingsPanel }                from "./settings.ts";

// ── DOM refs ──────────────────────────────────────────────────────────────────
const canvas          = document.getElementById("orb-canvas")        as HTMLCanvasElement;
const hudDot          = document.getElementById("hud-status-dot")!;
const hudLabel        = document.getElementById("hud-status-label")!;
const hudModelIcon    = document.getElementById("hud-model-icon")!;
const hudModelName    = document.getElementById("hud-model-name")!;
const hudTranscript   = document.getElementById("hud-transcript")!;
const listenIndicator = document.getElementById("listen-indicator")!;
const errorBody       = document.getElementById("error-body")!;
const termBackBody    = document.getElementById("term-backend-body")!;
const termFrontBody   = document.getElementById("term-frontend-body")!;
const taskbar         = document.getElementById("taskbar")!;
const btnReset        = document.getElementById("btn-reset")!;

// ── App state ─────────────────────────────────────────────────────────────────
type AppState = "init"|"idle"|"listening"|"thinking"|"speaking"|"error";
let appState:  AppState = "init";
let echoFilter          = true;
let activeModel         = "";   // currently active model id

// ── Subsystems ────────────────────────────────────────────────────────────────
const orb    = new OrbVisualizer(canvas);
const ws     = new SiaWebSocket(`ws://${location.host}/ws/voice`);
const player = new AudioPlayer();

const recognizer = new SpeechRecognizer(
  (text, isFinal) => {
    if (appState === "speaking" || appState === "thinking") return;
    if (echoFilter && player.isPlaying) return;
    hudTranscript.textContent = `"${text}"`;
    if (isFinal) sendTranscript(text);
  },
  (err) => {
    logError(`Speech: ${err}`);
    logFE(`Speech error: ${err}`, "FE-ERR");
    setState("error");
  },
);

// ── Settings ──────────────────────────────────────────────────────────────────
const settings = initSettingsPanel(
  (s) => { echoFilter = s.echoFilter; },
  (modelId) => switchModel(modelId),
);
echoFilter = settings.echoFilter;

player.onPlayStart = () => setState("speaking");
player.onPlayEnd   = () => setState("listening");

// ── Model HUD helpers ─────────────────────────────────────────────────────────
function updateModelHUD(modelId: string) {
  activeModel = modelId;
  const isCloud = modelId === "claude";
  hudModelIcon.textContent = isCloud ? "☁" : "⬡";
  hudModelName.textContent = isCloud ? "Claude" : modelId;
  hudModelIcon.style.color = isCloud ? "var(--amber)" : "var(--accent)";
}

function switchModel(modelId: string) {
  if (!modelId || modelId === activeModel) return;
  logFE(`Switching brain → ${modelId}`, "FE-WARN");
  ws.send({ type: "set_model", model: modelId });
}

// ══════════════════════════════════════════════════════════════════════════════
// PANEL SYSTEM — draggable, minimisable, closeable, taskbar restore
// ══════════════════════════════════════════════════════════════════════════════

interface PanelState { minimised: boolean; closed: boolean; x: number; y: number; }

const panelStates: Record<string, PanelState> = {
  error:    { minimised: false, closed: false, x: -1, y: -1 },
  terminal: { minimised: false, closed: false, x: -1, y: -1 },
};

const PANEL_NAMES: Record<string, string> = {
  error: "Error Log",
  terminal: "Terminal",
};

function initPanels() {
  document.querySelectorAll<HTMLElement>(".panel").forEach((panel) => {
    const id = panel.dataset.panel!;
    const rect = panel.getBoundingClientRect();
    panelStates[id].x = rect.left;
    panelStates[id].y = rect.top;
    panel.style.left   = rect.left + "px";
    panel.style.top    = rect.top  + "px";
    panel.style.right  = "auto";
    panel.style.bottom = "auto";
    makeDraggable(panel, id);
  });

  document.querySelectorAll<HTMLElement>("[data-action]").forEach((dot) => {
    dot.addEventListener("click", (e) => {
      e.stopPropagation();
      const action = dot.dataset.action!;
      const target = dot.dataset.target!;
      if (action === "minimise") toggleMinimise(target);
      if (action === "close")    closePanel(target);
    });
  });
}

function makeDraggable(panel: HTMLElement, id: string) {
  const handle = panel.querySelector<HTMLElement>(".drag-handle")!;
  let startX = 0, startY = 0, origX = 0, origY = 0;

  handle.addEventListener("mousedown", (e) => {
    if ((e.target as HTMLElement).closest("button, [data-action]")) return;
    e.preventDefault();
    startX = e.clientX; startY = e.clientY;
    origX  = parseInt(panel.style.left) || 0;
    origY  = parseInt(panel.style.top)  || 0;
    panel.classList.add("dragging");
    panel.style.zIndex = "35";

    const onMove = (ev: MouseEvent) => {
      const nx = origX + (ev.clientX - startX);
      const ny = origY + (ev.clientY - startY);
      panel.style.left = Math.max(0, Math.min(nx, window.innerWidth  - panel.offsetWidth))  + "px";
      panel.style.top  = Math.max(0, Math.min(ny, window.innerHeight - panel.offsetHeight)) + "px";
    };
    const onUp = () => {
      panel.classList.remove("dragging");
      panel.style.zIndex = "30";
      panelStates[id].x = parseInt(panel.style.left);
      panelStates[id].y = parseInt(panel.style.top);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup",   onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup",   onUp);
  });
}

function toggleMinimise(id: string) {
  const panel = document.querySelector<HTMLElement>(`.panel[data-panel="${id}"]`);
  if (!panel) return;
  const state = panelStates[id];
  state.minimised = !state.minimised;
  panel.classList.toggle("minimised", state.minimised);
  state.minimised ? addChip(id) : removeChip(id);
}

function closePanel(id: string) {
  const panel = document.querySelector<HTMLElement>(`.panel[data-panel="${id}"]`);
  if (!panel) return;
  panelStates[id].closed    = true;
  panelStates[id].minimised = false;
  panel.classList.add("hidden");
  removeChip(id);
  addChip(id, true);
}

function restorePanel(id: string) {
  const panel = document.querySelector<HTMLElement>(`.panel[data-panel="${id}"]`);
  if (!panel) return;
  panelStates[id].closed    = false;
  panelStates[id].minimised = false;
  panel.classList.remove("hidden", "minimised");
  removeChip(id);
}

function addChip(id: string, isClosed = false) {
  removeChip(id);
  const chip = document.createElement("div");
  chip.className  = "taskbar-chip";
  chip.dataset.chipFor = id;
  chip.innerHTML  = `<span class="chip-dot"></span>${PANEL_NAMES[id]}`;
  chip.title      = isClosed ? "Click to reopen" : "Click to restore";
  chip.addEventListener("click", () => restorePanel(id));
  taskbar.appendChild(chip);
}

function removeChip(id: string) {
  taskbar.querySelector(`[data-chip-for="${id}"]`)?.remove();
}

// ══════════════════════════════════════════════════════════════════════════════
// LOGGING
// ══════════════════════════════════════════════════════════════════════════════

function appendLine(container: HTMLElement, text: string, cls: string) {
  if (!text.trim()) return;
  container.querySelector(".log-ok")?.remove();
  const el = document.createElement("span");
  el.className  = `log-line ${cls}`;
  el.textContent = text.replace(/\x1b\[[0-9;]*m/g, "");
  container.appendChild(el);
  while (container.children.length > 400) container.removeChild(container.firstChild!);
  container.scrollTop = container.scrollHeight;
}

function logError(msg: string) {
  const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
  appendLine(errorBody, `${ts}  ${msg}`, "ERROR");
}

function logFE(msg: string, cls: "FE"|"FE-ERR"|"FE-WARN" = "FE") {
  const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
  appendLine(termFrontBody, `${ts}  ${msg}`, cls);
  if (cls === "FE-ERR") logError(msg);
}

function connectLogWs() {
  const lws = new WebSocket(`ws://${location.host}/ws/logs`);
  lws.onopen    = () => logFE("Backend log stream connected ✓");
  lws.onmessage = (e) => {
    try {
      const m = JSON.parse(e.data);
      if (m.level === "PING") return;
      appendLine(termBackBody, m.msg, m.level);
      if (m.level === "ERROR") logError(m.msg.replace(/^\S+\s\[ERROR\]\s/, ""));
    } catch (_) {}
  };
  lws.onclose = () => {
    logFE("Backend log stream disconnected — retrying…", "FE-WARN");
    setTimeout(connectLogWs, 3000);
  };
}

document.querySelectorAll<HTMLElement>(".term-clear").forEach((btn) => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const t = btn.dataset.target || btn.id;
    if (t === "backend")     termBackBody.innerHTML  = "";
    if (t === "frontend")    termFrontBody.innerHTML = "";
    if (t === "clear-errors" || btn.id === "clear-errors") {
      errorBody.innerHTML = '<span class="log-line log-ok">No errors — all clear ✓</span>';
    }
  });
});
document.getElementById("clear-errors")?.addEventListener("click", (e) => {
  e.stopPropagation();
  errorBody.innerHTML = '<span class="log-line log-ok">No errors — all clear ✓</span>';
});

// ══════════════════════════════════════════════════════════════════════════════
// STATE MACHINE
// ══════════════════════════════════════════════════════════════════════════════
const STATE_LABELS: Record<AppState, string> = {
  init:"Initialising", idle:"Idle", listening:"Listening",
  thinking:"Thinking", speaking:"Speaking", error:"Error",
};

function setState(s: AppState) {
  appState = s;
  const orbState: OrbState =
    s === "thinking" ? "thinking"
    : s === "speaking" ? "speaking"
    : s === "listening" ? "listening"
    : "idle";
  orb.setState(orbState);
  hudDot.className     = s === "error" ? "error" : s;
  hudLabel.textContent = STATE_LABELS[s];
  hudLabel.className   = s === "error" ? "error" : s;
  listenIndicator.className = s === "error" ? "error" : s;
}

// ── Display popup panels ──────────────────────────────────────────────────────
const openPanels: Map<string, Window | null> = new Map();

function showDisplayPanel(panel: Record<string, unknown>) {
  const title = (panel.title as string) || "panel";
  const key   = title.replace(/[^a-z0-9]/gi, "_").toLowerCase();

  const existing = openPanels.get(key);
  if (existing && !existing.closed) {
    const bc = new BroadcastChannel(key);
    bc.postMessage(panel);
    bc.close();
    existing.focus();
    return;
  }

  const popup = window.open(
    `/display.html?id=${key}`,
    `sia_display_${key}`,
    "width=640,height=500,top=80,left=900,toolbar=no,menubar=no,scrollbars=yes",
  );
  openPanels.set(key, popup);

  setTimeout(() => {
    const bc = new BroadcastChannel(key);
    bc.postMessage(panel);
    bc.close();
  }, 400);
}

// ── Voice WebSocket ───────────────────────────────────────────────────────────
ws.on((msg) => {
  switch (msg.type) {
    case "status_change":
      if (!(msg as any).connected) {
        logFE("WebSocket disconnected — reconnecting…", "FE-WARN");
      } else {
        logFE("WebSocket connected to backend ✓");
        // Push the saved model preference to the backend on (re)connect
        const saved = settings.selectedModel;
        if (saved) {
          setTimeout(() => {
            ws.send({ type: "set_model", model: saved });
          }, 300);
        }
      }
      break;

    case "status":
      if ((msg as any).state === "thinking")  setState("thinking");
      if ((msg as any).state === "listening") setState("listening");
      if ((msg as any).state === "reset") {
        hudTranscript.textContent = "";
        setState("listening");
      }
      break;

    case "model_switched": {
      const to = (msg as any).to as string;
      updateModelHUD(to);
      logFE(`Brain switched → ${to}`, "FE-WARN");
      break;
    }

    case "response":
      hudTranscript.textContent = "";
      logFE(`SIA → "${((msg as any).text as string).slice(0, 80)}"`, "FE");
      break;

    case "audio":
      player.enqueue((msg as any).data as string);
      break;

    case "audio_local":
      setState("listening");
      break;

    case "panel_data":
      showDisplayPanel((msg as any).panel as Record<string, unknown>);
      break;

    case "error":
      logError((msg as any).message as string);
      logFE(`Server error: ${(msg as any).message}`, "FE-ERR");
      setState("listening");
      break;
  }
});

function sendTranscript(text: string) {
  if (!text.trim()) return;
  logFE(`You → "${text.slice(0, 60)}"`, "FE");
  ws.send({ type: "transcript", text });
  setState("thinking");
}

btnReset.addEventListener("click", () => {
  ws.send({ type: "reset" });
  hudTranscript.textContent = "";
  logFE("Conversation reset.", "FE-WARN");
});

// ── Start ─────────────────────────────────────────────────────────────────────
let started = false;

async function startSIA() {
  if (started) return;
  started = true;
  player.init();
  await player.resume();
  if (!recognizer.init()) return;
  recognizer.start();
  ws.connect();
  connectLogWs();
  setInterval(() => ws.ping(), 20_000);
  setState("listening");
  logFE("SIA frontend started ✓");

  // Read status to know which brain is active by default
  try {
    const r = await fetch("/api/status");
    const d = await r.json();
    const brain = d.brain ?? (d.claude_configured ? "claude" : "");
    if (brain && !settings.selectedModel) {
      updateModelHUD(brain);
    } else if (settings.selectedModel) {
      updateModelHUD(settings.selectedModel);
    }
  } catch (_) {}
}

document.addEventListener("click", startSIA, { once: true });

window.addEventListener("load", () => {
  setTimeout(initPanels, 100);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.getElementById("settings-panel")?.classList.add("hidden");
  if (e.key === "r" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); btnReset.click(); }
});
