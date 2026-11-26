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
import { setupIntegrationHistory, renderIntegrationScreen } from "./integrations.js";
import { formatPrice } from "./price.js";
import "./glass-nav.js";
const root = document.querySelector("#workspace"),
  notice = document.querySelector("#notice"),
  workspaceTitle = document.querySelector("#workspace-title");
const workspacePlaceholder = root.firstElementChild.cloneNode(true);
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
const connectionNotice = (state) => state === "approved"
  ? "Агент подключён. Для настройки API нажмите «Открыть агента» в истории."
  : "Заявка отправлена на рассмотрение.";
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
let businessDataOwner, renderVersion = 0;
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
    <p class="muted">Введите код из письма. Если письма нет во входящих, проверьте папку «Спам».</p>
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

function openConfirmation(email) {
  rememberConfirmationEmail(email);
  authMode = "confirm";
  const url = new URL(location.href);
  url.searchParams.set("mode", "confirm");
  history.replaceState(null, "", url);
  authView();
  root.querySelector("[name=code]").focus({ preventScroll: true });
  window.scrollTo(0, 0);
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
        ${intent === "publish" ? '<input type="hidden" name="role" value="business">' : '<label>Что хотите делать?<select name="role"><option value="business">Подключать агентов для бизнеса</option><option value="developer">Добавлять своих агентов</option></select></label>'}` : ""}
      <button type="submit" class="btn btn--primary">${registering ? "Зарегистрироваться" : "Войти"}</button>
    </form>`,
  );
  const purpose = document.createElement("p"); purpose.className = "muted";
  purpose.textContent = intent === "publish" ? "Добавьте собственного агента в каталог: опишите возможности и отправьте заявку на рассмотрение." : intent === "connect" ? "Выберите готового агента из каталога и отправьте запрос на подключение для своей компании." : "Вход сохранится на этом устройстве, пока вы не нажмёте «Выйти».";
  root.querySelector(".work-panel h2").after(purpose);
  if (registering && intent !== "publish")
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
function loadBusinessData() {
  return Promise.all([all("/agents", { auth: false }), all("/connect-requests"), all("/files")]);
}
function renderBusinessRoute() {
  const url = new URL(location.href);
  const order = url.searchParams.get("order");
  if (url.searchParams.get("view") === "payments" && /^[0-9a-f-]{36}$/.test(order || "")) {
    workspaceTitle.textContent = "Покупка агента";
    root.innerHTML = `<div class="work-grid">${panel("Статус оплаты", '<p data-payment-status role="status"></p><form id="purchase-status"><button class="btn btn--secondary">Проверить оплату</button></form><p><a class="link" href="/account/">Вернуться в кабинет</a></p>', true)}</div>`;
    const form = root.querySelector("#purchase-status");
    form.dataset.order = order;
    form.requestSubmit();
    return;
  }
  const openingAgent = url.searchParams.get("view") === "integration" || url.hash === "#application-integrations";
  if (openingAgent) {
    workspaceTitle.textContent = "Подключить к своему приложению";
    const agent = agents.find((a) => a.slug === url.searchParams.get("agent") && a.status === "published"
      && connections.some((c) => c.agent_id === a.id && c.status === "approved"));
    const owner = businessDataOwner;
    renderIntegrationScreen(root, agent, files, tell, (updated) => {
      if (businessDataOwner === owner) files = updated;
    });
    return;
  }
  workspaceTitle.textContent = "Рабочий кабинет";
  document.title = "Кабинет — Keme AI";
  renderBusiness();
  draftView();
}
function renderBusiness(chosen = new URLSearchParams(location.search).get("agent")) {
  const published = agents.filter((a) => a.status === "published");
  const approved = published.filter((a) => connections.some((c) => c.agent_id === a.id && c.status === "approved"));
  const options = published
    .map((a) => `<option value="${e(a.id)}" ${a.slug === chosen ? "selected" : ""}>${e(a.name)}</option>`)
    .join("");
  root.innerHTML = `<div class="work-grid">${panel("Подключить готового агента", `<form id="connect" class="work-form"><label>Агент<select name="agent_id" required>${options}</select></label><p class="muted" data-agent-price hidden></p><label data-connection-task>Задача<textarea name="message" maxlength="4000"></textarea></label><button class="btn btn--primary">Подключить агента</button></form>`, true)}</div>`;

  const connect = root.querySelector("#connect");
  const sync = () => {
    const selected = published.find((a) => a.id === connect.elements.agent_id.value);
    const connected = approved.some((a) => a.id === selected?.id);
    const price = connect.querySelector("[data-agent-price]");
    const paid = selected?.price_minor != null;
    price.hidden = !paid;
    price.textContent = paid ? formatPrice(selected.price_minor) : "";
    connect.querySelector("[data-connection-task]").hidden = paid || connected;
    connect.querySelector("button").textContent = connected ? "Открыть агента" : paid ? "Купить картой" : "Подключить агента";
  };
  connect.elements.agent_id.addEventListener("change", sync);
  sync();

  const grid = root.querySelector(".work-grid");
  void setupIntegrationHistory(grid, agents, connections, tell, status);
  if (approved.length) renderTrialRun(grid, approved, chosen);
  grid.insertAdjacentHTML("beforeend", `<details class="work-panel wide workspace-details" id="run-history"><summary>История запусков</summary><div id="runs" aria-live="polite"></div></details>`);
  const history = grid.querySelector("#run-history");
  history.addEventListener("toggle", () => {
    if (history.open) showRuns();
  });
  if (location.hash === "#integration-history") grid.querySelector("#integration-history")?.scrollIntoView();
  if (location.hash === "#agent-run") grid.querySelector("#agent-run")?.scrollIntoView();
}

function renderTrialRun(grid, approved, chosen) {
  grid.insertAdjacentHTML("beforeend", `<details id="agent-run" class="work-panel wide workspace-details" ${chosen === "business-analytics" ? "open" : ""}><summary>Запуск агента в кабинете</summary><div class="work-grid">${panel(
    "Запуск агента",
    `<form id="run" class="work-form"><label>Агент<select name="slug">${approved.map((a) => `<option value="${e(a.slug)}" ${a.slug === chosen ? "selected" : ""}>${e(a.name)}</option>`).join("")}</select></label><label>Запрос<textarea name="message" required maxlength="8000"></textarea></label><label>Язык<select name="language"><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option><option value="auto">Автоматически</option></select></label><label class="file-picker" data-analysis-file hidden>Таблица в UTF-8 (необязательно)<input name="dataset" type="file" accept=".csv,.tsv"><span class="muted">До 128 КиБ и 5 000 строк данных.</span></label><fieldset data-engine-files><legend>Документы для запроса</legend>${
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
  const local = agent?.slug === "business-analytics";
  form.querySelector("[data-analysis-file]").hidden = !local;
  form.querySelector("[data-engine-files]").hidden = local;
  if (!local) form.elements.dataset.value = "";
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
  if (list.getAttribute("aria-busy") === "true") return;
  list.setAttribute("aria-busy", "true");
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
  } finally {
    list.setAttribute("aria-busy", "false");
  }
}
async function publicationView() {
  const rows = await all("/agent-submissions");
  root.innerHTML = `<div class="work-grid">${panel("Добавить своего агента", '<p class="muted">Опишите агента и отправьте заявку на публикацию в каталоге. Статус появится в разделе «Мои заявки».</p><form id="submission" class="work-form"><label>Название<input name="name" required maxlength="160"></label><label>Категория<input name="category" required maxlength="80"></label><label>Описание и ограничения<textarea name="description" required maxlength="10000"></textarea></label><label>Репозиторий HTTPS<input name="repository_url" type="url" placeholder="https://github.com/…"></label><button class="btn btn--primary">Отправить</button></form>')}${panel("Мои заявки", rows.map((r) => `<div class="work-item"><h3>${e(r.name)}</h3><p>${e(status(r.status))}</p><p>${e(r.review_note || "")}</p></div>`).join("") || "<p>Заявок пока нет.</p>")}</div>`;
}
async function adminView() {
  const [connects, submissions] = await Promise.all([
    all("/admin/connect-requests?status=pending"),
    all("/admin/agent-submissions?status=pending"),
  ]);
  const form = (type, row) =>
    `<form class="work-form work-item" data-review="${type}" data-id="${e(row.id)}"><p>${e(type === "connect-requests" ? row.company_id : row.name)}</p>${type === "connect-requests" ? `<p>${e(row.message)}</p><p class="muted">Агент: ${e(row.agent_id)}</p>` : `<p>${e(row.description)}</p>${row.repository_url ? `<a class="link" href="${e(row.repository_url)}" target="_blank" rel="noopener noreferrer">Открыть репозиторий ↗</a>` : ""}
      <label>Идентификатор в AI Engine (engine_slug)<input name="engine_slug" pattern="[a-z][a-z0-9-]{0,79}" placeholder="sales-assistant"></label>
      <p class="muted">Для активации укажите идентификатор уже подключённого к AI Engine агента.</p>
      <label>Адрес карточки в каталоге<input name="publication_slug" pattern="[a-z][a-z0-9-]{0,79}" placeholder="По умолчанию совпадает с engine_slug"></label>`}<label>Решение<select name="decision"><option value="approved">${type === "agent-submissions" ? "Одобрить и активировать" : "Одобрить"}</option>${type === "agent-submissions" ? '<option value="coming_soon">Одобрить со статусом «Скоро»</option>' : ""}<option value="rejected">Отклонить</option></select></label><label>Комментарий<textarea name="review_note" maxlength="4000"></textarea></label><button class="btn btn--primary">Сохранить решение</button></form>`;
  root.innerHTML = `<div class="work-grid">${panel("Подключения бизнеса", connects.map((r) => form("connect-requests", r)).join("") || "<p>Нет ожидающих заявок.</p>")}${panel("Заявки на публикацию", submissions.map((r) => form("agent-submissions", r)).join("") || "<p>Нет ожидающих заявок.</p>")}</div>`;
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
      tell(draft.kind === "conn" ? connectionNotice(result.status) : "Заявка отправлена.");
      await render();
    } else {
      tell(result.error, true);
      event.currentTarget.disabled = false;
    }
  });
}
async function render() {
  const version = ++renderVersion;
  businessDataOwner = null;
  const active = session();
  workspaceTitle.textContent = "Рабочий кабинет";
  document.title = "Кабинет — Keme AI";
  document.querySelector("#logout").hidden = !active;
  if (!active) {
    root.setAttribute("aria-busy", "false");
    document.querySelector("#identity").textContent = "Подключайте агентов и управляйте доступом к ним.";
    authView();
    return;
  }
  root.setAttribute("aria-busy", "true");
  root.classList.remove("auth-layout");
  const business = intent !== "publish" && active.profile?.role === "business"
    ? loadBusinessData().then((rows) => ({ rows }), (error) => ({ error }))
    : null;
  const me = await request("/auth/me");
  const current = session();
  if (version !== renderVersion || !current || (current.profile?.user_id && current.profile.user_id !== me.user_id)) return;
  saveSession({ ...current, profile: me });
  document.querySelector("#identity").textContent =
    `${me.display_name || me.email || ""} · ${{ business: "Бизнес", developer: "Разработчик", admin: "Администратор" }[me.role]}`;
  if (me.role === "business" && intent !== "publish") {
    const data = business ? await business : { rows: await loadBusinessData() };
    if (version !== renderVersion || session()?.profile?.user_id !== me.user_id) return;
    if (data.error) throw data.error;
    [agents, connections, files] = data.rows;
    businessDataOwner = me.user_id;
    renderBusinessRoute();
  } else {
    if (me.role === "admin") await adminView();
    else await publicationView();
    draftView();
  }
  root.setAttribute("aria-busy", "false");
}

function navigateBusinessView() {
  tell();
  renderBusinessRoute();
  if (!["#integration-history", "#agent-run"].includes(location.hash)) window.scrollTo(0, 0);
}
root.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-workspace-route]");
  if (!link || event.defaultPrevented || event.button !== 0 ||
      event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
      !businessDataOwner || businessDataOwner !== session()?.profile?.user_id) return;
  event.preventDefault();
  if (link.href !== location.href) history.pushState(null, "", link.href);
  navigateBusinessView();
  const heading = location.hash === "#integration-history" ? root.querySelector("#integration-history h2") : workspaceTitle;
  heading?.focus({ preventScroll: true });
});
window.addEventListener("popstate", () => {
  if (businessDataOwner && businessDataOwner === session()?.profile?.user_id) navigateBusinessView();
});
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
    const email = root.querySelector("#auth [name=email]")?.value.trim();
    if (email) rememberConfirmationEmail(email);
    authMode = button.dataset.auth;
    const url = new URL(location.href);
    if (authMode === "signup") url.searchParams.set("mode", "signup");
    else url.searchParams.delete("mode");
    history.replaceState(null, "", url);
    tell();
    authView();
    return;
  }
});
root.addEventListener("submit", async (event) => {
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
        goHomeAfterAuth(); return;
      }
      else {
        const result = await signup(value);
        if (result.status === "confirmation_required") {
          form.reset();
          openConfirmation(value.email);
          return;
        }
      }
      rememberConfirmationEmail("");
      goHomeAfterAuth(); return;
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
        goHomeAfterAuth();
        return;
      }
    } else if (form.id === "purchase-status") {
      const output = root.querySelector("[data-payment-status]");
      output.textContent = "Проверяем оплату…";
      const purchase = await request("/payments/status/" + encodeURIComponent(form.dataset.order), { method: "POST" });
      const agent = agents.find((a) => a.id === purchase.agent_id);
      if (purchase.status === "paid" && agent) {
        location.replace("/account/?view=integration&agent=" + encodeURIComponent(agent.slug));
        return;
      }
      output.textContent = purchase.status === "paid" ? "Оплата подтверждена." : purchase.status === "failed"
        ? "Оплата не завершена. Вы можете попробовать ещё раз в кабинете."
        : "Ожидаем подтверждения PayLink. Проверьте статус ещё раз через несколько секунд.";
    } else if (form.id === "connect") {
      const selected = agents.find((agent) => agent.id === value.agent_id);
      if (selected && connections.some((c) => c.agent_id === selected.id && c.status === "approved")) {
        location.assign("/account/?view=integration&agent=" + encodeURIComponent(selected.slug));
        return;
      }
      if (selected?.price_minor != null) {
        const payment = await request("/payments/checkout", { method: "POST",
          body: { agent_id: selected.id, amount: selected.price_minor } });
        if (payment.status === "connected") {
          location.replace("/account/?view=integration&agent=" + encodeURIComponent(selected.slug));
        } else {
          location.assign(payment.redirect_url);
        }
        return;
      }
      const connection = await request("/connect-requests", { method: "POST", body: value });
      connections.unshift(connection);
      tell(connectionNotice(connection.status));
      renderBusiness(agents.find((agent) => agent.id === connection.agent_id)?.slug);
      draftView();
      root.querySelector("#integration-history")?.scrollIntoView({ behavior: "smooth" });
    } else if (form.id === "run") {
      button.textContent = "Агент выполняет запрос…";
      const selectedFile = data.get("dataset");
      let dataset;
      if (value.slug === "business-analytics" && selectedFile?.name) {
        if (!/\.(csv|tsv)$/i.test(selectedFile.name)) throw new Error("Выберите CSV или TSV.");
        if (selectedFile.size > 128 * 1024) throw new Error("Размер файла должен быть не больше 128 КиБ.");
        if (!selectedFile.size) throw new Error("Файл пуст. Добавьте строку с данными.");
        try {
          dataset = { filename: selectedFile.name, text: new TextDecoder("utf-8", { fatal: true }).decode(await selectedFile.arrayBuffer()) };
        } catch {
          throw new Error("Сохраните таблицу в кодировке UTF-8.");
        }
      }
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
            ...(dataset && { dataset }),
          },
        },
      );
      root.querySelector("#result").textContent = result.execution.response;
      root.querySelector("#result-meta").textContent =
        `${status(result.execution.status)} · ${value.slug === "business-analytics"
          ? "Локальный анализ"
          : `${result.execution.mode === "mock" ? "Демонстрационный ответ (mock)" : result.execution.mode} · ${result.execution.usage.total_tokens} токенов`}${result.audit_saved ? "" : " · Журнал ожидает сверки"}`;
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
      const publication = form.dataset.review === "agent-submissions";
      const activate = publication && value.decision === "approved";
      const body = { decision: value.decision === "coming_soon" ? "approved" : value.decision, review_note: value.review_note };
      if (activate) {
        if (!value.engine_slug) throw new Error("Укажите идентификатор агента в AI Engine.");
        body.engine_slug = value.engine_slug;
        if (value.publication_slug) body.publication_slug = value.publication_slug;
        button.textContent = "Проверяем AI Engine…";
      } else if (publication && value.decision === "coming_soon") {
        if (!value.publication_slug) throw new Error("Укажите адрес карточки в каталоге.");
        body.publication_slug = value.publication_slug;
      }
      await request(`/admin/${form.dataset.review}/${form.dataset.id}/review`, { method: "POST", body });
      tell(activate ? "Агент активирован и доступен в каталоге." : "Решение сохранено.");
      await render();
    }
  } catch (error) {
    if (form.id === "auth" && error.code === "email_not_confirmed") {
      openConfirmation(value.email);
      return;
    }
    if (form.id === "purchase-status") {
      const output = root.querySelector("[data-payment-status]");
      if (output) output.textContent = "Статус оплаты пока не подтверждён.";
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
  try { if (await finishGoogleLogin()) { rememberConfirmationEmail(""); goHomeAfterAuth(); return; } }
  catch (error) { tell(error.message, true); }
  await render();
}
function showWorkspaceError(error) {
  root.setAttribute("aria-busy", "false");
  tell(error.message, true);
  if (!session()) return void render();
  if (!root.querySelector(".work-grid, .integration-screen")) {
    root.innerHTML = panel("Кабинет недоступен", '<button class="btn btn--secondary" type="button" id="retry-workspace">Повторить</button>');
    root.querySelector("#retry-workspace").onclick = () => {
      tell();
      render().catch(showWorkspaceError);
    };
  }
}
initialize().catch(showWorkspaceError);
window.addEventListener("keme-session-changed", () => {
  root.replaceChildren(workspacePlaceholder.cloneNode(true));
  render().catch(showWorkspaceError);
});
