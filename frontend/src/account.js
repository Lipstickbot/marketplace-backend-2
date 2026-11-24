import {
  request,
  all,
  session,
  saveSession,
  login,
  signup,
  logout,
  submitDraft,
} from "./api.js";
import { startGoogleLogin, finishGoogleLogin } from "./google-auth.js";
const root = document.querySelector("#workspace"),
  notice = document.querySelector("#notice");
const e = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const labels = {
  pending: "На рассмотрении",
  approved: "Одобрено",
  rejected: "Отклонено",
  success: "Выполнено",
  running: "Выполняется",
  error: "Ошибка",
  engine_unreachable: "Нет подтверждения выполнения",
  blocked: "Запрос заблокирован",
  escalation_required: "Нужен ответ сотрудника",
};
const status = (v) => labels[v] || v;
const panel = (title, body, wide = false) =>
  `<section class="work-panel ${wide ? "wide" : ""}"><h2>${title}</h2>${body}</section>`;
let agents = [],
  files = [],
  connections = [],
  authMode = "login";
let googleAvailable = null;
function tell(text = "", error = false) {
  notice.textContent = text;
  notice.classList.toggle("error", error);
}
function authView() {
  const registering = authMode === "signup";
  root.innerHTML = panel(
    "Вход в Keme AI",
    `<div class="work-tabs"><button class="btn btn--secondary" data-auth="login">Войти</button><button class="btn btn--secondary" data-auth="signup">Создать аккаунт</button></div><form id="auth" class="work-form"><label>Почта<input name="email" type="email" autocomplete="email" required maxlength="254"></label><label>Пароль<input name="password" type="password" autocomplete="${registering ? "new-password" : "current-password"}" required minlength="${registering ? 12 : 1}" maxlength="128"></label>${registering ? '<label>Ваше имя<input name="display_name" maxlength="120"></label><label>Компания<input name="company_name" maxlength="200"></label><label>Роль<select name="role"><option value="business">Бизнес</option><option value="developer">Разработчик</option></select></label><p class="muted">Пароль от 12 символов. После подтверждения почты вернитесь и войдите.</p>' : ""}<button class="btn btn--primary">${registering ? "Зарегистрироваться" : "Войти"}</button></form>`,
  );
  if (registering)
    root.querySelector("[name=role]").value =
      new URLSearchParams(location.search).get("role") === "developer"
        ? "developer"
        : "business";
  const google = document.createElement("div");
  google.className = "google-signin";
  google.innerHTML = `<div class="auth-divider"><span>или</span></div><button type="button" class="btn btn--secondary google-button" id="google-login"><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24"><path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.02v2.51h3.24c1.9-1.75 2.98-4.33 2.98-7.36Z"/><path fill="#34A853" d="M12 22c2.7 0 4.96-.9 6.62-2.41l-3.24-2.51c-.9.6-2.04.97-3.38.97-2.6 0-4.81-1.76-5.6-4.12H3.06v2.59A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" d="M6.4 13.93A6 6 0 0 1 6.09 12c0-.67.12-1.32.31-1.93V7.48H3.06A10 10 0 0 0 2 12c0 1.61.39 3.14 1.06 4.52l3.34-2.59Z"/><path fill="#EA4335" d="M12 5.95c1.47 0 2.78.51 3.82 1.51l2.86-2.87A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.94 5.48l3.34 2.59c.79-2.36 3-4.12 5.6-4.12Z"/></svg>Продолжить с Google</button><p class="muted google-note">Новый аккаунт Google создаётся с ролью «Бизнес».</p><p class="muted" id="google-status"></p>`;
  root.querySelector(".work-panel").append(google);
  const button = google.querySelector("button"), status = google.querySelector("#google-status");
  button.disabled = googleAvailable !== true;
  status.textContent = googleAvailable === false ? "Вход через Google скоро будет доступен. Можно войти по почте." : googleAvailable === null ? "Проверяем доступность Google…" : "";
  request("/auth/providers", { auth: false }).then((providers) => {
    googleAvailable = providers.google === true;
    if (!button.isConnected) return;
    button.disabled = !googleAvailable;
    status.textContent = googleAvailable ? "" : "Вход через Google скоро будет доступен. Можно войти по почте.";
  }).catch(() => {
    if (button.isConnected) status.textContent = "Не удалось проверить Google. Попробуйте обновить страницу.";
  });
}
async function businessView() {
  [agents, connections, files] = await Promise.all([
    all("/agents", { auth: false }),
    all("/connect-requests"),
    all("/files"),
  ]);
  const published = agents.filter((a) => a.status === "published");
  const chosen = new URLSearchParams(location.search).get("agent");
  const options = published
    .map((a) => `<option value="${e(a.id)}">${e(a.name)}</option>`)
    .join("");
  root.innerHTML = `<div class="work-grid">${panel("Подключения", `<form id="connect" class="work-form"><label>Агент<select name="agent_id">${options}</select></label><label>Задача<textarea name="message" maxlength="4000"></textarea></label><button class="btn btn--primary">Запросить подключение</button></form>${connections.map((c) => `<div class="work-item"><strong>${e(agents.find((a) => a.id === c.agent_id)?.name || c.agent_id)}</strong><p>${e(status(c.status))}</p><p>${e(c.review_note || "")}</p></div>`).join("")}`)}
  ${panel("Документы", `<p class="muted">PDF, DOCX или TXT до 10 MiB. Для проверки используйте вымышленные данные.</p><form id="upload" class="work-form"><label>Файл<input name="file" type="file" accept=".pdf,.docx,.txt" required></label><label>Назначение<select name="purpose"><option value="brief">Бриф Marketing</option><option value="knowledge_base">База знаний Support</option><option value="resume">Резюме HR</option><option value="job_description">Вакансия HR</option></select></label><button class="btn btn--secondary">Загрузить</button></form>${files.map((f) => `<div class="work-item"><strong>${e(f.original_name)}</strong><p class="muted">${e(f.purpose)} · ${f.engine_file_id ? "Синхронизирован" : "Ожидает синхронизации"}</p><div class="work-row"><button class="btn btn--secondary" data-download="${e(f.id)}">Скачать</button><button class="btn btn--secondary" data-delete="${e(f.id)}">Удалить</button></div></div>`).join("")}`)}
  ${panel(
    "Запуск агента",
    `<p class="muted">Mock-режим возвращает демонстрационные ответы. Для запуска нужно одобренное подключение.</p><form id="run" class="work-form"><label>Агент<select name="slug">${published.map((a) => `<option value="${e(a.slug)}" ${a.slug === chosen ? "selected" : ""}>${e(a.name)}</option>`).join("")}</select></label><p id="connection-status" class="muted"></p><label>Запрос<textarea name="message" required maxlength="8000"></textarea></label><label>Язык<select name="language"><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option><option value="auto">Автоматически</option></select></label><fieldset><legend>Документы для запроса</legend>${
      files
        .filter((f) => !f.deletion_requested_at)
        .map(
          (f) =>
            `<label data-purpose="${e(f.purpose)}"><input name="file_ids" type="checkbox" value="${e(f.id)}">${e(f.original_name)}</label>`,
        )
        .join("") || '<p class="muted">Документы ещё не загружены.</p>'
    }</fieldset><button class="btn btn--primary">Выполнить запрос</button></form>`,
  )}
  ${panel("Результат", '<p id="result-meta" class="muted">Текст результата не сохраняется в истории. Скопируйте его после выполнения.</p><pre id="result" class="work-output"></pre><div id="sources"></div>')}
  ${panel("История запусков", '<div id="runs">Загрузка…</div>', true)}</div>`;
  root.querySelector("#run [name=slug]").addEventListener("change", syncRun);
  syncRun();
  await showRuns();
}
function syncRun() {
  const form = root.querySelector("#run");
  const agent = agents.find((a) => a.slug === form.elements.slug.value);
  const connection = connections.find((c) => c.agent_id === agent?.id);
  root.querySelector("#connection-status").textContent = connection
    ? status(connection.status)
    : "Агент ещё не подключён";
  form.querySelector("button").disabled = connection?.status !== "approved";
  form.querySelectorAll("[data-purpose]").forEach((label) => {
    const allowed = agent?.accepted_file_purposes.includes(
      label.dataset.purpose,
    );
    label.hidden = !allowed;
    if (!allowed) label.querySelector("input").checked = false;
  });
}
async function showRuns() {
  const rows = await all("/runs");
  root.querySelector("#runs").innerHTML =
    rows
      .map(
        (r) =>
          `<div class="work-item"><strong>${e(r.engine_slug)} · ${e(status(r.status))}</strong><p class="muted">${e(new Date(r.created_at).toLocaleString())} · токены: ${r.total_tokens ?? "—"} · режим: ${e(r.mode || "—")}</p>${r.error_code ? `<p>${e(r.error_code)}</p>` : ""}</div>`,
      )
      .join("") || '<p class="muted">Запусков пока нет.</p>';
}
async function developerView() {
  const rows = await all("/agent-submissions");
  root.innerHTML = `<div class="work-grid">${panel("Предложить агента", '<form id="submission" class="work-form"><label>Название<input name="name" required maxlength="160"></label><label>Категория<input name="category" required maxlength="80"></label><label>Описание и ограничения<textarea name="description" required maxlength="10000"></textarea></label><label>Репозиторий HTTPS<input name="repository_url" type="url" placeholder="https://github.com/…"></label><button class="btn btn--primary">Отправить</button></form>')}${panel("Мои заявки", rows.map((r) => `<div class="work-item"><h3>${e(r.name)}</h3><p>${e(status(r.status))}</p><p>${e(r.review_note || "")}</p></div>`).join("") || "<p>Заявок пока нет.</p>")}</div>`;
}
async function adminView() {
  const [connects, submissions] = await Promise.all([
    all("/admin/connect-requests?status=pending"),
    all("/admin/agent-submissions?status=pending"),
  ]);
  const form = (type, row) =>
    `<form class="work-form work-item" data-review="${type}" data-id="${e(row.id)}"><p>${e(type === "connect-requests" ? row.company_id : row.name)}</p>${type === "connect-requests" ? `<p>${e(row.message)}</p><p class="muted">Агент: ${e(row.agent_id)}</p>` : `<p>${e(row.description)}</p><p>${e(row.repository_url || "")}</p><label>Slug карточки при одобрении<input name="publication_slug" pattern="[a-z][a-z0-9-]{0,79}"></label>`}<label>Решение<select name="decision"><option value="approved">Одобрить</option><option value="rejected">Отклонить</option></select></label><label>Комментарий<textarea name="review_note" maxlength="4000"></textarea></label><button class="btn btn--primary">Сохранить решение</button></form>`;
  root.innerHTML = `<div class="work-grid">${panel("Подключения бизнеса", connects.map((r) => form("connect-requests", r)).join("") || "<p>Нет ожидающих заявок.</p>")}${panel("Публикации разработчиков", submissions.map((r) => form("agent-submissions", r)).join("") || "<p>Нет ожидающих заявок.</p>")}</div>`;
}
function draftView() {
  let draft;
  try {
    draft = JSON.parse(sessionStorage.getItem("keme-draft"));
  } catch {
    return;
  }
  if (!draft) return;
  root.insertAdjacentHTML(
    "afterbegin",
    panel(
      "Сохранённая заявка",
      `<p>${e(draft.kind === "dev" ? draft.data.agentName : draft.data.need)}</p><button class="btn btn--primary" id="send-draft">Подтвердить отправку</button>`,
    ),
  );
  root.querySelector("#send-draft").addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    const result = await submitDraft(draft.kind, draft.data);
    if (result.ok) {
      sessionStorage.removeItem("keme-draft");
      tell("Заявка отправлена.");
      await render();
    } else {
      tell(result.error, true);
      event.currentTarget.disabled = false;
    }
  });
}
async function render() {
  document.querySelector("#logout").hidden = !session();
  if (!session()) {
    authView();
    return;
  }
  const me = await request("/auth/me");
  saveSession({ ...session(), profile: me });
  document.querySelector("#identity").textContent =
    `${me.display_name || me.email || ""} · ${{ business: "Бизнес", developer: "Разработчик", admin: "Администратор" }[me.role]}`;
  if (me.role === "business") await businessView();
  else if (me.role === "developer") await developerView();
  else await adminView();
  draftView();
}
root.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.id === "google-login") {
    button.disabled = true;
    tell("Открываем Google…");
    try { await startGoogleLogin(); }
    catch (error) { tell(error.message, true); button.disabled = false; }
    return;
  }
  if (button.dataset.auth) {
    authMode = button.dataset.auth;
    tell();
    authView();
    return;
  }
  if (!button.dataset.delete && !button.dataset.download) return;
  button.disabled = true;
  try {
    if (button.dataset.delete) {
      if (!confirm("Удалить документ из хранилища и движка?")) return;
      await request("/files/" + button.dataset.delete, { method: "DELETE" });
      tell("Документ удалён.");
      await render();
    } else {
      const file = files.find((f) => f.id === button.dataset.download);
      const blob = await request("/files/" + file.id + "/download", {
        binary: true,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.original_name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch (error) {
    tell(error.message, true);
  } finally {
    button.disabled = false;
  }
});
root.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target,
    button = form.querySelector("button"),
    data = new FormData(form),
    value = Object.fromEntries(data),
    label = button.textContent;
  button.disabled = true;
  tell();
  try {
    if (form.id === "auth") {
      if (authMode === "login") await login(value);
      else {
        const result = await signup(value);
        if (result.status === "confirmation_required") {
          form.reset();
          tell("Проверьте почту и подтвердите регистрацию. Затем войдите.");
          return;
        }
      }
      await render();
    } else if (form.id === "connect") {
      await request("/connect-requests", { method: "POST", body: value });
      tell("Заявка отправлена.");
      await render();
    } else if (form.id === "upload") {
      const file = data.get("file");
      if (!file.size || file.size > 10 * 1024 * 1024)
        throw new Error("Выберите непустой файл до 10 MiB.");
      await request("/files/upload", { method: "POST", body: data });
      tell("Документ загружен.");
      await render();
    } else if (form.id === "run") {
      button.textContent = "Агент выполняет запрос…";
      const result = await request(
        "/agents/" + encodeURIComponent(value.slug) + "/run",
        {
          method: "POST",
          body: {
            message: value.message,
            language: value.language,
            file_ids: data.getAll("file_ids"),
            options: {},
            history: [],
          },
        },
      );
      root.querySelector("#result").textContent = result.execution.response;
      root.querySelector("#result-meta").textContent =
        `${status(result.execution.status)} · ${result.execution.mode === "mock" ? "Демонстрационный ответ (mock)" : result.execution.mode} · ${result.execution.usage.total_tokens} токенов${result.audit_saved ? "" : " · Журнал ожидает сверки"}`;
      root.querySelector("#sources").innerHTML = result.execution.sources
        .map(
          (s) =>
            `<div class="work-item"><strong>${e(s.filename)}</strong><p>${e(s.excerpt)}</p></div>`,
        )
        .join("");
      await showRuns();
    } else if (form.id === "submission") {
      if (!value.repository_url) delete value.repository_url;
      await request("/agent-submissions", { method: "POST", body: value });
      tell("Заявка отправлена.");
      await render();
    } else if (form.dataset.review) {
      if (
        form.dataset.review === "agent-submissions" &&
        value.decision === "approved" &&
        !value.publication_slug
      )
        throw new Error("Укажите slug для публикации.");
      if (
        value.decision === "rejected" ||
        form.dataset.review === "connect-requests"
      )
        delete value.publication_slug;
      await request(`/admin/${form.dataset.review}/${form.dataset.id}/review`, {
        method: "POST",
        body: value,
      });
      tell("Решение сохранено.");
      await render();
    }
  } catch (error) {
    tell(
      error.message +
        (error.details?.original_saved
          ? " Оригинал сохранён. Обновите кабинет, чтобы увидеть его."
          : "") +
        (error.details?.platform_run_id
          ? " Запуск зарегистрирован; проверьте историю перед повтором."
          : ""),
      true,
    );
    if (form.id === "run") await showRuns().catch(() => {});
  } finally {
    button.disabled = false;
    button.textContent = label;
    if (form.id === "run") syncRun();
  }
});
document.querySelector("#logout").addEventListener("click", async () => {
  try {
    await logout();
  } catch (error) {
    tell(error.message, true);
  } finally {
    document.querySelector("#identity").textContent =
      "Агенты, документы и результаты в одном месте.";
    await render();
  }
});
async function initialize() {
  try { if (await finishGoogleLogin()) tell("Вы вошли через Google."); }
  catch (error) { tell(error.message, true); }
  await render();
}
initialize().catch((error) => {
  tell(error.message, true);
  if (!session()) authView();
});
