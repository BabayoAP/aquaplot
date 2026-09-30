/* AquaPlot's light/dark switch and the header's ⋮ menu, shared by every page.
 *
 * Loaded as a plain script in each page's <head>, so a saved choice is on <html> before the
 * first paint and a dark-mode visitor never sees a white flash. With no saved choice the page
 * follows the device. Pages mark where the switch goes with <span data-theme-switch></span>;
 * any class on that placeholder is kept on the switch. Pages that draw with colours in script
 * listen for the "aquaplot:theme" event.
 *
 * The menu is a <details class="menu"> written into each page's header, so its links are in
 * the page before any script runs (the check page wires up "ID guide" as it loads) and it
 * opens and closes with no script at all. This file styles it and adds what <details> lacks:
 * closing on a click elsewhere, on Escape, and once an item is chosen.
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
    @media (prefers-reduced-motion: reduce) { .theme-switch, .theme-switch * { transition: none !important; } }

    nav a[aria-current="page"] { color: var(--accent); border-color: var(--accent); }
    .menu { margin: 0; padding: 0; border: 0; }  /* a page's own details styles must not move the button */
    .menu > summary { list-style: none; display: grid; place-items: center; width: 36px; height: 35px; cursor: pointer;
      border-radius: 8px; border: 1px solid var(--line); background: var(--card); color: var(--ink);
      box-shadow: 0 1px 4px rgba(0,0,0,.15); -webkit-tap-highlight-color: transparent;
      transition: color .15s ease, border-color .15s ease; }
    .menu > summary::-webkit-details-marker { display: none; }
    .menu > summary:hover, .menu[open] > summary { color: var(--accent); border-color: var(--accent); }
    .menu > summary:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
    .menu > summary svg { width: 18px; height: 18px; }
    .menu-panel { position: absolute; top: calc(100% + 6px); right: 0; z-index: 30; min-width: 220px; padding: 6px;
      display: flex; flex-direction: column; background: var(--card); border: 1px solid var(--line); border-radius: 12px;
      box-shadow: 0 10px 28px rgba(0,0,0,.2); }
    .menu-panel a { color: var(--ink); text-decoration: none; font-weight: 600; font-size: 14px; padding: 9px 10px;
      border-radius: 8px; transition: background-color .12s ease, color .12s ease; }
    .menu-panel a:hover, .menu-panel a:focus-visible { background: var(--soft, rgba(127,127,127,.12)); color: var(--accent); }
    .menu-panel a[aria-current="page"] { color: var(--accent); }
    .menu-theme { display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer;
      margin-top: 6px; padding: 10px 10px 4px; border-top: 1px solid var(--line); font-weight: 600; font-size: 14px; }

    /* The panel drops in from under the button and leaves the same way, a little faster. Opening
       starts from @starting-style, since a closed <details> never rendered the panel. Closing
       holds ::details-content on screen until the fade ends. A browser without one of those
       skips that half: the menu still opens and closes, only without the motion. */
    .menu-panel { transform-origin: top right;
      transition: opacity .18s cubic-bezier(.2, .8, .2, 1), transform .18s cubic-bezier(.2, .8, .2, 1); }
    .menu:not([open]) .menu-panel { opacity: 0; transform: translateY(-6px) scale(.96); pointer-events: none;
      transition-duration: .12s; transition-timing-function: ease-in; }
    @starting-style { .menu[open] .menu-panel { opacity: 0; transform: translateY(-6px) scale(.96); } }
    .menu:not([open])::details-content { transition: content-visibility .12s allow-discrete; }
    @media (prefers-reduced-motion: reduce) {
      .menu-panel, .menu > summary, .menu-panel a { transition: none; }
      .menu:not([open])::details-content { transition: none; }
    }`;
  document.head.appendChild(style);

  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.menu[open]").forEach((menu) => {
      if (!menu.contains(event.target) || event.target.closest(".menu-panel a")) menu.open = false;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details.menu[open]").forEach((menu) => {
      menu.open = false;
      menu.querySelector("summary").focus();
    });
  });

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
