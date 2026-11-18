// Logo + Icons für slxt share (nur Node-Bordmittel). Gleiche Familie wie QR-Stream: Verlauf #6d4aff → #3b82f6,
// weiße Formen, Sternschnuppen-Schweif aus kleiner werdenden Modulen. Motiv: Ablage mit Pfeil nach oben (Hochladen/Teilen).
import { deflateSync, crc32 } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';

const ZIEL = new URL('../public/icons/', import.meta.url);
mkdirSync(ZIEL, { recursive: true });
const A = [0x6d, 0x4a, 0xff], B = [0x3b, 0x82, 0xf6];
// Formen im 64er-Raster: Rechtecke (x, y, b, h, r, a) und ein Dreieck (Pfeilspitze)
const RECHTECKE = [
  { x: 14, y: 40, b: 36, h: 6, r: 3, a: 1 },      // Ablage unten
  { x: 14, y: 31, b: 6, h: 15, r: 3, a: 1 },      // links
  { x: 44, y: 31, b: 6, h: 15, r: 3, a: 1 },      // rechts
  { x: 29, y: 20, b: 6, h: 17, r: 2, a: 1 },      // Pfeilschaft
  { x: 43, y: 12.5, b: 4.6, h: 4.6, r: 1.3, a: 0.75 },   // Schweif
  { x: 49.5, y: 7, b: 3.4, h: 3.4, r: 1, a: 0.45 },
];
const DREIECK = [[21, 24], [43, 24], [32, 12]];

export const SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs><linearGradient id="sh-g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6d4aff"/><stop offset="1" stop-color="#3b82f6"/></linearGradient></defs>
  <rect width="64" height="64" rx="14" fill="url(#sh-g)"/>
${RECHTECKE.map((r) => `  <rect x="${r.x}" y="${r.y}" width="${r.b}" height="${r.h}" rx="${r.r}" fill="#fff"${r.a < 1 ? ` fill-opacity="${r.a}"` : ''}/>`).join('\n')}
  <path d="M${DREIECK.map((p) => p.join(' ')).join('L')}Z" fill="#fff" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>
</svg>
`;

function inRR(px, py, { x, y, b, h, r }) {
  if (px < x || px > x + b || py < y || py > y + h) return false;
  const cx = Math.min(Math.max(px, x + r), x + b - r), cy = Math.min(Math.max(py, y + r), y + h - r);
  return (px - cx) ** 2 + (py - cy) ** 2 <= r * r;
}
function inDreieck(px, py, [[ax, ay], [bx, by], [cx, cy]], rand = 1) {
  // Punkt im Dreieck (mit 1 px „Stroke“ für die runden Ecken wie im SVG)
  const s = (x1, y1, x2, y2, x3, y3) => (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3);
  const d1 = s(px, py, ax, ay, bx, by), d2 = s(px, py, bx, by, cx, cy), d3 = s(px, py, cx, cy, ax, ay);
  if (!((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0))) return true;
  const seg = (x1, y1, x2, y2) => { const dx = x2 - x1, dy = y2 - y1, t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy))); return Math.hypot(px - x1 - t * dx, py - y1 - t * dy); };
  return Math.min(seg(ax, ay, bx, by), seg(bx, by, cx, cy), seg(cx, cy, ax, ay)) <= rand;
}
function farbe(u, v, rund, gu = u, gv = v) {
  if (rund && !inRR(u, v, { x: 0, y: 0, b: 64, h: 64, r: 14 })) return [0, 0, 0, 0];
  const t = Math.min(1, Math.max(0, (gu + gv) / 128));
  let c = A.map((a, i) => a + (B[i] - a) * t);
  const weiss = (al) => { c = c.map((x) => x + (255 - x) * al); };
  for (const r of RECHTECKE) if (inRR(u, v, r)) weiss(r.a);
  if (inDreieck(u, v, DREIECK)) weiss(1);
  return [...c, 255];
}
function png(g, { rand = 0, rund = true } = {}) {
  const px = Buffer.alloc(g * g * 4), N = 4;
  for (let y = 0; y < g; y++) for (let x = 0; x < g; x++) {
    const s = [0, 0, 0, 0];
    for (let sy = 0; sy < N; sy++) for (let sx = 0; sx < N; sx++) {
      const u = ((x + (sx + 0.5) / N) / g) * 64, v = ((y + (sy + 0.5) / N) / g) * 64, k = 1 - 2 * rand;
      const f = farbe((u - 32) / k + 32, (v - 32) / k + 32, rund && !rand, u, v), al = f[3] / 255;
      s[0] += f[0] * al; s[1] += f[1] * al; s[2] += f[2] * al; s[3] += al;
    }
    const i = (y * g + x) * 4, a = s[3] / (N * N);
    px[i] = a ? s[0] / s[3] : 0; px[i + 1] = a ? s[1] / s[3] : 0; px[i + 2] = a ? s[2] / s[3] : 0; px[i + 3] = Math.round(a * 255);
  }
  const zeilen = Buffer.alloc((g * 4 + 1) * g);
  for (let y = 0; y < g; y++) px.copy(zeilen, y * (g * 4 + 1) + 1, y * g * 4, (y + 1) * g * 4);
  const chunk = (typ, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(typ), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc32(td)); return Buffer.concat([l, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(g, 0); ihdr.writeUInt32BE(g, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(zeilen, { level: 9 })), chunk('IEND', Buffer.alloc(0))]);
}
writeFileSync(new URL('apple-touch-icon.png', ZIEL), png(180, { rund: false }));
writeFileSync(new URL('icon-192.png', ZIEL), png(192));
writeFileSync(new URL('icon-512.png', ZIEL), png(512));
writeFileSync(new URL('icon-maskable-512.png', ZIEL), png(512, { rand: 0.1 }));
writeFileSync(new URL('icon.svg', ZIEL), SVG);
console.log('Icons erzeugt');
