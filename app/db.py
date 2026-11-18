"""SQLite-Datenbank für slxt share. WAL-Modus, eine Verbindung pro Thread, Schema per Version."""
import os
import sqlite3
import threading
import time

DATEN = os.environ.get('SHARE_DATEN', '/daten')
DB = os.path.join(DATEN, 'share.sqlite3')
_lokal = threading.local()

SCHEMA = [
    # Version 1
    """
    CREATE TABLE benutzer (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL UNIQUE COLLATE NOCASE,
      email TEXT NOT NULL UNIQUE COLLATE NOCASE,
      salz TEXT NOT NULL,              -- PBKDF2-Salz des Browsers (hex), nicht geheim
      auth_hash TEXT NOT NULL,         -- argon2(Anmeldeschlüssel); der Server sieht nie das Passwort
      aktiv INTEGER NOT NULL DEFAULT 0,
      gesperrt INTEGER NOT NULL DEFAULT 0,
      kontingent INTEGER NOT NULL,     -- Bytes
      erstellt INTEGER NOT NULL,
      letzte_anfrage INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE vorgaenge (            -- laufende E-Mail-Code-Prüfungen (Registrierung, Anmeldung, Passwort)
      token_hash TEXT PRIMARY KEY,
      benutzer_id INTEGER NOT NULL REFERENCES benutzer(id) ON DELETE CASCADE,
      art TEXT NOT NULL,               -- registrieren | anmelden | passwort
      code_hash TEXT NOT NULL,
      versuche INTEGER NOT NULL DEFAULT 0,
      gueltig_bis INTEGER NOT NULL,
      daten TEXT NOT NULL DEFAULT ''   -- z. B. neues Salz/Hash beim Passwort-Zurücksetzen
    );
    CREATE TABLE sitzungen (
      token_hash TEXT PRIMARY KEY,
      benutzer_id INTEGER NOT NULL REFERENCES benutzer(id) ON DELETE CASCADE,
      erstellt INTEGER NOT NULL,
      gueltig_bis INTEGER NOT NULL
    );
    CREATE TABLE dateien (
      id TEXT PRIMARY KEY,             -- 128 Bit zufällig (base64url), Teil des Links
      benutzer_id INTEGER NOT NULL REFERENCES benutzer(id) ON DELETE CASCADE,
      groesse INTEGER NOT NULL,        -- Bytes Geheimtext (zählt fürs Kontingent)
      meta TEXT NOT NULL,              -- verschlüsselt (Name, Typ, Größe) – Server kann es nicht lesen
      schluessel TEXT NOT NULL,        -- Dateischlüssel, verschlüsselt mit dem Tresor-Schlüssel des Besitzers
      erstellt INTEGER NOT NULL,
      ablauf INTEGER,                  -- Unix-Zeit oder NULL = unbegrenzt
      downloads INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX dateien_benutzer ON dateien(benutzer_id);
    CREATE INDEX dateien_ablauf ON dateien(ablauf);
    CREATE TABLE protokoll (            -- Sicherheitsereignisse ohne Inhalte, 30 Tage
      zeit INTEGER NOT NULL, benutzer_id INTEGER, ereignis TEXT NOT NULL
    );
    """,
]


def verbindung():
    c = getattr(_lokal, 'c', None)
    if c is None:
        c = sqlite3.connect(DB, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=5000')
        _lokal.c = c
    return c


def einrichten():
    os.makedirs(os.path.join(DATEN, 'dateien'), exist_ok=True)
    os.makedirs(os.path.join(DATEN, 'tmp'), exist_ok=True)
    os.makedirs(os.path.join(DATEN, 'sicherung'), exist_ok=True)
    c = verbindung()
    c.execute('CREATE TABLE IF NOT EXISTS schema_version (v INTEGER NOT NULL)')
    v = (c.execute('SELECT v FROM schema_version').fetchone() or [0])[0]
    if v == 0 and not c.execute('SELECT 1 FROM schema_version').fetchone():
        c.execute('INSERT INTO schema_version VALUES (0)')
    for nr, sql in enumerate(SCHEMA, start=1):
        if v < nr:
            c.executescript('BEGIN;' + sql + f'UPDATE schema_version SET v = {nr}; COMMIT;')


def protokollieren(ereignis, benutzer_id=None):
    verbindung().execute('INSERT INTO protokoll VALUES (?, ?, ?)', (int(time.time()), benutzer_id, ereignis[:200]))


def sichern():
    """Konsistente Kopie der Datenbank (für das nächtliche Server-Backup, das den Ordner per tar sichert)."""
    ziel = os.path.join(DATEN, 'sicherung', 'share.sqlite3')
    tmp = ziel + '.neu'
    b = sqlite3.connect(tmp)
    verbindung().backup(b)
    b.close()
    os.replace(tmp, ziel)
