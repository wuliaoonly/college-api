"""Import a private TXT through an in-process authenticated API, never HTTP.

Run on the server as the deployment owner. Production credentials are read
from the restricted environment file. Input and credentials are never printed.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from portal.config import Config
from portal.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    values = dotenv_values(args.env)
    keys = args.file.read_text(encoding='utf-8-sig').splitlines()
    app = create_app(Config(data_dir=args.data, public_origin='http://127.0.0.1', production=True,
                            admin_username=values['ADMIN_USERNAME'], admin_password=values['ADMIN_PASSWORD'],
                            encryption_key=values['ENCRYPTION_KEY']))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        response = client.post('/portal-api/auth/login', json={'username': values['ADMIN_USERNAME'], 'password': values['ADMIN_PASSWORD']})
        response.raise_for_status()
        headers = {'X-CSRF-Token': response.json()['csrf']}
        try:
            response = client.post('/portal-api/admin/keys/import', headers=headers, json={'keys': keys})
            response.raise_for_status()
            result = response.json()
            print('Imported:', result['imported'], 'Duplicates:', result['duplicates'])
            response = client.get('/portal-api/admin/keys')
            response.raise_for_status()
            print('Assigned:', sum(row['status'] == 'assigned' for row in response.json()))
            print('Available:', sum(row['status'] == 'available' for row in response.json()))
        finally:
            client.post('/portal-api/auth/logout', headers=headers).raise_for_status()


if __name__ == '__main__':
    main()
