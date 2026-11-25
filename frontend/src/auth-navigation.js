export function goHomeAfterAuth() {
  try {
    const params = new URL(location.href).searchParams;
    const agent = params.get("agent");
    if (/^[a-z][a-z0-9-]{0,79}$/.test(agent || "")) sessionStorage.setItem("keme-auth-agent", agent);
    if (params.get("intent") === "publish") sessionStorage.setItem("keme-auth-publish", "1");
  } catch { /* navigation still works */ }
  location.replace("/");
}
export function consumePublicationIntent() {
  try {
    const pending = sessionStorage.getItem("keme-auth-publish") === "1";
    sessionStorage.removeItem("keme-auth-publish");
    return pending;
  } catch { return false; }
}
export function consumeAuthAgent() {
  try {
    const agent = sessionStorage.getItem("keme-auth-agent");
    sessionStorage.removeItem("keme-auth-agent");
    return /^[a-z][a-z0-9-]{0,79}$/.test(agent || "") ? agent : null;
  } catch { return null; }
}
