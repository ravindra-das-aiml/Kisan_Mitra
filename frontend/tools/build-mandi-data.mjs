// Builds js/mandi-data.js with every distinct State -> District and Commodity
// found in the data.gov.in resource 35985678-0d79-46b4-9ed6-6f13308a1d24.
// Usage (Node 18+):  DATA_GOV_API_KEY=your_key node tools/build-mandi-data.mjs
import { writeFileSync } from 'node:fs';
const KEY = process.env.DATA_GOV_API_KEY;
if (!KEY) { console.error('Set DATA_GOV_API_KEY first.'); process.exit(1); }
const RES = '35985678-0d79-46b4-9ed6-6f13308a1d24';
const LIMIT = 1000;
const states = {}, commodities = new Set();
let offset = 0, total = Infinity;
while (offset < total) {
  const url = `https://api.data.gov.in/resource/${RES}?api-key=${KEY}&format=json&limit=${LIMIT}&offset=${offset}&fields=state,district,commodity`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} at offset ${offset}`);
  const j = await res.json();
  total = Number(j.total ?? 0);
  for (const r of j.records ?? []) {
    const s = (r.state ?? '').trim(), d = (r.district ?? '').trim(), c = (r.commodity ?? '').trim();
    if (s) (states[s] ??= new Set()).add(d);
    if (c) commodities.add(c);
  }
  offset += LIMIT;
  process.stdout.write(`\r${Math.min(offset, total)}/${total}`);
}
const sortAZ = a => [...a].filter(Boolean).sort((x, y) => x.localeCompare(y));
const out = {
  generated: new Date().toISOString(),
  states: Object.fromEntries(Object.keys(states).sort().map(s => [s, sortAZ(states[s])])),
  commodities: sortAZ(commodities)
};
writeFileSync(new URL('../js/mandi-data.js', import.meta.url), 'window.MANDI_DATA = ' + JSON.stringify(out, null, 1) + ';\n');
console.log(`\nWrote js/mandi-data.js: ${Object.keys(out.states).length} states, ${out.commodities.length} commodities`);
