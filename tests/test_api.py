"""API-Tests für slxt share (pytest, ohne Browser). Mails landen im Testmodus nur im Speicher."""
import os
import re
import secrets
import tempfile

os.environ.update(SHARE_TEST='1', SHARE_COOKIE='share', SHARE_COOKIE_SECURE='0', SHARE_ADMIN_MAILS='chef@example.org',
                  SHARE_ADMIN_MAIL='admin@example.org', SHARE_DATEN=tempfile.mkdtemp(), SHARE_GEHEIM='x' * 64)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main, mail  # noqa: E402

H = {'X-Share': '1'}


def neu_client(ip='1.2.3.4'):
    return TestClient(main.app, headers={**H, 'CF-Connecting-IP': ip})


@pytest.fixture(autouse=True)
def frisch():
    main.grenze.d.clear()
    mail.POSTEINGANG_TEST.clear()
    yield


def code_fuer(email):
    for an, _, text in reversed(mail.POSTEINGANG_TEST):
        if an == email:
            return re.search(r'\b(\d{6})\b', text).group(1)
    raise AssertionError('keine Mail')


def warte_mail(email):
    import time
    for _ in range(50):
        if any(a == email for a, _, _ in mail.POSTEINGANG_TEST):
            return code_fuer(email)
        time.sleep(0.02)
    raise AssertionError('keine Mail angekommen')


def konto(c, name=None, email=None):
    name = name or 'u' + secrets.token_hex(4)
    email = email or f'{name}@example.org'
    auth = secrets.token_hex(32)
    r = c.post('/api/registrieren', json={'benutzer': name, 'email': email, 'salz': secrets.token_hex(16), 'auth': auth})
    assert r.status_code == 200, r.text
    r = c.post('/api/registrieren/bestaetigen', json={'vorgang': r.json()['vorgang'], 'code': warte_mail(email)})
    assert r.status_code == 200, r.text
    return name, email, auth


def hochladen(c, n, ablauf='7'):
    return c.post(f'/api/dateien?ablauf={ablauf}', content=os.urandom(n),
                  headers={'X-Meta': 'bWV0YWRhdGVuLXZlcnNjaGx1ZXNzZWx0', 'X-Schluessel': 'c2NobHVlc3NlbC12ZXJwYWNrdA=='})


def test_registrieren_und_anmelden_mit_email_code():
    c = neu_client()
    name, email, auth = konto(c)
    assert c.get('/api/ich').json()['benutzer'] == name
    c.post('/api/abmelden')
    assert c.get('/api/ich').status_code == 401
    # Anmeldung: Passwort allein reicht nicht – erst der Code aus der Mail
    r = c.post('/api/anmelden', json={'benutzer': name, 'auth': auth})
    assert r.status_code == 200 and '•••' in r.json()['email']
    assert c.get('/api/ich').status_code == 401
    r = c.post('/api/anmelden/code', json={'vorgang': r.json()['vorgang'], 'code': warte_mail(email)})
    assert r.status_code == 200
    assert c.get('/api/ich').json()['benutzer'] == name


def test_falsches_passwort_und_falsche_codes():
    c = neu_client('2.2.2.2')
    name, email, auth = konto(c)
    c.post('/api/abmelden')
    assert c.post('/api/anmelden', json={'benutzer': name, 'auth': secrets.token_hex(32)}).status_code == 400
    v = c.post('/api/anmelden', json={'benutzer': name, 'auth': auth}).json()['vorgang']
    richtig = warte_mail(email)
    falsch = f'{(int(richtig) + 1) % 1_000_000:06d}'
    for _ in range(5):
        assert c.post('/api/anmelden/code', json={'vorgang': v, 'code': falsch}).status_code == 400
    # nach 5 Fehlversuchen ist der Vorgang verbrannt – auch der richtige Code geht nicht mehr
    assert c.post('/api/anmelden/code', json={'vorgang': v, 'code': richtig}).status_code == 400
    assert c.get('/api/ich').status_code == 401


def test_unbekannter_name_verraet_nichts():
    c = neu_client('3.3.3.3')
    a = c.get('/api/salz', params={'benutzer': 'gibtsnicht1'}).json()['salz']
    b = c.get('/api/salz', params={'benutzer': 'gibtsnicht1'}).json()['salz']
    assert a == b and len(a) == 32                     # stabiles Schein-Salz
    r = c.post('/api/passwort/vergessen', json={'benutzer': 'gibtsnicht1', 'salz': secrets.token_hex(16), 'auth': secrets.token_hex(32)})
    assert r.status_code == 200 and r.json()['vorgang']


def test_doppelte_namen_und_mails():
    c = neu_client('4.4.4.4')
    name, email, _ = konto(c)
    r = c.post('/api/registrieren', json={'benutzer': name, 'email': 'x' + email, 'salz': secrets.token_hex(16), 'auth': secrets.token_hex(32)})
    assert r.status_code == 409


def test_grenze_10_mb_und_1_gb():
    c = neu_client('5.5.5.5')
    konto(c)
    assert hochladen(c, 10 * 1024 * 1024 + 28).status_code == 200            # genau 10 MB Klartext + IV + Tag
    assert hochladen(c, 10 * 1024 * 1024 + 29).status_code == 413            # 1 Byte zu viel
    # Kontingent: künstlich auf 25 MB senken, dann ist nach 2 weiteren Dateien Schluss
    main.db.verbindung().execute('UPDATE benutzer SET kontingent = ? WHERE name = ?', (25 * 1024 * 1024, c.get('/api/ich').json()['benutzer']))
    assert hochladen(c, 10 * 1024 * 1024).status_code == 200
    assert hochladen(c, 10 * 1024 * 1024).status_code == 507
    ich = c.get('/api/ich').json()
    assert ich['belegt'] <= ich['kontingent']


def test_standard_kontingent_ist_1_gb():
    c = neu_client('6.6.6.6')
    konto(c)
    assert c.get('/api/ich').json()['kontingent'] == 1024 ** 3


def test_teilen_ohne_konto_und_nur_eigene_dateien_loeschen():
    a, b, gast = neu_client('7.7.7.1'), neu_client('7.7.7.2'), neu_client('7.7.7.3')
    konto(a); konto(b)
    inhalt = os.urandom(5000)
    r = a.post('/api/dateien?ablauf=1', content=inhalt, headers={'X-Meta': 'bWV0YWRhdGVuLXZlcnNjaGx1ZXNzZWx0', 'X-Schluessel': 'c2NobHVlc3NlbC12ZXJwYWNrdA=='})
    i = r.json()['id']
    assert len(i) == 22
    assert gast.get(f'/api/teilen/{i}').json()['groesse'] == 5000          # Empfänger braucht kein Konto
    assert gast.get(f'/api/teilen/{i}/daten').content == inhalt
    assert b.delete(f'/api/dateien/{i}').status_code == 404               # fremde Datei: nicht löschbar
    assert i not in [d['id'] for d in b.get('/api/dateien').json()['dateien']]
    assert a.delete(f'/api/dateien/{i}').status_code == 200
    assert gast.get(f'/api/teilen/{i}').status_code == 404


def test_abgelaufene_freigabe_ist_weg():
    c = neu_client('8.8.8.8')
    konto(c)
    i = hochladen(c, 100, ablauf='1').json()['id']
    main.db.verbindung().execute('UPDATE dateien SET ablauf = 1 WHERE id = ?', (i,))
    assert c.get(f'/api/teilen/{i}').status_code == 404
    main.aufraeumen()
    assert not os.path.exists(main.datei_pfad(i))


def test_csrf_ohne_header_abgelehnt():
    c = TestClient(main.app)
    assert c.post('/api/anmelden', json={}).status_code == 403


def test_sicherheits_header():
    r = neu_client().get('/api/gesund')
    assert "default-src 'self'" in r.headers['content-security-policy']
    assert r.headers['referrer-policy'] == 'no-referrer'
    assert r.headers['cache-control'] == 'no-store'


def test_admin_kontingent_und_anfrage():
    chef, nutzer = neu_client('9.9.9.1'), neu_client('9.9.9.2')
    konto(chef, name='chef')
    # gleicher Name wie ein Admin reicht NICHT – nur die bestätigte Admin-Mail zählt
    falsch = neu_client('9.9.9.3'); konto(falsch, name='chef2', email='nicht-chef@example.org')
    assert falsch.get('/api/admin/benutzer').status_code == 403
    name, _, _ = konto(nutzer)
    assert nutzer.get('/api/admin/benutzer').status_code == 403
    assert nutzer.post('/api/speicher-anfragen', json={'gb': 5, 'nachricht': 'Fotos'}).status_code == 200
    assert nutzer.post('/api/speicher-anfragen', json={'gb': 5}).status_code == 429     # einmal am Tag
    liste = chef.get('/api/admin/benutzer').json()['benutzer']
    bid = next(b['id'] for b in liste if b['name'] == name)
    assert chef.post(f'/api/admin/benutzer/{bid}', json={'kontingent_gb': 6}).status_code == 200
    assert nutzer.get('/api/ich').json()['kontingent'] == 6 * 1024 ** 3


def test_konto_loeschen_entfernt_dateien():
    c = neu_client('10.0.0.9')
    _, _, auth = konto(c)
    i = hochladen(c, 1000).json()['id']
    assert c.post('/api/konto/loeschen', json={'auth': auth}).status_code == 200
    assert not os.path.exists(main.datei_pfad(i))
    assert neu_client().get(f'/api/teilen/{i}').status_code == 404


def test_zu_viele_anmeldeversuche():
    c = neu_client('11.11.11.11')
    codes = [c.post('/api/anmelden', json={'benutzer': 'niemand', 'auth': secrets.token_hex(32)}).status_code for _ in range(12)]
    assert 429 in codes
