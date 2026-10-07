"""Restore a verified snapshot into an empty, explicitly named target. Never delete live data."""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal.security import private_file


def restore_data(snapshot, target):
    source, destination = Path(snapshot).resolve(), Path(target).resolve()
    if source == destination or source in destination.parents:
        raise ValueError('Choose a separate restore directory')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Restore target must be empty; stop the service and preserve existing data separately')
    manifest = json.loads((source / 'manifest.json').read_text())
    files = manifest['files']
    if not {'portal.db','encryption.key'} <= set(files):
        raise ValueError('Incomplete snapshot')
    for name, expected in files.items():
        if name not in ('portal.db','encryption.key') and not re.fullmatch(r'media/[a-f0-9]{32}\.(png|jpg)',name):
            raise ValueError('Unsafe snapshot file path')
        path = source / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Snapshot checksum mismatch')
    destination.mkdir(parents=True, exist_ok=True)
    for name in files:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, path)
        private_file(path)
    conn = sqlite3.connect(destination / 'portal.db')
    try:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Restored database integrity check failed')
    finally:
        conn.close()
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot')
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    print(restore_data(args.snapshot,args.target))


if __name__ == '__main__':
    main()
