"use strict";
/* Accessibilità: le preferenze si applicano subito (attributi su <html> + variabili CSS)
   e vengono salvate nel browser. Questo script va caricato nell'<head>, prima del rendering. */
(() => {
  // Testi nella lingua scelta (i18n.js); senza traduzioni resta l'italiano
  const t = window.I18N?.t ?? ((k, v) => k);
  const KEY = "a11y-prefs-v1";
  const STEPS = [85, 100, 115, 130, 150, 175, 200];
  const FONTS = [
    ["default", t("fontDefault"), "Titillium Web"],
    ["dyslexic", t("fontDys"), "OpenDyslexic"],
    ["hyper", t("fontHyper"), "Atkinson Hyperlegible"]
  ];
  const CVD = [
    ["none", t("cvdNone"), t("cvdNoneD"), ["#0066cc", "#008758", "#a12b2b"]],
    ["deutan", t("cvdDeutan"), t("cvdDeutanD"), ["#0057b8", "#e69f00", "#b34700"]],
    ["tritan", t("cvdTritan"), t("cvdTritanD"), ["#b8194a", "#1b7f4b", "#3b4048"]],
    ["achro", t("cvdAchro"), t("cvdAchroD"), ["#111111", "#767676", "#dedede"]],
    ["contrast", t("cvdContrast"), t("cvdContrastD"), ["#000000", "#ffd400", "#00e5ff"]],
    ["soft", t("cvdSoft"), t("cvdSoftD"), ["#3d6b91", "#4f7f70", "#8a4a47"]]
  ];
  const THEMES = [["auto", t("themeAuto")], ["light", t("themeLight")], ["dark", t("themeDark")]];
  const DEF = {fs:100, font:"default", spacing:false, links:false, motion:false, theme:"auto", cvd:"none"};

  const sane = p => ({
    fs: STEPS.includes(+p.fs) ? +p.fs : 100,
    font: FONTS.some(f => f[0] === p.font) ? p.font : "default",
    spacing: p.spacing === true, links: p.links === true, motion: p.motion === true,
    theme: THEMES.some(t => t[0] === p.theme) ? p.theme : "auto",
    cvd: CVD.some(c => c[0] === p.cvd) ? p.cvd : "none"
  });
  let prefs = (() => { try { return sane({...DEF, ...JSON.parse(localStorage.getItem(KEY) || "{}")}); } catch { return {...DEF}; } })();
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch {} };
  const mq = window.matchMedia("(prefers-color-scheme: dark)");

  function apply(){
    const r = document.documentElement;
    r.style.setProperty("--fs", prefs.fs / 100);
    r.dataset.font = prefs.font;
    r.dataset.spacing = prefs.spacing ? "1" : "0";
    r.dataset.links = prefs.links ? "1" : "0";
    r.dataset.motion = prefs.motion ? "1" : "0";
    r.dataset.cvd = prefs.cvd;
    r.dataset.theme = prefs.theme === "auto" ? (mq.matches ? "dark" : "light") : prefs.theme;
    if (typeof window.aggiornaColoriMappa === "function") window.aggiornaColoriMappa();
  }
  apply();
  mq.addEventListener?.("change", () => { if (prefs.theme === "auto") apply(); });

  /* ---------- Interfaccia ---------- */
  const CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>';
  const opt = (key, val, title, sub = "", extra = "", style = "") =>
    `<button type="button" class="a11y-opt" data-set="${key}:${val}" aria-pressed="false"${style ? ` style="${style}"` : ""}>${extra}<span><span class="t">${title}</span>${sub ? `<small>${sub}</small>` : ""}</span><span class="ck">${CHECK}</span></button>`;
  const sw = cols => `<span class="a11y-sw" aria-hidden="true">${cols.map(c => `<i style="background:${c}"></i>`).join("")}</span>`;
  const toggle = (key, label) =>
    `<button type="button" class="a11y-switch" role="switch" aria-checked="false" data-toggle="${key}"><span>${label}</span><span class="trk" aria-hidden="true"></span></button>`;

  function build(){
    /* Se la pagina ha un pulsante [data-a11y="panel"] (barra in alto) lo si usa per aprire il pannello;
       altrimenti si crea il pulsante tondo fisso in basso a destra, come prima. */
    const trig = document.querySelector('[data-a11y="panel"]');
    const fab = trig || document.createElement("button");
    if (!trig) { fab.type = "button"; fab.className = "a11y-fab"; fab.id = "a11yFab"; }
    if (!trig) fab.setAttribute("aria-label", t("a11yOpts"));
    fab.setAttribute("aria-haspopup", "dialog"); fab.setAttribute("aria-expanded", "false"); fab.setAttribute("aria-controls", "a11yPanel");
    // Same icon as the totem's accessibility button (Font Awesome); it becomes an X while the panel is open
    if (!trig) fab.innerHTML = '<i class="fa-solid fa-universal-access" aria-hidden="true"></i>';

    const panel = document.createElement("div");
    panel.className = "a11y-panel" + (trig ? " a11y-panel--top" : ""); panel.id = "a11yPanel"; panel.hidden = true;
    panel.setAttribute("role", "dialog"); panel.setAttribute("aria-labelledby", "a11yTitle");
    panel.innerHTML = `
      <div class="a11y-head">
        <h2 id="a11yTitle" tabindex="-1">${t("a11yTitle")}</h2>
        <button type="button" class="a11y-x" data-act="close" aria-label="${t("a11yClose")}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
      </div>
      <div class="a11y-body">
        <section class="a11y-sec"><h3>${t("textSize")}</h3>
          <div class="a11y-size">
            <button type="button" data-act="fs-" aria-label="${t("decrease")}">A&minus;</button>
            <output id="a11yFs" aria-live="polite">100%</output>
            <button type="button" data-act="fs+" aria-label="${t("increase")}">A+</button>
          </div></section>
        <section class="a11y-sec"><h3>${t("font")}</h3>
          <div class="a11y-opts">${FONTS.map(f => opt("font", f[0], f[1], f[2], "", `font-family:'${f[2]}',sans-serif !important`)).join("")}</div></section>
        <section class="a11y-sec"><h3>${t("colors")}</h3>
          <div class="a11y-opts">${CVD.map(c => opt("cvd", c[0], c[1], c[2], sw(c[3]))).join("")}</div></section>
        <section class="a11y-sec"><h3>${t("theme")}</h3>
          <div class="a11y-opts c3">${THEMES.map(t => opt("theme", t[0], t[1])).join("")}</div></section>
        <section class="a11y-sec"><h3>${t("readMotion")}</h3>
          ${toggle("spacing", t("spacing"))}
          ${toggle("links", t("underline"))}
          ${toggle("motion", t("reduceMotion"))}</section>
      </div>
      <div class="a11y-foot"><button type="button" class="a11y-reset" data-act="reset">${t("resetAll")}</button></div>`;

    const live = document.createElement("div");
    live.className = "sr-only"; live.setAttribute("role", "status"); live.setAttribute("aria-live", "polite");

    document.body.append(...(trig ? [] : [fab]), panel, live);

    const setIcon = open => {
      const i = fab.querySelector("i");
      if (i) { i.classList.toggle("fa-universal-access", !open); i.classList.toggle("fa-xmark", open); }
    };
    const setOpen = open => {
      panel.hidden = !open;
      fab.setAttribute("aria-expanded", String(open));
      setIcon(open);
      if (open) panel.querySelector("#a11yTitle").focus(); else fab.focus();
    };
    const render = () => {
      panel.querySelector("#a11yFs").textContent = prefs.fs + "%";
      panel.querySelector('[data-act="fs-"]').disabled = prefs.fs <= STEPS[0];
      panel.querySelector('[data-act="fs+"]').disabled = prefs.fs >= STEPS[STEPS.length - 1];
      panel.querySelectorAll("[data-set]").forEach(b => {
        const [k, v] = b.dataset.set.split(":");
        b.setAttribute("aria-pressed", String(prefs[k] === v));
      });
      panel.querySelectorAll("[data-toggle]").forEach(b => b.setAttribute("aria-checked", String(prefs[b.dataset.toggle])));
    };
    const change = msg => { apply(); save(); render(); live.textContent = msg; };

    fab.addEventListener("click", () => setOpen(panel.hidden));
    document.addEventListener("keydown", e => { if (e.key === "Escape" && !panel.hidden) setOpen(false); });
    // Clic fuori dal pannello: si chiude (senza rubare il focus a ciò che è stato cliccato)
    document.addEventListener("pointerdown", e => {
      if (!panel.hidden && !panel.contains(e.target) && !fab.contains(e.target)) { panel.hidden = true; fab.setAttribute("aria-expanded", "false"); setIcon(false); }
    });
    panel.addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.set) {
        const [k, v] = b.dataset.set.split(":");
        prefs[k] = v;
        change(t("activated", {x:b.querySelector(".t").textContent}));
      } else if (b.dataset.toggle) {
        const k = b.dataset.toggle; prefs[k] = !prefs[k];
        change(t(prefs[k] ? "toggleOn" : "toggleOff", {x:b.querySelector("span").textContent}));
      } else if (b.dataset.act === "fs+" || b.dataset.act === "fs-") {
        const i = STEPS.indexOf(prefs.fs) + (b.dataset.act === "fs+" ? 1 : -1);
        prefs.fs = STEPS[Math.min(Math.max(i, 0), STEPS.length - 1)];
        change(t("sizeAnn", {n:prefs.fs}));
      } else if (b.dataset.act === "reset") {
        prefs = {...DEF}; change(t("resetAnn"));
      } else if (b.dataset.act === "close") setOpen(false);
    });
    render();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build); else build();
})();