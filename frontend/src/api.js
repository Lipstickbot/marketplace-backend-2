import { backendReady } from "./backend-ready.js";
import { readSession, writeSession, withSessionLock } from "./session-store.js";
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
export function session() {
  return readSession();
}
export function saveSession(value) {
  return writeSession(value);
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
async function refresh(rejectedToken = null) {
  if (!refreshing)
    refreshing = withSessionLock(async () => {
      const active = session();
      if (!active) throw new Error("Сессия завершена. Войдите снова.");
      // Another tab may already have rotated this one-use refresh token.
      if (rejectedToken && active.session.access_token !== rejectedToken) return;
      if (!rejectedToken && active.session.expires_at > Date.now() / 1000 + 30) return;
      const refreshToken = active.session.refresh_token;
      try {
        const r = await fetch(BASE + "/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            refresh_token: refreshToken,
          }),
        });
        const data = await r.json();
        if (!r.ok) {
          if ((r.status === 400 || r.status === 401) && session()?.session.refresh_token === refreshToken) saveSession(null);
          throw new ApiError(r.status, data);
        }
        // Never restore a session after logout or replace another signed-in account.
        if (session()?.session.refresh_token !== refreshToken) return;
        saveSession(data);
      } catch (error) {
        // Temporary network/server failures do not sign the user out of this device.
        throw error;
      }
    }).finally(() => {
      refreshing = null;
    });
  return refreshing;
}
export async function request(
  path,
  { method = "GET", body, auth = true, binary = false, retryUnauthorized = method === "GET" } = {},
) {
  if (auth && !session())
    throw new ApiError(401, {
      error: { message: "Сначала войдите в кабинет.", code: "login_required" },
    });
  await backendReady(BASE);
  if (auth && session()?.session.expires_at <= Date.now() / 1000 + 30)
    await refresh();
  let sentToken;
  const send = () => {
    const current = session();
    if (auth && !current) throw new Error("Сессия завершена. Войдите снова.");
    sentToken = current?.session.access_token;
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
  // Writes opt in only when the endpoint supports a safe retry after failed authentication.
  if (response.status === 401 && auth && retryUnauthorized) {
    await refresh(sentToken);
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
    location.assign(kind === "dev" ? "/account/?intent=publish#submission" : "/account/?intent=connect");
    return {
      ok: false,
      error: "Войдите и подтвердите отправку сохранённой заявки.",
    };
  }
  try {
    if (kind !== "dev" && session().profile.role !== "business")
      throw new Error("Для подключения готового агента войдите в аккаунт бизнеса.");
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
      const connection = await request("/connect-requests", {
        method: "POST",
        body: {
          agent_id: card.id,
          message: `${data.need}\nКомпания: ${data.company}\nКонтакт: ${data.contact}`,
        },
      });
      return { ok: true, status: connection.status };
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
