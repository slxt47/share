"""E-Mail-Versand (Codes, Speicher-Anfragen) über SMTP mit STARTTLS. Im Testmodus landen Mails nur im Speicher."""
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

TEST = os.environ.get('SHARE_TEST') == '1'
POSTEINGANG_TEST = []          # nur im Testmodus: (an, betreff, text)
_lock = threading.Lock()


def senden(an, betreff, text):
    if TEST:
        with _lock:
            POSTEINGANG_TEST.append((an, betreff, text))
        return
    m = EmailMessage()
    m['From'] = formataddr(('slxt share', os.environ['SMTP_FROM']))
    m['To'] = an
    m['Subject'] = betreff
    m['Message-ID'] = make_msgid(domain=os.environ['SMTP_FROM'].split('@')[-1])
    m.set_content(text + '\n\n– slxt share · https://share.slxt.dev\nDiese Nachricht wurde automatisch verschickt.\n')
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '587')), timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(os.environ['SMTP_USER'], os.environ['SMTP_PASS'])
        s.send_message(m)


def code_mail(an, code, zweck):
    texte = {
        'registrieren': ('Dein Bestätigungscode', 'mit diesem Code bestätigst du deine E-Mail-Adresse für slxt share'),
        'anmelden': ('Dein Anmeldecode', 'mit diesem Code meldest du dich bei slxt share an'),
        'passwort': ('Code zum Zurücksetzen', 'mit diesem Code setzt du dein Passwort bei slxt share zurück'),
    }
    betreff, satz = texte[zweck]
    senden(an, f'{code} – {betreff}', f'Hallo,\n\n{satz}:\n\n    {code}\n\nDer Code gilt 10 Minuten. '
           'Wenn du das nicht warst, kannst du diese Mail ignorieren – ohne den Code passiert nichts.')
