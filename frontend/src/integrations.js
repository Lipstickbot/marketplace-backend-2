import { request, BASE } from "./api.js";

const e = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
export const integrationBase = () => new URL(BASE + "/v1", location.origin).href;
export const agentLink = (slug) => new URL("/account/?agent=" + encodeURIComponent(slug), location.origin).href;
export function integrationExample(slug, base = integrationBase()) {
  return `curl "${base}/chat/completions" \\\n  -H "Authorization: Bearer YOUR_KEME_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify({ model: "keme/" + slug, messages: [{role:"user",content:"Помоги выполнить мою задачу"}], stream:false })}'`;
}

export async function setupIntegrations(root, agents, connections, files, tell) {
  const approved = agents.filter(a => a.status === "published" && connections.some(c => c.agent_id === a.id && c.status === "approved"));
  const chosen = new URLSearchParams(location.search).get("agent");
  const host = document.createElement("section");
  host.className = "work-panel wide"; host.id = "application-integrations";
  host.innerHTML = `<h2>Подключить к своему приложению</h2><p class="muted">Создайте подключение для конкретной задачи. Агент будет использовать выбранные документы и инструкции при каждом API-запросе.</p>${approved.length ? `<form class="work-form" id="integration-create"><div class="integration-fields"><label>Агент<select name="agent_slug">${approved.map(a => `<option value="${e(a.slug)}" ${a.slug === chosen ? "selected" : ""}>${e(a.name)}</option>`).join("")}</select></label><label>Название подключения<input name="name" required maxlength="120" placeholder="Например, поддержка моего магазина"></label></div><label>Задача и правила для агента<textarea name="task" maxlength="2000" placeholder="Что агент должен делать, каким тоном отвечать и какие правила учитывать"></textarea></label><div class="integration-fields"><label>Язык ответов<select name="language"><option value="auto">Автоматически</option><option value="ru">Русский</option><option value="kk">Қазақша</option><option value="en">English</option></select></label><label>Срок действия ключа<select name="expires_in_days"><option value="30">30 дней</option><option value="90" selected>90 дней</option><option value="365">1 год</option></select></label></div><fieldset><legend>Документы для этой задачи</legend>${files.filter(f => !f.deletion_requested_at).map(f => `<label data-integration-purpose="${e(f.purpose)}"><input type="checkbox" name="file_ids" value="${e(f.id)}">${e(f.original_name)}</label>`).join("") || '<p class="muted">Сначала загрузите документы в разделе выше, если они нужны агенту.</p>'}</fieldset><button class="btn btn--primary" type="submit">Создать API-подключение</button></form>` : '<p class="muted">Сначала запросите подключение готового агента и дождитесь одобрения. После этого здесь появится настройка API.</p>'}<div id="integration-new" hidden></div><h3 class="integration-heading">Мои API-подключения</h3><div id="integration-list">Загрузка…</div><details class="integration-guide"><summary>Как подключить к приложению или LLM-клиенту</summary><ol><li>Выберите провайдера OpenAI-compatible / Custom OpenAI.</li><li>Укажите Base URL и имя модели из созданного подключения.</li><li>В поле API key вставьте отдельный ключ Keme AI.</li><li>Отключите streaming. Поддерживаются текстовые сообщения.</li></ol><p class="muted">Это готовый агент со своей специализацией. Его нельзя заменить произвольной моделью. Веб-сайт должен вызывать API через свой сервер, чтобы ключ не попадал в публичный код. Ключ можно отозвать здесь в любой момент.</p></details>`;
  root.querySelector(".work-grid").append(host);
  const sync = () => {
    const a = approved.find(a => a.slug === host.querySelector("[name=agent_slug]")?.value);
    host.querySelectorAll("[data-integration-purpose]").forEach(label => {
      label.hidden = !a?.accepted_file_purposes.includes(label.dataset.integrationPurpose);
      if (label.hidden) label.querySelector("input").checked = false;
    });
  };
  host.querySelector("[name=agent_slug]")?.addEventListener("change", sync); sync();
  const showList = async () => {
    const rows = await request("/integrations");
    host.querySelector("#integration-list").innerHTML = rows.map(r => {
      const inactive = r.revoked_at || Date.parse(r.expires_at) <= Date.now();
      return `<div class="work-item"><strong>${e(r.name)}</strong><p class="muted">keme/${e(r.agent_slug)} · ${e(r.key_prefix)}… · ${r.revoked_at ? "Отозван" : inactive ? "Срок истёк" : "До " + new Date(r.expires_at).toLocaleDateString()}</p>${inactive ? "" : `<button class="btn btn--secondary" type="button" data-revoke-integration="${e(r.id)}">Отозвать ключ</button>`}</div>`;
    }).join("") || '<p class="muted">Подключений пока нет.</p>';
  };
  host.addEventListener("submit", async event => {
    if (event.target.id !== "integration-create") return;
    event.preventDefault(); event.stopPropagation();
    const form = event.target, button = form.querySelector("button"); button.disabled = true;
    try {
      const data = new FormData(form);
      const result = await request("/integrations", { method:"POST", body: {
        agent_slug:data.get("agent_slug"),name:data.get("name"),task:data.get("task"),language:data.get("language"),
        expires_in_days:Number(data.get("expires_in_days")),file_ids:data.getAll("file_ids"),
      }});
      const box = host.querySelector("#integration-new"); box.hidden = false; box.className = "integration-credentials";
      box.innerHTML = `<h3>Подключение создано</h3><p class="muted">Скопируйте ключ сейчас: повторно он не отображается. Ключ разрешает работу только этого агента с указанными документами. Истекает ${e(new Date(result.integration.expires_at).toLocaleDateString())}.</p><label>API key<span class="integration-copy"><input id="integration-key" type="password" readonly autocomplete="off" aria-label="API key"><button type="button" class="btn btn--secondary" data-copy-field="integration-key">Копировать</button></span></label><label>Base URL<span class="integration-copy"><input id="integration-base" readonly aria-label="Base URL" value="${e(integrationBase())}"><button type="button" class="btn btn--secondary" data-copy-field="integration-base">Копировать</button></span></label><label>Model<input readonly value="${e('keme/' + result.integration.agent_slug)}"></label><details><summary>Пример запроса cURL</summary><pre class="work-code"></pre></details>`;
      box.querySelector("#integration-key").value = result.api_key;
      box.querySelector("pre").textContent = integrationExample(result.integration.agent_slug);
      await showList(); tell("API-подключение создано. Скопируйте ключ в настройки своего приложения.");
      box.scrollIntoView({behavior:"smooth",block:"center"});
    } catch(error) { tell(error.message,true); }
    finally { button.disabled = false; }
  });
  host.addEventListener("click", async event => {
    const button = event.target.closest("button"); if (!button) return;
    if (button.dataset.copyField) {
      try { await navigator.clipboard.writeText(host.querySelector("#" + button.dataset.copyField).value); tell("Скопировано."); }
      catch { tell("Выделите значение поля и скопируйте вручную.",true); }
    }
    if (button.dataset.revokeIntegration) {
      button.disabled = true;
      try {
        await request("/integrations/" + button.dataset.revokeIntegration, {method:"DELETE"});
        host.querySelector("#integration-new").hidden = true; host.querySelector("#integration-new").replaceChildren();
        await showList(); tell("Ключ отозван. Новые API-запросы с ним запрещены.");
      } catch(error) { tell(error.message,true); button.disabled = false; }
    }
  });
  await showList();
}
