"""Isolated local browser test server. Never reads/writes live application data."""
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from portal.config import Config, ROOT
from portal.main import create_app

cfg = Config(data_dir=ROOT / 'artifacts' / ('e2e-data-' + uuid4().hex),
             public_origin='http://127.0.0.1:5174', production=False,
             admin_password='fixture-admin-password-long', encryption_key='')
if __name__ == '__main__':
    uvicorn.run(create_app(cfg), host='127.0.0.1',port=8001,access_log=False)
