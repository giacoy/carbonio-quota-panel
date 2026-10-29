import unittest
from unittest.mock import patch
from bridge import Carbonio

class BridgeSecurityTests(unittest.TestCase):
    def test_direct_change_rejects_remote_account_before_any_write(self):
        for quota in ['45','0',None]:
            calls=[]
            def run(*args):
                calls.append(args)
                return 'zimbraMailHost: remote.example.test\nzimbraMailQuota: 100\n'
            with self.subTest(quota=quota),patch.object(Carbonio,'run',side_effect=run),patch('bridge.subprocess.check_output',return_value='local.example.test\n'):
                with self.assertRaises(ValueError): Carbonio().change('account','a@example.test',quota)
            self.assertFalse(any(args[0] in ('ma','mc') for args in calls),calls)
    def test_direct_change_rejects_missing_host_before_any_write(self):
        with patch.object(Carbonio,'run',return_value='zimbraMailQuota: 100\n') as run,patch('bridge.subprocess.check_output',return_value='local.example.test\n'):
            with self.assertRaises(ValueError): Carbonio().change('account','a@example.test','45')
        self.assertFalse(any(c.args[0]=='ma' for c in run.call_args_list))
    def test_direct_change_verifies_local_host_then_writes_and_reads_back(self):
        calls=[]
        def run(*args):
            calls.append(args)
            if 'zimbraMailHost' in args: return 'zimbraMailHost: LOCAL.EXAMPLE.TEST\nzimbraMailQuota: 100\n'
            if 'ga' in args: return 'zimbraMailQuota: 48318382080\n'
            return ''
        with patch.object(Carbonio,'run',side_effect=run),patch('bridge.subprocess.check_output',return_value='local.example.test\n'):
            self.assertTrue(Carbonio().change('account','a@example.test','45')['verified'])
        self.assertIn('zimbraMailHost',calls[0])
        self.assertEqual(calls[1],('ma','a@example.test','zimbraMailQuota','48318382080'))
        self.assertEqual(calls[2],('-l','ga','a@example.test','zimbraMailQuota'))
    def test_cos_remains_global_and_does_not_check_mail_host(self):
        with patch.object(Carbonio,'run',side_effect=['','zimbraMailQuota: 0\n']) as run,patch('bridge.subprocess.check_output') as hostname:
            self.assertTrue(Carbonio().change('cos','default','0')['verified'])
        hostname.assert_not_called()
        self.assertEqual(run.call_args_list[0].args,('mc','default','zimbraMailQuota','0'))

    def test_lookup_failure_prevents_write(self):
        with patch.object(Carbonio,'run',side_effect=RuntimeError('LDAP unavailable')) as run:
            with self.assertRaises(RuntimeError): Carbonio().change('account','a@example.test','45')
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.args,('-l','ga','a@example.test','zimbraMailQuota','zimbraMailHost'))
    def test_missing_local_hostname_prevents_write(self):
        with patch.object(Carbonio,'run',return_value='zimbraMailHost: local.example.test\n') as run,patch('bridge.subprocess.check_output',return_value='\n'):
            with self.assertRaises(ValueError): Carbonio().change('account','a@example.test','45')
        self.assertFalse(any(c.args[0]=='ma' for c in run.call_args_list))
