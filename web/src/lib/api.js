// Kleiner fetch-Helfer: immer gleiche Herkunft, Header X-Share gegen CSRF, deutsche Fehlermeldungen.
export class ApiFehler extends Error {
  constructor(text, status) { super(text); this.status = status; }
}

export async function api(pfad, { methode = 'GET', json, body, header = {} } = {}) {
  let r;
  try {
    r = await fetch(pfad, {
      method: methode,
      credentials: 'same-origin',
      headers: { 'X-Share': '1', ...(json ? { 'Content-Type': 'application/json' } : {}), ...header },
      body: json ? JSON.stringify(json) : body,
    });
  } catch {
    throw new ApiFehler('Keine Verbindung zum Server.', 0);
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiFehler(d.fehler || `Fehler ${r.status}`, r.status);
  return d;
}

/** Hochladen mit Fortschritt (XMLHttpRequest – fetch kennt keinen Upload-Fortschritt). */
export function hochladen(pfad, daten, header, fortschritt) {
  return new Promise((ok, nein) => {
    const x = new XMLHttpRequest();
    x.open('POST', pfad);
    x.setRequestHeader('X-Share', '1');
    x.setRequestHeader('Content-Type', 'application/octet-stream');
    for (const [k, v] of Object.entries(header)) x.setRequestHeader(k, v);
    x.upload.onprogress = (e) => e.lengthComputable && fortschritt?.(e.loaded / e.total);
    x.onload = () => {
      let d = {};
      try { d = JSON.parse(x.responseText); } catch { /* leer */ }
      if (x.status >= 200 && x.status < 300) ok(d); else nein(new ApiFehler(d.fehler || `Fehler ${x.status}`, x.status));
    };
    x.onerror = () => nein(new ApiFehler('Keine Verbindung zum Server.', 0));
    x.send(daten);
  });
}

export const groesse = (n) => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1).replace('.', ',')} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1).replace('.', ',')} MB`;
  return `${(n / 1024 ** 3).toFixed(2).replace('.', ',')} GB`;
};
