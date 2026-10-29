import unittest
from decimal import Decimal
from unittest.mock import patch
from bridge import validate, parse_usage, attrs, quota_bytes, Carbonio

class CoreTests(unittest.TestCase):
    def test_no_command_injection(self):
        for value in ['a@b;id', '--help', 'a\nb', '../default', 'a b', '$(id)']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)
    def test_usage_warning_and_bytes(self):
        self.assertEqual(parse_usage('WARNING: This size refeers to Mails/Calendars/Contacts only\na@example.test 99566735067\n'), {'a@example.test':99566735067})
    def test_unknown_usage_format_rejected(self):
        for data in ['a@example.test 100 200', 'a@example.test -1', 'unexpected error']:
            with self.assertRaises(ValueError): parse_usage(data)
    def test_gib_exact_conversion(self):
        self.assertEqual(quota_bytes('45'),48318382080)
        self.assertEqual(quota_bytes('0'),0)
        for value in ['-1','NaN','Infinity','1e99','abc',True,'0.0000000001']:
            with self.assertRaises(ValueError): quota_bytes(value)
    def test_attrs_preserves_empty_and_repeated(self):
        self.assertEqual(attrs('# name a\nzimbraMailQuota: 100\nzimbraCOSId: abc\n')['zimbraMailQuota'],'100')
    def test_mutation_uses_argument_array_and_reads_back(self):
        c=Carbonio(); calls=[]
        def run(*args):
            calls.append(args)
            if 'zimbraMailHost' in args: return 'zimbraMailHost: local.example.test\n'
            if 'ga' in args: return 'zimbraMailQuota: 53687091200\n'
            return ''
        with patch.object(c,'run',side_effect=run),patch('bridge.subprocess.check_output',return_value='local.example.test\n'):
            result=c.change('account','a@example.test','50')
        self.assertEqual(result['verified'],True)
        self.assertEqual(calls[1],('ma','a@example.test','zimbraMailQuota','53687091200'))
    def test_readback_mismatch_is_failure(self):
        c=Carbonio()
        with patch.object(c,'run',return_value='zimbraMailQuota: 1\n'):
            with self.assertRaises(RuntimeError): c.change('cos','default','50')
    def test_inherit_deletes_override(self):
        c=Carbonio(); calls=[]
        def run(*args):
            calls.append(args)
            return 'zimbraMailHost: local.example.test\n' if 'zimbraMailHost' in args else ''
        with patch.object(c,'run',side_effect=run),patch('bridge.subprocess.check_output',return_value='local.example.test\n'):
            self.assertTrue(c.change('account','a@example.test',None)['verified'])
        self.assertEqual(calls[1],('ma','a@example.test','zimbraMailQuota',''))
    def test_snapshot_domain_cos_and_effective_quota(self):
        c=Carbonio()
        def batch(command,names,attributes,ldap=False):
            if command=='gc':
                return {'default':{'zimbraId':'id1','zimbraMailQuota':'100'},
                        'custom':{'zimbraId':'id2','zimbraMailQuota':'200'}}
            if command=='gd': return {'example.test':{'zimbraDomainDefaultCOSId':'id2'}}
            if ldap: return {'a@example.test':{'displayName':'Test'}}
            return {'a@example.test':{'zimbraMailQuota':'200'}}
        with patch('bridge.subprocess.check_output',return_value='mail.example.test\n'), patch.object(c,'run',side_effect=['a@example.test 42\n','default\ncustom\n']),patch.object(c,'batch',side_effect=batch):
            account=c.snapshot()['accounts'][0]
        self.assertEqual((account['used'],account['quota'],account['override'],account['cos']),(42,200,None,'custom'))

    def test_cos_cannot_inherit(self):
        with self.assertRaises(ValueError): Carbonio().change('cos','default',None)

if __name__=='__main__': unittest.main()
