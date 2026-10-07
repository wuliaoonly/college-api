"""SQLite online backup plus media and matching encryption key; no credentials in output."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal.security import private_file


def backup_data(data_dir, output_dir, supplied_key=None):
    data = Path(data_dir).resolve()
    output = Path(output_dir).resolve()
    if not (data / 'portal.db').is_file():
        raise ValueError('Database not found')
    if output == data or data in output.parents:
        raise ValueError('Backup must be outside the live data directory')
    snapshot = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    snapshot.mkdir(parents=True)
    if os.name != 'nt':
        os.chmod(snapshot, 0o700)
    source = sqlite3.connect(data / 'portal.db')
    destination = sqlite3.connect(snapshot / 'portal.db')
    try:
        source.backup(destination)
        assert destination.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        destination.close()
        source.close()
    if supplied_key:
        (snapshot / 'encryption.key').write_text(supplied_key, encoding='ascii')
    elif (data / 'encryption.key').is_file():
        shutil.copyfile(data / 'encryption.key', snapshot / 'encryption.key')
    else:
        raise ValueError('Matching encryption key required; supply ENCRYPTION_KEY in the environment')
    # Media are immutable and retained. Copy after the DB snapshot to include all referenced images.
    if (data / 'media').exists():
        shutil.copytree(data / 'media', snapshot / 'media')
    entries = {}
    for path in snapshot.rglob('*'):
        if path.is_file():
            private_file(path)
            entries[path.relative_to(snapshot).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (snapshot / 'manifest.json').write_text(json.dumps({'schema':1,'files':entries}, indent=2), encoding='utf-8')
    private_file(snapshot / 'manifest.json')
    return snapshot


def main():
    from dotenv import load_dotenv
    if os.getenv('APP_ENV') != 'production':
        load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=os.getenv('DATA_DIR','data'))
    parser.add_argument('--out', default='backups')
    args = parser.parse_args()
    print(backup_data(args.data, args.out, os.getenv('ENCRYPTION_KEY')))


if __name__ == '__main__':
    main()
