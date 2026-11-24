const KEY = "keme-auth-notice";
export function goHomeAfterAuth(reason = "signed_in") {
  try { sessionStorage.setItem(KEY, reason); } catch { /* navigation still works */ }
  location.replace("/");
}
export function consumeAuthNotice() {
  try {
    const reason = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return ["signed_in", "registered", "confirm_email"].includes(reason) ? reason : null;
  } catch { return null; }
}
