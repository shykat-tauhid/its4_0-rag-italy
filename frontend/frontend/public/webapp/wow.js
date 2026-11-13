"use strict";
/* Solo grafica: inclina la carta d'identità dell'illustrazione seguendo il puntatore.
   Non tocca la ricerca né le funzioni del sito. Si ferma se la persona ha scelto
   "Riduci le animazioni" (sistema o pannello di accessibilità). */
(() => {
  const art = document.getElementById("heroArt");
  if (!art) return;
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  const fermo = () => mq.matches || document.documentElement.dataset.motion === "1";
  let raf = 0;
  const muovi = e => {
    if (fermo() || raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const r = art.getBoundingClientRect();
      const x = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width - .5) * 2));
      const y = Math.max(-1, Math.min(1, ((e.clientY - r.top) / r.height - .5) * 2));
      art.style.setProperty("--ry", (x * 9).toFixed(2) + "deg");
      art.style.setProperty("--rx", (-y * 7).toFixed(2) + "deg");
    });
  };
  const riposo = () => { art.style.setProperty("--ry", "0deg"); art.style.setProperty("--rx", "0deg"); };
  window.addEventListener("pointermove", muovi, {passive: true});
  document.addEventListener("pointerleave", riposo);
})();
