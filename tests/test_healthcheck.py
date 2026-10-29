from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from deploy.healthcheck import check, read_config

class HealthTests(unittest.TestCase):
    def test_reads_custom_audit_path_without_credentials(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'config.env'
            path.write_text('QUOTA_PASSWORD_HASH=secret\nQUOTA_BIND=127.0.0.1\nQUOTA_PORT=8790\nQUOTA_AUDIT_DB="/srv/panel/audit.db"\n')
            result=read_config(path)
        self.assertEqual(result,{'host':'127.0.0.1','port':8790,'audit':'/srv/panel/audit.db'})
    def test_requires_panel_authentication_challenge(self):
        connection=Mock(); connection.getresponse.return_value=SimpleNamespace(status=401,getheader=lambda key,default='':'Basic realm="Carbonio cuotas", charset="UTF-8"')
        with patch('deploy.healthcheck.http.client.HTTPConnection',return_value=connection):
            check('127.0.0.1',8787,attempts=1)
        connection.close.assert_called_once()
    def test_wrong_service_is_not_ready(self):
        connection=Mock(); connection.getresponse.return_value=SimpleNamespace(status=200,getheader=lambda *args:'')
        with patch('deploy.healthcheck.http.client.HTTPConnection',return_value=connection):
            with self.assertRaises(RuntimeError): check('127.0.0.1',8787,attempts=1)
