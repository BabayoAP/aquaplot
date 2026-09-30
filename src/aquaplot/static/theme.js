/* AquaPlot's light/dark switch, shared by every page.
 *
 * Loaded as a plain script in each page's <head>, so a saved choice is on <html> before the
 * first paint and a dark-mode visitor never sees a white flash. With no saved choice the page
 * follows the device. Pages mark where the switch goes with <span data-theme-switch></span>;
 * any class on that placeholder is kept on the switch. Pages that draw with colours in script
 * listen for the "aquaplot:theme" event.
 */
(() => {
  const KEY = "aquaplot-theme";
  const root = document.documentElement;
  const system = matchMedia("(prefers-color-scheme: dark)");

  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") root.dataset.theme = saved;
  } catch (e) { /* storage blocked: follow the device */ }

  const current = () => root.dataset.theme || (system.matches ? "dark" : "light");
  const sync = () => document.querySelectorAll(".theme-switch")
    .forEach((b) => b.setAttribute("aria-checked", String(current() === "dark")));
  const announce = () => window.dispatchEvent(new CustomEvent("aquaplot:theme", { detail: current() }));

  function set(theme) {
    root.dataset.theme = theme;
    try { localStorage.setItem(KEY, theme); } catch (e) {}
    sync();
    announce();
  }
  system.addEventListener("change", () => { if (!root.dataset.theme) { sync(); announce(); } });
  window.aquaplotTheme = { current, set };

  // An iOS-style switch: a pill track and a white knob that springs across. The knob carries
  // a sun in light mode and a moon in dark mode.
  const style = document.createElement("style");
  style.textContent = `
    .theme-switch { position: relative; flex: none; width: 52px; height: 31px; padding: 0; border: 0;
      border-radius: 999px; cursor: pointer; background: #e3e7ea; box-shadow: inset 0 0 0 1px rgba(0,0,0,.08);
      transition: background-color .3s ease; -webkit-tap-highlight-color: transparent; }
    .theme-switch[aria-checked="true"] { background: var(--accent, #34c759); box-shadow: none; }
    .theme-switch .ts-knob { position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 999px;
      background: #fff; display: grid; place-items: center;
      box-shadow: 0 3px 8px rgba(0,0,0,.15), 0 1px 1px rgba(0,0,0,.16), 0 3px 1px rgba(0,0,0,.1);
      transition: transform .35s cubic-bezier(.3, 1.35, .5, 1), width .2s ease; }
    .theme-switch[aria-checked="true"] .ts-knob { transform: translateX(21px); }
    .theme-switch:active .ts-knob { width: 31px; }
    .theme-switch[aria-checked="true"]:active .ts-knob { transform: translateX(17px); }
    .theme-switch svg { position: absolute; width: 15px; height: 15px; transition: opacity .25s ease, transform .35s ease; }
    .theme-switch .ts-sun { color: #f2a516; }
    .theme-switch .ts-moon { color: #3f5578; opacity: 0; transform: rotate(-40deg) scale(.6); }
    .theme-switch[aria-checked="true"] .ts-sun { opacity: 0; transform: rotate(40deg) scale(.6); }
    .theme-switch[aria-checked="true"] .ts-moon { opacity: 1; transform: none; }
    .theme-switch:focus-visible { outline: 3px solid var(--accent, #0f6b7a); outline-offset: 2px; }
    @media (prefers-reduced-motion: reduce) { .theme-switch, .theme-switch * { transition: none !important; } }`;
  document.head.appendChild(style);

  const SUN = '<svg class="ts-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">'
    + '<circle cx="12" cy="12" r="4.2" fill="currentColor"/><path d="M12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22'
    + 'M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6"/></svg>';
  const MOON = '<svg class="ts-moon" viewBox="0 0 24 24"><path fill="currentColor" '
    + 'd="M20.4 14.6A8.5 8.5 0 0 1 9.4 3.6a8.5 8.5 0 1 0 11 11z"/></svg>';

  function build() {
    document.querySelectorAll("[data-theme-switch]").forEach((slot) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = ("theme-switch " + slot.className).trim();
      b.setAttribute("role", "switch");
      b.setAttribute("aria-label", "Dark mode");
      b.title = "Dark mode";
      b.innerHTML = `<span class="ts-knob">${SUN}${MOON}</span>`;
      b.addEventListener("click", () => set(current() === "dark" ? "light" : "dark"));
      slot.replaceWith(b);
    });
    sync();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
