// Meine Dateien: hochladen (im Browser verschlüsselt), Liste mit Link / QR-Code / Teilen, Speicher, Konto.
import QRCode from 'qrcode';
import { status } from './common.js';
import { api, ApiFehler, hochladen, groesse } from './lib/api.js';
import {
  ableiten, neuesSalz, dateiVerschluesseln, auspacken, neuVerpacken, metaLesen, b64url,
  tresorHolen, tresorMerken, tresorVergessen,
} from './lib/krypto.js';

const $ = (id) => document.getElementById(id);
let ich = null, tresor = null;
const schluesselCache = new Map();     // id → roher Dateischlüssel (nur im Speicher dieser Seite)

const SYMBOL_DATEI = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>';

function meldung(id, text, art = 'err') { const s = $(id); s.hidden = false; status(s, text, art); }

// ---------------------------------------------------------------- Start
(async function start() {
  try { ich = await api('/api/ich'); } catch { location.replace('/'); return; }
  kopfzeile();
  const gemerkt = await tresorHolen();
  if (gemerkt?.k && gemerkt.benutzer === ich.benutzer) { tresor = gemerkt.k; await bereit(); } else $('karte-tresor').hidden = false;
})();

function kopfzeile() {
  const r = $('kopf-rechts');
  if (ich.admin) { const a = document.createElement('a'); a.className = 'btn'; a.href = '/admin'; a.textContent = 'Admin'; r.prepend(a); }
  const ab = document.createElement('button');
  ab.className = 'btn'; ab.type = 'button'; ab.textContent = 'Abmelden';
  ab.addEventListener('click', async () => { await api('/api/abmelden', { methode: 'POST' }).catch(() => {}); await tresorVergessen(); location.replace('/'); });
  r.prepend(ab);
  $('konto-text').textContent = `Angemeldet als ${ich.benutzer} · ${ich.email}`;
}

$('f-tresor').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pw = e.target.passwort.value;
  try {
    const k = await ableiten(pw, ich.salz);
    await api('/api/tresor-pruefen', { methode: 'POST', json: { auth: k.auth } });
    tresor = k.tresor;
    await tresorMerken(tresor, ich.benutzer).catch(() => {});
    e.target.passwort.value = '';
    $('karte-tresor').hidden = true;
    await bereit();
  } catch (err) { alert(err.message); }
});

async function bereit() {
  for (const k of ['karte-hochladen', 'karte-speicher', 'karte-liste', 'karte-konto']) $(k).hidden = false;
  await liste();
}

// ---------------------------------------------------------------- Liste
const ablaufText = (t) => {
  if (!t) return 'läuft nicht ab';
  const tage = Math.ceil((t * 1000 - Date.now()) / 864e5);
  return tage <= 1 ? 'läuft heute/morgen ab' : `noch ${tage} Tage`;
};

function linkFuer(id, roh) { return `${location.origin}/d/${id}#${b64url(roh)}`; }

async function liste() {
  const d = await api('/api/dateien');
  speicher(d.belegt, d.kontingent);
  const ul = $('liste');
  ul.replaceChildren();
  if (!d.dateien.length) {
    const li = document.createElement('li'); li.className = 'leer'; li.textContent = 'Noch nichts geteilt. Zieh oben eine Datei hinein.'; ul.append(li);
    return;
  }
  for (const f of d.dateien) {
    let name = 'Name nicht lesbar (mit altem Passwort verschlüsselt)', roh = null, typ = '';
    try {
      roh = schluesselCache.get(f.id) || await auspacken(f.schluessel, tresor);
      schluesselCache.set(f.id, roh);
      const m = await metaLesen(f.meta, roh);
      name = m.name; typ = m.typ;
    } catch { roh = null; }
    const li = document.createElement('li');
    const kopf = document.createElement('div'); kopf.className = 'kopf';
    const sym = document.createElement('span'); sym.className = 'symbol'; sym.innerHTML = SYMBOL_DATEI;
    const text = document.createElement('div'); text.className = 'text';
    const n = document.createElement('span'); n.className = 'name'; n.textContent = name; n.title = name;
    const info = document.createElement('span'); info.className = 'info';
    info.textContent = `${groesse(f.groesse)} · ${ablaufText(f.ablauf)} · ${f.downloads}× geladen${typ ? ' · ' + typ.split('/').pop() : ''}`;
    text.append(n, info); kopf.append(sym, text);
    const akt = document.createElement('div'); akt.className = 'aktionen';
    if (roh) {
      const link = linkFuer(f.id, roh);
      akt.append(knopf('Link kopieren', () => kopieren(link)), knopf('QR-Code', () => qrZeigen(link, name)));
      if (navigator.share) akt.append(knopf('Teilen …', () => navigator.share({ title: name, url: link }).catch(() => {})));
    }
    akt.append(knopf('Löschen', async () => {
      if (!confirm(`„${name}“ löschen? Der Link funktioniert danach nicht mehr.`)) return;
      await api('/api/dateien/' + f.id, { methode: 'DELETE' });
      schluesselCache.delete(f.id);
      liste();
    }, 'gefahr'));
    li.append(kopf, akt);
    ul.append(li);
  }
}

function knopf(text, fn, art = '') {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'btn' + (art ? ' ' + art : ''); b.textContent = text;
  b.addEventListener('click', fn);
  return b;
}

async function kopieren(text) {
  try { await navigator.clipboard.writeText(text); meldung('status-upload', 'Link kopiert – er enthält den Schlüssel, teile ihn nur mit dem Empfänger.', 'ok'); }
  catch { prompt('Link kopieren:', text); }
}

function speicher(belegt, kontingent) {
  const p = Math.min(100, (belegt / kontingent) * 100);
  $('speicher-text').textContent = `${groesse(belegt)} von ${groesse(kontingent)} belegt`;
  $('speicher-prozent').textContent = `${p.toFixed(p < 10 ? 1 : 0).replace('.', ',')} %`;
  $('speicher-balken').querySelector('i').style.width = p + '%';
  $('speicher-balken').classList.toggle('voll', p > 90);
}

// ---------------------------------------------------------------- QR-Dialog
function qrZeigen(link, name) {
  const qr = QRCode.create(link, { errorCorrectionLevel: 'M' });
  const n = qr.modules.size, rand = 4, seite = n + 2 * rand, c = $('qr-canvas');
  c.width = c.height = seite;
  const ctx = c.getContext('2d'), bild = ctx.createImageData(seite, seite);
  bild.data.fill(255);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (qr.modules.data[y * n + x]) {
    const i = ((y + rand) * seite + x + rand) * 4; bild.data[i] = bild.data[i + 1] = bild.data[i + 2] = 0;
  }
  ctx.putImageData(bild, 0, 0);
  $('qr-titel').textContent = name;
  $('qr-link').textContent = link;
  $('qr-dialog').showModal();
  $('qr-kopieren').onclick = () => kopieren(link);
}
$('qr-schliessen').addEventListener('click', () => $('qr-dialog').close());
$('qr-dialog').addEventListener('click', (e) => { if (e.target === $('qr-dialog')) $('qr-dialog').close(); });

// ---------------------------------------------------------------- Hochladen
const ablage = $('ablage');
$('datei').addEventListener('change', (e) => { dateienHochladen([...e.target.files]); e.target.value = ''; });
for (const ev of ['dragenter', 'dragover']) ablage.addEventListener(ev, (e) => { e.preventDefault(); ablage.classList.add('drueber'); });
for (const ev of ['dragleave', 'drop']) ablage.addEventListener(ev, () => ablage.classList.remove('drueber'));
ablage.addEventListener('drop', (e) => { e.preventDefault(); dateienHochladen([...e.dataTransfer.files]); });
for (const ev of ['dragover', 'drop']) window.addEventListener(ev, (e) => e.preventDefault());

async function dateienHochladen(dateien) {
  if (!tresor || !dateien.length) return;
  const ablauf = document.querySelector('input[name="ablauf"]:checked').value;
  const balken = $('upload-balken'), i = balken.querySelector('i');
  for (const [n, f] of dateien.entries()) {
    const vorsilbe = dateien.length > 1 ? `(${n + 1}/${dateien.length}) ` : '';
    if (f.size > ich.max_datei) { meldung('status-upload', `${vorsilbe}„${f.name}“ ist größer als 10 MB (${groesse(f.size)}) – bitte eine kleinere Datei wählen.`); continue; }
    try {
      meldung('status-upload', `${vorsilbe}Verschlüssele „${f.name}“ …`, '');
      const bytes = new Uint8Array(await f.arrayBuffer());
      const v = await dateiVerschluesseln(bytes, { name: f.name, typ: f.type }, tresor);
      bytes.fill(0);
      balken.hidden = false; i.style.width = '0';
      meldung('status-upload', `${vorsilbe}Lade „${f.name}“ hoch …`, '');
      const r = await hochladen(`/api/dateien?ablauf=${ablauf}`, v.geheimtext, { 'X-Meta': v.meta, 'X-Schluessel': v.verpackt }, (p) => { i.style.width = (p * 100).toFixed(1) + '%'; });
      schluesselCache.set(r.id, v.roh);
      meldung('status-upload', `${vorsilbe}„${f.name}“ ist bereit – Link oder QR-Code unten in der Liste.`, 'ok');
    } catch (e) {
      meldung('status-upload', `${vorsilbe}${e instanceof ApiFehler ? e.message : 'Fehler: ' + e.message}`);
    }
  }
  balken.hidden = true;
  await liste();
}

// ---------------------------------------------------------------- Mehr Speicher
$('f-speicher').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/api/speicher-anfragen', { methode: 'POST', json: { gb: Number(e.target.gb.value), nachricht: e.target.nachricht.value } });
    meldung('status-konto', 'Anfrage gesendet – wir melden uns per E-Mail.', 'ok');
    $('mehr-speicher').open = false;
  } catch (err) { meldung('status-konto', err.message); }
});

// ---------------------------------------------------------------- Passwort ändern / Konto löschen
$('f-passwort').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    meldung('status-konto', 'Verschlüssele deine Dateischlüssel neu …', '');
    const alt = await ableiten(f.alt.value, ich.salz);
    const salz = neuesSalz(), neu = await ableiten(f.neu.value, salz);
    const d = await api('/api/dateien');
    const schluessel = [];
    for (const x of d.dateien) {
      try { schluessel.push({ id: x.id, schluessel: await neuVerpacken(await auspacken(x.schluessel, alt.tresor), neu.tresor) }); }
      catch { schluessel.push({ id: x.id, schluessel: x.schluessel }); }     // schon unlesbar → so lassen
    }
    await api('/api/passwort/aendern', { methode: 'POST', json: { alt_auth: alt.auth, salz, auth: neu.auth, schluessel } });
    tresor = neu.tresor; ich.salz = salz;
    await tresorMerken(tresor, ich.benutzer).catch(() => {});
    f.reset();
    meldung('status-konto', 'Passwort geändert. Andere Geräte sind abgemeldet.', 'ok');
  } catch (err) { meldung('status-konto', err.message); }
});

$('f-loeschen').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!confirm('Konto und alle Dateien wirklich endgültig löschen?')) return;
  try {
    const k = await ableiten(e.target.passwort.value, ich.salz);
    await api('/api/konto/loeschen', { methode: 'POST', json: { auth: k.auth } });
    await tresorVergessen();
    location.replace('/');
  } catch (err) { meldung('status-konto', err.message); }
});
