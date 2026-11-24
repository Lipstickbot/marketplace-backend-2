import { LANGS, T } from "./i18n.js";
import { all, SLUGS } from "./api.js";
import { catalogCopy, getAgent } from "./catalog-data.js";
import { agentMark } from "./catalog-cards.js";
const root = document.querySelector("#directory"),
  url = new URL(location.href);
const e = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let lang = "ru",
  rows = [],
  query = url.searchParams.get("q") || "",
  group = url.searchParams.get("group") || "all";
try {
  lang = localStorage.getItem("keme-lang") || lang;
} catch {}
if (!LANGS.includes(lang)) lang = "ru";
const categoryNames = {
  operations: ["Операции", "Операциялар", "Operations"],
  hr: ["HR и найм", "HR және жалдау", "HR & hiring"],
  analytics: ["Аналитика", "Аналитика", "Analytics"],
  documents: ["Документы", "Құжаттар", "Documents"],
  customer_support: ["Поддержка", "Қолдау", "Support"],
  marketing: ["Маркетинг", "Маркетинг", "Marketing"],
  finance: ["Финансы", "Қаржы", "Finance"],
  sales: ["Продажи", "Сатылым", "Sales"],
  productivity: ["Продуктивность", "Өнімділік", "Productivity"],
};
const categoryLabel = (key) => categoryNames[key]?.[LANGS.indexOf(lang)] || key;
const uiId = (slug) => Object.keys(SLUGS).find((id) => SLUGS[id] === slug);
const text = (ru, kk, en) => ({ ru, kk, en })[lang];
function display(row) {
  const id = uiId(row.engine_slug);
  return id
    ? { ...getAgent(id, lang), row }
    : {
        id: "other",
        name: row.name,
        category: categoryLabel(row.category),
        task: row.description,
        features: row.capabilities,
        row,
      };
}
function profileUrl(row) {
  return "/catalog/?agent=" + encodeURIComponent(row.slug);
}
function badge(row) {
  return row.status === "coming_soon"
    ? text("Скоро", "Жақында", "Coming soon")
    : text("Демо · mock", "Демо · mock", "Demo · mock");
}
function card(row) {
  const a = display(row);
  return `<article class="acard directory-card"><div class="acard__top">${agentMark(a.id)}<span class="pill">${badge(row)}</span></div><p class="acard__cat">${e(a.category)}</p><h3><a href="${profileUrl(row)}">${e(a.name)}</a></h3><p class="acard__task">${e(a.task)}</p><div class="directory-card__foot"><a class="link" href="${profileUrl(row)}">${e(catalogCopy(lang).profile)}</a>${row.status === "published" ? `<a class="link" href="/account/?agent=${encodeURIComponent(row.slug)}&intent=connect">${text("Подключить", "Қосу", "Connect")} →</a>` : ""}</div></article>`;
}
function results() {
  const matches = rows.filter((row) => {
    const a = display(row);
    return (
      (group === "all" ||
        (group === "sup" ? "customer_support" : SLUGS[group]) ===
          row.category ||
        group === row.category) &&
      [a.name, a.task, a.category]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase().trim())
    );
  });
  root.querySelector("#count").textContent =
    catalogCopy(lang).results + " · " + matches.length;
  root.querySelector("#matches").innerHTML =
    matches.map(card).join("") ||
    text("Агенты не найдены", "Агенттер табылмады", "No matching agents");
}
function render() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-label]").forEach((el) => {
    el.textContent = T[lang][el.dataset.label];
  });
  document.querySelectorAll("[data-lang]").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.lang === lang);
    b.setAttribute("aria-pressed", b.dataset.lang === lang);
  });
  const id = url.searchParams.get("agent");
  if (id) {
    const row = rows.find((r) => r.slug === (SLUGS[id] || id));
    if (!row) {
      root.innerHTML = `<a href="/catalog/">${e(catalogCopy(lang).back)}</a><h1>${e(catalogCopy(lang).missing)}</h1>`;
      return;
    }
    const a = display(row);
    root.innerHTML = `<a class="link directory-back" href="/catalog/">${e(catalogCopy(lang).back)}</a><div class="profile-grid"><section class="profile-intro"><div class="profile-identity">${agentMark(a.id)}<span class="pill">${badge(row)}</span></div><h1 class="display">${e(a.name)}</h1><p class="lead">${e(a.task)}</p><ul class="acard__does">${a.features.map((f) => `<li>${e(f)}</li>`).join("")}</ul>${row.status === "published" ? `<a class="btn btn--primary" href="/account/?agent=${encodeURIComponent(row.slug)}">${text("Подключить под свою задачу", "Өз міндетіме қосу", "Connect for my task")}</a>` : `<p>${text("Подключение появится позже.", "Қосылу кейінірек қолжетімді болады.", "Connection will be available later.")}</p>`}</section><section class="profile-example"><h2 class="h2">${e(catalogCopy(lang).sample)}</h2><p>${e(a.input || a.task)}</p><p>${e(a.output || "")}</p><p class="note">${row.status === "published" ? text("Демонстрационный режим. Для запуска войдите и получите одобрение подключения.", "Демо режимі. Кіру және қосылуды мақұлдау қажет.", "Demo mode. Sign in and obtain connection approval before running.") : badge(row)}</p></section></div>`;
    return;
  }
  const c = catalogCopy(lang);
  root.innerHTML = `<header class="directory-head"><h1 class="display">${e(c.title)}</h1><p class="lead">${text("Три демо-агента доступны для подключения. Остальные направления готовятся к запуску.", "Үш демо-агент қосылуға қолжетімді. Қалған бағыттар әзірленуде.", "Three demo agents are available to connect. More business areas are coming soon.")}</p></header><div class="directory-tools"><label class="directory-search"><input id="search" type="search" placeholder="${e(c.search)}" aria-label="${e(c.search)}"></label><label>${e(c.filter)} <select id="group"><option value="all">${e(c.all)}</option>${[...new Set(rows.map((r) => r.category))].map((category) => `<option value="${e(category)}">${e(categoryLabel(category))}</option>`).join("")}</select></label></div><p id="count" class="directory-count" role="status"></p><div id="matches" class="acards"></div>`;
  root.querySelector("#search").value = query;
  const add = document.createElement("a"); add.className = "btn btn--primary directory-add";
  add.href = "/account/?intent=publish&role=developer&mode=signup#submission";
  add.textContent = "+ " + text("Добавить агента", "Агент қосу", "Add agent");
  root.querySelector(".directory-head").append(add);
  root.querySelector("#group").value =
    (group === "sup" ? "customer_support" : SLUGS[group]) || group;
  results();
}
root.addEventListener("input", (event) => {
  if (event.target.id === "search") {
    query = event.target.value;
    results();
  }
});
root.addEventListener("change", (event) => {
  if (event.target.id === "group") {
    group = event.target.value;
    results();
  }
});
document.querySelector(".lang").addEventListener("click", (event) => {
  const button = event.target.closest("[data-lang]");
  if (!button) return;
  lang = button.dataset.lang;
  try {
    localStorage.setItem("keme-lang", lang);
  } catch {}
  render();
});
async function load() {
  root.textContent = text(
    "Загрузка каталога…",
    "Каталог жүктелуде…",
    "Loading catalog…",
  );
  try {
    rows = await all("/agents", { auth: false });
    rows.sort((a, b) => Number(b.status === "published") - Number(a.status === "published"));
    render();
  } catch (error) {
    root.innerHTML = `<h1 class="h2">${text("Каталог недоступен", "Каталог қолжетімсіз", "Catalog unavailable")}</h1><p>${e(error.message)}</p><button class="btn btn--secondary" id="retry">${text("Повторить", "Қайталау", "Retry")}</button>`;
    root.querySelector("#retry").onclick = load;
  }
}
load();
