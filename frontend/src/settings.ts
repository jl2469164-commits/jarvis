/**
 * JARVIS — Settings Panel
 *
 * Overlay panel for API keys, connection status, preferences, and system info.
 * Slides in from the right with glass-morphism styling.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface VoiceConfig {
  ready: boolean;
  model_dir: string;
  repo: string;
  prompt_wav: string;
  prompt_text: string;
  speaker: string;
  device: string;
}

interface StatusResponse {
  claude_code_installed: boolean;
  server_port: number;
  uptime_seconds: number;
  env_keys_set: {
    cosyvoice: boolean;
    user_name: string;
  };
  voice?: VoiceConfig;
}

interface PreferencesResponse {
  user_name: string;
  honorific: string;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let panelEl: HTMLElement | null = null;
let isOpen = false;
let isFirstTimeSetup = false;
let setupStep = 0; // 0=voice, 1=name, 2=done

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiGet<T>(url: string): Promise<T> {
  const res = await fetch(url);
  return res.json();
}

async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

// ---------------------------------------------------------------------------
// Panel HTML
// ---------------------------------------------------------------------------

function buildPanelHTML(): string {
  return `
    <div class="settings-backdrop" id="settings-backdrop"></div>
    <div class="settings-panel" id="settings-panel-inner">
      <div class="settings-header">
        <h2>Settings</h2>
        <button class="settings-close" id="settings-close">&times;</button>
      </div>

      <div class="settings-welcome" id="settings-welcome" style="display:none">
        <p>Welcome to JARVIS. Let's get you set up.</p>
      </div>

      <div class="settings-body">

        <!-- Local voice -->
        <section class="settings-section" id="section-voice">
          <h3>Voice (CosyVoice)</h3>
          <p class="settings-hint">Local model. On a Mac, use cpu. It is slow. Weights are not downloaded from this page. See docs/cosyvoice.md.</p>

          <div class="settings-field">
            <label>Model directory</label>
            <input type="text" id="input-cosy-model" placeholder="/Users/you/models/CosyVoice2-0.5B" />
          </div>

          <div class="settings-field">
            <label>CosyVoice checkout</label>
            <input type="text" id="input-cosy-repo" placeholder="/Users/you/src/CosyVoice" />
          </div>

          <div class="settings-field">
            <label>Prompt wav</label>
            <input type="text" id="input-cosy-prompt-wav" placeholder="/Users/you/models/jarvis-prompt.wav" />
          </div>

          <div class="settings-field">
            <label>Prompt transcript</label>
            <input type="text" id="input-cosy-prompt-text" placeholder="The words spoken in that wav" />
          </div>

          <div class="settings-field">
            <label>Speaker id (optional, instead of a prompt wav)</label>
            <input type="text" id="input-cosy-speaker" placeholder="leave blank for zero-shot" />
          </div>

          <div class="settings-field">
            <label>Device</label>
            <select id="input-cosy-device">
              <option value="cpu">cpu (Mac-safe, slow)</option>
              <option value="mps">mps (Apple Silicon, best-effort)</option>
              <option value="cuda">cuda (NVIDIA)</option>
            </select>
          </div>

          <div class="settings-actions">
            <button class="settings-btn primary" id="btn-save-voice" type="button">Save voice</button>
            <button class="settings-btn" id="btn-test-cosyvoice" type="button">Test CosyVoice</button>
            <span class="status-dot" id="status-cosyvoice"></span>
          </div>
          <p class="settings-hint" id="voice-test-result"></p>
          <p class="settings-restart-notice" id="keys-restart-notice" style="display:none">
            Saved. Restart the server (menu &rarr; Restart Server) before speaking.
          </p>
        </section>

        <!-- Connection Status -->
        <section class="settings-section" id="section-status">
          <h3>Connection Status</h3>
          <div class="status-grid">
            <div class="status-row"><span class="status-dot" id="status-claude-cli"></span><span>Claude Code CLI</span></div>
            <div class="status-row"><span class="status-dot" id="status-server"></span><span>Server</span><span class="status-detail" id="status-server-detail"></span></div>
          </div>
        </section>

        <!-- User Preferences -->
        <section class="settings-section" id="section-preferences">
          <h3>User Preferences</h3>

          <div class="settings-field">
            <label>Your Name</label>
            <input type="text" id="input-user-name" placeholder="Your name" />
          </div>

          <div class="settings-field">
            <label>Honorific</label>
            <select id="input-honorific">
              <option value="sir">Sir</option>
              <option value="ma'am">Ma'am</option>
              <option value="none">None</option>
            </select>
          </div>

          <div class="settings-actions">
            <button class="settings-btn primary" id="btn-save-prefs">Save Preferences</button>
          </div>
        </section>

        <!-- System Info -->
        <section class="settings-section" id="section-sysinfo">
          <h3>System Info</h3>
          <div class="sysinfo-grid">
            <div class="sysinfo-row"><span class="sysinfo-label">Server port</span><span id="sysinfo-port">--</span></div>
            <div class="sysinfo-row"><span class="sysinfo-label">Uptime</span><span id="sysinfo-uptime">--</span></div>
          </div>
        </section>

        <!-- Setup Navigation (first-time only) -->
        <div class="setup-nav" id="setup-nav" style="display:none">
          <button class="settings-btn primary" id="btn-setup-next">Next</button>
        </div>

      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Panel lifecycle
// ---------------------------------------------------------------------------

function createPanel(): HTMLElement {
  const container = document.createElement("div");
  container.id = "settings-container";
  container.innerHTML = buildPanelHTML();
  document.body.appendChild(container);
  return container;
}

function setDotStatus(id: string, status: "green" | "red" | "yellow" | "off") {
  const dot = document.getElementById(id);
  if (!dot) return;
  dot.className = "status-dot";
  if (status !== "off") dot.classList.add(`status-${status}`);
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

async function loadStatus() {
  try {
    const status = await apiGet<StatusResponse>("/api/settings/status");

    setDotStatus("status-claude-cli", status.claude_code_installed ? "green" : "red");
    setDotStatus("status-server", "green");

    const serverDetail = document.getElementById("status-server-detail");
    if (serverDetail) serverDetail.textContent = `port ${status.server_port} | up ${formatUptime(status.uptime_seconds)}`;

    setDotStatus("status-cosyvoice", status.env_keys_set.cosyvoice ? "green" : "red");
    fillVoiceFields(status.voice);

    // System info
    const portEl = document.getElementById("sysinfo-port");
    if (portEl) portEl.textContent = String(status.server_port);
    const upEl = document.getElementById("sysinfo-uptime");
    if (upEl) upEl.textContent = formatUptime(status.uptime_seconds);

    return status;
  } catch (e) {
    console.error("[settings] failed to load status:", e);
    // EVERY dot, not just the server's. The CLI and voice dots are drawn from
    // fields of the answer that never arrived, so leaving them green states
    // as fact something this call failed to find out. "off" is the absence
    // of a reading, which is what we have.
    setDotStatus("status-server", "red");
    setDotStatus("status-claude-cli", "off");
    setDotStatus("status-cosyvoice", "off");
    const serverDetail = document.getElementById("status-server-detail");
    if (serverDetail) serverDetail.textContent = "no answer from the server";
    for (const id of ["sysinfo-port", "sysinfo-uptime"]) {
      const node = document.getElementById(id);
      if (node) node.textContent = "—";
    }
    return null;
  }
}

async function loadPreferences() {
  try {
    const prefs = await apiGet<PreferencesResponse>("/api/settings/preferences");
    const nameEl = document.getElementById("input-user-name") as HTMLInputElement;
    const honEl = document.getElementById("input-honorific") as HTMLSelectElement;
    if (nameEl) nameEl.value = prefs.user_name || "";
    if (honEl) honEl.value = prefs.honorific || "sir";
  } catch (e) {
    console.error("[settings] failed to load preferences:", e);
  }
}

function fieldValue(id: string): string {
  const el = document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null;
  return el ? el.value.trim() : "";
}

function fillVoiceFields(voice: VoiceConfig | undefined) {
  if (!voice) return;
  const set = (id: string, value: string) => {
    const el = document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null;
    if (el) el.value = value || "";
  };
  set("input-cosy-model", voice.model_dir);
  set("input-cosy-repo", voice.repo);
  set("input-cosy-prompt-wav", voice.prompt_wav);
  set("input-cosy-prompt-text", voice.prompt_text);
  set("input-cosy-speaker", voice.speaker);
  set("input-cosy-device", voice.device || "cpu");
}

function showVoiceNote(text: string) {
  const note = document.getElementById("voice-test-result");
  if (note) note.textContent = text;
}

async function saveVoiceKey(name: string, value: string): Promise<string | null> {
  const res = await fetch("/api/settings/keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key_name: name, key_value: value }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.success === false) {
    return typeof body.error === "string" ? body.error : `Could not save ${name}`;
  }
  return null;
}

function wireEvents() {
  // Close
  document.getElementById("settings-close")?.addEventListener("click", closeSettings);
  document.getElementById("settings-backdrop")?.addEventListener("click", closeSettings);

  document.getElementById("btn-save-voice")?.addEventListener("click", async () => {
    const pairs: Array<[string, string]> = [
      ["COSYVOICE_MODEL_DIR", fieldValue("input-cosy-model")],
      ["COSYVOICE_REPO", fieldValue("input-cosy-repo")],
      ["COSYVOICE_PROMPT_WAV", fieldValue("input-cosy-prompt-wav")],
      ["COSYVOICE_PROMPT_TEXT", fieldValue("input-cosy-prompt-text")],
      ["COSYVOICE_SPEAKER", fieldValue("input-cosy-speaker")],
      ["COSYVOICE_DEVICE", fieldValue("input-cosy-device") || "cpu"],
    ];
    for (const [name, value] of pairs) {
      const problem = await saveVoiceKey(name, value);
      if (problem) {
        showVoiceNote(problem);
        setDotStatus("status-cosyvoice", "red");
        return;
      }
    }
    await loadStatus();
    const notice = document.getElementById("keys-restart-notice");
    if (notice) notice.style.display = "block";
  });

  document.getElementById("btn-test-cosyvoice")?.addEventListener("click", async () => {
    setDotStatus("status-cosyvoice", "yellow");
    showVoiceNote("Checking the model folder and the CosyVoice install…");
    try {
      const result = await apiPost<{ valid: boolean; error?: string; detail?: string }>(
        "/api/settings/test-cosyvoice", {});
      setDotStatus("status-cosyvoice", result.valid ? "green" : "red");
      showVoiceNote(result.valid ? (result.detail || "CosyVoice is ready.") : (result.error || "CosyVoice is not ready."));
    } catch {
      setDotStatus("status-cosyvoice", "red");
      showVoiceNote("Could not reach the server.");
    }
  });

  // Save preferences
  document.getElementById("btn-save-prefs")?.addEventListener("click", async () => {
    const user_name = (document.getElementById("input-user-name") as HTMLInputElement).value.trim();
    const honorific = (document.getElementById("input-honorific") as HTMLSelectElement).value;
    await apiPost("/api/settings/preferences", { user_name, honorific });
    await loadStatus();
  });

  // Setup next button
  document.getElementById("btn-setup-next")?.addEventListener("click", advanceSetup);
}

// ---------------------------------------------------------------------------
// First-time setup wizard
// ---------------------------------------------------------------------------

function enterSetupMode() {
  isFirstTimeSetup = true;
  setupStep = 0;

  const welcome = document.getElementById("settings-welcome");
  if (welcome) welcome.style.display = "block";

  const nav = document.getElementById("setup-nav");
  if (nav) nav.style.display = "flex";

  // Hide sections except API keys
  showSetupStep(0);
}

function showSetupStep(step: number) {
  const sections = ["section-voice", "section-preferences"];
  sections.forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (step === 0 && i === 0) el.style.display = "";
    else if (step === 1 && i === 1) el.style.display = "";
    else el.style.display = "none";
  });

  const nextBtn = document.getElementById("btn-setup-next");
  if (nextBtn) {
    if (step === 0) nextBtn.textContent = "Next: Set Your Name";
    else if (step === 1) nextBtn.textContent = "Finish Setup";
    else nextBtn.style.display = "none";
  }
}

async function advanceSetup() {
  setupStep++;
  if (setupStep >= 2) {
    // Done — save everything and close
    isFirstTimeSetup = false;
    const welcome = document.getElementById("settings-welcome");
    if (welcome) welcome.style.display = "none";
    const nav = document.getElementById("setup-nav");
    if (nav) nav.style.display = "none";

    // Show all sections
    ["section-voice", "section-status", "section-preferences", "section-sysinfo"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = "";
    });

    closeSettings();
    return;
  }
  showSetupStep(setupStep);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function openSettings() {
  if (isOpen) return;
  isOpen = true;

  if (!panelEl) {
    panelEl = createPanel();
    wireEvents();
  }

  panelEl.style.display = "block";

  // Trigger animation
  requestAnimationFrame(() => {
    panelEl!.classList.add("open");
  });

  // Load data
  const status = await loadStatus();
  await loadPreferences();

  // Check for first-time setup
  if (status && !status.env_keys_set.cosyvoice) {
    enterSetupMode();
  }
}

export function closeSettings() {
  if (!panelEl || !isOpen) return;
  isOpen = false;
  panelEl.classList.remove("open");
  setTimeout(() => {
    if (panelEl) panelEl.style.display = "none";
  }, 300);
}

export function isSettingsOpen(): boolean {
  return isOpen;
}

/**
 * Check if first-time setup is needed and auto-open.
 */
export async function checkFirstTimeSetup(): Promise<boolean> {
  try {
    const status = await apiGet<StatusResponse>("/api/settings/status");
    if (!status.env_keys_set.cosyvoice) {
      openSettings();
      return true;
    }
  } catch {
    // Server not ready yet, skip
  }
  return false;
}
