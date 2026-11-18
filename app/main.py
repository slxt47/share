"""slxt share – Dateien Ende-zu-Ende verschlüsselt teilen (Link oder QR-Code).

Der Server sieht nie Dateiinhalte, Dateinamen oder Schlüssel: Der Browser verschlüsselt vorher (AES-256-GCM),
der Dateischlüssel steckt nur im #-Teil des Links. Konten: Benutzername + Passwort (der Browser schickt nur einen
abgeleiteten Anmeldeschlüssel) + Code per E-Mail bei jeder Anmeldung. Grenzen: 10 MB je Datei, 1 GB je Konto.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.staticfiles import StaticFiles

from . import db, mail

MAX_DATEI = 10 * 1024 * 1024                 # 10 MB Klartext
MAX_GEHEIMTEXT = MAX_DATEI + 12 + 16         # + IV + GCM-Tag
KONTINGENT = 1024 ** 3                       # 1 GB je Konto (Geheimtext-Bytes)
SITZUNG_S = 14 * 86400
CODE_S = 600
ABLAUF_TAGE = {'1': 1, '7': 7, '30': 30, '0': None}
TEST = os.environ.get('SHARE_TEST') == '1'
COOKIE = os.environ.get('SHARE_COOKIE', '__Host-share')
COOKIE_SECURE = os.environ.get('SHARE_COOKIE_SECURE', '1') == '1'
# Admin über die BESTÄTIGTE E-Mail-Adresse (nicht den Namen – bei offener Registrierung könnte jemand den Namen belegen)
ADMINS = {n.strip().lower() for n in os.environ.get('SHARE_ADMIN_MAILS', '').split(',') if n.strip()}
ADMIN_MAIL = os.environ.get('SHARE_ADMIN_MAIL', '')
GEHEIM = (os.environ.get('SHARE_GEHEIM') or secrets.token_hex(32)).encode()   # für Schein-Salze unbekannter Namen
WEB = os.environ.get('SHARE_WEB', os.path.join(os.path.dirname(__file__), '..', 'web', 'dist'))
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_.-]{2,31}$')
MAIL_RE = re.compile(r'^[^@\s<>"]{1,64}@[^@\s<>"]{1,190}\.[a-z]{2,24}$', re.I)
HEX64 = re.compile(r'^[0-9a-f]{64}$')
ID_RE = re.compile(r'^[A-Za-z0-9_-]{22}$')
B64 = re.compile(r'^[A-Za-z0-9+/=_-]{16,4096}$')

ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
db.einrichten()      # idempotent; gleich beim Laden, damit auch Tests ohne Lifespan eine Datenbank haben


@asynccontextmanager
async def lebenszeit(_app):
    if not TEST:
        threading.Thread(target=hintergrund, daemon=True).start()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lebenszeit)


# ---------------------------------------------------------------- Hilfen
def jetzt():
    return int(time.time())


def h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def client_ip(req: Request):
    # Nur cloudflared erreicht die App (kein Host-Port) → CF-Connecting-IP ist vertrauenswürdig
    return req.headers.get('cf-connecting-ip') or (req.client.host if req.client else '?')


class Begrenzer:
    """Gleitendes Fenster je Schlüssel, nur im Arbeitsspeicher."""
    def __init__(self):
        self.d = defaultdict(deque)
        self.lock = threading.Lock()

    def pruefen(self, schluessel, anzahl, sekunden):
        t = time.monotonic()
        with self.lock:
            q = self.d[schluessel]
            while q and t - q[0] > sekunden:
                q.popleft()
            if len(q) >= anzahl:
                raise HTTPException(429, 'Zu viele Versuche – bitte kurz warten.')
            q.append(t)
            if len(self.d) > 50000:          # Speicher begrenzen
                for k in list(self.d)[:10000]:
                    del self.d[k]


grenze = Begrenzer()


def fehler(code, text):
    raise HTTPException(code, text)


@app.exception_handler(HTTPException)
async def http_fehler(req, e: HTTPException):
    return JSONResponse({'fehler': e.detail}, status_code=e.status_code, headers=getattr(e, 'headers', None))


SICHERHEIT = {
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
                               "connect-src 'self'; worker-src 'self'; manifest-src 'self'; font-src 'self'; object-src 'none'; "
                               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
    'X-Content-Type-Options': 'nosniff',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'X-Frame-Options': 'DENY',
}


@app.middleware('http')
async def schutz(req: Request, call_next):
    # Zustandsändernde Aufrufe nur mit eigenem Header (CSRF: fremde Seiten können ihn ohne CORS nicht setzen)
    if req.method in ('POST', 'PUT', 'PATCH', 'DELETE') and req.headers.get('x-share') != '1':
        return JSONResponse({'fehler': 'Anfrage abgelehnt'}, status_code=403)
    r = await call_next(req)
    for k, v in SICHERHEIT.items():
        r.headers.setdefault(k, v)
    p = req.url.path
    if p.startswith('/assets/'):
        r.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif not p.startswith('/icons/'):
        r.headers['Cache-Control'] = 'no-store'
    return r


async def json_body(req: Request, maximal=8192):
    roh = await req.body()
    if len(roh) > maximal:
        fehler(413, 'Anfrage zu groß')
    try:
        import json
        d = json.loads(roh or b'{}')
    except ValueError:
        fehler(400, 'Ungültige Anfrage')
    if not isinstance(d, dict):
        fehler(400, 'Ungültige Anfrage')
    return d


def benutzer_aus_sitzung(req: Request, pflicht=True):
    t = req.cookies.get(COOKIE)
    row = None
    if t and len(t) < 100:
        row = db.verbindung().execute(
            'SELECT b.* FROM sitzungen s JOIN benutzer b ON b.id = s.benutzer_id WHERE s.token_hash = ? AND s.gueltig_bis > ?',
            (h(t), jetzt())).fetchone()
    if row and (row['gesperrt'] or not row['aktiv']):
        row = None
    if pflicht and not row:
        fehler(401, 'Bitte anmelden.')
    return row


def sitzung_setzen(resp: Response, benutzer_id):
    t = secrets.token_urlsafe(32)
    db.verbindung().execute('INSERT INTO sitzungen VALUES (?, ?, ?, ?)', (h(t), benutzer_id, jetzt(), jetzt() + SITZUNG_S))
    resp.set_cookie(COOKIE, t, max_age=SITZUNG_S, httponly=True, secure=COOKIE_SECURE, samesite='strict', path='/')


def ist_admin(b):
    return bool(b) and b['aktiv'] == 1 and b['email'].lower() in ADMINS


def belegt(benutzer_id):
    return db.verbindung().execute('SELECT COALESCE(SUM(groesse), 0) FROM dateien WHERE benutzer_id = ?', (benutzer_id,)).fetchone()[0]


def vorgang_starten(benutzer, art, daten=''):
    """6-stelligen Code per Mail schicken; der Browser bekommt nur ein Vorgangs-Token."""
    c = db.verbindung()
    c.execute('DELETE FROM vorgaenge WHERE benutzer_id = ? AND art = ?', (benutzer['id'], art))
    code = f'{secrets.randbelow(1_000_000):06d}'
    token = secrets.token_urlsafe(24)
    c.execute('INSERT INTO vorgaenge VALUES (?, ?, ?, ?, 0, ?, ?)',
              (h(token), benutzer['id'], art, h(token + code), jetzt() + CODE_S, daten))
    threading.Thread(target=_mail_sicher, args=(benutzer['email'], code, art), daemon=True).start()
    return token


def _mail_sicher(an, code, art):
    try:
        mail.code_mail(an, code, art)
    except Exception as e:   # noqa: BLE001 – Fehler nur protokollieren, nie den Code
        print(f'mail-fehler {type(e).__name__}', flush=True)


def vorgang_pruefen(token, code, art):
    c = db.verbindung()
    if not isinstance(token, str) or not isinstance(code, str) or not re.fullmatch(r'\d{6}', code.strip()):
        fehler(400, 'Bitte den 6-stelligen Code eingeben.')
    v = c.execute('SELECT * FROM vorgaenge WHERE token_hash = ? AND art = ?', (h(token), art)).fetchone()
    if not v or v['gueltig_bis'] < jetzt():
        fehler(400, 'Der Code ist abgelaufen – bitte neu anfordern.')
    if v['versuche'] >= 5:
        c.execute('DELETE FROM vorgaenge WHERE token_hash = ?', (v['token_hash'],))
        fehler(400, 'Zu viele falsche Codes – bitte neu anfordern.')
    if not hmac.compare_digest(v['code_hash'], h(token + code.strip())):
        c.execute('UPDATE vorgaenge SET versuche = versuche + 1 WHERE token_hash = ?', (v['token_hash'],))
        fehler(400, f'Falscher Code (noch {4 - v["versuche"]} Versuche).')
    c.execute('DELETE FROM vorgaenge WHERE token_hash = ?', (v['token_hash'],))
    return v


def schein_salz(name):
    """Für unbekannte Namen ein stabiles Schein-Salz – so verrät /salz nicht, ob es ein Konto gibt."""
    return hmac.new(GEHEIM, b'salz:' + name.lower().encode(), hashlib.sha256).hexdigest()[:32]


def hash_auth(auth):
    return ph.hash(auth)


def auth_ok(hash_, auth):
    try:
        return ph.verify(hash_, auth)
    except (VerificationError, InvalidHashError):
        return False


DUMMY_HASH = ph.hash('0' * 64)    # gleiche Rechenzeit für unbekannte Namen


# ---------------------------------------------------------------- Konto
@app.get('/api/salz')
def salz(benutzer: str, req: Request):
    grenze.pruefen('salz:' + client_ip(req), 60, 600)
    name = benutzer.strip().lower()
    if not NAME_RE.match(name):
        fehler(400, 'Ungültiger Benutzername')
    row = db.verbindung().execute('SELECT salz FROM benutzer WHERE name = ?', (name,)).fetchone()
    return {'salz': row['salz'] if row else schein_salz(name)}


@app.post('/api/registrieren')
async def registrieren(req: Request):
    d = await json_body(req)
    grenze.pruefen('reg:' + client_ip(req), 5, 3600)
    name, email = str(d.get('benutzer', '')).strip().lower(), str(d.get('email', '')).strip()
    salz_, auth = str(d.get('salz', '')), str(d.get('auth', ''))
    if not NAME_RE.match(name):
        fehler(400, 'Benutzername: 3–32 Zeichen, nur a–z, 0–9, Punkt, Strich, Unterstrich.')
    if not MAIL_RE.match(email):
        fehler(400, 'Bitte eine gültige E-Mail-Adresse eingeben.')
    if not re.fullmatch(r'[0-9a-f]{32}', salz_) or not HEX64.match(auth):
        fehler(400, 'Ungültige Anfrage')
    c = db.verbindung()
    # Nie bestätigte Konten werden nach 24 h frei (Aufräumen läuft auch im Hintergrund)
    c.execute('DELETE FROM benutzer WHERE aktiv = 0 AND erstellt < ?', (jetzt() - 86400,))
    alt = c.execute('SELECT * FROM benutzer WHERE name = ? OR email = ?', (name, email)).fetchone()
    if alt and alt['aktiv']:
        fehler(409, 'Benutzername oder E-Mail-Adresse ist schon vergeben.')
    if alt:
        c.execute('DELETE FROM benutzer WHERE id = ?', (alt['id'],))
    c.execute('INSERT INTO benutzer (name, email, salz, auth_hash, aktiv, kontingent, erstellt) VALUES (?, ?, ?, ?, 0, ?, ?)',
              (name, email, salz_, hash_auth(auth), KONTINGENT, jetzt()))
    b = c.execute('SELECT * FROM benutzer WHERE name = ?', (name,)).fetchone()
    db.protokollieren('registriert (unbestätigt)', b['id'])
    return {'vorgang': vorgang_starten(b, 'registrieren'), 'email': email}


@app.post('/api/registrieren/bestaetigen')
async def registrieren_bestaetigen(req: Request):
    d = await json_body(req)
    grenze.pruefen('code:' + client_ip(req), 20, 600)
    v = vorgang_pruefen(d.get('vorgang'), str(d.get('code', '')), 'registrieren')
    c = db.verbindung()
    c.execute('UPDATE benutzer SET aktiv = 1 WHERE id = ?', (v['benutzer_id'],))
    db.protokollieren('E-Mail bestätigt', v['benutzer_id'])
    resp = JSONResponse({'ok': True})
    sitzung_setzen(resp, v['benutzer_id'])
    return resp


@app.post('/api/anmelden')
async def anmelden(req: Request):
    d = await json_body(req)
    ip = client_ip(req)
    grenze.pruefen('login:' + ip, 10, 900)
    name, auth = str(d.get('benutzer', '')).strip().lower(), str(d.get('auth', ''))
    if not NAME_RE.match(name) or not HEX64.match(auth):
        fehler(400, 'Benutzername oder Passwort falsch.')
    grenze.pruefen('login-name:' + name, 10, 900)
    b = db.verbindung().execute('SELECT * FROM benutzer WHERE name = ? AND aktiv = 1', (name,)).fetchone()
    if not auth_ok(b['auth_hash'] if b else DUMMY_HASH, auth) or not b:
        db.protokollieren('Anmeldung: falsches Passwort', b['id'] if b else None)
        fehler(400, 'Benutzername oder Passwort falsch.')
    if b['gesperrt']:
        fehler(403, 'Dieses Konto ist gesperrt.')
    return {'vorgang': vorgang_starten(b, 'anmelden'), 'email': maskieren(b['email'])}


def maskieren(email):
    lokal, _, dom = email.partition('@')
    return (lokal[:2] + '•••@' + dom) if len(lokal) > 2 else ('•••@' + dom)


@app.post('/api/anmelden/code')
async def anmelden_code(req: Request):
    d = await json_body(req)
    grenze.pruefen('code:' + client_ip(req), 20, 600)
    v = vorgang_pruefen(d.get('vorgang'), str(d.get('code', '')), 'anmelden')
    db.protokollieren('angemeldet', v['benutzer_id'])
    resp = JSONResponse({'ok': True})
    sitzung_setzen(resp, v['benutzer_id'])
    return resp


@app.post('/api/abmelden')
async def abmelden(req: Request):
    t = req.cookies.get(COOKIE)
    if t:
        db.verbindung().execute('DELETE FROM sitzungen WHERE token_hash = ?', (h(t),))
    resp = JSONResponse({'ok': True})
    resp.delete_cookie(COOKIE, path='/', secure=COOKIE_SECURE, httponly=True, samesite='strict')
    return resp


@app.get('/api/ich')
def ich(req: Request):
    b = benutzer_aus_sitzung(req)
    return {'benutzer': b['name'], 'email': b['email'], 'salz': b['salz'], 'belegt': belegt(b['id']),
            'kontingent': b['kontingent'], 'max_datei': MAX_DATEI, 'admin': ist_admin(b)}


@app.post('/api/tresor-pruefen')
async def tresor_pruefen(req: Request):
    """Passwort erneut eingeben, um im Browser den Tresor-Schlüssel abzuleiten (z. B. nach Neuladen)."""
    b = benutzer_aus_sitzung(req)
    d = await json_body(req)
    grenze.pruefen('tresor:' + str(b['id']), 10, 900)
    if not HEX64.match(str(d.get('auth', ''))) or not auth_ok(b['auth_hash'], d['auth']):
        fehler(400, 'Passwort falsch.')
    return {'ok': True}


@app.post('/api/passwort/vergessen')
async def passwort_vergessen(req: Request):
    d = await json_body(req)
    grenze.pruefen('vergessen:' + client_ip(req), 5, 3600)
    name = str(d.get('benutzer', '')).strip().lower()
    salz_, auth = str(d.get('salz', '')), str(d.get('auth', ''))
    if not re.fullmatch(r'[0-9a-f]{32}', salz_) or not HEX64.match(auth):
        fehler(400, 'Ungültige Anfrage')
    b = db.verbindung().execute('SELECT * FROM benutzer WHERE name = ? AND aktiv = 1', (name,)).fetchone() if NAME_RE.match(name) else None
    token = vorgang_starten(b, 'passwort', salz_ + ':' + hash_auth(auth)) if b and not b['gesperrt'] else secrets.token_urlsafe(24)
    return {'vorgang': token}     # gleiche Antwort, ob es das Konto gibt oder nicht


@app.post('/api/passwort/neu')
async def passwort_neu(req: Request):
    d = await json_body(req)
    grenze.pruefen('code:' + client_ip(req), 20, 600)
    v = vorgang_pruefen(d.get('vorgang'), str(d.get('code', '')), 'passwort')
    salz_, hash_ = v['daten'].split(':', 1)
    c = db.verbindung()
    c.execute('UPDATE benutzer SET salz = ?, auth_hash = ? WHERE id = ?', (salz_, hash_, v['benutzer_id']))
    c.execute('DELETE FROM sitzungen WHERE benutzer_id = ?', (v['benutzer_id'],))
    db.protokollieren('Passwort zurückgesetzt', v['benutzer_id'])
    resp = JSONResponse({'ok': True})
    sitzung_setzen(resp, v['benutzer_id'])
    return resp


@app.post('/api/passwort/aendern')
async def passwort_aendern(req: Request):
    """Angemeldet: altes Passwort bestätigen, neuer Anmeldeschlüssel + alle Dateischlüssel neu verpackt (im Browser)."""
    b = benutzer_aus_sitzung(req)
    d = await json_body(req, 2_000_000)
    grenze.pruefen('aendern:' + str(b['id']), 5, 900)
    if not HEX64.match(str(d.get('alt_auth', ''))) or not auth_ok(b['auth_hash'], d['alt_auth']):
        fehler(400, 'Altes Passwort falsch.')
    salz_, auth = str(d.get('salz', '')), str(d.get('auth', ''))
    schl = d.get('schluessel', [])
    if not re.fullmatch(r'[0-9a-f]{32}', salz_) or not HEX64.match(auth) or not isinstance(schl, list):
        fehler(400, 'Ungültige Anfrage')
    c = db.verbindung()
    eigene = {r['id'] for r in c.execute('SELECT id FROM dateien WHERE benutzer_id = ?', (b['id'],))}
    neu = {s.get('id'): s.get('schluessel') for s in schl if isinstance(s, dict)}
    if set(neu) != eigene or not all(isinstance(x, str) and B64.match(x) for x in neu.values()):
        fehler(400, 'Schlüsselliste unvollständig – bitte Seite neu laden und erneut versuchen.')
    c.execute('BEGIN')
    for i, s in neu.items():
        c.execute('UPDATE dateien SET schluessel = ? WHERE id = ? AND benutzer_id = ?', (s, i, b['id']))
    c.execute('UPDATE benutzer SET salz = ?, auth_hash = ? WHERE id = ?', (salz_, hash_auth(auth), b['id']))
    c.execute('DELETE FROM sitzungen WHERE benutzer_id = ?', (b['id'],))
    c.execute('COMMIT')
    db.protokollieren('Passwort geändert', b['id'])
    resp = JSONResponse({'ok': True})
    sitzung_setzen(resp, b['id'])
    return resp


@app.post('/api/konto/loeschen')
async def konto_loeschen(req: Request):
    b = benutzer_aus_sitzung(req)
    d = await json_body(req)
    if not HEX64.match(str(d.get('auth', ''))) or not auth_ok(b['auth_hash'], d['auth']):
        fehler(400, 'Passwort falsch.')
    for r in db.verbindung().execute('SELECT id FROM dateien WHERE benutzer_id = ?', (b['id'],)).fetchall():
        datei_entfernen(r['id'])
    db.verbindung().execute('DELETE FROM benutzer WHERE id = ?', (b['id'],))
    db.protokollieren(f'Konto gelöscht (#{b["id"]})')
    resp = JSONResponse({'ok': True})
    resp.delete_cookie(COOKIE, path='/', secure=COOKIE_SECURE, httponly=True, samesite='strict')
    return resp


@app.post('/api/speicher-anfragen')
async def speicher_anfragen(req: Request):
    b = benutzer_aus_sitzung(req)
    d = await json_body(req)
    if b['letzte_anfrage'] > jetzt() - 86400:
        fehler(429, 'Du hast heute schon angefragt – wir melden uns per E-Mail.')
    gb = d.get('gb')
    if not isinstance(gb, int) or not 1 <= gb <= 100:
        fehler(400, 'Bitte 1–100 GB angeben.')
    text = re.sub(r'[\x00-\x08\x0b-\x1f]', ' ', str(d.get('nachricht', '')))[:500]
    db.verbindung().execute('UPDATE benutzer SET letzte_anfrage = ? WHERE id = ?', (jetzt(), b['id']))
    if ADMIN_MAIL:
        threading.Thread(target=lambda: _senden_sicher(
            ADMIN_MAIL, f'slxt share: {b["name"]} möchte +{gb} GB',
            f'Benutzer: {b["name"]}\nE-Mail: {b["email"]}\nBelegt: {belegt(b["id"]) / 1024 ** 3:.2f} GB von '
            f'{b["kontingent"] / 1024 ** 3:.2f} GB\nGewünscht: +{gb} GB\n\nNachricht:\n{text or "–"}\n\n'
            'Freigeben: https://share.slxt.dev/admin'), daemon=True).start()
    db.protokollieren(f'Speicher angefragt: +{gb} GB', b['id'])
    return {'ok': True}


def _senden_sicher(an, betreff, text):
    try:
        mail.senden(an, betreff, text)
    except Exception as e:   # noqa: BLE001
        print(f'mail-fehler {type(e).__name__}', flush=True)


# ---------------------------------------------------------------- Dateien
def datei_pfad(i):
    return os.path.join(db.DATEN, 'dateien', i)


def datei_entfernen(i):
    try:
        os.remove(datei_pfad(i))
    except FileNotFoundError:
        pass
    db.verbindung().execute('DELETE FROM dateien WHERE id = ?', (i,))


@app.post('/api/dateien')
async def hochladen(req: Request, ablauf: str = '7'):
    b = benutzer_aus_sitzung(req)
    grenze.pruefen('upload:' + str(b['id']), 60, 600)
    meta, schl = req.headers.get('x-meta', ''), req.headers.get('x-schluessel', '')
    if not B64.match(meta) or not B64.match(schl) or ablauf not in ABLAUF_TAGE:
        fehler(400, 'Ungültige Anfrage')
    laenge = int(req.headers.get('content-length') or 0)
    if laenge > MAX_GEHEIMTEXT:
        fehler(413, 'Die Datei ist größer als 10 MB.')
    if belegt(b['id']) + max(laenge, 1) > b['kontingent']:
        fehler(507, 'Dein Speicher ist voll. Lösche alte Dateien oder frag nach mehr Speicher.')
    i = secrets.token_urlsafe(16)            # 128 Bit → 22 Zeichen
    tmp = os.path.join(db.DATEN, 'tmp', i)
    n = 0
    try:
        with open(tmp, 'wb') as f:
            async for teil in req.stream():
                n += len(teil)
                if n > MAX_GEHEIMTEXT:
                    fehler(413, 'Die Datei ist größer als 10 MB.')
                f.write(teil)
        if n < 29:
            fehler(400, 'Leere Datei')
        c = db.verbindung()
        c.execute('BEGIN IMMEDIATE')
        if belegt(b['id']) + n > b['kontingent']:       # nochmal unter Sperre (parallele Uploads)
            c.execute('ROLLBACK')
            fehler(507, 'Dein Speicher ist voll. Lösche alte Dateien oder frag nach mehr Speicher.')
        tage = ABLAUF_TAGE[ablauf]
        c.execute('INSERT INTO dateien (id, benutzer_id, groesse, meta, schluessel, erstellt, ablauf) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (i, b['id'], n, meta, schl, jetzt(), jetzt() + tage * 86400 if tage else None))
        os.replace(tmp, datei_pfad(i))
        c.execute('COMMIT')
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return {'id': i, 'groesse': n}


@app.get('/api/dateien')
def dateien(req: Request):
    b = benutzer_aus_sitzung(req)
    rows = db.verbindung().execute('SELECT id, groesse, meta, schluessel, erstellt, ablauf, downloads FROM dateien '
                                   'WHERE benutzer_id = ? ORDER BY erstellt DESC', (b['id'],)).fetchall()
    return {'dateien': [dict(r) for r in rows], 'belegt': belegt(b['id']), 'kontingent': b['kontingent']}


@app.delete('/api/dateien/{i}')
def loeschen(i: str, req: Request):
    b = benutzer_aus_sitzung(req)
    if not ID_RE.match(i) or not db.verbindung().execute('SELECT 1 FROM dateien WHERE id = ? AND benutzer_id = ?', (i, b['id'])).fetchone():
        fehler(404, 'Nicht gefunden')
    datei_entfernen(i)
    return {'ok': True}


def oeffentlich(i):
    if not ID_RE.match(i):
        fehler(404, 'Diese Freigabe gibt es nicht (mehr).')
    r = db.verbindung().execute('SELECT * FROM dateien WHERE id = ?', (i,)).fetchone()
    if not r or (r['ablauf'] and r['ablauf'] < jetzt()):
        fehler(404, 'Diese Freigabe gibt es nicht (mehr).')
    return r


@app.get('/api/teilen/{i}')
def teilen_info(i: str, req: Request):
    grenze.pruefen('teilen:' + client_ip(req), 120, 60)
    r = oeffentlich(i)
    return {'meta': r['meta'], 'groesse': r['groesse'], 'ablauf': r['ablauf']}


@app.get('/api/teilen/{i}/daten')
def teilen_daten(i: str, req: Request):
    grenze.pruefen('laden:' + client_ip(req), 60, 600)
    r = oeffentlich(i)
    db.verbindung().execute('UPDATE dateien SET downloads = downloads + 1 WHERE id = ?', (i,))
    return FileResponse(datei_pfad(i), media_type='application/octet-stream', headers={'Cache-Control': 'no-store'})


# ---------------------------------------------------------------- Admin
def admin(req):
    b = benutzer_aus_sitzung(req)
    if not ist_admin(b):
        fehler(403, 'Nur für Admins')
    return b


@app.get('/api/admin/benutzer')
def admin_benutzer(req: Request):
    admin(req)
    rows = db.verbindung().execute(
        'SELECT b.id, b.name, b.email, b.aktiv, b.gesperrt, b.kontingent, b.erstellt, b.letzte_anfrage, '
        'COALESCE(SUM(d.groesse), 0) AS belegt, COUNT(d.id) AS anzahl FROM benutzer b '
        'LEFT JOIN dateien d ON d.benutzer_id = b.id GROUP BY b.id ORDER BY b.letzte_anfrage DESC, b.erstellt DESC').fetchall()
    return {'benutzer': [dict(r) for r in rows]}


@app.post('/api/admin/benutzer/{bid}')
async def admin_aendern(bid: int, req: Request):
    a = admin(req)
    d = await json_body(req)
    c = db.verbindung()
    if 'kontingent_gb' in d:
        gb = d['kontingent_gb']
        if not isinstance(gb, (int, float)) or not 0 <= gb <= 1000:
            fehler(400, 'Kontingent 0–1000 GB')
        c.execute('UPDATE benutzer SET kontingent = ? WHERE id = ?', (int(gb * 1024 ** 3), bid))
        db.protokollieren(f'Kontingent → {gb} GB (durch {a["name"]})', bid)
    if 'gesperrt' in d:
        c.execute('UPDATE benutzer SET gesperrt = ? WHERE id = ?', (1 if d['gesperrt'] else 0, bid))
        if d['gesperrt']:
            c.execute('DELETE FROM sitzungen WHERE benutzer_id = ?', (bid,))
        db.protokollieren(f'gesperrt={bool(d["gesperrt"])} (durch {a["name"]})', bid)
    return {'ok': True}


@app.delete('/api/admin/dateien/{i}')
def admin_datei_loeschen(i: str, req: Request):
    a = admin(req)
    if not ID_RE.match(i) or not db.verbindung().execute('SELECT 1 FROM dateien WHERE id = ?', (i,)).fetchone():
        fehler(404, 'Nicht gefunden')
    datei_entfernen(i)
    db.protokollieren(f'Datei {i} gelöscht (Meldung, durch {a["name"]})')
    return {'ok': True}


# ---------------------------------------------------------------- Test-Hilfe (nur SHARE_TEST=1)
if TEST:
    @app.get('/api/test/posteingang')
    def test_posteingang():
        return {'mails': [{'an': a, 'betreff': b, 'text': t} for a, b, t in mail.POSTEINGANG_TEST]}


@app.get('/api/gesund')
def gesund():
    db.verbindung().execute('SELECT 1')
    return {'ok': True}


# ---------------------------------------------------------------- Hintergrund: Ablauf, Aufräumen, Sicherung
def aufraeumen():
    c = db.verbindung()
    for r in c.execute('SELECT id FROM dateien WHERE ablauf IS NOT NULL AND ablauf < ?', (jetzt(),)).fetchall():
        datei_entfernen(r['id'])
    c.execute('DELETE FROM sitzungen WHERE gueltig_bis < ?', (jetzt(),))
    c.execute('DELETE FROM vorgaenge WHERE gueltig_bis < ?', (jetzt(),))
    c.execute('DELETE FROM benutzer WHERE aktiv = 0 AND erstellt < ?', (jetzt() - 86400,))
    c.execute('DELETE FROM protokoll WHERE zeit < ?', (jetzt() - 30 * 86400,))
    tmp = os.path.join(db.DATEN, 'tmp')
    for n in os.listdir(tmp):                # abgebrochene Uploads
        p = os.path.join(tmp, n)
        if os.path.getmtime(p) < time.time() - 3600:
            os.remove(p)


def hintergrund():
    letzte_sicherung = 0
    while True:
        try:
            aufraeumen()
            if time.time() - letzte_sicherung > 6 * 3600:
                db.sichern()
                letzte_sicherung = time.time()
        except Exception as e:   # noqa: BLE001
            print(f'hintergrund-fehler {type(e).__name__}: {e}', flush=True)
        time.sleep(300)


# ---------------------------------------------------------------- Seiten
SEITEN = {'/': 'index.html', '/app': 'app.html', '/admin': 'admin.html'}


@app.get('/d/{i}')
def download_seite(i: str):
    return FileResponse(os.path.join(WEB, 'd.html'), media_type='text/html')


for pfad, datei in SEITEN.items():
    app.add_api_route(pfad, (lambda d=datei: FileResponse(os.path.join(WEB, d), media_type='text/html')), methods=['GET'])

if os.path.isdir(WEB):
    app.mount('/', StaticFiles(directory=WEB, html=False), name='web')
