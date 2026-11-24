const KEY = "keme-session";
let memory = null;
let storageWritable = true;

function parse(raw) {
  try {
    const value = JSON.parse(raw);
    if (typeof value?.session?.access_token !== "string" || !value.session.access_token ||
        typeof value.session.refresh_token !== "string" || !value.session.refresh_token) return null;
    if (!Number.isFinite(value.session.expires_at))
      value.session.expires_at = Date.now() / 1000 + (value.session.expires_in || 3600);
    return value;
  } catch { return null; }
}

export function readSession() {
  try { if (storageWritable) memory = parse(localStorage.getItem(KEY)); } catch { /* memory fallback */ }
  return memory;
}

export function writeSession(value) {
  memory = value ? parse(JSON.stringify(value)) : null;
  try {
    if (memory) localStorage.setItem(KEY, JSON.stringify(memory));
    else localStorage.removeItem(KEY);
    storageWritable = true;
  } catch { storageWritable = false; /* Preserve this tab's memory session if writes are blocked. */ }
  try { sessionStorage.removeItem(KEY); } catch { /* legacy storage unavailable */ }
  return memory;
}

// Preserve existing logins while migrating from tab-only storage to this device.
readSession();
if (!memory) {
  try {
    const legacy = parse(sessionStorage.getItem(KEY));
    if (legacy) writeSession(legacy);
  } catch { /* no previous tab session */ }
}

export function withSessionLock(action) {
  if (globalThis.navigator?.locks?.request)
    return navigator.locks.request("keme-auth-session", { mode: "exclusive" }, action);
  return action();
}

if (typeof window !== "undefined") window.addEventListener("storage", (event) => {
  if (event.key !== KEY && event.key !== null) return;
  memory = parse(event.newValue);
  try { sessionStorage.removeItem(KEY); } catch { /* legacy cleanup */ }
  window.dispatchEvent(new CustomEvent("keme-session-changed"));
});
