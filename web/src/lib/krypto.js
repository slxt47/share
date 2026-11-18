// Ende-zu-Ende-Verschlüsselung für slxt share – nur Web Crypto (crypto.subtle).
//
// Passwort → PBKDF2-SHA-256 (600 000 Runden, Salz pro Konto) → 64 Byte:
//   • Bytes 0–31  = Anmeldeschlüssel (geht an den Server, der speichert nur argon2 davon)
//   • Bytes 32–63 = Tresor-Schlüssel (AES-256-GCM, verlässt NIE den Browser) – verpackt die Dateischlüssel
// Jede Datei: eigener zufälliger AES-256-GCM-Schlüssel. Er steckt im #-Teil des Freigabe-Links
// (geht nie an einen Server) und verpackt mit dem Tresor-Schlüssel beim Besitzer (für Liste/Link/QR).
const subtle = globalThis.crypto.subtle;
const enc = new TextEncoder(), dec = new TextDecoder();
const RUNDEN = 600_000;

export const hex = (b) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, '0')).join('');
export const vonHex = (s) => Uint8Array.from(s.match(/../g).map((x) => parseInt(x, 16)));
export const zufall = (n) => globalThis.crypto.getRandomValues(new Uint8Array(n));
export const b64 = (b) => btoa(String.fromCharCode(...new Uint8Array(b)));
export const vonB64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
export const b64url = (b) => b64(b).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
export const vonB64url = (s) => vonB64(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4));

export const neuesSalz = () => hex(zufall(16));

/** Passwort + Salz → { auth: hex (für den Server), tresor: CryptoKey (bleibt im Browser) } */
export async function ableiten(passwort, salzHex) {
  const basis = await subtle.importKey('raw', enc.encode(passwort.normalize('NFC')), 'PBKDF2', false, ['deriveBits']);
  const bits = new Uint8Array(await subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: vonHex(salzHex), iterations: RUNDEN }, basis, 512));
  const auth = hex(bits.slice(0, 32));
  const tresor = await subtle.importKey('raw', bits.slice(32), { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
  bits.fill(0);
  return { auth, tresor };
}

async function gcm(schluessel, daten) {
  const iv = zufall(12);
  const ct = new Uint8Array(await subtle.encrypt({ name: 'AES-GCM', iv }, schluessel, daten));
  const out = new Uint8Array(12 + ct.length);
  out.set(iv); out.set(ct, 12);
  return out;
}

async function ungcm(schluessel, daten) {
  return new Uint8Array(await subtle.decrypt({ name: 'AES-GCM', iv: daten.subarray(0, 12) }, schluessel, daten.subarray(12)));
}

const dateiSchluessel = (roh) => subtle.importKey('raw', roh, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);

/** Datei verschlüsseln → { geheimtext, meta (b64), verpackt (b64), roh (Dateischlüssel, für den Link) } */
export async function dateiVerschluesseln(bytes, info, tresor) {
  const roh = zufall(32);
  const k = await dateiSchluessel(roh);
  const geheimtext = await gcm(k, bytes);
  const meta = b64(await gcm(k, enc.encode(JSON.stringify({ name: info.name, typ: info.typ || 'application/octet-stream', groesse: bytes.length }))));
  const verpackt = b64(await gcm(tresor, roh));
  return { geheimtext, meta, verpackt, roh };
}

export async function auspacken(verpacktB64, tresor) {
  return ungcm(tresor, vonB64(verpacktB64));
}

export async function neuVerpacken(roh, tresor) {
  return b64(await gcm(tresor, roh));
}

export async function metaLesen(metaB64, roh) {
  return JSON.parse(dec.decode(await ungcm(await dateiSchluessel(roh), vonB64(metaB64))));
}

export async function dateiEntschluesseln(geheimtext, roh) {
  return ungcm(await dateiSchluessel(roh), geheimtext);
}

// ---------- Tresor-Schlüssel im Browser merken (IndexedDB, als nicht exportierbarer CryptoKey) ----------
function idb() {
  return new Promise((ok, nein) => {
    const r = indexedDB.open('slxt-share', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('tresor');
    r.onsuccess = () => ok(r.result);
    r.onerror = () => nein(r.error);
  });
}
async function idbAktion(modus, fn) {
  const d = await idb();
  return new Promise((ok, nein) => {
    const tx = d.transaction('tresor', modus);
    const r = fn(tx.objectStore('tresor'));
    tx.oncomplete = () => { ok(r?.result); d.close(); };
    tx.onerror = () => { nein(tx.error); d.close(); };
  });
}
export const tresorMerken = (k, benutzer) => idbAktion('readwrite', (s) => s.put({ k, benutzer }, 'aktuell'));
export const tresorHolen = () => idbAktion('readonly', (s) => s.get('aktuell')).catch(() => null);
export const tresorVergessen = () => idbAktion('readwrite', (s) => s.delete('aktuell')).catch(() => null);
