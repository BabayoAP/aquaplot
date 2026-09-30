/* The ID guide and the photo viewer, shared by every page.
 *
 * The ⋮ menu on every page has "ID guide", so the guide opens over whatever page you are on,
 * not only the check. Anything with a data-open-guide attribute opens it. The check page's
 * animal picker enlarges its photos in the same viewer, through window.aquaplotGuide, and
 * lists the same families from it, so there is one guide, not one per page.
 *
 * Loaded as a plain script in each page's <head>, before the page's own scripts use it. The
 * families are fetched once, when first needed. The guide and the viewer are built the
 * first time they open, and take their colours from the page's own palette.
 */
(() => {
  let families = null, sheet = null, viewer = null, opener = null;

  function load() {
    families = families || fetch("/api/guide")
      .then((r) => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
      .then((g) => g.families)
      .catch((e) => { families = null; throw e; });  // offline now does not mean offline forever
    return families;
  }

  const style = document.createElement("style");
  style.textContent = `
    .idg { position: fixed; inset: auto 0 0 0; z-index: 2000; max-height: 72vh; overflow: auto; padding: 16px;
      background: var(--card, #fff); color: var(--ink, #14202a); border-top: 1px solid var(--line, #dde5e9);
      box-shadow: 0 -12px 40px rgba(0,0,0,.2); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
    .idg[hidden] { display: none; }
    .idg-inner { max-width: 720px; margin: 0 auto; }
    .idg h2 { font-size: 18px; font-weight: 700; margin: 0 0 4px; text-transform: none; letter-spacing: normal; color: inherit; }
    .idg-hint { color: var(--muted, #5c6c78); font-size: 13px; margin: 4px 0 0; }
    .idg .idg-search { width: 100%; margin: 8px 0 4px; border: 1px solid var(--line, #dde5e9); border-radius: 9px; padding: 10px;
      background: transparent; color: inherit; font: inherit; }
    .idg-item { display: flex; gap: 12px; align-items: flex-start; border-bottom: 1px solid var(--line, #dde5e9); padding: 10px 0; }
    .idg-item b { display: block; }
    .idg-s { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted, #5c6c78); }
    .idg-why { color: var(--muted, #5c6c78); font-size: 13px; margin: 6px 0 0; }
    .idg-credit { display: block; font-size: 11px; color: var(--muted, #5c6c78); margin-top: 3px; }
    .idg-btn { border: 1px solid var(--line, #dde5e9); border-radius: 9px; padding: 9px 14px; font: inherit; font-weight: 600;
      background: var(--card, #fff); color: var(--accent, #0f6b7a); cursor: pointer; }
    .idg-close { position: sticky; top: 0; float: right; }
    .idg-zoom { flex: none; padding: 0; border: 0; background: none; border-radius: 8px; cursor: zoom-in; position: relative; line-height: 0; }
    .idg-zoom img { width: 76px; height: 76px; border-radius: 8px; object-fit: cover; display: block; background: var(--line, #dde5e9); }
    .idg-zoom::after { content: ""; position: absolute; right: 3px; bottom: 3px; width: 18px; height: 18px; border-radius: 50%;
      background: rgba(0,0,0,.55) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2.6' stroke-linecap='round'%3E%3Ccircle cx='10.5' cy='10.5' r='6'/%3E%3Cpath d='M15 15l5 5M10.5 8v5M8 10.5h5'/%3E%3C/svg%3E") center / 12px no-repeat; }
    .idg-photo { background: var(--card, #fff); color: var(--ink, #14202a); border: 1px solid var(--line, #dde5e9); border-radius: 14px;
      padding: 12px; width: min(860px, calc(100vw - 24px)); max-height: calc(100vh - 24px);
      font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
    .idg-photo::backdrop { background: rgba(0,0,0,.72); }
    .idg-photo img { display: block; width: 100%; max-height: calc(100vh - 170px); object-fit: contain; border-radius: 9px; background: #000; }
    .idg-photo .idg-cap { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; margin-top: 10px; }
    .idg-photo .idg-cap b { display: block; }
    .idg-photo .idg-credit { font-size: 12px; }
    .idg :focus-visible, .idg-photo :focus-visible { outline: 3px solid var(--accent, #0f6b7a); outline-offset: 2px; border-radius: 4px; }`;
  document.head.appendChild(style);

  const el = (tag, className, text) => {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  // ---- the enlarged photo
  // Shows the thumbnail at once, then swaps in the large version when it arrives. With no signal and
  // the large one never opened before, the thumbnail stays: blurrier, but still the right animal.
  function openPhoto(photo, label, look) {
    if (!viewer) {
      viewer = el("dialog", "idg-photo");
      viewer.setAttribute("aria-labelledby", "idg-pvname");
      viewer.innerHTML = '<img alt=""><div class="idg-cap"><div><b id="idg-pvname"></b><span class="idg-why"></span>'
        + '<a class="idg-credit" target="_blank" rel="noopener"></a></div>'
        + '<button type="button" class="idg-btn" autofocus>Close</button></div>';
      viewer.querySelector("button").addEventListener("click", () => viewer.close());
      viewer.addEventListener("click", (e) => { if (e.target === viewer) viewer.close(); });  // a tap on the backdrop
      document.body.append(viewer);
    }
    const img = viewer.querySelector("img"), lookEl = viewer.querySelector(".idg-why"), credit = viewer.querySelector(".idg-credit");
    img.src = photo.url; img.alt = `Photo of a ${label}`;
    viewer.querySelector("b").textContent = label;
    lookEl.textContent = look || "";
    lookEl.style.display = look ? "block" : "none";
    credit.textContent = `Photo: ${photo.attribution}`;
    credit.href = photo.observation;
    if (photo.large_url) {
      const large = new Image();
      large.onload = () => { if (img.alt === `Photo of a ${label}`) img.src = photo.large_url; };
      large.src = photo.large_url;
    }
    viewer.showModal();
  }

  // ---- the guide
  function build() {
    sheet = el("section", "idg");
    sheet.hidden = true;
    sheet.setAttribute("aria-label", "ID guide");
    sheet.innerHTML = '<div class="idg-inner"><button type="button" class="idg-btn idg-close">Close</button>'
      + "<h2>What am I looking at?</h2>"
      + '<p class="idg-hint">Sorted by how sensitive the animal is. Finding the ones at the top is good news.</p>'
      + '<input type="text" class="idg-search" placeholder="Search, e.g. \'three tails\', \'case\', \'red worm\'" '
      + 'aria-label="Search the identification guide"><p class="idg-hint idg-count"></p><div class="idg-list"></div></div>';
    sheet.querySelector(".idg-close").addEventListener("click", close);
    sheet.querySelector(".idg-search").addEventListener("input", draw);
    document.body.append(sheet);
  }

  async function draw() {
    const count = sheet.querySelector(".idg-count"), list = sheet.querySelector(".idg-list");
    let all;
    try {
      all = await load();
    } catch (e) {
      count.textContent = "The animal list could not load. Check your connection and open the guide again.";
      return;
    }
    // Search the description too, not just the name: a citizen holding a tray knows
    // "three tails" and "a case made of sand", and does not know "Leptoceridae".
    const query = sheet.querySelector(".idg-search").value, q = query.trim().toLowerCase();
    const shown = !q ? all : all.filter((f) =>
      [f.plain_name, f.common_name, f.family, f.group, f.look_for, f.means, f.sensitivity]
        .some((v) => (v || "").toLowerCase().includes(q)));
    list.innerHTML = "";
    shown.forEach((f) => {
      const item = el("div", "idg-item"), text = el("div");
      text.append(
        el("div", "idg-s", `${f.sensitivity}${f.score === null ? "" : ` · score ${f.score}/10`} · ${f.group}`
          + `${f.ept ? " · EPT" : ""}${f.vector ? " · health-relevant" : ""}`),
        el("b", "", f.plain_name), el("div", "", f.look_for), el("div", "idg-why", f.means));
      if (f.photo) {
        const credit = el("a", "idg-credit", `Photo: ${f.photo.attribution}`);
        credit.href = f.photo.observation; credit.target = "_blank"; credit.rel = "noopener";
        text.append(credit);
        // A button of its own, so enlarging a photo never does anything else.
        const zoom = el("button", "idg-zoom");
        zoom.type = "button";
        zoom.setAttribute("aria-label", `Enlarge the photo of a ${f.plain_name}`);
        const img = el("img");
        img.src = f.photo.url; img.alt = `Photo of a ${f.plain_name}`;
        img.loading = "lazy"; img.decoding = "async"; img.width = 76; img.height = 76;
        zoom.append(img);
        zoom.addEventListener("click", () => openPhoto(f.photo, f.plain_name, f.look_for));
        item.append(zoom);
      }
      item.append(text);
      list.append(item);
    });
    count.textContent = q
      ? `${shown.length} of ${all.length} match "${query.trim()}"` + (shown.length ? "" : ". Try a shape or a colour instead of a name.")
      : `${all.length} families.`;
  }

  function open(from) {
    if (!sheet) build();
    opener = from || null;
    sheet.hidden = false;
    sheet.querySelector(".idg-search").focus();
    draw();
  }

  // An opener in the header's menu is hidden once the menu closes, so focus goes back to the menu button.
  function close() {
    sheet.hidden = true;
    if (opener) (opener.closest("details.menu")?.querySelector("summary") || opener).focus();
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-open-guide]");
    if (!trigger) return;
    e.preventDefault();
    open(trigger);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !sheet || sheet.hidden || document.querySelector("dialog[open]")) return;  // an open dialog closes itself first
    close();
  });

  window.aquaplotGuide = { families: load, open, openPhoto };
})();
