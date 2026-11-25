const nav = document.querySelector(".glass-nav");
const links = nav.querySelectorAll("a");
const current = nav.querySelector('[aria-current="page"]');
const pill = document.createElement("span");
pill.className = "glass-nav__pill";
pill.setAttribute("aria-hidden", "true");
nav.prepend(pill);

let pointedLink;
let pressedLink;

function positionPill() {
  const link = pressedLink || pointedLink || nav.querySelector("a:focus-visible") || current;
  pill.style.setProperty("--pill-x", `${link.offsetLeft}px`);
  pill.style.setProperty("--pill-width", `${link.offsetWidth}px`);
}

positionPill();
nav.classList.add("glass-nav--ready");

nav.addEventListener("pointerover", (event) => {
  if (event.pointerType === "touch") return;
  pointedLink = event.target.closest("a");
  positionPill();
});
nav.addEventListener("pointerleave", () => {
  pointedLink = null;
  positionPill();
});
nav.addEventListener("focusin", positionPill);
nav.addEventListener("focusout", () => queueMicrotask(positionPill));
nav.addEventListener("pointerdown", (event) => {
  const link = event.target.closest("a");
  if (link && event.button === 0) {
    pressedLink = link;
    nav.classList.add("glass-nav--pressed");
    positionPill();
  }
});
for (const eventType of ["pointerup", "pointercancel"]) {
  window.addEventListener(eventType, () => {
    if (!pressedLink) return;
    pressedLink = null;
    nav.classList.remove("glass-nav--pressed");
    positionPill();
  });
}
// Match the selected page again when a document is restored from browser history.
window.addEventListener("pageshow", () => {
  pressedLink = pointedLink = null;
  nav.classList.remove("glass-nav--pressed");
  positionPill();
});

// Localized labels and font loading can change the widths without a window resize.
const observer = new ResizeObserver(positionPill);
links.forEach((link) => observer.observe(link));
