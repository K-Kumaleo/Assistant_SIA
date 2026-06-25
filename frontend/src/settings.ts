// settings.ts — SIA Settings panel, including live model selector

export interface SiaSettings {
  userName:      string;
  volume:        number;
  echoFilter:    boolean;
  selectedModel: string;   // "claude" | "qwen3:4b" | any Ollama model id
}

export interface ModelInfo {
  id:        string;
  name:      string;
  provider:  "anthropic" | "ollama";
  size_gb:   number | null;
  available: boolean;
}

const STORAGE_KEY = "sia_settings_v2";

// ── Persistence ───────────────────────────────────────────────────────────────

export function loadSettings(): SiaSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...defaultSettings(), ...JSON.parse(raw) };
  } catch (_) {}
  return defaultSettings();
}

export function saveSettings(s: SiaSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

function defaultSettings(): SiaSettings {
  return { userName: "", volume: 80, echoFilter: true, selectedModel: "" };
}

// ── Model discovery ───────────────────────────────────────────────────────────

export async function fetchModels(): Promise<ModelInfo[]> {
  try {
    const r = await fetch("/api/models");
    if (!r.ok) return [];
    const data = await r.json();
    return (data.models ?? []) as ModelInfo[];
  } catch (_) {
    return [];
  }
}

function renderModelOption(m: ModelInfo): string {
  const badge  = m.provider === "anthropic" ? "☁" : "⬡";
  const size   = m.size_gb != null ? ` · ${m.size_gb} GB` : "";
  const dimmed = !m.available ? " (unavailable)" : "";
  return `${badge} ${m.name}${size}${dimmed}`;
}

// ── Panel init ────────────────────────────────────────────────────────────────

export function initSettingsPanel(
  onChanged:      (s: SiaSettings)  => void,
  onModelChanged: (modelId: string) => void,
): SiaSettings {
  const settings = loadSettings();

  const panel      = document.getElementById("settings-panel")!;
  const btnOpen    = document.getElementById("btn-settings")!;
  const btnClose   = document.getElementById("btn-close-settings")!;
  const inputName  = document.getElementById("setting-name")    as HTMLInputElement;
  const inputVol   = document.getElementById("setting-volume")  as HTMLInputElement;
  const inputEcho  = document.getElementById("setting-echo-filter") as HTMLInputElement;
  const modelSel   = document.getElementById("setting-model")   as HTMLSelectElement;
  const modelRefresh = document.getElementById("btn-refresh-models")!;
  const modelStatus  = document.getElementById("model-status")!;

  // Populate non-model fields
  inputName.value  = settings.userName;
  inputVol.value   = String(settings.volume);
  inputEcho.checked = settings.echoFilter;

  // ── Populate model list ───────────────────────────────────────────────────
  async function loadModelList() {
    modelStatus.textContent = "Scanning…";
    modelSel.disabled = true;

    const models = await fetchModels();
    modelSel.innerHTML = "";

    if (models.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No models found";
      modelSel.appendChild(opt);
      modelStatus.textContent = "Could not reach Ollama or Anthropic.";
      modelSel.disabled = false;
      return;
    }

    models.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = renderModelOption(m);
      opt.disabled = !m.available;
      modelSel.appendChild(opt);
    });

    // Restore saved selection, or fall back to first available
    const saved = settings.selectedModel;
    const match = models.find((m) => m.id === saved && m.available);
    modelSel.value = match ? match.id : (models.find((m) => m.available)?.id ?? "");
    settings.selectedModel = modelSel.value;

    modelStatus.textContent = `${models.length} model${models.length === 1 ? "" : "s"} found`;
    modelSel.disabled = false;
  }

  loadModelList();
  modelRefresh.addEventListener("click", loadModelList);

  // ── Event wiring ──────────────────────────────────────────────────────────
  btnOpen.addEventListener("click",  () => panel.classList.toggle("hidden"));
  btnClose.addEventListener("click", () => panel.classList.add("hidden"));

  const sync = () => {
    settings.userName      = inputName.value.trim();
    settings.volume        = Number(inputVol.value);
    settings.echoFilter    = inputEcho.checked;
    saveSettings(settings);
    onChanged(settings);
  };

  inputName.addEventListener("change", sync);
  inputVol.addEventListener("input",  sync);
  inputEcho.addEventListener("change", sync);

  modelSel.addEventListener("change", () => {
    const chosen = modelSel.value;
    if (!chosen) return;
    settings.selectedModel = chosen;
    saveSettings(settings);
    onModelChanged(chosen);
  });

  return settings;
}
