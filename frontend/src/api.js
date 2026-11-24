import { backendReady } from "./backend-ready.js";
// All requests go through Backend 2. Server secrets never belong in this app.
export const BASE = (import.meta.env?.VITE_API_BASE || "/api").replace(
  /\/$/,
  "",
);
export const SLUGS = { sup: "support", mkt: "marketing", hr: "hr" };
export const AGENT_DEMOS = Object.fromEntries(
  Object.keys(SLUGS).map((id) => [
    id,
    { liveDemoUrl: `/account/?agent=${SLUGS[id]}` },
  ]),
);
const KEY = "keme-session";
let current = null;
try {
  current = JSON.parse(sessionStorage.getItem(KEY));
} catch {
  /* memory-only fallback */
}
if (!current?.session?.access_token || !current?.session?.refresh_token)
  current = null;
export function session() {
  return current;
}
export function saveSession(value) {
  if (value?.session && !Number.isFinite(value.session.expires_at))
    value = { ...value, session: { ...value.session, expires_at: Date.now() / 1000 + (value.session.expires_in || 3600) } };
  current = value;
  try {
    value
      ? sessionStorage.setItem(KEY, JSON.stringify(value))
      : sessionStorage.removeItem(KEY);
  } catch {
    /* memory-only */
  }
}
export class ApiError extends Error {
  constructor(status, data) {
    super(data?.error?.message || `Ошибка запроса (${status}).`);
    this.status = status;
    this.code = data?.error?.code;
    this.details = data?.error?.details;
  }
}
let refreshing;
async function refresh() {
  if (!refreshing)
    refreshing = (async () => {
      try {
        const r = await fetch(BASE + "/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            refresh_token: current?.session.refresh_token,
          }),
        });
        const data = await r.json();
        if (!r.ok) throw new ApiError(r.status, data);
        saveSession(data);
      } catch (error) {
        saveSession(null);
        throw error;
      }
    })().finally(() => {
      refreshing = null;
    });
  return refreshing;
}
export async function request(
  path,
  { method = "GET", body, auth = true, binary = false } = {},
) {
  if (auth && !current)
    throw new ApiError(401, {
      error: { message: "Сначала войдите в кабинет.", code: "login_required" },
    });
  await backendReady(BASE);
  if (auth && current.session.expires_at <= Date.now() / 1000 + 30)
    await refresh();
  const send = () => {
    const headers = auth
      ? { Authorization: `Bearer ${current.session.access_token}` }
      : {};
    if (body !== undefined && !(body instanceof FormData))
      headers["Content-Type"] = "application/json";
    return fetch(BASE + path, {
      method,
      headers,
      body:
        body instanceof FormData
          ? body
          : body === undefined
            ? undefined
            : JSON.stringify(body),
    });
  };
  let response;
  try {
    response = await send();
  } catch {
    throw new Error("Сервер недоступен. Запрос не повторён автоматически.");
  }
  // Retry reads only: a POST execution can consume quota even after a timeout.
  if (response.status === 401 && auth && method === "GET") {
    await refresh();
    response = await send();
  }
  if (response.status === 204) return null;
  if (binary && response.ok) return response.blob();
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("Некорректный ответ сервера.");
  }
  if (!response.ok) throw new ApiError(response.status, data);
  return data;
}
export async function all(path, options) {
  const rows = [];
  for (let offset = 0; ; offset += 100) {
    const page = await request(
      `${path}${path.includes("?") ? "&" : "?"}limit=100&offset=${offset}`,
      options,
    );
    rows.push(...page.items);
    if (!page.has_more) return rows;
  }
}
export const login = async (body) => {
  const data = await request("/auth/login", {
    method: "POST",
    body,
    auth: false,
  });
  saveSession(data);
  return data;
};
export const signup = async (body) => {
  const data = await request("/auth/signup", {
    method: "POST",
    body,
    auth: false,
  });
  if (data.session) saveSession(data.session);
  return data;
};
export async function logout() {
  try {
    await request("/auth/logout", { method: "POST" });
  } finally {
    saveSession(null);
  }
}
export async function submitDraft(kind, data) {
  if (!session()) {
    try {
      sessionStorage.setItem("keme-draft", JSON.stringify({ kind, data }));
    } catch {
      return {
        ok: false,
        error: "Разрешите хранилище вкладки или отправьте заявку из кабинета.",
      };
    }
    location.assign(
      `/account/?role=${kind === "dev" ? "developer" : "business"}`,
    );
    return {
      ok: false,
      error: "Войдите и подтвердите отправку сохранённой заявки.",
    };
  }
  try {
    if (session().profile.role !== (kind === "dev" ? "developer" : "business"))
      throw new Error("Для этой заявки войдите с подходящей ролью.");
    if (kind === "dev")
      await request("/agent-submissions", {
        method: "POST",
        body: {
          name: data.agentName,
          category: "other",
          description: `${data.task}\n${data.capabilities}\nКоманда: ${data.name}\nКонтакт: ${data.contact}\nЗапуск: ${data.launch}\nЯзыки: ${data.languages.join(", ")}`,
        },
      });
    else {
      const card = await request(
        "/agents/" + (SLUGS[data.agent] || data.agent),
        { auth: false },
      );
      await request("/connect-requests", {
        method: "POST",
        body: {
          agent_id: card.id,
          message: `${data.need}\nКомпания: ${data.company}\nКонтакт: ${data.contact}`,
        },
      });
    }
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error.message };
  }
}
export const submitDeveloperApplication = (data) => submitDraft("dev", data);
export const submitConnectionRequest = (data) => submitDraft("conn", data);

if (typeof document !== "undefined") {
  document.addEventListener("keme-connection", (event) => {
    let banner = document.getElementById("connection-message");
    if (!banner) {
      banner = document.createElement("p"); banner.id = "connection-message";
      banner.className = "connection-message"; banner.setAttribute("role", "status");
      banner.textContent = "Подключаем сервис… Первое подключение может занять около минуты.";
      document.body.append(banner);
    }
    banner.hidden = !event.detail.waiting;
  });
}
