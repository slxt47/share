// Admin: Kontingente freigeben, Konten sperren, gemeldete Freigaben entfernen. Inhalte sieht auch der Admin nicht.
import { status } from './common.js';
import { api, groesse } from './lib/api.js';

const $ = (id) => document.getElementById(id);
function meldung(text, art = 'err') { const s = $('status'); s.hidden = false; status(s, text, art); }

async function laden() {
  let d;
  try { d = await api('/api/admin/benutzer'); } catch { location.replace('/app'); return; }
  const tb = $('zeilen'); tb.replaceChildren();
  for (const b of d.benutzer) {
    const tr = document.createElement('tr');
    const zelle = (t) => { const td = document.createElement('td'); td.textContent = t; tr.append(td); return td; };
    zelle(b.name + (b.letzte_anfrage > Date.now() / 1000 - 7 * 86400 ? ' ⭐ Anfrage' : ''));
    zelle(b.email);
    zelle(`${groesse(b.belegt)} · ${b.anzahl} Dateien`);
    const td = document.createElement('td');
    const inp = document.createElement('input');
    inp.type = 'number'; inp.min = '0'; inp.max = '1000'; inp.step = '0.5'; inp.value = String(+(b.kontingent / 1024 ** 3).toFixed(2));
    inp.setAttribute('aria-label', `Kontingent ${b.name} in GB`);
    inp.addEventListener('change', async () => {
      await api(`/api/admin/benutzer/${b.id}`, { methode: 'POST', json: { kontingent_gb: Number(inp.value) } });
      meldung(`${b.name}: Kontingent ${inp.value} GB gespeichert.`, 'ok');
    });
    td.append(inp); tr.append(td);
    zelle(!b.aktiv ? 'unbestätigt' : b.gesperrt ? 'gesperrt' : 'aktiv');
    const td2 = document.createElement('td');
    const k = document.createElement('button');
    k.className = 'btn' + (b.gesperrt ? '' : ' gefahr'); k.type = 'button'; k.textContent = b.gesperrt ? 'Entsperren' : 'Sperren';
    k.addEventListener('click', async () => {
      if (!b.gesperrt && !confirm(`${b.name} sperren?`)) return;
      await api(`/api/admin/benutzer/${b.id}`, { methode: 'POST', json: { gesperrt: !b.gesperrt } });
      laden();
    });
    td2.append(k); tr.append(td2);
    tb.append(tr);
  }
}
laden();

$('f-entfernen').addEventListener('submit', async (e) => {
  e.preventDefault();
  const roh = $('entfernen-id').value.trim();
  const id = (roh.match(/\/d\/([A-Za-z0-9_-]{22})/) || roh.match(/^([A-Za-z0-9_-]{22})$/) || [])[1];
  if (!id) { meldung('Bitte einen Freigabe-Link oder die 22-stellige ID eingeben.'); return; }
  if (!confirm(`Freigabe ${id} endgültig entfernen?`)) return;
  try { await api(`/api/admin/dateien/${id}`, { methode: 'DELETE' }); meldung('Entfernt.', 'ok'); $('entfernen-id').value = ''; laden(); }
  catch (err) { meldung(err.message); }
});
