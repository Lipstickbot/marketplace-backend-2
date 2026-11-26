import { all, request, BASE } from "./api.js";
import { isAnalyticsAgent } from "./analytics-agent.js";

const e = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
export const integrationBase = (slug) => new URL(`${BASE}/agents/${encodeURIComponent(slug)}/v1`, location.origin).href;
export function agentLink(slug, view) {
  const url = new URL("/account/?agent=" + encodeURIComponent(slug), location.origin);
  if (view) url.searchParams.set("view", view);
  return url.href;
}
export function integrationExample(slug, base = integrationBase(slug)) {
  return `curl "${base}/chat/completions" \\\n  -H "Authorization: Bearer YOUR_KEME_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify({ model: "keme/" + slug, messages: [{role:"user",content:"Помоги выполнить мою задачу"}], stream:false })}'`;
}

function copyField(id, name, value = "", secret = false) {
  return `<div class="integration-field">
    <label for="${e(id)}">${e(name)}</label>
    <div class="integration-copy">
      <input id="${e(id)}" type="${secret ? "password" : "text"}" value="${e(value)}" readonly autocomplete="off">
      <button type="button" class="btn btn--secondary" data-copy-field="${e(id)}" aria-label="Скопировать ${e(name)}">Копировать</button>
    </div>
  </div>`;
}

function connectionRecord(connection, agent, statusLabel) {
  const agentName = agent?.name || "Агент недоступен";
  const canOpen = agent?.status === "published" || agent?.status === "coming_soon";
  const opensWorkspace = canOpen && connection.status === "approved" && agent.status === "published";
  const link = canOpen ? agentLink(agent.slug, opensWorkspace ? "integration" : undefined) : null;
  const route = opensWorkspace ? " data-workspace-route" : "";
  return `<li class="connection-record">
    <div><strong>${e(agentName)}</strong>${connection.review_note ? `<p class="muted">${e(connection.review_note)}</p>` : ""}</div>
    <span class="pill connection-status" data-state="${e(connection.status)}">${e(statusLabel(connection.status))}</span>
    ${canOpen ? `<a class="link" href="${e(link)}"${route} aria-label="Открыть агента: ${e(agentName)}">Открыть агента →</a>` : ""}
  </li>`;
}

export function renderConnectionHistory(grid, agents, connections, statusLabel) {
  const history = document.createElement("section");
  history.className = "work-panel wide";
  history.id = "integration-history";
  const requests = connections.map((connection) => connectionRecord(
    connection, agents.find((agent) => agent.id === connection.agent_id), statusLabel,
  ));
  history.innerHTML = `<h2 tabindex="-1">История подключений</h2>
    ${requests.length ? `<ul class="connection-history">${requests.join("")}</ul>` : '<p class="muted">Заявок на подключение пока нет.</p>'}`;
  grid.append(history);
}

function setupCredentials(box, agent, tell) {
  let connections = [];
  let selectedId;
  let issued;
  let loaded = false;
  let requestVersion = 0;

  function render() {
    const row = connections.find((item) => item.id === selectedId) || connections[0];
    box.hidden = !row;
    if (!row) {
      box.replaceChildren();
      return;
    }
    selectedId = row.id;
    const key = issued?.id === row.id ? issued.key : null;
    const expiry = new Date(row.expires_at).toLocaleDateString();
    box.innerHTML = `<h2>${key ? "Подключение создано" : "Параметры подключения"}</h2>
      ${connections.length > 1 ? `<div class="integration-field"><label for="integration-selection">Подключение</label>
        <select id="integration-selection">${connections.map((item) => `<option value="${e(item.id)}" ${item.id === row.id ? "selected" : ""}>${e(item.name)} · ${e(item.key_prefix)}…</option>`).join("")}</select>
      </div>` : ""}
      <p class="muted">${key ? "Скопируйте ключ сейчас. Он действует до" : "Ключ действует до"} ${e(expiry)}.</p>
      ${key ? copyField("integration-key", "API key", "", true)
        : `<p class="muted">API key · ${e(row.key_prefix)}…</p>`}
      ${copyField("integration-base", "Base URL", integrationBase(row.agent_slug))}
      ${copyField("integration-model", "Model", `keme/${row.agent_slug}`)}
      <details><summary>Пример запроса cURL</summary><pre class="work-code"></pre></details>
      <div><button class="btn btn--secondary" type="button" data-revoke-integration="${e(row.id)}">Отозвать ключ</button></div>`;
    if (key) box.querySelector("#integration-key").value = key;
    box.querySelector("pre").textContent = integrationExample(row.agent_slug);
  }

  async function load() {
    const version = ++requestVersion;
    try {
      const rows = await request("/integrations?agent_id=" + encodeURIComponent(agent.id));
      if (version !== requestVersion || !box.isConnected) return;
      loaded = true;
      connections = rows.filter((row) => row.agent_id === agent.id && !row.revoked_at
        && Date.parse(row.expires_at) > Date.now());
      render();
    } catch {
      if (version !== requestVersion || !box.isConnected || connections.length) return;
      box.hidden = false;
      box.innerHTML = '<p class="muted">Не удалось загрузить параметры подключения.</p><div><button type="button" class="btn btn--secondary" data-reload-credentials>Повторить</button></div>';
    }
  }

  box.addEventListener("change", (event) => {
    if (event.target.id !== "integration-selection") return;
    selectedId = event.target.value;
    render();
    box.querySelector("#integration-selection")?.focus();
  });
  box.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.hasAttribute("data-reload-credentials")) {
      button.disabled = true;
      await load();
      return;
    }
    const id = button.dataset.revokeIntegration;
    if (!id) return;
    button.disabled = true;
    try {
      await request("/integrations/" + encodeURIComponent(id), { method: "DELETE" });
      if (!box.isConnected) return;
      requestVersion++;
      connections = connections.filter((row) => row.id !== id);
      if (issued?.id === id) issued = undefined;
      render();
      tell("Ключ отозван.");
    } catch (error) {
      if (box.isConnected) tell(error.message, true);
      button.disabled = false;
    }
  });
  void load();
  return ({ integration, api_key: key }) => {
    if (!box.isConnected) return;
    requestVersion++;
    issued = { id: integration.id, key };
    selectedId = integration.id;
    connections = [integration, ...connections.filter((row) => row.id !== integration.id)];
    render();
    if (!loaded) void load();
  };
}

function enableCopy(container, tell) {
  container.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-field]");
    if (!button) return;
    const field = document.getElementById(button.dataset.copyField);
    if (!field || !container.contains(field)) return;
    try {
      await navigator.clipboard.writeText(field.value);
      tell("Скопировано.");
    } catch {
      field.focus();
      field.select();
      tell("Скопируйте выделенное значение вручную.", true);
    }
  });
}

const purposes = {
  brief: "Бриф",
  knowledge_base: "База знаний",
  resume: "Резюме",
  job_description: "Описание вакансии",
};
const historyUrl = "/account/#integration-history";

export function renderIntegrationScreen(root, agent, files, tell, updateFiles) {
  root.innerHTML = `
    <a class="link integration-back" href="${historyUrl}" data-workspace-route>← К истории подключений</a>
    <div class="work-grid">
      <section class="work-panel wide integration-screen" id="application-integrations"></section>
    </div>`;
  const host = root.querySelector("#application-integrations");
  if (!agent) {
    host.innerHTML = '<p>Настройка доступна после одобрения подключения этого агента.</p>';
    return;
  }
  document.title = `Настройка ${agent.name} — Keme AI`;
  const acceptedPurposes = agent.accepted_file_purposes;
  host.innerHTML = `
    <div class="work-row">
      <a class="link" href="${e(agentLink(agent.slug, "run"))}" data-workspace-route>${isAnalyticsAgent(agent.slug) ? "Запустить анализ CSV или TSV" : "Запустить агента"} →</a>
    </div>
    <p class="muted">${acceptedPurposes.length
      ? "Задайте инструкции для агента и при необходимости добавьте документы. Агент будет использовать их при каждом API-запросе."
      : "Задайте инструкции и язык ответов для своего приложения."}</p>
    <form class="work-form" id="integration-create">
      <div class="integration-fields">
        <label>Агент<input value="${e(agent.name)}" readonly></label>
        <label>Название подключения<input name="name" required maxlength="120" placeholder="Например, поддержка моего магазина"></label>
      </div>
      <label>Задача и правила для агента<textarea name="task" maxlength="2000" placeholder="Что агент должен делать и какие правила учитывать"></textarea></label>
      <div class="integration-fields">
        <label>Язык ответов<select name="language"><option value="auto">Автоматически</option><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option></select></label>
        <label>Срок действия ключа<select name="expires_in_days"><option value="30">30 дней</option><option value="90" selected>90 дней</option><option value="365">1 год</option></select></label>
      </div>
    </form>
    ${acceptedPurposes.length ? `
      <fieldset class="integration-documents">
        <legend>Документы для этой задачи</legend>
        <p class="muted">PDF, DOCX или TXT до 10 МиБ. Отметьте файлы, которые агент будет использовать.</p>
        <form class="work-form" id="integration-upload">
          <div class="integration-fields">
            <label class="file-picker">Файл<input name="file" type="file" accept=".pdf,.docx,.txt" required></label>
            <label>Назначение<select name="purpose">${acceptedPurposes.map((p) => `<option value="${e(p)}">${e(purposes[p] || p)}</option>`).join("")}</select></label>
          </div>
          <div class="work-row"><button class="btn btn--secondary" type="submit">Загрузить документ</button></div>
        </form>
        <div id="integration-documents-list"></div>
      </fieldset>` : ""}
    <button class="btn btn--primary integration-submit" type="submit" form="integration-create">Создать API-подключение</button>
    <section class="integration-credentials" id="integration-new" hidden></section>
    <details class="integration-guide">
      <summary>Как подключить к приложению или LLM-клиенту</summary>
      <ol><li>Выберите провайдера OpenAI-compatible / Custom OpenAI.</li><li>Укажите Base URL и имя модели из созданного подключения.</li><li>В поле API key вставьте отдельный ключ Keme AI.</li><li>Отключите streaming. Поддерживаются текстовые сообщения.</li></ol>
      <p class="muted">Храните ключ на сервере своего приложения.</p>
    </details>`;

  const form = host.querySelector("#integration-create");
  const upload = host.querySelector("#integration-upload");
  const list = host.querySelector("#integration-documents-list");
  const box = host.querySelector("#integration-new");
  const showCredentials = setupCredentials(box, agent, tell);
  let working = false;

  function renderDocuments(selected = new FormData(form).getAll("file_ids")) {
    if (!list) return;
    list.innerHTML = files.filter((file) => acceptedPurposes.includes(file.purpose)).map((file) => `
      <div class="work-item integration-document">
        <div>
          <label>${file.deletion_requested_at ? "" : `<input type="checkbox" name="file_ids" value="${e(file.id)}" form="integration-create" ${selected.includes(file.id) ? "checked" : ""}>`} ${e(file.original_name)}</label>
          <p class="muted">${e(purposes[file.purpose] || file.purpose)} · ${file.deletion_requested_at ? "Ожидает удаления" : file.engine_file_id ? "Загружен" : "Ожидает синхронизации"}</p>
        </div>
        <div class="work-row">
          ${file.deletion_requested_at ? "" : `<button class="btn btn--secondary" type="button" data-download="${e(file.id)}">Скачать</button>`}
          <button class="btn btn--secondary" type="button" data-delete="${e(file.id)}">Удалить</button>
        </div>
      </div>`).join("");
  }

  async function perform(action) {
    if (working) return;
    working = true;
    const buttons = host.querySelectorAll(".integration-submit, #integration-upload button, [data-delete]");
    buttons.forEach((button) => { button.disabled = true; });
    tell();
    try {
      await action();
    } catch (error) {
      if (error.details?.original_saved) {
        files = await all("/files").catch(() => files);
        updateFiles(files);
        renderDocuments();
      }
      tell(error.message + (error.details?.original_saved ? " Оригинал сохранён." : ""), true);
    } finally {
      working = false;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  renderDocuments();
  enableCopy(host, tell);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const data = new FormData(form);
    void perform(async () => {
      const result = await request("/integrations", { method: "POST", body: {
        agent_slug: agent.slug,
        name: data.get("name"),
        task: data.get("task"),
        language: data.get("language"),
        expires_in_days: Number(data.get("expires_in_days")),
        file_ids: data.getAll("file_ids"),
      } });
      if (!box.isConnected) return;
      showCredentials(result);
      tell("API-подключение создано. Скопируйте ключ в настройки своего приложения.");
      box.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
  upload?.addEventListener("submit", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const data = new FormData(upload);
    void perform(async () => {
      const file = data.get("file");
      if (!file.size || file.size > 10 * 1024 * 1024)
        throw new Error("Выберите непустой файл до 10 МиБ.");
      const saved = await request("/files/upload", { method: "POST", body: data });
      files = [saved, ...files];
      updateFiles(files);
      renderDocuments([...new FormData(form).getAll("file_ids"), saved.id]);
      upload.reset();
      tell("Документ загружен и отмечен для этой задачи.");
    });
  });
  list?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete], [data-download]");
    if (!button || working) return;
    const file = files.find((item) => item.id === (button.dataset.delete || button.dataset.download));
    if (!file) return;
    if (button.dataset.delete) {
      if (!confirm("Удалить документ из хранилища и движка?")) return;
      await perform(async () => {
        try {
          await request("/files/" + encodeURIComponent(file.id), { method: "DELETE" });
        } catch (error) {
          files = await all("/files").catch(() => files);
          updateFiles(files);
          renderDocuments();
          throw error;
        }
        files = files.filter((item) => item.id !== file.id);
        updateFiles(files);
        renderDocuments();
        tell("Документ удалён.");
      });
      return;
    }
    button.disabled = true;
    try {
      const blob = await request("/files/" + encodeURIComponent(file.id) + "/download", { binary: true });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.original_name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      tell(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}
