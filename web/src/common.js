// Gemeinsam für alle Seiten:
//  • Erscheinungsbild folgt dem System (Apple HIG: kein App-eigener Zwang); der Schalter übersteuert nur für diesen
//    Besuch – bewusst ohne Speichern, die App legt nichts im Browser ab.
//  • Wechsel als Kreisblende vom Schalter aus (View Transitions, 0,6 s); bei „Bewegung reduzieren“ sofort.
//  • Himmel wie auf slxt.org: Sterne (dunkel) + seltene Sternschnuppen. Während gesendet/gescannt wird, ruht der Himmel
//    (spart Akku/CPU und lenkt nicht ab).
//  • Hilfen für Status-Zeilen und Löschen.
import './app.css';

const d = document.documentElement;
const SONNE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/></svg>';
const MOND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z"/></svg>';
const FARBE = { hell: '#efe3f8', dunkel: '#0b0e2a' };
const systemDunkel = matchMedia('(prefers-color-scheme: dark)');
const ruhig = matchMedia('(prefers-reduced-motion: reduce)');
let uebersteuert = null;      // null = System folgen

export const modus = () => uebersteuert ?? (systemDunkel.matches ? 'dunkel' : 'hell');

function anwenden() {
  const m = modus();
  if (uebersteuert) d.dataset.modus = m; else delete d.dataset.modus;   // ohne Attribut gilt die System-Mediaquery im CSS
  // zwei theme-color-Metas (hell/dunkel per media); übersteuert → beide auf die gewählte Farbe
  for (const meta of document.querySelectorAll('meta[name="theme-color"][data-fuer]')) {
    meta.content = uebersteuert ? FARBE[m] : FARBE[meta.dataset.fuer];
  }
  const k = document.querySelector('[data-modus-schalter]');
  if (k) {
    k.innerHTML = m === 'dunkel' ? SONNE : MOND;
    k.setAttribute('aria-label', m === 'dunkel' ? 'Helles Erscheinungsbild' : 'Dunkles Erscheinungsbild');
    k.title = k.getAttribute('aria-label');
  }
  himmelModus(m);
}

function wechseln(e) {
  const neu = modus() === 'dunkel' ? 'hell' : 'dunkel';
  const setzen = () => { uebersteuert = neu === (systemDunkel.matches ? 'dunkel' : 'hell') ? null : neu; anwenden(); };
  if (!document.startViewTransition || ruhig.matches) { setzen(); return; }
  // Kreisblende: Mittelpunkt = Schalter, Radius bis zur entferntesten Ecke
  const r = e.currentTarget.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  d.classList.add('modus-wechsel');
  const vt = document.startViewTransition(setzen);
  vt.ready.then(() => {
    d.animate({ clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      { duration: 600, easing: 'cubic-bezier(.2, .8, .2, 1)', pseudoElement: '::view-transition-new(root)' });
  }).catch(() => {});
  vt.finished.finally(() => d.classList.remove('modus-wechsel'));
}

document.querySelector('[data-modus-schalter]')?.addEventListener('click', wechseln);
systemDunkel.addEventListener('change', () => { if (!uebersteuert) anwenden(); });

// ---------------------------------------------------------------- Himmel
const himmel = document.querySelector('.sky');
const sternCanvas = himmel?.querySelector('canvas');
const meteorBox = himmel?.querySelector('.meteors');
let ruhe = false;      // true = gerade wird gesendet/gescannt

function sterne() {
  if (!sternCanvas) return;
  const dpr = Math.min(2, devicePixelRatio || 1), w = innerWidth, h = innerHeight;
  sternCanvas.width = w * dpr; sternCanvas.height = h * dpr;
  const c = sternCanvas.getContext('2d');
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, w, h);
  const n = Math.round((w * h) / 5200);
  for (let i = 0; i < n; i++) {
    const rad = Math.random() < 0.08 ? 1.3 : Math.random() * 0.8 + 0.3;
    c.globalAlpha = 0.25 + Math.random() * 0.65;
    c.fillStyle = Math.random() < 0.15 ? '#cdd8ff' : '#ffffff';
    c.beginPath(); c.arc(Math.random() * w, Math.random() * h * 0.92, rad, 0, Math.PI * 2); c.fill();
  }
}

function himmelModus(m) {
  if (m === 'dunkel' && sternCanvas && !sternCanvas.dataset.gemalt) { sterne(); sternCanvas.dataset.gemalt = '1'; }
}
let rt = 0;
addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { if (sternCanvas?.dataset.gemalt) sterne(); }, 200); });

/** Eine Sternschnuppe (wie slxt.org): nur transform/opacity, läuft auf der GPU. */
function sternschnuppe(x0, y0) {
  if (!meteorBox || ruhig.matches || ruhe || document.hidden) return;
  const W = innerWidth, H = innerHeight;
  const len = 80 + Math.random() * 150;
  const dir = x0 === undefined ? (Math.random() < 0.5 ? 1 : -1) : (x0 < W / 2 ? 1 : -1);
  const ang = ((14 + Math.random() * 26) * Math.PI) / 180;
  const dist = Math.max(W, H) * (0.22 + Math.random() * 0.25);
  if (x0 === undefined) { x0 = dir > 0 ? Math.random() * W * 0.65 : W * 0.35 + Math.random() * W * 0.65; y0 = Math.random() * H * 0.42; }
  const x1 = x0 + dir * Math.cos(ang) * dist, y1 = y0 + Math.sin(ang) * dist;
  const deg = (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI;
  const el = document.createElement('i');
  el.className = 'meteor';
  el.style.width = len + 'px';
  meteorBox.appendChild(el);
  const at = (x, y, s) => `translate(${x - len}px, ${y - 1}px) rotate(${deg}deg) scaleX(${s})`;
  const a = el.animate([
    { transform: at(x0, y0, 0.3), opacity: 0 }, { opacity: 1, offset: 0.12 }, { opacity: 0.9, offset: 0.65 },
    { transform: at(x1, y1, 1), opacity: 0 },
  ], { duration: 650 + Math.random() * 700, easing: 'cubic-bezier(.3, .55, .55, 1)' });
  a.onfinish = a.oncancel = () => el.remove();
}
(function planen(erst) {
  setTimeout(() => {
    sternschnuppe();
    if (Math.random() < 0.18) setTimeout(sternschnuppe, 200 + Math.random() * 700);
    planen(false);
  }, erst ? 1500 + Math.random() * 2500 : 3500 + Math.random() * 9000);
})(true);
// In den freien Himmel tippen = eigene Sternschnuppe (wie slxt.org)
addEventListener('click', (e) => {
  if (e.target.closest('.card, a, button, input, label, footer, .bar, .kacheln')) return;
  sternschnuppe(e.clientX, e.clientY);
});

/** Ruhemodus während Senden/Scannen: Himmel steht still, Schnuppen pausieren. */
export function konzentration(an) {
  ruhe = an;
  d.classList.toggle('ruhe', an);
  if (an) meteorBox?.replaceChildren();
}

anwenden();

// ---------------------------------------------------------------- Dienste

/** Bildschirm während der Übertragung nicht abdunkeln (Screen Wake Lock, iOS ≥ 16.4). Gibt das Lock oder null zurück. */
export async function wachBleiben() {
  try { return (await navigator.wakeLock?.request('screen')) || null; } catch { return null; }
}

/** Puffer überschreiben (soweit JavaScript das erlaubt – Kopien der Engine kann niemand garantiert löschen). */
export function ueberschreiben(...puffer) {
  for (const p of puffer) {
    if (!p) continue;
    if (p instanceof ArrayBuffer) new Uint8Array(p).fill(0);
    else if (ArrayBuffer.isView(p)) new Uint8Array(p.buffer, p.byteOffset, p.byteLength).fill(0);
  }
}

/** Browserspeicher dieser Seite leeren (die App legt dort nichts ab – nur zur Sicherheit). */
export function browserspeicherLeeren() {
  try { sessionStorage.clear(); } catch { /* nicht verfügbar */ }
  try { localStorage.clear(); } catch { /* nicht verfügbar */ }
}

export function groesseText(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1).replace('.', ',')} KB`;
  return `${(n / 1024 / 1024).toFixed(2).replace('.', ',')} MB`;
}

export function dauerText(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${s % 60 ? (s % 60) + ' s' : ''}`.trim();
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function status(el, text, art = '') {
  el.className = 'status' + (art ? ' ' + art : '');
  el.textContent = text;
}
