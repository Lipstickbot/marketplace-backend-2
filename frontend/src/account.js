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
import { goHomeAfterAuth } from "./auth-navigation.js";
import { setupIntegrations, agentLink } from "./integrations.js";
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
const accountUrl = new URL(location.href);
const returningFromConfirmation = accountUrl.searchParams.get("email_confirmation") === "1";
const confirmationFailed = returningFromConfirmation && new URLSearchParams(accountUrl.hash.slice(1)).has("error");
if (returningFromConfirmation) {
  accountUrl.searchParams.delete("email_confirmation");
  accountUrl.hash = "";
  history.replaceState(null, "", accountUrl.pathname + accountUrl.search);
}
const confirmationEmailKey = "keme-confirmation-email";
let confirmationEmail = "";
try { confirmationEmail = sessionStorage.getItem(confirmationEmailKey) || ""; } catch { /* Storage is optional. */ }

let agents = [],
  files = [],
  connections = [],
  authMode = accountUrl.searchParams.get("mode") === "signup" ? "signup" : "login";
if (accountUrl.searchParams.get("mode") === "confirm" || confirmationFailed) authMode = "confirm";
const intent = new URLSearchParams(location.search).get("intent");
let googleAvailable = null;
function tell(text = "", error = false) {
  notice.textContent = text;
  notice.classList.toggle("error", error);
}
function rememberConfirmationEmail(email) {
  confirmationEmail = email;
  try {
    if (email) sessionStorage.setItem(confirmationEmailKey, email);
    else sessionStorage.removeItem(confirmationEmailKey);
  } catch { /* Storage is optional. */ }
}

function confirmationView() {
  root.innerHTML = panel("Подтвердите почту", `
    <p class="muted">Откройте ссылку из письма или введите код, если он указан. Если письмо не пришло, проверьте спам и запросите его ещё раз.</p>
    <form id="confirm-email" class="work-form">
      <label>Почта<input name="email" type="email" autocomplete="email" value="${e(confirmationEmail)}" maxlength="254" required></label>
      <label>Код из письма<input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6,10}" maxlength="10" required></label>
      <div class="work-row">
        <button type="submit" class="btn btn--primary">Подтвердить</button>
        <button type="submit" value="resend" formnovalidate class="btn btn--secondary">Отправить письмо ещё раз</button>
      </div>
    </form>
    <button type="button" class="auth-text-button" data-auth="login">Вернуться ко входу</button>
  `);
}

function authView() {
  root.classList.add("auth-layout");
  if (authMode === "confirm") {
    confirmationView();
    return;
  }
  const registering = authMode === "signup";
  root.innerHTML = panel(
    registering ? "Создать аккаунт" : "Вход в Keme AI",
    `<div class="work-tabs"><button type="button" data-auth="login" aria-pressed="${!registering}">Войти</button><button type="button" data-auth="signup" aria-pressed="${registering}">Регистрация</button></div>
    <form id="auth" class="work-form">
      <label>Почта<input name="email" type="email" autocomplete="email" value="${e(confirmationEmail)}" required maxlength="254"></label>
      <label>Пароль<input name="password" type="password" autocomplete="${registering ? "new-password" : "current-password"}" required minlength="${registering ? 12 : 1}" maxlength="128" ${registering ? 'aria-describedby="password-hint"' : ""}></label>
      ${registering ? `<p id="password-hint" class="muted">Минимум 12 символов</p>
        <div class="auth-fields"><label>Ваше имя<input name="display_name" autocomplete="name" maxlength="120"></label><label>Компания<input name="company_name" autocomplete="organization" maxlength="200"></label></div>
        <label>Что хотите делать?<select name="role"><option value="business">Подключать агентов для бизнеса</option><option value="developer">Добавлять своих агентов</option></select></label>` : ""}
      <button type="submit" class="btn btn--primary">${registering ? "Зарегистрироваться" : "Войти"}</button>
    </form>
    <button type="button" class="auth-text-button" data-auth="confirm">Подтвердить почту или запросить письмо</button>`,
  );
  const purpose = document.createElement("p"); purpose.className = "muted";
  purpose.textContent = intent === "publish" ? "Добавьте собственного агента в каталог: опишите возможности и отправьте заявку на рассмотрение." : intent === "connect" ? "Выберите готового агента из каталога и отправьте запрос на подключение для своей компании." : "Вход сохранится на этом устройстве, пока вы не нажмёте «Выйти».";
  root.querySelector(".work-panel h2").after(purpose);
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
  const updateGoogle = () => {
    const developerSignup = registering && root.querySelector("[name=role]")?.value === "developer";
    button.disabled = googleAvailable !== true || developerSignup;
    google.querySelector(".google-note").textContent = developerSignup ? "Для создания аккаунта разработчика зарегистрируйтесь по почте. В существующий аккаунт можно войти через Google." : "Новый аккаунт Google создаётся для подключения агентов бизнесом.";
  };
  updateGoogle();
  root.querySelector("[name=role]")?.addEventListener("change", updateGoogle);
  status.textContent = googleAvailable === false ? "Вход через Google скоро будет доступен. Можно войти по почте." : googleAvailable === null ? "Проверяем доступность Google…" : "";
  request("/auth/providers", { auth: false }).then((providers) => {
    googleAvailable = providers.google === true;
    if (!button.isConnected) return;
    updateGoogle();
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
  const approved = published.filter((a) => connections.some((c) => c.agent_id === a.id && c.status === "approved"));
  const chosen = new URLSearchParams(location.search).get("agent");
  const options = published
    .map((a) => `<option value="${e(a.id)}">${e(a.name)}</option>`)
    .join("");
  root.innerHTML = `<div class="work-grid">${panel("Подключить готового агента", `<p class="muted">Выберите агента из каталога для работы в вашей компании. Эта заявка не публикует нового агента.</p><form id="connect" class="work-form"><label>Агент<select name="agent_id">${options}</select></label><label>Задача<textarea name="message" maxlength="4000"></textarea></label><button class="btn btn--primary">Запросить подключение</button></form>${connections.map((c) => `<div class="work-item"><strong>${e(agents.find((a) => a.id === c.agent_id)?.name || c.agent_id)}</strong><p>${e(status(c.status))}</p><p>${e(c.review_note || "")}</p></div>`).join("")}`)}
  ${panel("Документы", `<p class="muted">PDF, DOCX или TXT до 10 MiB. Для проверки используйте вымышленные данные.</p><form id="upload" class="work-form"><label>Файл<input name="file" type="file" accept=".pdf,.docx,.txt" required></label><label>Назначение<select name="purpose"><option value="brief">Бриф Marketing</option><option value="knowledge_base">База знаний Support</option><option value="resume">Резюме HR</option><option value="job_description">Вакансия HR</option></select></label><button class="btn btn--secondary">Загрузить</button></form>${files.map((f) => `<div class="work-item"><strong>${e(f.original_name)}</strong><p class="muted">${e(f.purpose)} · ${f.engine_file_id ? "Синхронизирован" : "Ожидает синхронизации"}</p><div class="work-row"><button class="btn btn--secondary" data-download="${e(f.id)}">Скачать</button><button class="btn btn--secondary" data-delete="${e(f.id)}">Удалить</button></div></div>`).join("")}`)}
  </div>`;

  const grid = root.querySelector(".work-grid");
  const selected = published.find((a) => a.slug === chosen);
  if (selected) {
    const linkBox = document.createElement("section");
    linkBox.className = "work-panel wide";
    linkBox.innerHTML = `<h2>${e(selected.name)} — подключение под задачу</h2><p class="muted">Запросите доступ. После одобрения настройте задачу и создайте API-подключение. Документы можно добавить по необходимости.</p><label class="work-form">Ссылка на агента<input readonly value="${e(agentLink(selected.slug))}" aria-label="Ссылка на агента"></label><a class="btn btn--secondary" href="#application-integrations">Настроить API / LLM</a>`;
    grid.prepend(linkBox);
    root.querySelector("#connect [name=agent_id]").value = selected.id;
  }

  const integrationsReady = setupIntegrations(root, agents, connections, files, tell);
  if (approved.length) renderTrialRun(grid, approved, chosen);
  grid.insertAdjacentHTML("beforeend", `<details class="work-panel wide workspace-details" id="run-history"><summary>История запусков</summary><div id="runs" aria-live="polite"></div></details>`);
  const history = grid.querySelector("#run-history");
  history.addEventListener("toggle", () => {
    if (history.open) showRuns();
  });
  await integrationsReady;
}

function renderTrialRun(grid, approved, chosen) {
  grid.insertAdjacentHTML("beforeend", `<details class="work-panel wide workspace-details"><summary>Пробный запуск в кабинете</summary><div class="work-grid">${panel(
    "Запуск агента",
    `<p class="muted">Текущий движок возвращает демонстрационные ответы.</p><form id="run" class="work-form"><label>Агент<select name="slug">${approved.map((a) => `<option value="${e(a.slug)}" ${a.slug === chosen ? "selected" : ""}>${e(a.name)}</option>`).join("")}</select></label><label>Запрос<textarea name="message" required maxlength="8000"></textarea></label><label>Язык<select name="language"><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option><option value="auto">Автоматически</option></select></label><fieldset><legend>Документы для запроса</legend>${
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
  </div></details>`);
  const form = grid.querySelector("#run");
  form.elements.slug.addEventListener("change", () => syncRunFiles(form));
  syncRunFiles(form);
}
function syncRunFiles(form) {
  const agent = agents.find((a) => a.slug === form.elements.slug.value);
  form.querySelectorAll("[data-purpose]").forEach((label) => {
    const allowed = agent?.accepted_file_purposes.includes(
      label.dataset.purpose,
    );
    label.hidden = !allowed;
    if (!allowed) label.querySelector("input").checked = false;
  });
}
async function showRuns() {
  const list = root.querySelector("#run-history[open] #runs");
  if (!list) return;
  list.textContent = "Загрузка…";
  try {
    const rows = await all("/runs");
    list.innerHTML =
    rows
      .map(
        (r) =>
          `<div class="work-item"><strong>${e(r.engine_slug)} · ${e(status(r.status))}</strong><p class="muted">${e(new Date(r.created_at).toLocaleString())} · токены: ${r.total_tokens ?? "—"} · режим: ${e(r.mode || "—")}</p>${r.error_code ? `<p>${e(r.error_code)}</p>` : ""}</div>`,
      )
      .join("") || '<p class="muted">Запусков пока нет.</p>';
  } catch (error) {
    list.textContent = error.message;
  }
}
async function developerView() {
  const rows = await all("/agent-submissions");
  root.innerHTML = `<div class="work-grid">${panel("Добавить своего агента", '<p class="muted">Опишите собственного агента для публикации в каталоге. Подключение готового агента оформляется отдельно в аккаунте бизнеса.</p><form id="submission" class="work-form"><label>Название<input name="name" required maxlength="160"></label><label>Категория<input name="category" required maxlength="80"></label><label>Описание и ограничения<textarea name="description" required maxlength="10000"></textarea></label><label>Репозиторий HTTPS<input name="repository_url" type="url" placeholder="https://github.com/…"></label><button class="btn btn--primary">Отправить</button></form>')}${panel("Мои заявки", rows.map((r) => `<div class="work-item"><h3>${e(r.name)}</h3><p>${e(status(r.status))}</p><p>${e(r.review_note || "")}</p></div>`).join("") || "<p>Заявок пока нет.</p>")}</div>`;
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
      draft.kind === "dev" ? "Заявка на добавление своего агента" : "Заявка на подключение агента",
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
  root.classList.remove("auth-layout");
  const me = await request("/auth/me");
  saveSession({ ...session(), profile: me });
  document.querySelector("#identity").textContent =
    `${me.display_name || me.email || ""} · ${{ business: "Бизнес", developer: "Разработчик", admin: "Администратор" }[me.role]}`;
  if (me.role === "business" && intent === "publish") {
    root.innerHTML = panel("Добавить своего агента", '<p class="muted">Сейчас вы вошли в аккаунт бизнеса: он подключает готовых агентов. Публикация собственного агента доступна аккаунту разработчика.</p><button type="button" class="btn btn--primary" id="developer-signin">Войти как разработчик</button><p><a class="link" href="/catalog/">Вернуться в каталог</a></p>');
    return;
  }
  if (me.role === "business") await businessView();
  else if (me.role === "developer") await developerView();
  else await adminView();
  draftView();
}
root.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.id === "developer-signin") {
    button.disabled = true;
    try { await logout(); authMode = "signup"; await render(); document.querySelector("#identity").textContent = "Агенты, документы и результаты в одном месте."; }
    catch(error) { tell(error.message,true); button.disabled = false; }
    return;
  }
  if (button.id === "google-login") {
    button.disabled = true;
    tell("Открываем Google…");
    try { await startGoogleLogin(); }
    catch (error) { tell(error.message, true); button.disabled = false; }
    return;
  }
  if (button.dataset.auth) {
    const email = root.querySelector("#auth [name=email]")?.value.trim();
    if (email) rememberConfirmationEmail(email);
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
  if (event.target.id === "integration-create") return;
  event.preventDefault();
  const form = event.target,
    button = event.submitter || form.querySelector("button"),
    data = new FormData(form),
    value = Object.fromEntries(data),
    label = button.textContent;
  button.disabled = true;
  tell();
  try {
    if (form.id === "auth") {
      if (authMode === "login") {
        await login(value);
        rememberConfirmationEmail("");
        goHomeAfterAuth("signed_in"); return;
      }
      else {
        const result = await signup(value);
        if (result.status === "confirmation_required") {
          rememberConfirmationEmail(value.email);
          form.reset();
          goHomeAfterAuth("confirm_email");
          return;
        }
      }
      rememberConfirmationEmail("");
      goHomeAfterAuth("registered"); return;
    } else if (form.id === "confirm-email") {
      if (!form.elements.email.reportValidity()) return;
      rememberConfirmationEmail(value.email);
      if (button.value === "resend") {
        await request("/auth/email/resend", { method: "POST", auth: false, body: { email: value.email } });
        tell("Если адрес ожидает подтверждения, на него придёт новое письмо. Проверьте входящие и спам.");
      } else {
        const result = await request("/auth/email/verify", { method: "POST", auth: false, body: value });
        saveSession(result);
        rememberConfirmationEmail("");
        goHomeAfterAuth("registered");
        return;
      }
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
    if (form.id === "auth" && error.code === "email_not_confirmed") {
      rememberConfirmationEmail(value.email);
      authMode = "confirm";
      authView();
    }
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
    if (form.id === "run") await showRuns();
  } finally {
    button.disabled = false;
    button.textContent = label;
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
  if (returningFromConfirmation && !session()) {
    tell(confirmationFailed ? "Ссылка недействительна или истекла. Запросите новое письмо." : "Войдите с почтой и паролем, чтобы открыть аккаунт.", confirmationFailed);
  }
  try { if (await finishGoogleLogin()) { goHomeAfterAuth("signed_in"); return; } }
  catch (error) { tell(error.message, true); }
  await render();
}
initialize().catch((error) => {
  tell(error.message, true);
  if (!session()) authView();
});
window.addEventListener("keme-session-changed", () => {
  root.innerHTML = "";
  render().catch((error) => { tell(error.message, true); if (!session()) authView(); });
});
