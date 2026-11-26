import { request, session } from "./api.js";

const storageKey = "keme-paylink-test";
const statuses = {
  successful: "Тестовая оплата подтверждена.",
  unsuccessful: "Тестовая оплата не прошла или была отменена.",
  pending: "Платёж ещё обрабатывается. Проверьте статус позже.",
};

export function setupTestPayments(grid) {
  const panel = document.createElement("details");
  panel.className = "work-panel wide workspace-details";
  panel.id = "test-payments";
  panel.innerHTML = `<summary>Тестовая оплата</summary>
    <p class="muted">Проверка разового платежа. Реальных списаний и покупок нет.</p>
    <div class="work-row billing-actions">
      <button type="button" class="btn btn--primary" data-billing="start">Начать тест</button>
      <button type="button" class="btn btn--secondary" data-billing="check" hidden>Проверить статус PayLink</button>
    </div>
    <div class="work-row billing-actions" data-simulation hidden>
      <button type="button" class="btn btn--primary" data-billing="successful">Показать успешную оплату</button>
      <button type="button" class="btn btn--secondary" data-billing="unsuccessful">Показать отказ</button>
    </div>
    <p class="muted billing-status" role="status"></p>`;
  grid.append(panel);

  const status = panel.querySelector("[role=status]");
  const simulation = panel.querySelector("[data-simulation]");
  const check = panel.querySelector('[data-billing="check"]');
  const start = panel.querySelector('[data-billing="start"]');
  const userId = session()?.profile?.user_id;
  let lastCheckout;
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (userId && saved?.userId === userId) lastCheckout = saved.ticket;
  } catch { /* A new test can still be started. */ }
  check.hidden = !lastCheckout;

  async function perform(action) {
    start.disabled = check.disabled = true;
    panel.setAttribute("aria-busy", "true");
    status.textContent = "Проверяем тестовый платёж…";
    try { await action(); }
    catch (error) { status.textContent = error.message; }
    finally {
      start.disabled = check.disabled = false;
      panel.setAttribute("aria-busy", "false");
    }
  }

  function checkStatus() {
    return perform(async () => {
      const result = await request("/payments/status", { method: "POST", body: lastCheckout });
      status.textContent = "PayLink · " + statuses[result.status];
    });
  }

  panel.addEventListener("click", (event) => {
    const button = event.target.closest("[data-billing]");
    if (!button) return;
    const action = button.dataset.billing;
    if (action === "check") {
      void checkStatus();
    } else if (action === "start") {
      simulation.hidden = true;
      void perform(async () => {
        const plan = await request("/payments/preview");
        if (plan.mode === "simulation") {
          const amount = new Intl.NumberFormat("ru-KZ", { style: "currency", currency: plan.currency }).format(plan.amount / 100);
          status.textContent = `Симуляция · ${amount}. Выберите результат теста.`;
          simulation.hidden = false;
          return;
        }
        const { redirect_url: destination, ...ticket } = await request("/payments/checkout", { method: "POST" });
        try { sessionStorage.setItem(storageKey, JSON.stringify({ userId, ticket })); }
        catch { throw new Error("Разрешите хранилище вкладки, чтобы проверить результат оплаты."); }
        location.assign(destination);
      });
    } else {
      status.textContent = "Симуляция · " + statuses[action];
    }
  });

  if (new URL(location.href).searchParams.get("view") === "payments") {
    panel.open = true;
    if (lastCheckout) void checkStatus();
  }
}
