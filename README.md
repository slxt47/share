# slxt share

Dateien **Ende-zu-Ende verschlüsselt** teilen – per Link oder QR-Code. Live: **https://share.slxt.dev**

- Hochladen im Browser, Empfänger öffnen den Link oder scannen den QR-Code – **ohne Konto**.
- Der Browser verschlüsselt Datei **und Dateiname** (AES-256-GCM) vor dem Hochladen. Der Schlüssel steht nur im Link hinter dem `#` – diesen Teil schicken Browser nie an einen Server. Der Server (und sein Betreiber) kann nichts lesen.
- Konten: Benutzername + Passwort + **Code per E-Mail bei jeder Anmeldung** (2FA). Das Passwort verlässt das Gerät nicht.
- **10 MB je Datei, 1 GB kostenlos je Konto**; mehr Speicher auf Anfrage (Admin gibt frei). Freigaben laufen nach 1, 7 oder 30 Tagen ab und werden dann gelöscht.
- Design wie [slxt.org](https://slxt.org) / [QR-Stream](https://github.com/slxt47/qr-stream): Himmel mit Sternschnuppen, folgt hell/dunkel des Geräts.

## Wie die Verschlüsselung funktioniert

```
Passwort ──PBKDF2-SHA-256 (600 000 Runden, Salz je Konto)──▶ 64 Byte
             ├─ Bytes 0–31  Anmeldeschlüssel → Server speichert nur argon2 davon
             └─ Bytes 32–63 Tresor-Schlüssel (AES-256-GCM, bleibt im Browser)

Datei ──▶ eigener Zufallsschlüssel K (AES-256-GCM)
           ├─ Inhalt + Metadaten (Name, Typ, Größe) mit K verschlüsselt → Server
           ├─ K mit Tresor-Schlüssel verpackt → Server (damit der Besitzer Liste, Link, QR sieht)
           └─ K im Link:  https://share.slxt.dev/d/<id>#<K>
```

- Passwort zurücksetzen (per E-Mail-Code) geht – alte Dateinamen in der eigenen Liste sind danach nicht mehr lesbar (sie waren mit dem alten Tresor-Schlüssel verpackt); geteilte Links funktionieren weiter.
- Passwort ändern (angemeldet) verpackt alle Dateischlüssel im Browser neu.
- Admin wird über die **bestätigte E-Mail-Adresse** bestimmt (nicht den Namen – bei offener Registrierung könnte jemand ihn belegen).

## Sicherheit

- Anmeldeversuche, Codes (6 Ziffern, 10 min, max. 5 Versuche), Registrierungen und Downloads sind je IP/Konto begrenzt; unbekannte Namen verraten nichts (Schein-Salz, gleiche Antworten, gleiche Rechenzeit).
- Sitzungs-Cookie `__Host-share` (HttpOnly, Secure, SameSite=Strict) + eigener Header gegen CSRF.
- Strenge CSP (`default-src 'self'`, kein Inline-Code), `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, kein Zugriffsprotokoll.
- Container: Nicht-root, Dateisystem nur lesbar (außer `/daten`), `cap_drop: ALL`, `no-new-privileges`, keine Host-Ports – erreichbar nur über einen Cloudflare-Tunnel.
- Uploads kommen als roher Datenstrom (kein Multipart-Parser), die Grenze wird schon beim Empfangen erzwungen.

## Starten

```sh
cp .env.example app.env && nano app.env      # SMTP-Zugang, SHARE_GEHEIM, Admin-Mail
python3 cloudflare-einrichten.py share.example.org --env cloudflare.env   # Tunnel + Route + DNS, schreibt .env (TUNNEL_TOKEN)
docker compose up -d --build
```

Daten (SQLite + verschlüsselte Dateien) liegen in `./daten`; die App legt alle 6 Stunden eine konsistente Datenbank-Kopie nach `daten/sicherung/` (für Datei-Backups).

## Tests

```sh
docker build --target test -t share:test . && docker run --rm share:test        # 13 API-Tests (pytest)
```

Browser-Durchlauf (Playwright) gegen eine Test-Instanz, in der Mails nur im Speicher landen:

```sh
docker network create share-probe
docker run -d --name share-probe --network share-probe -e SHARE_TEST=1 -e SHARE_COOKIE=share -e SHARE_COOKIE_SECURE=0 \
  --read-only --tmpfs /tmp --tmpfs /daten:uid=1000 share:1.0.0
docker run --rm --network container:share-probe -e BASIS=http://127.0.0.1:8080 -v "$PWD/tests:/t:ro" -v /tmp/out:/out \
  --entrypoint python3 <playwright-python-image> /t/browser_e2e.py
```

(`127.0.0.1` über das Container-Netz, weil Web Crypto eine sichere Umgebung braucht.) Geprüft: Registrierung + Code, Upload, Name/Inhalt nie im Klartext beim Server, Download ohne Konto byte-identisch (SHA-256), Link ohne/mit falschem Schlüssel liefert nichts, Anmeldung mit 2FA, 10-MB-Grenze, Löschen.

## Rechtliches

[Nutzungsbedingungen](https://slxt.org/nutzungsbedingungen/#share) · [Datenschutz](https://slxt.org/datenschutz/#share) · [Impressum](https://slxt.org/impressum/)

## Lizenz

[MIT](LICENSE) © 2026 Florian Neubauer. Mitgeliefert: qrcode (MIT); FastAPI, Starlette, Pydantic, Uvicorn (MIT/BSD), argon2-cffi (MIT).
