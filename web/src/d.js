// Empfänger-Seite /d/<id>#<schlüssel>: Infos laden, im Browser entschlüsseln, herunterladen. Kein Konto nötig.
import { status } from './common.js';
import { groesse } from './lib/api.js';
import { vonB64url, metaLesen, dateiEntschluesseln } from './lib/krypto.js';

const $ = (id) => document.getElementById(id);
const id = location.pathname.split('/').pop();
let roh = null, meta = null, url = null;

function meldung(text, art = 'err') { const s = $('status'); s.hidden = false; status(s, text, art); }
function info(...zeilen) {
  const el = $('info'); el.replaceChildren();
  for (const [fett, text] of zeilen) {
    const s = document.createElement('span');
    if (fett) { const b = document.createElement('b'); b.textContent = fett; s.append(b); } else { s.className = 'sec klein'; s.textContent = text; }
    el.append(s);
  }
}

$('melden').href = `mailto:office@slxt.org?subject=${encodeURIComponent('Missbrauch melden: ' + id)}&body=${encodeURIComponent('Freigabe-ID: ' + id + '\nWas ist das Problem?\n')}`;

(async function start() {
  try { roh = vonB64url(location.hash.slice(1)); } catch { roh = null; }
  if (!roh || roh.length !== 32) { info(['Link unvollständig', null], [null, 'Dem Link fehlt der Schlüssel hinter dem „#“. Bitte den ganzen Link verwenden.']); return; }
  const r = await fetch(`/api/teilen/${encodeURIComponent(id)}`, { credentials: 'omit' });
  if (!r.ok) { info(['Nicht (mehr) verfügbar', null], [null, 'Diese Freigabe ist abgelaufen, wurde gelöscht oder hat nie existiert.']); return; }
  const d = await r.json();
  try { meta = await metaLesen(d.meta, roh); }
  catch { info(['Schlüssel passt nicht', null], [null, 'Der Link ist beschädigt – bitte den Absender um den vollständigen Link bitten.']); return; }
  const ablauf = d.ablauf ? `verfügbar bis ${new Date(d.ablauf * 1000).toLocaleString('de-AT', { dateStyle: 'medium', timeStyle: 'short' })}` : 'ohne Ablaufdatum';
  info([meta.name, null], [null, `${groesse(meta.groesse)} · ${meta.typ} · ${ablauf}`]);
  document.title = `${meta.name} – slxt share`;
  $('laden').disabled = false;
})();

$('laden').addEventListener('click', async () => {
  if (url) { speichern(); return; }
  $('laden').disabled = true;
  const balken = $('balken'), i = balken.querySelector('i');
  balken.hidden = false;
  try {
    const r = await fetch(`/api/teilen/${encodeURIComponent(id)}/daten`, { credentials: 'omit' });
    if (!r.ok) throw new Error('Die Datei ist nicht mehr verfügbar.');
    const gesamt = Number(r.headers.get('content-length')) || 0, teile = [];
    let n = 0;
    const leser = r.body.getReader();
    for (;;) {
      const { done, value } = await leser.read();
      if (done) break;
      teile.push(value); n += value.length;
      if (gesamt) i.style.width = ((n / gesamt) * 100).toFixed(1) + '%';
    }
    const geheim = new Uint8Array(n);
    let o = 0; for (const t of teile) { geheim.set(t, o); o += t.length; }
    meldung('Entschlüssele …', '');
    const daten = await dateiEntschluesseln(geheim, roh);
    url = URL.createObjectURL(new Blob([daten], { type: meta.typ }));
    daten.fill(0); geheim.fill(0);
    meldung('Entschlüsselt und geprüft – die Datei ist unverändert angekommen.', 'ok');
    $('laden').textContent = 'Nochmal speichern';
    speichern();
  } catch (e) {
    meldung(e.name === 'OperationError' ? 'Die Datei lässt sich mit diesem Schlüssel nicht entschlüsseln (beschädigt oder falscher Link).' : e.message);
  } finally {
    $('laden').disabled = false; balken.hidden = true;
  }
});

function speichern() {
  const a = document.createElement('a');
  a.href = url; a.download = meta.name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').slice(0, 200) || 'datei'; a.rel = 'noopener';
  document.body.append(a); a.click(); a.remove();
}

window.addEventListener('pagehide', () => { if (url) URL.revokeObjectURL(url); roh?.fill(0); });
