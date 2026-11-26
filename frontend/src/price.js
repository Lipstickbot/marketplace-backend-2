export function formatPrice(amount, language = "ru") {
  return new Intl.NumberFormat(language, { style: "currency", currency: "KZT",
    minimumFractionDigits: amount % 100 === 0 ? 0 : 2 }).format(amount / 100);
}
