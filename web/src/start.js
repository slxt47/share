// Startseite: Anmelden (Passwort → E-Mail-Code), Registrieren (→ Bestätigungscode), Passwort vergessen.
import { status } from './common.js';
import { api, ApiFehler } from './lib/api.js';
import { ableiten, neuesSalz, tresorMerken } from './lib/krypto.js';

const $ = (id) => document.getElementById(id);
const formulare = ['f-anmelden', 'f-registrieren', 'f-vergessen', 'f-code'];
let vorgang = null, codeZiel = null, tresor = null, benutzerName = '';

// Schon angemeldet? → direkt zu den Dateien
api('/api/ich').then(() => location.replace('/app')).catch(() => {});

function zeigen(id) {
  for (const f of formulare) $(f).hidden = f !== id;
  $('status').hidden = true;
  const anmelden = id !== 'f-registrieren';
  $('tab-anmelden').setAttribute('aria-selected', String(anmelden));
  $('tab-registrieren').setAttribute('aria-selected', String(!anmelden));
  $(id).querySelector('input')?.focus();
}
function meldung(text, art = 'err') { const s = $('status'); s.hidden = false; status(s, text, art); }

$('tab-anmelden').addEventListener('click', () => zeigen('f-anmelden'));
$('tab-registrieren').addEventListener('click', () => zeigen('f-registrieren'));
$('vergessen-knopf').addEventListener('click', () => zeigen('f-vergessen'));
$('zurueck-knopf').addEventListener('click', () => zeigen('f-anmelden'));

async function beschaeftigt(form, fn) {
  const knopf = form.querySelector('button[type="submit"]');
  const text = knopf.textContent;
  knopf.disabled = true; knopf.textContent = 'Einen Moment …';
  try { await fn(); } catch (e) { meldung(e instanceof ApiFehler ? e.message : 'Etwas ist schiefgelaufen: ' + e.message); }
  finally { knopf.disabled = false; knopf.textContent = text; }
}

function codeSchritt(antwort, ziel, hinweis) {
  vorgang = antwort.vorgang; codeZiel = ziel;
  zeigen('f-code');
  $('code-hinweis').textContent = hinweis;
  meldung('Code ist unterwegs – schau auch im Spam-Ordner.', 'ok');
}

$('f-anmelden').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.target;
  beschaeftigt(f, async () => {
    benutzerName = f.benutzer.value.trim().toLowerCase();
    const { salz } = await api('/api/salz?benutzer=' + encodeURIComponent(benutzerName));
    const k = await ableiten(f.passwort.value, salz);
    tresor = k.tresor;
    const r = await api('/api/anmelden', { methode: 'POST', json: { benutzer: benutzerName, auth: k.auth } });
    f.passwort.value = '';
    codeSchritt(r, '/api/anmelden/code', `Wir haben dir einen 6-stelligen Code an ${r.email} geschickt.`);
  });
});

$('f-registrieren').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.target;
  beschaeftigt(f, async () => {
    benutzerName = f.benutzer.value.trim().toLowerCase();
    const salz = neuesSalz();
    const k = await ableiten(f.passwort.value, salz);
    tresor = k.tresor;
    const r = await api('/api/registrieren', { methode: 'POST', json: { benutzer: benutzerName, email: f.email.value.trim(), salz, auth: k.auth } });
    f.passwort.value = '';
    codeSchritt(r, '/api/registrieren/bestaetigen', `Bestätige deine E-Mail-Adresse: Code an ${r.email}.`);
  });
});

$('f-vergessen').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.target;
  beschaeftigt(f, async () => {
    benutzerName = f.benutzer.value.trim().toLowerCase();
    const salz = neuesSalz();
    const k = await ableiten(f.passwort.value, salz);
    tresor = k.tresor;
    const r = await api('/api/passwort/vergessen', { methode: 'POST', json: { benutzer: benutzerName, salz, auth: k.auth } });
    f.passwort.value = '';
    codeSchritt(r, '/api/passwort/neu', 'Falls es das Konto gibt, ist ein Code an die hinterlegte E-Mail-Adresse unterwegs.');
  });
});

$('f-code').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.target;
  beschaeftigt(f, async () => {
    await api(codeZiel, { methode: 'POST', json: { vorgang, code: f.code.value.trim() } });
    await tresorMerken(tresor, benutzerName).catch(() => {});
    location.replace('/app');
  });
});

$('f-code').code.addEventListener('input', (e) => {
  e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6);
  if (e.target.value.length === 6) $('f-code').requestSubmit();
});
