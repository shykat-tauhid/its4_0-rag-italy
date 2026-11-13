"use strict";
// Testi nella lingua scelta sul totem (i18n.js); l'HTML si traduce subito, prima di disegnare
const t = I18N.t, LANG = I18N.lang;
I18N.applica();
document.title = t("title");
// Dentro il totem: "Indietro" chiede alla pagina che ci contiene di tornare alla scelta
// Kiosk: no page zoom from a touchpad pinch (Ctrl + wheel) or Safari gestures; touch pinch is off in style.css.
document.addEventListener("wheel", e => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
document.addEventListener("gesturestart", e => e.preventDefault());
// Kiosk: nessun menu tenendo premuto (o col tasto destro)
document.addEventListener("contextmenu", e => e.preventDefault());
// Dentro il totem non ci sono schede: i link che aprirebbero una nuova scheda o un altro sito
// si aprono nel totem stesso, sopra la web app.
if (I18N.embed) document.addEventListener("click", e => {
  const a = e.target.closest?.("a[href]");
  if (!a) return;
  const url = new URL(a.href, location.href);
  if (a.target !== "_blank" && url.origin === location.origin) return;
  e.preventDefault();
  const copia = a.cloneNode(true);
  copia.querySelectorAll(".sr-only").forEach(el => el.remove());
  const title = copia.textContent.trim() || a.getAttribute("aria-label") || url.hostname;
  parent.postMessage({type:"tramite:open", url:url.href, title}, location.origin);
}, true);
document.getElementById("btnLang")?.addEventListener("click", () => parent.postMessage({type:"tramite:lang"}, location.origin));
document.getElementById("btnTotem")?.addEventListener("click", () => parent.postMessage({type:"tramite:back"}, location.origin));
/* Nessuna chiave API né pagamento: mappa Leaflet + dati OpenStreetMap
   (Overpass API per le sedi, Nominatim per la ricerca delle città).
   Velocità: (1) Anagrafi e CAF in un'unica query; (2) risultati salvati in cache locale;
   (3) server Overpass interrogati "a staffetta" (il successivo parte se il primo è lento o fallisce);
   (4) i raggi 3 e 5 km si precaricano in background. */

const OVERPASS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.private.coffee/api/interpreter",
  "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
];
const NOMINATIM = "https://nominatim.openstreetmap.org/search";

const CATEGORIE = ["carta_identita", "caf"];
const RAGGI = [1, 3, 5, 10];
const ATTESA_MIRROR = 1200;       // ms: se il server non risponde entro tanto, si prova in parallelo il successivo
// Tempo massimo per l'intera ricerca (server pubblici a volte lenti: meglio aspettare che fallire)
const budget = km => km <= 3 ? 14000 : 20000;
const CACHE_TTL = 24 * 3600 * 1000; // 24 ore
const PREFISSO_CACHE = "sedi6:";

const state = {
  cat:"carta_identita", raggio:1,
  centro:{lat:41.9028, lng:12.4964, nome:"Roma"},
  dati:{carta_identita:null, caf:null},          // per categoria: {items, area:{lat, lng, km}}
  caricando:{carta_identita:false, caf:false},
  errore:{carta_identita:null, caf:null},
  dettaglio:{carta_identita:"", caf:""},
  reale:false,          // true = stiamo usando la posizione vera dell'utente
  ripiego:false,        // true = posizione non disponibile, si cerca dal centro di Roma
  avviso:"",            // avviso "persistente" (es. posizione non trovata), in HTML sicuro
  alternativa:false, precarico:"", soloAperti:false
};
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let map, circle, centroMarker, layer, markers = [], token = 0, visibili = [];

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const haversine = (a, b, c, d) => {
  const R = 6371, r = x => x*Math.PI/180, dLa = r(c-a), dLo = r(d-b);
  const h = Math.sin(dLa/2)**2 + Math.cos(r(a))*Math.cos(r(c))*Math.sin(dLo/2)**2;
  return 2*R*Math.asin(Math.sqrt(h));
};
// Movimento ridotto: rispetta sia il sistema operativo sia il pannello accessibilità
const scorri = () => matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "1" ? "auto" : "smooth";
// "Roma, Roma Capitale, Lazio, Italia" → "Roma, Roma Capitale"
const nomeBreve = n => String(n).split(",").slice(0, 2).join(",").trim();
// "480 m" sotto il km, "2,4 km" sopra (virgola all'italiana)
const numero = new Intl.NumberFormat(LANG, {minimumFractionDigits:1, maximumFractionDigits:1});
const distanza = km => km < 1 ? `${Math.max(10, Math.round(km*100)*10)} m` : `${numero.format(km)} km`;
// A piedi ~80 m al minuto; oltre i 2 km non ha senso indicarlo
const aPiedi = km => km <= 2 ? t("walk", {n:Math.max(1, Math.round(km*1000/80))}) : "";

/* ---------- Annunci per lo screen reader ----------
   Una sola regione live (#statusSr): riceve solo frasi significative e mai due volte la stessa. */
let ultimoAnnuncio = "";
function annuncia(t){ if (t && t !== ultimoAnnuncio) { ultimoAnnuncio = t; $("#statusSr").textContent = t; } }

/* ---------- Icone (SVG decorativi: aria-hidden) ---------- */
const svg = (p, w = 22, sw = 2) => `<svg width="${w}" height="${w}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const ico = {
  pin:   svg('<path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>'),
  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  phone: svg('<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>'),
  nav:   svg('<path d="M3 11l18-8-8 18-2-8z"/>', 22, 2.2),
  check: svg('<path d="M5 12l5 5L20 7"/>', 18, 3),
  x:     svg('<path d="M6 6l12 12M18 6 6 18"/>', 16, 3),
  info:  svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>', 18),
  ext:   '<svg class="ext" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>'
};
// Link che aprono una nuova scheda: icona + avviso per lo screen reader (WCAG 3.2.5)
const NUOVA = ico.ext + `<span class="sr-only">${t("newTab")}</span>`;

/* ---------- Mappa ---------- */
// Allinea il colore del cerchio alla palette scelta (accessibilità)
window.aggiornaColoriMappa = () => {
  if (!circle) return;
  const acc = getComputedStyle(document.documentElement).getPropertyValue("--primary").trim() || "#0A58B0";
  circle.setStyle({color:acc, fillColor:acc});
};
function initMap(){
  const {lat, lng} = state.centro;
  map = L.map("map", {zoomControl:false}).setView([lat, lng], 12);
  // Controlli zoom con etichette in italiano
  L.control.zoom({zoomInTitle:t("zoomIn"), zoomOutTitle:t("zoomOut")}).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom:19,
    attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'
  }).addTo(map);
  layer = L.layerGroup().addTo(map);
  circle = L.circle([lat, lng], {radius:state.raggio*1000, weight:2, fillOpacity:.06, interactive:false}).addTo(map);
  // Punto cercato: pallino scuro con etichetta, come nel mockup
  centroMarker = L.marker([lat, lng], {
    icon:L.divIcon({className:"ctr-wrap", iconSize:[26, 26], iconAnchor:[13, 13],
      html:`<div class="ctr"><span class="ctr__dot"></span><span class="ctr__lab">${t("searchedPoint")}</span></div>`}),
    interactive:false, keyboard:false, zIndexOffset:-100
  }).addTo(map);
  map.on("dragend", () => $("#btnArea").hidden = false);
  window.aggiornaColoriMappa();
  avvio();
}

/* ---------- Query Overpass: una sola richiesta per Anagrafi + CAF ---------- */
const RE_NOME_CAF = "CAF|CAAF|CGIL|CISL|UIL|ACLI|CNA|Confartigianato|Coldiretti|Confagricoltura|Patronato|Assistenza [Ff]iscale|Caf ";
const RE_NOME_ANAG = "anagrafe|demografic|stato civile|municipio|comune di|palazzo comunale";
/* Query LEGGERA: ogni riga parte da un filtro indicizzato (amenity=townhall, office=...), mai da una
   ricerca di testo su tutti gli elementi della zona (era quella a far andare in timeout i server). */
function queryTutto(lat, lng, km){
  const a = `(around:${Math.round(km*1000)},${lat},${lng})`;
  return `[out:json][timeout:12];(
    nwr["amenity"="townhall"]${a};
    nwr["office"="government"]["government"~"register_office|civil_registry"]${a};
    nwr["office"="government"]["name"~"${RE_NOME_ANAG}",i]${a};
    nwr["office"="tax_advisor"]["name"~"${RE_NOME_CAF}"]${a};
    nwr["office"]["name"~"${RE_NOME_CAF}"]${a};
  );out center tags;`;
}

/* Richiesta "a staffetta": parte il primo server; se non risponde entro ATTESA_MIRROR
   (o fallisce subito) parte il successivo, senza annullare il precedente. Vince il più veloce.
   Scadenza unica per tutta la ricerca (ms). Il server che risponde passa in testa alla lista per le
   richieste successive, quelli lenti o rotti finiscono in fondo: niente più attese inutili. */
let ordineServer = [...OVERPASS];
function overpass(query, ms){
  return new Promise((resolve, reject) => {
    const server = [...ordineServer], ctrls = [], errori = [], falliti = new Set();
    const host = u => new URL(u).hostname;
    const motivo = e => e instanceof TypeError ? "connessione bloccata o server irraggiungibile" : e.message;
    let finito = false, avviati = 0, inCorso = 0, timerStaffetta;
    const sposta = (vincitore, lenti) => {
      ordineServer = [...(vincitore ? [vincitore] : []), ...ordineServer.filter(u => u !== vincitore && !lenti.includes(u)), ...lenti];
    };
    const scadenza = setTimeout(() => {
      if (finito) return;
      finito = true; clearTimeout(timerStaffetta); ctrls.forEach(c => c.abort());
      server.slice(0, avviati).filter(u => !falliti.has(u)).forEach(u => errori.push(`${host(u)}: nessuna risposta entro ${Math.round(ms/1000)} s`));
      sposta(null, server.slice(0, avviati));
      reject(Object.assign(new Error("Overpass non raggiungibile"), {dettagli:errori}));
    }, ms);
    const avvia = () => {
      clearTimeout(timerStaffetta);
      if (finito || avviati >= server.length) return;
      const url = server[avviati++], ctrl = new AbortController();
      ctrls.push(ctrl); inCorso++;
      fetch(url, {method:"POST", signal:ctrl.signal, headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:"data=" + encodeURIComponent(query)})
        .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(j => {
          if (finito) return;
          // Overpass a volte risponde 200 con un "remark" di errore e zero risultati: non è una vera risposta
          if (j.remark && /runtime error|timed out|out of memory/i.test(j.remark) && !(j.elements || []).length) throw new Error("Overpass: " + j.remark);
          finito = true; clearTimeout(timerStaffetta); clearTimeout(scadenza);
          ctrls.forEach(c => c.abort());
          sposta(url, server.slice(0, avviati).filter(u => u !== url));
          resolve(j.elements || []);
        })
        .catch(e => {
          if (finito) return;
          console.warn("Overpass non disponibile:", url, e);
          falliti.add(url); errori.push(`${host(url)}: ${motivo(e)}`); inCorso--;
          if (avviati < server.length) { if (!inCorso) avvia(); }
          else if (!inCorso) {
            finito = true; clearTimeout(scadenza);
            sposta(null, server.slice(0, avviati));
            reject(Object.assign(new Error("Overpass non raggiungibile"), {dettagli:errori}));
          }
        });
      if (avviati < server.length) timerStaffetta = setTimeout(avvia, ATTESA_MIRROR);
    };
    avvia();
  });
}

/* ---------- Cache locale (localStorage, scade dopo 6 ore) ---------- */
try { Object.keys(localStorage).filter(k => /^sedi[1-5]:/.test(k)).forEach(k => localStorage.removeItem(k)); } catch {}
const chiaveCache = (lat, lng, km) => `${PREFISSO_CACHE}${lat}:${lng}:${km}`;
// Risultati già scaricati in questa sessione (anche quelli della ricerca alternativa e del precaricamento)
const memoria = new Map();
const chiaveMem = (lat, lng, km) => `${lat}:${lng}:${km}`;
// Cerca il raggio richiesto o uno più grande (che lo contiene comunque): prima in memoria, poi nella cache locale
function leggiCache(lat, lng, km){
  for (const r of RAGGI.filter(r => r >= km)) {
    const m = memoria.get(chiaveMem(lat, lng, r));
    if (m) return {dati:m.dati, km:r, alt:m.alt};
    try {
      const chiave = chiaveCache(lat, lng, r), raw = localStorage.getItem(chiave);
      if (!raw) continue;
      const {t, dati} = JSON.parse(raw);
      if (Date.now() - t > CACHE_TTL) { localStorage.removeItem(chiave); continue; }
      return {dati, km:r, alt:false};
    } catch { /* cache non disponibile o corrotta: si scarica */ }
  }
  return null;
}
function scriviCache(lat, lng, km, dati){
  const chiave = chiaveCache(lat, lng, km), valore = JSON.stringify({t:Date.now(), dati});
  try { localStorage.setItem(chiave, valore); }
  catch {
    try {   // spazio pieno: butta le voci vecchie e riprova una volta
      Object.keys(localStorage).filter(k => k.startsWith(PREFISSO_CACHE)).forEach(k => localStorage.removeItem(k));
      localStorage.setItem(chiave, valore);
    } catch { /* pazienza: funziona anche senza cache */ }
  }
}

/* ---------- Classificazione dei dati OSM ---------- */
const RE_CAF = /(^|[^A-Za-zÀ-ÿ])(CAF|CAAF)([^A-Za-zÀ-ÿ]|$)|assistenza fiscale/i;
const RE_SIND = /\b(CGIL|CISL|UIL|ACLI|CNA|Confartigianato|Coldiretti|Confagricoltura|Patronato)\b/i;
const RE_ANAG = /anagrafe|demografic|stato civile|municipio|comune di|palazzo comunale/i;

function classifica(tg){
  const nome = tg.name || "";
  // chip = chiave di traduzione: il testo si sceglie quando si disegna la card (anche per i dati in cache)
  if (RE_CAF.test(nome)) return {cat:"caf", chip:"chipCaf"};
  if (RE_SIND.test(nome)) return {cat:"caf", chip:"chipUnion"};
  if (tg.amenity === "townhall") return {cat:"carta_identita", chip:"chipComune"};
  if (tg.office === "government" && (/register_office|civil_registry/.test(tg.government || "") || RE_ANAG.test(nome)))
    return {cat:"carta_identita", chip:"chipComune"};
  return null;
}

const indirizzo = tg => {
  const via = [tg["addr:street"], tg["addr:housenumber"]].filter(Boolean).join(" ");
  const citta = [tg["addr:postcode"], tg["addr:city"]].filter(Boolean).join(" ");
  return [via, citta].filter(Boolean).join(", ");
};


/* ---------- Scaricamento dati ---------- */
const TAG_UTILI = ["name","addr:street","addr:housenumber","addr:postcode","addr:city","phone","contact:phone","website","contact:website","opening_hours"];
const tagUtili = tg => Object.fromEntries(TAG_UTILI.filter(k => tg[k]).map(k => [k, tg[k]]));
const arrotonda = c => ({lat:+c.lat.toFixed(3), lng:+c.lng.toFixed(3)});   // ~100 m: rende utile la cache

// I dati di una categoria valgono per il cerchio attuale se questo sta dentro l'area già scaricata
const coperto = d => !!d && haversine(state.centro.lat, state.centro.lng, d.area.lat, d.area.lng) + state.raggio <= d.area.km + 1e-6;
const stessoCentro = d => !!d && haversine(state.centro.lat, state.centro.lng, d.area.lat, d.area.lng) < 0.15;

/* ---------- Ricerche alternative (se Overpass fallisce o non restituisce nulla) ---------- */
const PHOTON = "https://photon.komoot.io/api/";
const pausa = ms => new Promise(r => setTimeout(r, ms));
async function fetchJson(url, ms = 15000){
  const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
  try { const r = await fetch(url, {signal:c.signal}); if (!r.ok) throw new Error("HTTP " + r.status); return await r.json(); }
  finally { clearTimeout(t); }
}
const cassa = (lat, lng, km) => {
  const r = km, dLat = r/111.32, dLng = r/(111.32*Math.cos(lat*Math.PI/180));
  return {w:lng-dLng, s:lat-dLat, e:lng+dLng, n:lat+dLat};
};

// Photon (komoot): ricerca per tag OSM dentro un riquadro, in parallelo
async function photonSedi(lat, lng, km){
  const b = cassa(lat, lng, km);
  const RICHIESTE = [["comune","amenity:townhall"], ["municipio","amenity:townhall"], ["palazzo comunale","amenity:townhall"],
    ["anagrafe","office:government"], ["CAF","office"], ["CAAF","office"], ["patronato","office"], ["assistenza fiscale","office"]];
  const tipo = {N:"node", W:"way", R:"relation"};
  const esiti = await Promise.allSettled(RICHIESTE.map(([q, tag]) =>
    fetchJson(`${PHOTON}?q=${encodeURIComponent(q)}&osm_tag=${encodeURIComponent(tag)}&bbox=${b.w},${b.s},${b.e},${b.n}&limit=50&lang=it`)));
  if (!esiti.some(e => e.status === "fulfilled")) throw new Error("Photon non raggiungibile");
  const out = [];
  esiti.forEach(e => (e.status === "fulfilled" ? e.value.features || [] : []).forEach(f => {
    const p = f.properties || {}, g = f.geometry?.coordinates;
    if (!g || !p.name) return;
    const t = {name:p.name};
    if (p.osm_key && p.osm_value) t[p.osm_key] = p.osm_value;
    if (p.street) t["addr:street"] = p.street;
    if (p.housenumber) t["addr:housenumber"] = p.housenumber;
    if (p.postcode) t["addr:postcode"] = p.postcode;
    if (p.city) t["addr:city"] = p.city;
    out.push({type:tipo[p.osm_type] || "node", id:p.osm_id, lat:g[1], lon:g[0], tags:t});
  }));
  return out;
}

// Nominatim: una richiesta al secondo, con dettagli (orari, telefono) quando ci sono
async function nominatimSedi(lat, lng, km){
  const b = cassa(lat, lng, km), box = `${b.w},${b.n},${b.e},${b.s}`;
  const termini = ["comune", "municipio", "town hall", "anagrafe", "CAF", "CAAF", "patronato"];
  const out = []; let riusciti = 0;
  for (const [i, termine] of termini.entries()) {
    if (i) await pausa(1100);
    try {
      const dati = await fetchJson(`${NOMINATIM}?format=jsonv2&limit=40&bounded=1&viewbox=${box}&addressdetails=1&extratags=1&countrycodes=it&accept-language=it&q=${encodeURIComponent(termine)}`);
      dati.forEach(x => {
        const ex = x.extratags || {}, ad = x.address || {};
        const t = {...ex, name:x.name || (x.display_name || "").split(",")[0]};
        if (["amenity","office","shop"].includes(x.category)) t[x.category] = x.type;
        if (ad.road) t["addr:street"] = ad.road;
        if (ad.house_number) t["addr:housenumber"] = ad.house_number;
        if (ad.postcode) t["addr:postcode"] = ad.postcode;
        t["addr:city"] = ad.city || ad.town || ad.village || ad.municipality || "";
        out.push({type:x.osm_type, id:x.osm_id, lat:+x.lat, lon:+x.lon, tags:t});
      });
      riusciti++;
    } catch (e) { console.warn("Nominatim non disponibile:", e); }
  }
  if (!riusciti) throw new Error("Nominatim non raggiungibile");
  return out;
}

async function alternativa(lat, lng, km){
  const [ph, no] = await Promise.allSettled([photonSedi(lat, lng, km), nominatimSedi(lat, lng, km)]);
  console.info("[sedi] Photon:", ph.status, ph.value?.length ?? ph.reason?.message, "| Nominatim:", no.status, no.value?.length ?? no.reason?.message);
  if (ph.status === "rejected" && no.status === "rejected") throw new Error("nessuna ricerca alternativa raggiungibile");
  // Photon ha meno dettagli (niente orari): se lo stesso elemento c'è in Nominatim si tiene quello ricco
  const mappa = new Map();
  [...(ph.value || []), ...(no.value || [])].forEach(e => mappa.set(e.type + e.id, {...(mappa.get(e.type + e.id) || {}), ...e, tags:{...(mappa.get(e.type + e.id)?.tags || {}), ...e.tags}}));
  return [...mappa.values()];
}

/* ---------- Dati precaricati (Roma, Verona…): niente rete, risposta immediata ----------
   Il file dati/sedi-precaricate.js lo genera scripts/aggiorna-dati.mjs. Si usa solo se il cerchio
   cercato sta dentro una delle zone scaricate e se i dati non sono troppo vecchi; altrimenti si va online. */
const MAX_ETA_GIORNI = 30;
function daPrecaricati(lat, lng, km){
  const P = window.SEDI_PRECARICATE;
  if (!P || !P.generato || !(P.elementi || []).length) return null;
  if (Date.now() - Date.parse(P.generato) > MAX_ETA_GIORNI * 864e5) return null;
  const r = km;                                       // stesso raggio della query Overpass (km*1000 m)
  if (!(P.zone || []).some(z => haversine(lat, lng, z.lat, z.lng) + r <= z.raggioKm)) return null;
  return P.elementi.filter(e => haversine(lat, lng, e.lat, e.lon) <= r);
}

const inVolo = new Map();   // stessa area richiesta due volte (primo piano + precaricamento): una sola richiesta
function scarica(lat, lng, km, silenzioso = false){
  const k = chiaveMem(lat, lng, km);
  if (!inVolo.has(k)) inVolo.set(k, scaricaDavvero(lat, lng, km, silenzioso).finally(() => inVolo.delete(k)));
  return inVolo.get(k);
}
async function scaricaDavvero(lat, lng, km, silenzioso){
  const t0 = performance.now();
  let elementi = [], usataAlt = false, dettagli = [];
  const locali = daPrecaricati(lat, lng, km);
  if (locali) elementi = locali;
  else {
    try { elementi = await overpass(queryTutto(lat, lng, km), budget(km)); }
    catch (e) { dettagli = e.dettagli || [e.message]; elementi = null; }
  }
  if (!locali && (!elementi || !elementi.length)) {          // Overpass fallito, oppure risposta vuota (sospetta): si prova altrove
    if (!silenzioso) setStatus("Il server principale non ha dato risultati, provo una ricerca alternativa…");
    try { const alt = await alternativa(lat, lng, km); elementi = alt; usataAlt = true; }
    catch (e2) {
      if (elementi) elementi = [];   // Overpass ha risposto davvero "zero"
      else throw Object.assign(new Error("Ricerca non riuscita"), {dettagli:[...dettagli, "Photon e Nominatim: non raggiungibili"]});
    }
  }
  console.info(`[sedi] ${km} km: ${elementi.length} elementi in ${Math.round(performance.now() - t0)} ms${locali ? " (dati precaricati)" : usataAlt ? " (ricerca alternativa)" : " (Overpass)"}`);
  const per = {carta_identita:new Map(), caf:new Map()};
  elementi.forEach(e => {
    const la = e.lat ?? e.center?.lat, lo = e.lon ?? e.center?.lon, t = e.tags || {};
    if (la == null || lo == null || !t.name) return;
    const c = classifica(t); if (!c) return;
    per[c.cat].set(e.type + e.id, {osm:`${e.type}/${e.id}`, nome:t.name, lat:la, lng:lo, tags:tagUtili(t), cat:c.cat, chip:c.chip});
  });
  const dati = {carta_identita:[...per.carta_identita.values()], caf:[...per.caf.values()]};
  memoria.set(chiaveMem(lat, lng, km), {dati, alt:usataAlt});
  if (!usataAlt && !locali) scriviCache(lat, lng, km, dati);
  return {dati, alt:usataAlt};
}

/* =====================================================================
   ORARI: da opening_hours di OSM a una settimana leggibile
   Supporta i formati semplici ("Mo-Fr 09:00-12:00,14:00-16:00; Sa off").
   Come nello standard OSM, una regola successiva sostituisce quella
   precedente per gli stessi giorni. Regole "PH" (festivi) ignorate.
   ===================================================================== */
const GG = ["Su","Mo","Tu","We","Th","Fr","Sa"];
const GIORNI = t("days").split(",");
const Maiusc = s => s[0].toUpperCase() + s.slice(1);
const FASCE = "\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}";
const REGOLA = new RegExp(`^([A-Za-z,\\-\\s]+?)\\s+(off|closed|${FASCE}(?:\\s*,\\s*${FASCE})*)$`, "i");
const hhmm = m => `${String(Math.floor(m/60)).padStart(2, "0")}:${String(m%60).padStart(2, "0")}`;

// Restituisce: "sempre" | array di 7 giorni (0 = domenica) con fasce [[inizio, fine], …] in minuti | null se illeggibile
function settimana(str){
  if (!str) return null;
  if (str.trim() === "24/7") return "sempre";
  const giorni = Array.from({length:7}, () => []);
  for (const raw of str.split(";")) {
    const regola = raw.trim(); if (!regola) continue;
    if (/^PH\b/.test(regola)) continue;                       // festivi: non gestiti
    const m = regola.match(REGOLA); if (!m) return null;
    const insieme = new Set();
    for (const parte of m[1].split(",")) {
      const p = parte.trim().split("-").map(s => GG.indexOf(s.trim()));
      if (p.some(i => i < 0)) return null;
      if (p.length === 1) insieme.add(p[0]);
      else for (let d = p[0];; d = (d+1) % 7) { insieme.add(d); if (d === p[1]) break; }
    }
    const fasce = /^(off|closed)$/i.test(m[2]) ? [] : m[2].split(",").map(s =>
      s.split("-").map(x => { const [h, mi] = x.trim().split(":").map(Number); return h*60 + mi; }));
    insieme.forEach(d => { giorni[d] = fasce; });              // la regola successiva sostituisce
  }
  // Solo giorni "off" (es. "Sa,Su off"): non sappiamo quando apre → trattato come orari non disponibili
  return giorni.some(f => f.length) ? giorni : null;
}

// true / false / undefined (orari assenti o non leggibili)
function isOpenOSM(str, now = new Date()){
  const s = settimana(str);
  if (s === "sempre") return true;
  if (!s) return undefined;
  const min = now.getHours()*60 + now.getMinutes();
  return s[now.getDay()].some(([a, b]) => min >= a && min < b);
}

// Frase di riepilogo: "Chiude oggi alle 16:00", "Apre domani alle 09:00"…
function riepilogoOrari(s, now = new Date()){
  if (s === "sempre") return t("always");
  const oggi = now.getDay(), min = now.getHours()*60 + now.getMinutes();
  const ora = s[oggi].find(([a, b]) => min >= a && min < b);
  if (ora) {
    const poi = s[oggi].find(([a]) => a >= ora[1]);
    return t("closesAt", {t:hhmm(ora[1])}) + (poi ? t("reopensAt", {t:hhmm(poi[0])}) : "");
  }
  for (let k = 0; k < 7; k++) {
    const d = (oggi + k) % 7;
    const f = s[d].find(([a]) => k > 0 || a > min);
    if (f) return k === 0 ? t("opensToday", {t:hhmm(f[0])}) : k === 1 ? t("opensTomorrow", {t:hhmm(f[0])}) : t("opensDay", {d:GIORNI[d], t:hhmm(f[0])});
  }
  return t("closedWeek");
}

// Tabella: solo i giorni con orari (più oggi, anche se chiuso), da lunedì a domenica
function tabellaOrari(s, now = new Date()){
  if (s === "sempre") return "";
  const oggi = now.getDay();
  const righe = [1, 2, 3, 4, 5, 6, 0].filter(d => s[d].length || d === oggi).map(d => {
    const fasce = s[d].length ? s[d].map(([a, b]) => `<span class="nw">${hhmm(a)} – ${hhmm(b)}</span>`).join(" · ") : t("closed");
    return `<tr${d === oggi ? ' class="oggi"' : ""}><th scope="row">${Maiusc(GIORNI[d])}${d === oggi ? t("today") : ""}</th><td>${fasce}</td></tr>`;
  });
  return `<table class="hours"><caption class="sr-only">${t("hoursCaption")}</caption><tbody>${righe.join("")}</tbody></table>`;
}

/* =====================================================================
   COSA PORTARE
   ===================================================================== */
// 1. I DATI: una lista per ogni servizio.
//    La chiave è uguale al value del radio del servizio (value="carta_identita" / "caf").
const COSA_PORTARE = {
  "carta_identita": {
    elementi: [
      t("bringId1"), t("bringId2"), t("bringId3"), t("bringId4")
    ],
    // Link facoltativo per la prenotazione (null se non serve)
    prenota: "https://www.prenotazionicie.interno.gov.it"
  },
  "caf": {
    elementi: [ /* da completare: dipende dalla pratica (730, ISEE…) */ ],
    prenota: null
  }
};

// 2. LA FUNZIONE: restituisce l'HTML del blocco da mettere dentro la card.
//    idCard serve a creare un id unico, così aria-labelledby collega il titolo alla sezione.
function bloccoCosaPortare(servizio, idCard, x) {
  const dati = COSA_PORTARE[servizio];
  if (!dati || dati.elementi.length === 0) return ""; // niente lista → niente blocco

  const voci = dati.elementi
    .map(testo => `<li>${testo}</li>`)   // un <li> per ogni documento
    .join("");

  const prenota = dati.nota ? `<p class="porta__nota">${dati.nota}</p>` : dati.prenota
    ? `<p class="porta__nota">${t("bookOften", {link:`<a href="${dati.prenota}" target="_blank" rel="noopener">${t("bookOnline")}<span class="sr-only">${t("newTab")}</span></a>`})}</p>`
    : "";

  // <section> + titolo: gli screen reader lo annunciano come zona con un nome.
  // Il nome include anche il titolo della card ("Cosa portare, Municipio II"): con più card
  // ogni zona ha un nome diverso e nell'elenco dei punti di riferimento si distinguono.
  return `
    <section class="porta" aria-labelledby="porta-${idCard} card-t-${idCard}">
      <h4 id="porta-${idCard}" class="porta__titolo">${t("bringTitle")}</h4>
      <ul class="porta__lista">${voci}</ul>
      ${prenota}
    </section>`;
}

/* =====================================================================
   CARICAMENTO
   ===================================================================== */
// "Aperto ora" dipende dall'orario attuale: si calcola qui e mai dalla cache
const applica = (dati, area) => CATEGORIE.forEach(c => {
  state.dati[c] = {area, items:dati[c].map(x => ({...x, aperto:isOpenOSM(x.tags.opening_hours)}))};
});

async function caricaZona(mio){
  const {lat, lng} = arrotonda(state.centro), km = state.raggio;
  try {
    const hit = leggiCache(lat, lng, km);
    if (hit) { state.alternativa = hit.alt; applica(hit.dati, {lat, lng, km:hit.km}); }
    else {
      const r = await scarica(lat, lng, km);
      if (mio !== token) return;
      state.alternativa = r.alt;
      applica(r.dati, {lat, lng, km});
    }
    if (mio !== token) return;
    CATEGORIE.forEach(c => { state.caricando[c] = false; });
    aggiorna();
    precarica(lat, lng);
  } catch (e) {
    if (mio !== token) return;
    console.error(e);
    CATEGORIE.forEach(c => {
      state.caricando[c] = false;
      state.errore[c] = t("errFetch");
      state.dettaglio[c] = (e.dettagli || [e.message]).join(" · ");
    });
    aggiorna();
  }
}

let inizioRicerca = 0;
function carica(){
  const mio = ++token;
  if (precaricoAttivo && precaricoAttivo !== `${arrotonda(state.centro).lat}:${arrotonda(state.centro).lng}`) { precaricoAttivo = ""; state.precarico = ""; }
  inizioRicerca = performance.now();
  const {lat, lng} = state.centro, km = state.raggio;
  $("#btnArea").hidden = true;
  circle.setLatLng([lat, lng]).setRadius(km*1000);
  centroMarker.setLatLng([lat, lng]);
  const serve = !(coperto(state.dati.carta_identita) && coperto(state.dati.caf));   // altrimenti tutto già in memoria
  CATEGORIE.forEach(c => {
    state.errore[c] = null; state.dettaglio[c] = "";
    state.caricando[c] = serve;
    if (serve && !stessoCentro(state.dati[c])) state.dati[c] = null;   // zona cambiata: dati vecchi da scartare
  });
  aggiorna();
  if (serve) caricaZona(mio);
}

/* ---------- Precaricamento in background: dopo 1 km si scaricano 3 e 5 km ----------
   Una richiesta alla volta, con pausa: non si sovraccaricano i server e la vista non cambia. */
const PRECARICA = [3, 5, 10];
const precaricoFallito = new Set();
let precaricoAttivo = "";
async function precarica(lat, lng){
  const id = `${lat}:${lng}`;
  if (precaricoAttivo === id || state.alternativa) return;
  precaricoAttivo = id;
  const stessaZona = () => precaricoAttivo === id;
  for (const km of PRECARICA) {
    if (!stessaZona()) return;
    const k = chiaveMem(lat, lng, km);
    if (leggiCache(lat, lng, km) || precaricoFallito.has(k)) continue;
    try {
      const r = await scarica(lat, lng, km, true);
      if (r.alt) { precaricoFallito.add(k); break; }   // solo ricerca alternativa disponibile: non insistere
    } catch (e) { console.warn("Precaricamento non riuscito:", km, e); precaricoFallito.add(k); break; }
    if (!stessaZona()) return;
    await pausa(300);
  }
  if (stessaZona()) precaricoAttivo = "";
}
// scaricaDavvero() chiama setStatus con messaggi tecnici: non li mostriamo,
// l'attesa è già segnalata dal riquadro avviso e dagli scheletri delle card
function setStatus(){}

/* =====================================================================
   AVVISO (riquadro giallo/azzurro sotto il campo località)
   ===================================================================== */
function mostraAvviso(){
  const box = $("#notice"), txt = $("#noticeTxt");
  const inCorso = state.caricando[state.cat] && !state.errore[state.cat];
  const sec = Math.round((performance.now() - inizioRicerca) / 1000);
  let tipo = "", html = "";
  if (inCorso && sec >= 6) {
    tipo = "info";
    html = `<span class="spin" aria-hidden="true"></span> ${sec < 15 ? t("stillSearching") : t("slowServers")}… (${sec} s)`;
  } else if (state.avviso) { tipo = "warn"; html = state.avviso; }
  else if (!inCorso && state.alternativa) { tipo = "info"; html = t("altUsed"); }
  box.hidden = !tipo;
  box.className = "notice" + (tipo === "info" ? " notice--info" : "");
  if (txt.innerHTML !== html) txt.innerHTML = html;
}
// Ogni secondo aggiorna solo il riquadro visivo; allo screen reader va al massimo un messaggio
setInterval(() => {
  if (!state.caricando[state.cat] || state.errore[state.cat]) return;
  mostraAvviso();
  if (performance.now() - inizioRicerca > 10000) annuncia(t("takingLong"));
}, 1000);

/* =====================================================================
   DISEGNO: intestazione, elenco, mappa — sempre dai dati in memoria
   ===================================================================== */
function sedi(cat){
  const d = state.dati[cat]; if (!d) return [];
  const lim = Math.min(state.raggio, d.area.km);
  return d.items.map(x => ({...x, km:haversine(state.centro.lat, state.centro.lng, x.lat, x.lng)}))
    .filter(x => x.km <= lim && (!state.soloAperti || x.aperto === true)).sort((a, b) => a.km - b.km);
}

// "dal centro di Roma", "dalla tua posizione", "da Via Roma 10, Napoli"
const daDove = () => state.reale ? t("fromYou") : state.ripiego ? t("fromRome") : t("fromPlace", {p:nomeBreve(state.centro.nome)});

function titolo(n){
  const base = (state.cat === "caf" ? "caf" : "id") + (n === 0 ? "None" : n === 1 ? "One" : "Many");
  return t(base + (state.soloAperti ? "Open" : ""), {n});
}

function aggiorna(){ disegna(); mostraAvviso(); }

function disegna(){
  const cat = state.cat, d = state.dati[cat], grid = $("#grid");
  // Contatori nelle scelte del servizio (con testo nascosto per lo screen reader)
  CATEGORIE.forEach(c => { $(`#cnt-${c}`).innerHTML = state.dati[c] ? `${sedi(c).length}<span class="sr-only">${t("results")}</span>` : ""; });
  layer.clearLayers(); markers = [];
  grid.setAttribute("aria-busy", String(!d && !state.errore[cat]));

  // --- Errore ---
  if (!d && state.errore[cat]) {
    visibili = [];
    $("#titolo").textContent = t("searchFailed");
    $("#conteggio").textContent = "";
    grid.innerHTML = `<div class="nudge">
      <p class="nudge__t">${esc(state.errore[cat])}</p>
      <p>${t("checkConn")}</p>
      <div class="nudge__btns"><button class="btn btn--primary" type="button" id="btnRiprova">${t("retry")}</button></div>
      <details><summary>${t("techDetails")}</summary>${esc(state.dettaglio[cat])}</details></div>`;
    $("#btnRiprova").addEventListener("click", () => { ordineServer = [...OVERPASS]; carica(); });
    annuncia(t("searchFailed") + ". " + state.errore[cat]);
    return;
  }
  // --- Caricamento ---
  if (!d) {
    visibili = [];
    $("#titolo").textContent = t("searching");
    $("#conteggio").textContent = t("within", {km:state.raggio, from:daDove()});
    grid.innerHTML = '<div class="skel" aria-hidden="true"></div>'.repeat(2);
    annuncia(t("searchingAnn"));
    return;
  }

  // --- Risultati ---
  visibili = sedi(cat);
  const n = visibili.length, kmVis = Math.min(state.raggio, d.area.km), parziale = d.area.km < state.raggio;
  const ancora = parziale && state.caricando[cat];
  $("#titolo").textContent = titolo(n);
  $("#conteggio").textContent = t("within", {km:kmVis, from:daDove()}) + (n > 1 ? t("sortedDist") : "") +
    (ancora ? t("searchingFarther") : parziale ? t("widerFailed") : "");

  const punti = [[state.centro.lat, state.centro.lng]];
  visibili.forEach((x, i) => {
    const tipo = x.aperto === true ? "" : x.aperto === false ? " mk--closed" : " mk--nd";
    const icon = L.divIcon({className:"mk-wrap", iconSize:[44, 44], iconAnchor:[22, 53],
      html:`<div class="mk${tipo}"><span class="mk__pin"><b>${i+1}</b></span><span class="mk__lab">${esc(x.nome)}</span></div>`});
    // Il titolo del segnaposto contiene numero, nome e stato: non si dipende dal colore
    const m = L.marker([x.lat, x.lng], {icon, title:`${i+1}. ${x.nome} – ${statoTesto(x.aperto)}`, keyboard:true, riseOnHover:true}).addTo(layer)
      .bindPopup(`<div class="pop"><strong>${i+1}. ${esc(x.nome)}</strong><br>${esc(indirizzo(x.tags) || t("noAddressShort"))}</div>`)
      .on("click", () => seleziona(i, false));
    // Da tastiera: Invio o Spazio sul segnaposto portano alla scheda nell'elenco
    m.getElement()?.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); seleziona(i, false); } });
    markers.push(m); punti.push([x.lat, x.lng]);
  });
  if (n) map.fitBounds(L.latLngBounds(punti).pad(.2));
  else map.setView([state.centro.lat, state.centro.lng], state.raggio <= 1 ? 15 : state.raggio <= 3 ? 14 : state.raggio <= 5 ? 13 : 12);

  grid.innerHTML = visibili.map(card).join("") + (ancora
    ? `<div class="nudge"><p class="nudge__t"><span class="spin" aria-hidden="true"></span> ${t("alsoFarther")}</p></div>`
    : suggerimento(n, kmVis));
  $$(".card [data-map]").forEach(b => b.addEventListener("click", () => seleziona(+b.dataset.map, true)));
  $("#grid [data-act=allarga]")?.addEventListener("click", e => impostaRaggio(+e.currentTarget.dataset.km, true));
  $("#grid [data-act=tutti]")?.addEventListener("click", () => impostaFiltro(false, true));

  annuncia(`${titolo(n)}, ${t("within", {km:kmVis, from:daDove()})}.` + (state.alternativa ? t("annAlt") : ""));
}

// Riquadro tratteggiato sotto l'elenco: con pochi risultati propone azioni concrete
function suggerimento(n, km){
  const prossimo = RAGGI.find(r => r > state.raggio);
  const aperti = state.soloAperti;
  if (n > 2 || (!prossimo && !aperti)) return "";
  const tit = n === 0 ? (aperti ? t("noneOpenNear") : t("noneInArea", {km}))
    : n === 1 ? (aperti ? t("oneOpenNear") : t("oneNear"))
    : (aperti ? t("fewOpenNear") : t("fewNear"));
  const p = aperti ? t("nudgeOpen") : t("nudgeFar");
  const btn = [
    prossimo ? `<button type="button" class="btn" data-act="allarga" data-km="${prossimo}">${t("searchKm", {km:prossimo})}</button>` : "",
    aperti ? `<button type="button" class="btn" data-act="tutti">${t("showClosed")}</button>` : ""
  ].join("");
  return `<div class="nudge"><p class="nudge__t">${tit}</p><p>${p}</p><div class="nudge__btns">${btn}</div></div>`;
}

/* =====================================================================
   CARD DI UN UFFICIO
   ===================================================================== */
const statoTesto = a => a === undefined ? t("noHours") : a ? t("openNow") : t("closedNow");
function badge(a){
  if (a === undefined) return `<span class="badge badge--nd">${ico.info}${t("noHours")}</span>`;
  return a ? `<span class="badge badge--open">${ico.check}${t("openNow")}</span>` : `<span class="badge badge--closed">${ico.x}${t("closedNow")}</span>`;
}

function card(x, i){
  const tg = x.tags, s = settimana(tg.opening_hours);
  const tel = tg.phone || tg["contact:phone"];
  let web = tg.website || tg["contact:website"];
  if (web && !/^https?:\/\//i.test(web)) web = "https://" + web;
  const dir = `https://www.google.com/maps/dir/?api=1&destination=${x.lat},${x.lng}`;
  const ind = indirizzo(tg);
  // L'indirizzo apre Google Maps su quella via; se manca, sul punto esatto
  const luogo = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(ind || x.lat + "," + x.lng)}`;
  const segnala = `https://www.openstreetmap.org/note/new#map=19/${x.lat}/${x.lng}`;
  const num = x.aperto === true ? "" : x.aperto === false ? " num--closed" : " num--nd";
  const chip = t(x.chip);

  // Orari: riepilogo + tabella se leggibili, testo originale se il formato è complesso
  let orari = "";
  if (s) orari = `<span class="info__strong">${riepilogoOrari(s)}</span>${tabellaOrari(s)}`;
  else if (tg.opening_hours) orari = `<span class="info__strong">${t("hoursLabel")}</span><span class="hours__raw">${esc(tg.opening_hours)}</span>`;
  const blocOrari = orari ? `<div class="info">${ico.clock}<div class="info__main">${orari}
      <span class="hours__note">${t("hoursNote")}</span></div></div>` : "";

  return `<article class="card" id="card-${i}" tabindex="-1" aria-labelledby="card-t-${i}">
    <div class="card__head">
      <span class="num${num}" aria-hidden="true">${i+1}</span>
      <div class="card__title">
        <span class="card__chip">${esc(chip)}</span>
        <h3 id="card-t-${i}"><span class="sr-only">${i+1}. </span>${esc(x.nome)}</h3>
      </div>
      ${badge(x.aperto)}
    </div>
    <div class="card__body">
      <div class="info">${ico.pin}<div class="info__main" style="gap:0">
        ${ind ? `<a class="info__strong info__link" href="${luogo}" target="_blank" rel="noopener noreferrer" aria-describedby="card-t-${i}">${esc(ind)}${NUOVA}</a>` : `<span class="info__strong">${t("noAddress")}</span>`}
        <span class="info__sub">${t(state.reale ? "distFromYou" : "distFromPoint", {d:distanza(x.km)})}${aPiedi(x.km)}</span>
      </div></div>
      ${blocOrari}
    </div>
    ${bloccoCosaPortare(x.cat, i, x)}
    <div class="actions">
      <a class="btn btn--primary" href="${dir}" target="_blank" rel="noopener noreferrer" aria-describedby="card-t-${i}">${ico.nav}${t("directions")}${NUOVA}</a>
      ${tel ? `<a class="btn" href="tel:${esc(tel.replace(/[^\d+]/g, ""))}" aria-describedby="card-t-${i}">${ico.phone}${t("call", {tel:esc(tel)})}</a>` : ""}
    </div>
    <div class="links">
      ${web ? `<a href="${esc(web)}" target="_blank" rel="noopener noreferrer">${t(x.cat === "carta_identita" ? "websiteComune" : "website")}${NUOVA}</a>` : ""}
      <button type="button" class="linkbtn" data-map="${i}" aria-describedby="card-t-${i}">${t("seeMap")}</button>
      <a href="${segnala}" target="_blank" rel="noopener noreferrer">${t("reportError")}${NUOVA}</a>
    </div>
  </article>`;
}

/* Collega card e segnaposto. Il focus segue l'azione: dalla card al segnaposto
   (Invio lo riporta indietro), dal segnaposto alla card. */
function seleziona(i, daCard){
  const x = visibili[i]; if (!x) return;
  $$(".card.sel").forEach(c => c.classList.remove("sel"));
  $$(".mk.sel").forEach(p => p.classList.remove("sel"));
  const c = $(`#card-${i}`); c.classList.add("sel");
  markers.forEach((m, k) => m.setZIndexOffset(k === i ? 1000 : 0));
  markers[i].getElement()?.querySelector(".mk")?.classList.add("sel");
  markers[i].openPopup();
  if (daCard) {
    map.setView([x.lat, x.lng], Math.max(map.getZoom(), 16));
    $("#map").scrollIntoView({behavior:scorri(), block:"center"});
    markers[i].getElement()?.focus({preventScroll:true});
  } else {
    c.scrollIntoView({behavior:scorri(), block:"start"});
    c.focus({preventScroll:true});
  }
}

/* =====================================================================
   EVENTI
   ===================================================================== */
const vaiAiRisultati = () => { $("#risultati").scrollIntoView({behavior:scorri(), block:"start"}); $("#risultati").focus({preventScroll:true}); };

// Servizio: si aggiorna subito (i dati dell'altra categoria sono già in memoria)
$$('input[name="servizio"]').forEach(r => r.addEventListener("change", () => { state.cat = r.value; aggiorna(); }));

// Distanza
function impostaRaggio(km, dalSuggerimento = false){
  state.raggio = km;
  $$('input[name="raggio"]').forEach(r => { r.checked = +r.value === km; });
  carica();   // se l'area è già scaricata (o in cache) è istantaneo
  if (dalSuggerimento) $("#risultati").focus({preventScroll:true});   // il pulsante cliccato sparisce: il focus non va perso
}
$$('input[name="raggio"]').forEach(r => r.addEventListener("change", () => impostaRaggio(+r.value)));

// Filtro "Tutti / Solo aperti adesso"
function impostaFiltro(soloAperti, dalSuggerimento = false){
  state.soloAperti = soloAperti;
  $$(".segmented button").forEach(b => b.setAttribute("aria-pressed", String((b.dataset.filtro === "aperti") === soloAperti)));
  aggiorna();
  if (dalSuggerimento) $("#risultati").focus({preventScroll:true});
}
$$(".segmented button").forEach(b => b.addEventListener("click", () => impostaFiltro(b.dataset.filtro === "aperti")));

$("#btnArea").addEventListener("click", () => {
  const c = map.getCenter();
  sceltaManuale = true;
  state.centro = {lat:c.lat, lng:c.lng, nome:t("thisArea")}; state.reale = false; state.ripiego = false; state.avviso = "";
  carica();
});

/* ---------- Campo località ---------- */
const geoCache = new Map();
let ultimaCercata = "";
function erroreCampo(msg){
  const inp = $("#citta"), box = $("#cittaErr");
  box.textContent = msg || ""; box.hidden = !msg;
  if (msg) inp.setAttribute("aria-invalid", "true"); else inp.removeAttribute("aria-invalid");
}
// Pulsante "occupato": spinner + testo; resta focalizzabile (disabled farebbe perdere il focus)
function occupato(btn, si, testo){
  if (si) { btn.setAttribute("aria-busy", "true"); btn.dataset.html ??= btn.innerHTML; btn.innerHTML = `<span class="spin" aria-hidden="true"></span>${testo}`; }
  else if (btn.dataset.html) { btn.removeAttribute("aria-busy"); btn.innerHTML = btn.dataset.html; delete btn.dataset.html; }
}
async function cercaCitta(q){
  const chiave = q.toLowerCase();
  let dati = geoCache.get(chiave);   // stessa località già cercata: niente nuova richiesta
  if (!dati) {
    const r = await fetch(`${NOMINATIM}?format=jsonv2&limit=1&countrycodes=it&accept-language=${LANG},it&q=${encodeURIComponent(q)}`);
    dati = await r.json();
    if (dati.length) geoCache.set(chiave, dati);
  }
  return dati[0] || null;
}

// "Mostra gli uffici": se il campo è cambiato cerca la località, poi porta ai risultati
$("#ricerca").addEventListener("submit", async e => {
  e.preventDefault();
  const btn = $("#btnCerca");
  if (btn.getAttribute("aria-busy")) return;
  const q = $("#citta").value.trim();
  erroreCampo("");
  if (q && q !== ultimaCercata) {
    occupato(btn, true, t("lookingPlace"));
    try {
      const luogo = await cercaCitta(q);
      if (!luogo) { erroreCampo(t("notFound", {q})); $("#citta").focus(); return; }
      ultimaCercata = q; sceltaManuale = true;
      state.centro = {lat:+luogo.lat, lng:+luogo.lon, nome:luogo.display_name};
      state.reale = false; state.ripiego = false; state.avviso = "";
      map.setView([state.centro.lat, state.centro.lng], 13);
      carica();
    } catch {
      erroreCampo(t("cantSearch")); $("#citta").focus(); return;
    } finally { occupato(btn, false); }
  } else if (!q && !state.reale && !state.ripiego && !ultimaCercata) {
    erroreCampo(t("writeCity")); $("#citta").focus(); return;
  }
  vaiAiRisultati();
});
$("#citta").addEventListener("input", () => { if ($("#citta").getAttribute("aria-invalid")) erroreCampo(""); });

/* ---------- Posizione ---------- */
const AVVISO_ROMA = t("romeNotice");
$("#btnGeo").addEventListener("click", () => {
  const btn = $("#btnGeo");
  if (btn.getAttribute("aria-busy")) return;
  if (!("geolocation" in navigator)) { state.avviso = `<strong>${t("noGeo")}</strong> ${t("noGeoWrite")}`; mostraAvviso(); return; }
  sceltaManuale = true; erroreCampo("");
  occupato(btn, true, t("lookingYou"));
  navigator.geolocation.getCurrentPosition(
    p => {
      occupato(btn, false);
      $("#citta").value = ""; ultimaCercata = "";
      state.centro = {lat:p.coords.latitude, lng:p.coords.longitude, nome:t("yourPos")};
      state.reale = true; state.ripiego = false; state.avviso = "";
      map.setView([state.centro.lat, state.centro.lng], 13);
      carica();
      annuncia(t("posFound"));
    },
    err => {
      occupato(btn, false);
      state.avviso = err.code === 1
        ? `<strong>${t("noPermission")}</strong> ${t("writeAddr")}`
        : `<strong>${t("cantFind")}</strong> ${t("writeAddr")}`;
      mostraAvviso(); annuncia($("#noticeTxt").textContent);
      $("#citta").focus();
    },
    {enableHighAccuracy:false, timeout:8000, maximumAge:300000}   // non serve il GPS preciso: risposta più rapida
  );
});

/* ---------- Avvio: posizione dell'utente, altrimenti centro di Roma ---------- */
let sceltaManuale = false;
function avvio(){
  let partito = false;
  const daRoma = motivo => {
    if (sceltaManuale || partito) return;
    partito = true;
    state.ripiego = true; state.centro.nome = "Roma";
    state.avviso = `<strong>${motivo}</strong> ${AVVISO_ROMA}`;
    $("#citta").value = "Roma"; ultimaCercata = "Roma";
    carica();
    annuncia(`${motivo} ${AVVISO_ROMA}`);
  };
  if (!("geolocation" in navigator)) return daRoma(t("noGeo"));
  disegna();                                   // scheletro subito, mentre si rileva la posizione
  $("#titolo").textContent = t("lookingYou");
  // Se l'utente non risponde alla richiesta di permesso, dopo 8 s si parte comunque da Roma
  const timer = setTimeout(() => daRoma(t("cantFind")), 8000);
  navigator.geolocation.getCurrentPosition(
    p => {
      clearTimeout(timer); partito = true;
      if (sceltaManuale) return;               // l'utente ha già scelto una zona: non la scavalco
      state.centro = {lat:p.coords.latitude, lng:p.coords.longitude, nome:t("yourPos")}; state.reale = true;
      map.setView([state.centro.lat, state.centro.lng], 13);
      carica();
    },
    err => { clearTimeout(timer); daRoma(err.code === 1 ? t("noPermission") : t("cantFind")); },
    {enableHighAccuracy:false, timeout:7000, maximumAge:600000}
  );
}

/* =====================================================================
   NAVIGAZIONE tra le viste (#cerca, #come-funziona, #domande)
   Link veri: funzionano "indietro", i segnalibri e "apri in nuova scheda".
   ===================================================================== */
const VISTE = {"#cerca":"servizi", "#come-funziona":"come", "#domande":"faq"};
function vai(view, daUtente){
  Object.values(VISTE).forEach(v => { $(`#view-${v}`).hidden = v !== view; });
  $$(".mainnav a").forEach(a => a.dataset.view === view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  document.title = (view === "servizi" ? "" : $(`#view-${view} h1`).textContent + " – ") + t("title");
  if (view === "servizi") setTimeout(() => map.invalidateSize(), 0);
  if (!daUtente) return;
  window.scrollTo({top:0});
  // Cambio "pagina" senza ricaricare: il focus va all'inizio del nuovo contenuto, come farebbe il browser
  (view === "servizi" ? $("#ricerca") : $(`#view-${view} h1`)).focus({preventScroll:true});
}
// Nessun hash (pagina appena aperta, o "indietro" fino all'inizio) = vista di ricerca
addEventListener("hashchange", () => { const v = VISTE[location.hash || "#cerca"]; if (v) vai(v, true); });

initMap();
if (VISTE[location.hash]) vai(VISTE[location.hash], false);