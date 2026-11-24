// Wake a sleeping API using reads before sending a write. A user action is never replayed.
let checkedAt = 0, pending;
const notify = (waiting) => {
  if (typeof document !== "undefined") document.dispatchEvent(new CustomEvent("keme-connection", { detail: { waiting } }));
};
export async function backendReady(base) {
  if (!/^https:\/\//.test(base) || Date.now() - checkedAt < 60000) return;
  if (pending) return pending;
  pending = (async () => {
    const show = setTimeout(() => notify(true), 1800);
    try {
      const deadline = Date.now() + 100000;
      while (Date.now() < deadline) {
        try {
          const response = await fetch(base + "/health", { headers: { Accept: "application/json" }, signal: AbortSignal.timeout(12000) });
          if (response.ok && (await response.json()).status === "ok") { checkedAt = Date.now(); return; }
        } catch { /* An initial cold start can return HTML or a temporary gateway error. */ }
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      throw new Error("Не удалось подключиться. Подождите немного и попробуйте ещё раз.");
    } finally { clearTimeout(show); notify(false); }
  })().finally(() => { pending = null; });
  return pending;
}
