"""E-Mail-Versand (Codes, Speicher-Anfragen) über SMTP mit STARTTLS – im slxt-Design.

Jede Mail hat eine Textfassung und eine HTML-Fassung: tabellenbasiert, Styles inline (Gmail/Outlook), Logo als
eingebettetes Bild (cid:, nichts wird nachgeladen – keine Tracking-Pixel), dunkler Nachthimmel wie slxt.org,
helle Variante über prefers-color-scheme (Apple Mail, iOS). Im Testmodus landen Mails nur im Speicher.
"""
import html
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

TEST = os.environ.get('SHARE_TEST') == '1'
POSTEINGANG_TEST = []          # nur im Testmodus: (an, betreff, text, html)
_lock = threading.Lock()
LOGO = os.path.join(os.environ.get('SHARE_WEB', os.path.join(os.path.dirname(__file__), '..', 'web', 'dist')), 'icons', 'icon-192.png')
SEITE = 'https://share.slxt.dev'


def html_mail(titel, absaetze, code=None, knopf=None, hinweis=None, vorschau=''):
    """slxt-Design: Nachthimmel, Glaskarte, violetter Akzent, Systemschrift. Alles inline."""
    e = html.escape
    absatz_html = ''.join(f'<p style="margin:0 0 14px;font-size:16px;line-height:1.55;color:#c9cbe0" class="sec">{e(a)}</p>' for a in absaetze)
    code_html = ''
    if code:
        ziffern = ''.join(f'<span style="display:inline-block;margin:0 3px">{e(z)}</span>' for z in code)
        code_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 18px"><tr><td align="center" '
            'class="code" style="background:#211d4a;border:1px solid #4b3fa8;border-radius:16px;padding:20px 12px">'
            f'<div style="font:700 34px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:4px;color:#ffffff" class="codetext">{ziffern}</div>'
            '<div style="margin-top:10px;font-size:13px;color:#a993ff" class="akzent">gilt 10 Minuten</div></td></tr></table>')
    knopf_html = ''
    if knopf:
        text, url = knopf
        knopf_html = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:4px 0 18px"><tr><td style="border-radius:999px;background:#a993ff">'
                      f'<a href="{e(url)}" style="display:inline-block;padding:14px 26px;font-weight:700;font-size:16px;color:#0b0b10;text-decoration:none;border-radius:999px">{e(text)}</a></td></tr></table>')
    hinweis_html = f'<p style="margin:4px 0 0;font-size:13px;line-height:1.5;color:#8e90ad" class="leise">{e(hinweis)}</p>' if hinweis else ''
    return f'''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light"><meta name="supported-color-schemes" content="dark light"><title>{e(titel)}</title>
<style>
  @media (prefers-color-scheme: light) {{
    body, .koerper {{ background:#fde7da !important; }}
    .himmel {{ background:#efe3f8 !important; background-image:linear-gradient(180deg,#dfe5ff,#efe3f8 55%,#fde7da) !important; }}
    .karte {{ background:#ffffff !important; border-color:#e4def5 !important; }}
    .titel, .marke, .codetext {{ color:#1d1d1f !important; }}
    .sec {{ color:#54546a !important; }}
    .leise, .fuss, .fuss a {{ color:#6e6e85 !important; }}
    .fuss a.akzent {{ color:#5b3df5 !important; }}
    .code {{ background:#f1edff !important; border-color:#cfc4ff !important; }}
    .akzent {{ color:#5b3df5 !important; }}
  }}
  @media (max-width: 480px) {{ .karte {{ padding:24px 20px !important; }} .codetext {{ font-size:30px !important; }} }}
</style></head>
<body class="koerper" style="margin:0;padding:0;background:#0b0e2a">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{e(vorschau)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="himmel"
  style="background:#0b0e2a;background-image:linear-gradient(180deg,#04050d,#0b0e2a 55%,#1a1240)"><tr><td align="center" style="padding:36px 16px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">
    <tr><td style="padding:0 4px 18px">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="vertical-align:middle"><img src="cid:logo" width="36" height="36" alt="" style="display:block;border-radius:9px"></td>
        <td style="vertical-align:middle;padding-left:10px;font:700 19px/1 -apple-system,BlinkMacSystemFont,'SF Pro Rounded','Segoe UI',Roboto,sans-serif;color:#f2f2f7" class="marke">slxt share<span class="akzent" style="color:#a993ff">.</span></td>
      </tr></table>
    </td></tr>
    <tr><td class="karte" style="background:#17172e;border:1px solid #2c2b4d;border-radius:24px;padding:30px 28px;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif">
      <h1 class="titel" style="margin:0 0 14px;font:800 26px/1.15 -apple-system,BlinkMacSystemFont,'SF Pro Rounded','Segoe UI',Roboto,sans-serif;letter-spacing:-.3px;color:#f2f2f7">{e(titel)}<span class="akzent" style="color:#a993ff">.</span></h1>
      {absatz_html}{code_html}{knopf_html}{hinweis_html}
    </td></tr>
    <tr><td class="fuss" style="padding:20px 8px 0;text-align:center;font:13px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#8e90ad">
      Ende-zu-Ende verschlüsselt · ohne Werbung, ohne Tracking<br>
      <a href="{SEITE}" class="akzent" style="color:#a993ff;text-decoration:none">share.slxt.dev</a> ·
      <a href="https://slxt.org/impressum/" style="color:#8e90ad;text-decoration:none">Impressum</a> ·
      <a href="https://slxt.org/datenschutz/#share" style="color:#8e90ad;text-decoration:none">Datenschutz</a>
    </td></tr>
  </table>
</td></tr></table>
</body></html>'''


def senden(an, betreff, text, html_text=None):
    if TEST:
        with _lock:
            POSTEINGANG_TEST.append((an, betreff, text, html_text))
        return
    m = EmailMessage()
    m['From'] = formataddr(('slxt share', os.environ['SMTP_FROM']))
    m['To'] = an
    m['Subject'] = betreff
    m['Message-ID'] = make_msgid(domain=os.environ['SMTP_FROM'].split('@')[-1])
    m.set_content(text + f'\n\n– slxt share · {SEITE}\nDiese Nachricht wurde automatisch verschickt.\n')
    if html_text:
        m.add_alternative(html_text, subtype='html')
        if os.path.exists(LOGO):
            m.get_payload()[1].add_related(open(LOGO, 'rb').read(), 'image', 'png', cid='<logo>', filename='logo.png')
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '587')), timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(os.environ['SMTP_USER'], os.environ['SMTP_PASS'])
        s.send_message(m)


TEXTE = {
    'registrieren': ('Dein Bestätigungscode', 'Willkommen bei slxt share',
                     'Mit diesem Code bestätigst du deine E-Mail-Adresse. Danach ist dein Konto mit 1 GB Speicher bereit.'),
    'anmelden': ('Dein Anmeldecode', 'Dein Anmeldecode',
                 'Mit diesem Code meldest du dich bei slxt share an.'),
    'passwort': ('Code zum Zurücksetzen', 'Passwort zurücksetzen',
                 'Mit diesem Code setzt du dein Passwort zurück. Deine geteilten Links funktionieren danach weiter.'),
}


def code_mail(an, code, zweck):
    betreff, titel, satz = TEXTE[zweck]
    hinweis = 'Wenn du das nicht warst, kannst du diese Mail ignorieren – ohne den Code passiert nichts. Wir fragen dich nie nach deinem Passwort.'
    text = f'Hallo,\n\n{satz}\n\n    {code}\n\nDer Code gilt 10 Minuten.\n{hinweis}'
    senden(an, f'{code} – {betreff}', text, html_mail(titel, ['Hallo,', satz], code=code, hinweis=hinweis, vorschau=f'{code} · gilt 10 Minuten'))


def anfrage_mail(an, betreff, zeilen, nachricht):
    text = '\n'.join(zeilen) + f'\n\nNachricht:\n{nachricht or "–"}\n\nFreigeben: {SEITE}/admin'
    senden(an, betreff, text, html_mail('Mehr Speicher angefragt', zeilen + [f'Nachricht: {nachricht or "–"}'],
                                        knopf=('Im Admin-Bereich freigeben', f'{SEITE}/admin'), vorschau=zeilen[0]))
