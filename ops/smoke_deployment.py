"""Verify a deployed portal locally; keep credentials and session values out of output."""
import argparse
import time
import io
import json
import re
import zipfile
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--base')
    args = parser.parse_args()
    env = dotenv_values(args.env)
    origin = env['PUBLIC_ORIGIN'].rstrip('/')
    from urllib.parse import urlparse
    parsed = urlparse(origin)
    base = args.base or (origin if parsed.scheme == 'https' else 'http://127.0.0.1')
    with httpx.Client(base_url=base, headers={'Host': parsed.netloc, 'Origin': origin}, timeout=10) as client:
        # systemd reports a simple service started before uvicorn has bound its
        # socket; allow startup time without mistaking it for a failed release.
        for attempt in range(15):
            try:
                health = client.get('/portal-api/health')
                if health.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Portal did not become healthy within the startup window')
        assert health.json()['model_traffic'] == 'direct_to_provider'
        page = client.get('/login')
        assert page.status_code == 200 and '<html' in page.text
        assert page.headers.get('x-content-type-options') == 'nosniff'
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"',page.text)
        assert assets, 'Built frontend assets missing from page'
        for path in assets:
            asset = client.get(path)
            assert asset.status_code == 200 and not asset.text.lstrip().startswith('<'), 'Frontend asset unavailable: ' + path
            content_type = asset.headers.get('content-type','')
            assert ('javascript' in content_type if path.endswith('.js') else 'text/css' in content_type), 'Incorrect frontend asset type: ' + path
        assert client.post('/v1/messages', json={}).status_code == 404
        assert client.get('/portal-api/admin/keys').status_code == 401
        login = client.post('/portal-api/auth/login', json={'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']})
        assert login.status_code == 200, 'Administrator login failed'
        csrf = login.json()['csrf']
        assert 'httponly' in login.headers['set-cookie'].lower()
        client.headers['x-csrf-token'] = csrf
        try:
            assert client.get('/portal-api/me').json()['role'] == 'admin'
            for section in ('keys', 'users', 'orders', 'usage', 'invites', 'providers', 'audits'):
                response = client.get('/portal-api/admin/' + section)
                assert response.status_code == 200, 'Admin section failed: ' + section
            if parsed.scheme == 'https' or parsed.hostname in ('localhost', '127.0.0.1', '::1'):
                package = client.post('/portal-api/installer/package', json={'clients':['deepseek-harness']})
                assert package.status_code == 200, 'Administrator software download failed'
                with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
                    selection = json.loads(archive.read('selection.json'))
                    assert selection['clients'] == ['deepseek-harness']
                    assert 'Harness.Launch.ps1' in archive.namelist()
                    if not selection['configuration_available']:
                        assert 'ticket.json' not in archive.namelist(), 'Keyless package must not contain a ticket'
            assert client.post('/portal-api/auth/logout', headers={'x-csrf-token': 'invalid'}).status_code == 403
            assert client.post('/portal-api/auth/logout', headers={'Origin': 'https://invalid.example'}).status_code == 403
            if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
                result = client.post('/portal-api/admin/keys/import', json={'provider_id': 1, 'keys': ['sk-deployment-smoke-test-placeholder']})
                assert result.status_code == 503, 'Insecure key delivery must be disabled'
                print('HTTP validation mode: secret import remains disabled.')
        finally:
            assert client.post('/portal-api/auth/logout').status_code == 200
        assert client.get('/portal-api/me').status_code == 401
    print('Passed: health, web, administrator login, access isolation, CSRF, origin checks, and direct model traffic.')


if __name__ == '__main__':
    main()
