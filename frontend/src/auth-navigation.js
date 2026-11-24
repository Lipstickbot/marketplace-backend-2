const KEY = "keme-auth-notice";
export function goHomeAfterAuth(reason = "signed_in") {
  try {
    sessionStorage.setItem(KEY, reason);
    const agent = new URL(location.href).searchParams.get("agent");
    if (/^[a-z][a-z0-9-]{0,79}$/.test(agent || "")) sessionStorage.setItem("keme-auth-agent", agent);
  } catch { /* navigation still works */ }
  location.replace("/");
}
export function consumeAuthAgent() {
  try {
    const agent = sessionStorage.getItem("keme-auth-agent");
    sessionStorage.removeItem("keme-auth-agent");
    return /^[a-z][a-z0-9-]{0,79}$/.test(agent || "") ? agent : null;
  } catch { return null; }
}
export function consumeAuthNotice() {
  try {
    const reason = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return ["signed_in", "registered", "confirm_email"].includes(reason) ? reason : null;
  } catch { return null; }
}
