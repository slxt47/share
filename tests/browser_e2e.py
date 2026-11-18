"""Browser-Durchlauf (Playwright/Chromium) gegen eine Test-Instanz (SHARE_TEST=1: Mails nur im Speicher, lesbar über
/api/test/posteingang). Prüft die ganze Kette und dass der Server nie Klartext sieht.

Aufruf: siehe README (Test-Instanz + Playwright-Image, BASIS=http://<ip>:8080).
"""
import hashlib, os, re, sys, time
from playwright.sync_api import sync_playwright

BASIS = os.environ.get('BASIS', 'http://127.0.0.1:8080')
fehler = []


def pruefe(bed, text):
    print(('  ✔ ' if bed else '  ✘ ') + text)
    if not bed:
        fehler.append(text)


def code_aus_mail(seite, email, alt=0):
    for _ in range(60):
        mails = [m for m in seite.request.get(BASIS + '/api/test/posteingang').json()['mails'] if m['an'] == email]
        if len(mails) > alt:
            return re.search(r'\b(\d{6})\b', mails[-1]['text']).group(1), len(mails)
        time.sleep(0.2)
    raise AssertionError('keine Mail')


ARGS = ['--disable-features=HttpsUpgrades', f'--unsafely-treat-insecure-origin-as-secure={BASIS}']

with sync_playwright() as p:
    b = p.chromium.launch(args=ARGS)
    k = b.new_context(accept_downloads=True)
    s = k.new_page()
    gesendet = []
    s.on('request', lambda r: gesendet.append((r.method, r.url, r.post_data_buffer or b'', r.headers)))

    name, email, pw = f'test{int(time.time()) % 100000}', f'test{int(time.time())}@example.org', 'Ein langes Passwort 123!'
    print('Registrieren:')
    s.goto(BASIS + '/')
    s.click('#tab-registrieren')
    s.fill('#f-registrieren [name=benutzer]', name)
    s.fill('#f-registrieren [name=email]', email)
    s.fill('#f-registrieren [name=passwort]', pw)
    s.click('#f-registrieren button[type=submit]')
    s.wait_for_selector('#f-code:not([hidden])', timeout=60000)
    code, n = code_aus_mail(s, email)
    s.fill('#f-code [name=code]', code)                       # 6 Ziffern → schickt automatisch ab
    s.wait_for_url('**/app', timeout=20000)
    s.wait_for_selector('#karte-hochladen:not([hidden])')
    pruefe(True, f'Konto „{name}“ angelegt und mit E-Mail-Code bestätigt')

    print('Hochladen:')
    original = os.urandom(3 * 1024 * 1024 + 7)
    dateiname = 'Geheimer Bericht 2026.pdf'
    with open('/tmp/' + dateiname, 'wb') as f:
        f.write(original)
    s.set_input_files('#datei', '/tmp/' + dateiname)
    s.wait_for_selector('#liste li .name', timeout=60000)
    pruefe(s.inner_text('#liste li .name') == dateiname, 'Datei erscheint mit Namen in „Meine Freigaben“')
    pruefe('MB von 1,00 GB' in s.inner_text('#speicher-text'), f'Speicheranzeige: {s.inner_text("#speicher-text")}')
    upload = [g for g in gesendet if g[0] == 'POST' and '/api/dateien' in g[1]][0]
    pruefe(original[:64] not in upload[2] and original[1000:1064] not in upload[2], 'Upload enthält den Dateiinhalt NICHT im Klartext')
    pruefe(all(dateiname.encode() not in g[2] and dateiname not in str(g[3]) and 'Geheimer' not in g[1] for g in gesendet),
           'Dateiname geht in keiner Anfrage an den Server')
    s.click('#liste li button:has-text("QR-Code")')
    link = s.inner_text('#qr-link')
    pruefe(re.fullmatch(re.escape(BASIS) + r'/d/[A-Za-z0-9_-]{22}#[A-Za-z0-9_-]{43}', link) is not None, 'Link mit Schlüssel im #-Teil, QR-Code angezeigt')
    s.click('#qr-schliessen')

    print('Empfänger ohne Konto:')
    k2 = b.new_context(accept_downloads=True)
    r = k2.new_page()
    anfragen2 = []
    r.on('request', lambda q: anfragen2.append(q.url))
    r.goto(link)
    r.wait_for_selector('#laden:not([disabled])', timeout=20000)
    pruefe(dateiname in r.inner_text('#info'), 'Name im Browser entschlüsselt angezeigt')
    with r.expect_download() as dl:
        r.click('#laden')
    pfad = '/tmp/empfangen.bin'
    dl.value.save_as(pfad)
    daten = open(pfad, 'rb').read()
    print(f'  SHA-256 Original : {hashlib.sha256(original).hexdigest()}')
    print(f'  SHA-256 Empfangen: {hashlib.sha256(daten).hexdigest()}')
    pruefe(daten == original, 'Download byte-identisch')
    pruefe(dl.value.suggested_filename == dateiname, f'Dateiname beim Speichern: {dl.value.suggested_filename}')
    pruefe(all('#' not in u for u in anfragen2), 'Schlüssel (#-Teil) in keiner Anfrage des Empfängers')
    pruefe(k2.cookies() == [], 'Empfänger: keine Cookies')

    print('Falsche Links:')
    r.goto(link.split('#')[0]); r.wait_for_timeout(800)
    pruefe('unvollständig' in r.inner_text('#info'), 'Link ohne Schlüssel → „Link unvollständig“, nichts geladen')
    falsch = link[:-5] + ('AAAAA' if not link.endswith('AAAAA') else 'BBBBB')
    r.goto(BASIS + '/'); r.goto(falsch); r.wait_for_timeout(1500)
    pruefe('passt nicht' in r.inner_text('#info') and r.is_disabled('#laden'), 'Falscher Schlüssel → nichts entschlüsselbar')

    print('Abmelden + Anmelden mit Code:')
    s.click('#kopf-rechts button:has-text("Abmelden")'); s.wait_for_url(BASIS + '/')
    s.fill('#f-anmelden [name=benutzer]', name); s.fill('#f-anmelden [name=passwort]', pw)
    s.click('#f-anmelden button[type=submit]')
    s.wait_for_selector('#f-code:not([hidden])', timeout=60000)
    code, n = code_aus_mail(s, email, n)
    s.fill('#f-code [name=code]', code)
    s.wait_for_url('**/app', timeout=20000)
    s.wait_for_selector('#liste li .name', timeout=20000)
    pruefe(s.inner_text('#liste li .name') == dateiname, 'Nach erneuter Anmeldung (2FA) ist die Datei wieder lesbar')

    print('Grenze 10 MB:')
    with open('/tmp/gross.bin', 'wb') as f:
        f.write(os.urandom(10 * 1024 * 1024 + 1))
    s.set_input_files('#datei', '/tmp/gross.bin'); s.wait_for_timeout(500)
    pruefe('größer als 10 MB' in s.inner_text('#status-upload'), 'Datei > 10 MB wird abgelehnt (vor dem Hochladen)')

    print('Löschen:')
    s.once('dialog', lambda d: d.accept())
    s.click('#liste li button:has-text("Löschen")'); s.wait_for_timeout(800)
    r.goto(BASIS + '/'); r.goto(link); r.wait_for_timeout(1000)
    pruefe('Nicht (mehr) verfügbar' in r.inner_text('#info'), 'Gelöschte Freigabe ist für den Empfänger weg')
    s.screenshot(path='/out/share-app.png', full_page=True)
    b.close()

print('\nERGEBNIS:', 'alles bestanden' if not fehler else f'{len(fehler)} Fehler: {fehler}')
sys.exit(1 if fehler else 0)
