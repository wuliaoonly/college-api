from contextlib import contextmanager
import sqlite3

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'student',
 status TEXT NOT NULL DEFAULT 'active', created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS invites(
 id INTEGER PRIMARY KEY AUTOINCREMENT, code_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL,
 max_uses INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0, expires_at INTEGER,
 enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);
-- Additive ownership table preserves compatibility with existing invitation
-- rows and older releases. No account, balance, or key records are migrated.
CREATE TABLE IF NOT EXISTS invite_creators(
 invite_id INTEGER PRIMARY KEY REFERENCES invites(id),
 user_id INTEGER NOT NULL REFERENCES users(id));
CREATE INDEX IF NOT EXISTS invite_creator_user ON invite_creators(user_id);
CREATE TABLE IF NOT EXISTS providers(
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
 base_url TEXT NOT NULL, models_url TEXT NOT NULL, model TEXT NOT NULL,
 protocol TEXT NOT NULL DEFAULT 'anthropic', capabilities TEXT NOT NULL DEFAULT '{}',
 enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS api_keys(
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id INTEGER NOT NULL REFERENCES providers(id),
 fingerprint TEXT NOT NULL UNIQUE, ciphertext TEXT NOT NULL, masked TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'available', owner_id INTEGER REFERENCES users(id),
 imported_at INTEGER NOT NULL, assigned_at INTEGER, expires_at INTEGER, revoked_at INTEGER,
 last_verification TEXT, verified_at INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_key_per_user ON api_keys(owner_id)
 WHERE status IN ('assigned','pending_revocation');
CREATE TABLE IF NOT EXISTS sessions(
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tickets(
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 key_id INTEGER NOT NULL REFERENCES api_keys(id), expires_at INTEGER NOT NULL,
 consumed_at INTEGER, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), gross_fen INTEGER NOT NULL,
 fee_fen INTEGER NOT NULL, net_fen INTEGER NOT NULL, method TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending_payment', created_at INTEGER NOT NULL,
 reviewed_at INTEGER, reviewed_by INTEGER REFERENCES users(id), note TEXT NOT NULL DEFAULT '',
 policy_accepted INTEGER NOT NULL CHECK(policy_accepted=1));
CREATE TABLE IF NOT EXISTS ledger(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 order_id TEXT UNIQUE REFERENCES orders(id), type TEXT NOT NULL, amount_fen INTEGER NOT NULL,
 source_id INTEGER UNIQUE, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS usage_entries(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 key_id INTEGER NOT NULL REFERENCES api_keys(id), amount_fen INTEGER NOT NULL CHECK(amount_fen>=0),
 model TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
 period_start INTEGER NOT NULL, period_end INTEGER NOT NULL,
 checked_at INTEGER NOT NULL, checked_by INTEGER NOT NULL REFERENCES users(id), reference TEXT NOT NULL UNIQUE,
 voided INTEGER NOT NULL DEFAULT 0,
 CHECK(period_end>period_start));
CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS announcements(
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL,
 published INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audits(
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL,
 target TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
INSERT OR IGNORE INTO schema_versions VALUES(1);
'''


class Database:
    def __init__(self, path):
        self.path = path

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        return conn

    def initialize(self):
        conn = self.connect()
        try:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_versions'").fetchone()
            if exists and (conn.execute('SELECT MAX(version) FROM schema_versions').fetchone()[0] or 0) > 1:
                raise RuntimeError('Database schema is newer than this application; preserve data and use the matching release')
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def one(self, sql, args=()):
        conn = self.connect()
        try:
            return conn.execute(sql, args).fetchone()
        finally:
            conn.close()

    def all(self, sql, args=()):
        conn = self.connect()
        try:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()

