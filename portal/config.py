from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Production services receive secrets from their supervisor. The process does
# not need filesystem access to the root-owned deployment environment file.
if os.getenv('APP_ENV') != 'production':
    load_dotenv(ROOT / '.env')


@dataclass
class Config:
    data_dir: Path = Path(os.getenv('DATA_DIR', str(ROOT / 'data')))
    public_origin: str = os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:5173').rstrip('/')
    production: bool = os.getenv('APP_ENV', 'development') == 'production'
    admin_username: str = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password: str = os.getenv('ADMIN_PASSWORD', '')
    encryption_key: str = os.getenv('ENCRYPTION_KEY', '')
    provider_allowed_hosts: tuple = tuple(os.getenv('PROVIDER_ALLOWED_HOSTS', 'api.deepseek.com').split(','))
    secure_cookies: bool = os.getenv('PUBLIC_ORIGIN', '').startswith('https://')

