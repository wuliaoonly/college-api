"""Create local secrets once, without printing them or replacing existing settings."""
import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
from portal.security import private_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', default='http://127.0.0.1:5173')
    parser.add_argument('--production', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / '.env'
    if target.exists():
        print('Existing .env retained; no secrets changed.')
        return
    target.write_text('\n'.join([
        'APP_ENV=' + ('production' if args.production else 'development'),
        'PUBLIC_ORIGIN=' + args.origin.rstrip('/'), 'SITE_ADDRESS=' + args.origin,
        'DATA_DIR=./data', 'ADMIN_USERNAME=admin',
        'ADMIN_PASSWORD=' + secrets.token_urlsafe(24),
        'ENCRYPTION_KEY=' + Fernet.generate_key().decode(),
        'PROVIDER_ALLOWED_HOSTS=api.deepseek.com', ''
    ]), encoding='utf-8')
    private_file(target)
    print('Created .env. Read the admin password in this local file; it is not printed or logged.')


if __name__ == '__main__':
    main()
