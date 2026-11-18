#!/usr/bin/env python3
"""Cloudflare für slxt share einrichten (einmalig, idempotent): eigener Tunnel „share“ (remote verwaltet),
Route  HOSTNAME → http://app:8080, DNS-CNAME (proxied), Tunnel-Token → ./.env (0600, wird nie ausgegeben).
Aufruf:  python3 cloudflare-einrichten.py <hostname> [--env <datei>]
Zugangsdaten: CF_API_TOKEN und CF_ACCOUNT_ID aus der Umgebung oder aus einer env-Datei (Standard ./cloudflare.env,
steht in .gitignore). Token-Rechte: Account › Cloudflare Tunnel › Edit, Zone › DNS › Edit, Zone › Zone Settings › Read.
"""
import json, os, re, sys, urllib.error, urllib.request

args = [a for a in sys.argv[1:]]
ENV_DATEI = args[args.index('--env') + 1] if '--env' in args else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cloudflare.env')
if '--env' in args:
    del args[args.index('--env'):args.index('--env') + 2]
if len(args) != 1:
    sys.exit('Aufruf: python3 cloudflare-einrichten.py <hostname> [--env <datei>]')
HOST = args[0]
TUNNEL = 'share'
HIER = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ)
if os.path.exists(ENV_DATEI):
    env.update(re.findall(r'^(\w+)="?([^"\n]*)"?', open(ENV_DATEI).read(), re.M))
if not env.get('CF_API_TOKEN') or not env.get('CF_ACCOUNT_ID'):
    sys.exit(f'CF_API_TOKEN / CF_ACCOUNT_ID fehlen (Umgebung oder {ENV_DATEI})')
TOK, ACC = env['CF_API_TOKEN'], env['CF_ACCOUNT_ID']


def cf(method, path, body=None):
    req = urllib.request.Request('https://api.cloudflare.com/client/v4' + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': 'Bearer ' + TOK, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        d = json.load(e)
    if not d.get('success'):
        sys.exit(f'Cloudflare-Fehler bei {method} {path.split("?")[0]}: {d.get("errors")}')
    return d['result']


# 1) Zone finden
zone = next((z for z in cf('GET', '/zones?per_page=50') if HOST == z['name'] or HOST.endswith('.' + z['name'])), None)
if not zone:
    sys.exit(f'Keine Zone für {HOST} im Konto')
print(f'Zone: {zone["name"]}')

# 2) DNS-Eintrag darf noch nicht anderweitig belegt sein
dns = cf('GET', f'/zones/{zone["id"]}/dns_records?name={HOST}')

# 3) Tunnel anlegen oder vorhandenen nehmen
t = next((t for t in cf('GET', f'/accounts/{ACC}/cfd_tunnel?is_deleted=false&name={TUNNEL}')), None)
if not t:
    t = cf('POST', f'/accounts/{ACC}/cfd_tunnel', {'name': TUNNEL, 'config_src': 'cloudflare'})
    print(f'Tunnel angelegt: {TUNNEL} ({t["id"]})')
else:
    print(f'Tunnel vorhanden: {TUNNEL} ({t["id"]})')
ziel = f'{t["id"]}.cfargotunnel.com'
fremd = [d for d in dns if not (d['type'] == 'CNAME' and d['content'] == ziel)]
if fremd:
    sys.exit(f'{HOST} ist schon belegt ({fremd[0]["type"]} → {fremd[0]["content"]}) – nichts geändert')

# 4) Route (Ingress) setzen
cf('PUT', f'/accounts/{ACC}/cfd_tunnel/{t["id"]}/configurations', {'config': {'ingress': [
    {'hostname': HOST, 'service': 'http://app:8080'},
    {'service': 'http_status:404'}]}})
print(f'Route: {HOST} → http://app:8080')

# 5) DNS
if not dns:
    cf('POST', f'/zones/{zone["id"]}/dns_records', {'type': 'CNAME', 'name': HOST, 'content': ziel, 'proxied': True,
                                                    'comment': 'slxt share (Tunnel share)'})
    print(f'DNS: {HOST} CNAME → {ziel} (proxied)')
else:
    print('DNS: schon vorhanden')

# 6) Token → .env (0600, gehört dem Projekt-Benutzer), nie ausgeben
token = cf('GET', f'/accounts/{ACC}/cfd_tunnel/{t["id"]}/token')
pfad = os.path.join(HIER, '.env')
# nur die Zeile TUNNEL_TOKEN ersetzen/ergänzen (.env gehört cloudflared; App-Einstellungen stehen in app.env)
alt = open(pfad).read().splitlines() if os.path.exists(pfad) else []
neu = [z for z in alt if not z.startswith('TUNNEL_TOKEN=')] + ['TUNNEL_TOKEN=' + token]
fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('\n'.join(neu) + '\n')
st = os.stat(HIER)
os.chown(pfad, st.st_uid, st.st_gid)
os.chmod(pfad, 0o600)
print(f'Token gespeichert in {pfad} (0600)')

# 7) Zonen-Einstellungen nur anzeigen (gelten für die ganze Zone – hier nichts ändern)
for s in ('rocket_loader', 'email_obfuscation', 'always_use_https', 'automatic_https_rewrites'):
    print(f'  Zone {s}: {cf("GET", f"/zones/{zone["id"]}/settings/{s}")["value"]}')
