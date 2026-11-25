import { request, saveSession } from "./api.js";

const KEY = "keme-google-pkce";
const MAX_AGE = 10 * 60 * 1000;
const random = () => base64url(crypto.getRandomValues(new Uint8Array(32)));
function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
export async function startGoogleLogin() {
  if (!crypto?.subtle) throw new Error("Для входа через Google откройте сайт по HTTPS.");
  const verifier = random(), state = random();
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const params = new URLSearchParams(location.search);
  const pending = { verifier, state, createdAt: Date.now(), agent: params.get("agent"), publish: params.get("intent") === "publish" };
  try {
    sessionStorage.setItem(KEY, JSON.stringify(pending));
    if (sessionStorage.getItem(KEY) !== JSON.stringify(pending)) throw new Error();
  } catch {
    throw new Error("Разрешите хранилище вкладки, чтобы войти через Google.");
  }
  try {
    const callback = new URL("/account/", location.origin);
    callback.searchParams.set("oauth_state", state);
    const data = await request("/auth/google/start", {
      method: "POST", auth: false,
      body: { code_challenge: base64url(new Uint8Array(digest)), redirect_to: callback.href },
    });
    const target = new URL(data.url);
    if (target.protocol !== "https:" || target.pathname !== "/auth/v1/authorize" || target.searchParams.get("provider") !== "google")
      throw new Error("Некорректный адрес входа через Google.");
    location.assign(target.href);
  } catch (error) {
    sessionStorage.removeItem(KEY);
    throw error;
  }
}

export async function finishGoogleLogin() {
  const url = new URL(location.href);
  const code = url.searchParams.get("code");
  const returnedState = url.searchParams.get("oauth_state");
  const error = url.searchParams.get("error");
  const hash = new URLSearchParams(url.hash.slice(1));
  if (!code && !error && !returnedState && !hash.has("error") && !hash.has("access_token")) return false;
  let pending;
  try { pending = JSON.parse(sessionStorage.getItem(KEY)); } catch { /* no stored attempt */ }
  sessionStorage.removeItem(KEY);
  // Remove one-use codes and all possible tokens from the address before any API call.
  const clean = new URL("/account/", url.origin);
  if (/^[a-z][a-z0-9-]{0,79}$/.test(pending?.agent || "")) clean.searchParams.set("agent", pending.agent);
  if (pending?.publish === true) clean.searchParams.set("intent", "publish");
  history.replaceState(null, "", clean.pathname + clean.search);
  if (error || hash.has("error")) throw new Error("Вход через Google отменён или не завершён. Попробуйте ещё раз.");
  if (!pending?.verifier || !code || returnedState !== pending.state ||
      !Number.isFinite(pending.createdAt) || Date.now() - pending.createdAt > MAX_AGE || Date.now() < pending.createdAt)
    throw new Error("Ссылка входа устарела или открыта в другой вкладке. Начните вход через Google ещё раз.");
  const result = await request("/auth/google/exchange", {
    method: "POST", auth: false,
    body: { auth_code: code, code_verifier: pending.verifier },
  });
  saveSession(result);
  return true;
}
