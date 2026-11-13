// Scarica da OpenStreetMap (Overpass) anagrafi e CAF delle zone indicate qui sotto
// e li salva in dati/sedi-precaricate.js, che il sito legge al posto di interrogare i server pubblici.
//
// Uso (Node 18 o superiore):   node scripts/aggiorna-dati.mjs
// Per aggiornare i dati basta rilanciarlo (ad esempio una volta al giorno o alla settimana).

import { writeFile } from "node:fs/promises";

// Per aggiungere una zona: nome, centro e raggio in km. Il sito usa i dati solo se la ricerca cade dentro la zona.
const ZONE = [
  { nome: "Roma",   lat: 41.9028, lng: 12.4964, raggioKm: 25 },
  { nome: "Verona", lat: 45.4384, lng: 10.9916, raggioKm: 20 },
];

const SERVER = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.private.coffee/api/interpreter",
];

// Stessi filtri e stesse parole chiave di app.js (queryTutto)
const RE_NOME_CAF  = "CAF|CAAF|CGIL|CISL|UIL|ACLI|CNA|Confartigianato|Coldiretti|Confagricoltura|Patronato|Assistenza [Ff]iscale|Caf ";
const RE_NOME_ANAG = "anagrafe|demografic|stato civile|municipio|comune di|palazzo comunale";

// Solo i tag che servono al sito (e alla classificazione): il file resta leggero
const TAG = ["name","amenity","office","government","addr:street","addr:housenumber","addr:postcode","addr:city",
             "phone","contact:phone","website","contact:website","opening_hours"];

const query = z => {
  const a = `(around:${Math.round(z.raggioKm * 1000)},${z.lat},${z.lng})`;
  return `[out:json][timeout:180];(
    nwr["amenity"="townhall"]${a};
    nwr["office"="government"]["government"~"register_office|civil_registry"]${a};
    nwr["office"="government"]["name"~"${RE_NOME_ANAG}",i]${a};
    nwr["office"="tax_advisor"]["name"~"${RE_NOME_CAF}"]${a};
    nwr["office"]["name"~"${RE_NOME_CAF}"]${a};
  );out center tags;`;
};

async function scarica(z) {
  const errori = [];
  for (const url of SERVER) {
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "data=" + encodeURIComponent(query(z)),
        signal: AbortSignal.timeout(200000),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      if (j.remark && /runtime error|timed out|out of memory/i.test(j.remark) && !(j.elements || []).length)
        throw new Error(j.remark);
      return j.elements || [];
    } catch (e) { errori.push(`${new URL(url).hostname}: ${e.message}`); }
  }
  throw new Error(`${z.nome}: nessun server ha risposto (${errori.join(" | ")})`);
}

const elementi = new Map();   // senza doppioni se due zone si sovrappongono
for (const z of ZONE) {
  console.log(`Scarico ${z.nome} (${z.raggioKm} km)…`);
  const els = await scarica(z);
  console.log(`  ${els.length} elementi`);
  for (const e of els) {
    const lat = e.lat ?? e.center?.lat, lon = e.lon ?? e.center?.lon;
    if (lat == null || lon == null || !e.tags?.name) continue;
    const tags = Object.fromEntries(TAG.filter(k => e.tags[k]).map(k => [k, e.tags[k]]));
    elementi.set(e.type + e.id, { type: e.type, id: e.id, lat: +lat.toFixed(6), lon: +lon.toFixed(6), tags });
  }
}

const dati = {
  generato: new Date().toISOString(),
  zone: ZONE.map(({ nome, lat, lng, raggioKm }) => ({ nome, lat, lng, raggioKm })),
  elementi: [...elementi.values()],
};
await writeFile(new URL("../dati/sedi-precaricate.js", import.meta.url),
  "// Generato da scripts/aggiorna-dati.mjs — non modificare a mano\nwindow.SEDI_PRECARICATE = " + JSON.stringify(dati) + ";\n");
console.log(`Fatto: ${dati.elementi.length} sedi salvate in dati/sedi-precaricate.js`);
