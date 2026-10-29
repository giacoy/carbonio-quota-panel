import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from server import bridge

class DeploymentTests(unittest.TestCase):
    def test_service_allows_required_sudo_on_systemd_249(self):
        unit=(Path(__file__).resolve().parents[1]/'deploy/carbonio-quota-panel.service').read_text()
        active=[line.strip() for line in unit.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        self.assertNotIn('RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6',active)
        self.assertIn('NoNewPrivileges=false',active)
        self.assertIn('User=carbonio-quota',active)
        self.assertIn('ProtectSystem=full',active)
    def test_bridge_error_logs_stderr_without_dumping_stdout(self):
        failed=SimpleNamespace(returncode=1,stdout='private account data',stderr='sudo: The no new privileges flag is set')
        with patch('server.subprocess.run',return_value=failed):
            with self.assertLogs('server',level=logging.ERROR) as captured:
                with self.assertRaises(RuntimeError): bridge({'action':'snapshot'})
        output='\n'.join(captured.output)
        self.assertIn('no new privileges',output)
        self.assertNotIn('private account data',output)
