import { request, BASE } from "./api.js";

const e = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
export const integrationBase = (slug) => new URL(`${BASE}/agents/${encodeURIComponent(slug)}/v1`, location.origin).href;
export const agentLink = (slug) => new URL("/account/?agent=" + encodeURIComponent(slug), location.origin).href;
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

function integrationRecord(row, agentName) {
  const expiry = Date.parse(row.expires_at);
  const inactive = Boolean(row.revoked_at) || expiry <= Date.now();
  const state = row.revoked_at ? "Ключ отозван" : inactive ? "Срок истёк" : "Активно до " + new Date(expiry).toLocaleDateString();
  return `<article class="work-item integration-record">
    <div class="integration-record-head">
      <div><h3>${e(row.name)}</h3><p class="muted">${e(agentName)} · Ключ ${e(row.key_prefix)}… · Создано ${e(new Date(row.created_at).toLocaleDateString())}</p></div>
      <span class="pill">${e(state)}</span>
    </div>
    <div class="integration-addresses">
      ${copyField(`history-url-${row.id}`, "Base URL", integrationBase(row.agent_slug))}
      ${copyField(`history-model-${row.id}`, "Model", `keme/${row.agent_slug}`)}
    </div>
    ${inactive ? "" : `<button class="btn btn--secondary" type="button" data-revoke-integration="${e(row.id)}">Отозвать ключ</button>`}
  </article>`;
}

function connectionRecord(connection, agent, statusLabel) {
  const agentName = agent?.name || "Агент недоступен";
  const canOpen = agent?.status === "published" || agent?.status === "coming_soon";
  const link = canOpen ? new URL(agentLink(agent.slug)) : null;
  if (link && connection.status === "approved" && agent.status === "published") {
    // The view parameter makes opening an agent on its own account page a navigation.
    link.searchParams.set("view", "integration");
    link.hash = "application-integrations";
  }
  return `<li class="connection-record">
    <div><strong>${e(agentName)}</strong>${connection.review_note ? `<p class="muted">${e(connection.review_note)}</p>` : ""}</div>
    <span class="pill connection-status" data-state="${e(connection.status)}">${e(statusLabel(connection.status))}</span>
    ${canOpen ? `<a class="link" href="${e(link)}" aria-label="Открыть агента: ${e(agentName)}">Открыть агента →</a>` : ""}
  </li>`;
}

export async function setupIntegrations(root, agents, connections, files, tell, statusLabel) {
  const url = new URL(location.href);
  const chosen = url.searchParams.get("agent");
  const openingAgent = url.searchParams.get("view") === "integration" || url.hash === "#application-integrations";
  const agent = openingAgent && agents.find(a => a.slug === chosen && a.status === "published"
    && connections.some(c => c.agent_id === a.id && c.status === "approved"));
  const host = document.createElement("section");
  host.className = "work-panel wide"; host.id = "application-integrations";
  if (agent) {
    const documents = files.filter(f => !f.deletion_requested_at && agent.accepted_file_purposes.includes(f.purpose));
    host.innerHTML = `<h2>Подключить к своему приложению</h2><p class="muted">Создайте подключение для конкретной задачи. Агент будет использовать выбранные документы и инструкции при каждом API-запросе.</p><form class="work-form" id="integration-create"><div class="integration-fields"><label>Агент<input value="${e(agent.name)}" readonly></label><label>Название подключения<input name="name" required maxlength="120" placeholder="Например, поддержка моего магазина"></label></div><label>Задача и правила для агента<textarea name="task" maxlength="2000" placeholder="Что агент должен делать, каким тоном отвечать и какие правила учитывать"></textarea></label><div class="integration-fields"><label>Язык ответов<select name="language"><option value="auto">Автоматически</option><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option></select></label><label>Срок действия ключа<select name="expires_in_days"><option value="30">30 дней</option><option value="90" selected>90 дней</option><option value="365">1 год</option></select></label></div><fieldset><legend>Документы для этой задачи</legend>${documents.map(f => `<label><input type="checkbox" name="file_ids" value="${e(f.id)}">${e(f.original_name)}</label>`).join("") || '<p class="muted">Сначала загрузите документы в разделе выше, если они нужны агенту.</p>'}</fieldset><button class="btn btn--primary" type="submit">Создать API-подключение</button></form><div class="integration-credentials" id="integration-new" hidden></div><details class="integration-guide"><summary>Как подключить к приложению или LLM-клиенту</summary><ol><li>Выберите провайдера OpenAI-compatible / Custom OpenAI.</li><li>Укажите Base URL и имя модели из созданного подключения.</li><li>В поле API key вставьте отдельный ключ Keme AI.</li><li>Отключите streaming. Поддерживаются текстовые сообщения.</li></ol><p class="muted">Это готовый агент со своей специализацией. Его нельзя заменить произвольной моделью. Веб-сайт должен вызывать API через свой сервер, чтобы ключ не попадал в публичный код. Ключ можно отозвать здесь в любой момент.</p></details>`;
  }
  const grid = root.querySelector(".work-grid");
  const history = document.createElement("section");
  history.className = "work-panel wide";
  history.id = "integration-history";
  const requests = connections.map((connection) => connectionRecord(
    connection, agents.find((agent) => agent.id === connection.agent_id), statusLabel,
  ));
  history.innerHTML = `<h2>История подключений</h2>
    ${requests.length ? `<ul class="connection-history">${requests.join("")}</ul>` : '<p class="muted">Заявок на подключение пока нет.</p>'}
    <div class="integration-history-list">
      <h3>API-подключения</h3>
      <div id="integration-list" aria-live="polite">Загрузка…</div>
    </div>`;
  if (agent) grid.append(host);
  grid.append(history);
  const box = host.querySelector("#integration-new");
  const list = history.querySelector("#integration-list");
  let historyRequest = 0;
  async function showList() {
    const sequence = ++historyRequest;
    try {
      const rows = await request("/integrations");
      if (sequence !== historyRequest) return;
      list.innerHTML = rows.map((row) => {
        const agentName = agents.find((agent) => agent.slug === row.agent_slug)?.name || row.agent_slug;
        return integrationRecord(row, agentName);
      }).join("") || '<p class="muted">API-подключений пока нет.</p>';
    } catch {
      if (sequence !== historyRequest) return;
      list.innerHTML = '<p class="muted">Не удалось загрузить историю.</p><button type="button" class="btn btn--secondary" data-reload-integration-history>Повторить</button>';
    }
  }
  host.addEventListener("submit", async event => {
    if (event.target.id !== "integration-create") return;
    event.preventDefault(); event.stopPropagation();
    const form = event.target, button = form.querySelector("button"); button.disabled = true;
    try {
      const data = new FormData(form);
      const result = await request("/integrations", { method:"POST", body: {
        agent_slug:agent.slug,name:data.get("name"),task:data.get("task"),language:data.get("language"),
        expires_in_days:Number(data.get("expires_in_days")),file_ids:data.getAll("file_ids"),
      }});
      const { agent_slug: slug, expires_at: expiresAt, id } = result.integration;
      box.dataset.integrationId = id;
      box.innerHTML = `<h3>Подключение создано</h3>
        <p class="muted">Скопируйте ключ сейчас. Он действует до ${e(new Date(expiresAt).toLocaleDateString())}.</p>
        ${copyField("integration-key", "API key", "", true)}
        ${copyField("integration-base", "Base URL", integrationBase(slug))}
        ${copyField("integration-model", "Model", `keme/${slug}`)}
        <details><summary>Пример запроса cURL</summary><pre class="work-code"></pre></details>
        <a class="link" href="#integration-history">Открыть историю подключений</a>`;
      box.querySelector("#integration-key").value = result.api_key;
      box.querySelector("pre").textContent = integrationExample(slug);
      box.hidden = false;
      tell("API-подключение создано. Скопируйте ключ в настройки своего приложения.");
      box.scrollIntoView({behavior:"smooth",block:"center"});
      await showList();
    } catch(error) { tell(error.message,true); }
    finally { button.disabled = false; }
  });
  grid.addEventListener("click", async event => {
    const button = event.target.closest("button"); if (!button) return;
    if (button.hasAttribute("data-reload-integration-history")) {
      button.disabled = true;
      await showList();
      return;
    }
    if (button.dataset.copyField) {
      const field = document.getElementById(button.dataset.copyField);
      if (!field || !grid.contains(field)) return;
      try { await navigator.clipboard.writeText(field.value); tell("Скопировано."); }
      catch { field.focus(); field.select(); tell("Скопируйте выделенное значение вручную.", true); }
      return;
    }
    if (button.dataset.revokeIntegration) {
      button.disabled = true;
      try {
        await request("/integrations/" + button.dataset.revokeIntegration, {method:"DELETE"});
        if (box?.dataset.integrationId === button.dataset.revokeIntegration) {
          box.hidden = true;
          box.replaceChildren();
          delete box.dataset.integrationId;
        }
        tell("Ключ отозван. Новые API-запросы с ним запрещены.");
        await showList();
      } catch(error) { tell(error.message,true); button.disabled = false; }
    }
  });
  await showList();
}
