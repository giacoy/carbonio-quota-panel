import unittest
from types import SimpleNamespace
from unittest.mock import patch
from bridge import Carbonio, parse_blocks

class BatchTests(unittest.TestCase):
    def test_prompted_blocks_and_missing_override(self):
        text='prov> # name a@example.test\ndisplayName: A\n\nprov> # name b@example.test\nzimbraMailQuota: 0\n\nprov> '
        data=parse_blocks(text,['a@example.test','b@example.test'])
        self.assertNotIn('zimbraMailQuota',data['a@example.test'])
        self.assertEqual(data['b@example.test']['zimbraMailQuota'],'0')
    def test_partial_or_error_batch_is_not_valid_data(self):
        for text in ['prov> # name a@example.test\nzimbraMailQuota: 1\n',
                     'ERROR: account.NO_SUCH_ACCOUNT',
                     '# name a@example.test\n# name a@example.test\n# name b@example.test\n']:
            with self.subTest(text=text),self.assertRaises(RuntimeError):
                parse_blocks(text,['a@example.test','b@example.test'])
    def test_batch_single_process_and_safe_input(self):
        c=Carbonio()
        output=SimpleNamespace(returncode=0,stderr='',stdout='prov> # name a@example.test\nzimbraMailQuota: 0\nprov> # name b@example.test\nzimbraMailQuota: 10\nprov> ')
        with patch('bridge.subprocess.run',return_value=output) as run:
            data=c.batch('ga',['a@example.test','b@example.test'],['zimbraMailQuota'],ldap=True)
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.args[0],['/opt/zextras/bin/carbonio','prov','-l','-f','/dev/stdin'])
        self.assertEqual(run.call_args.kwargs['input'],'ga a@example.test zimbraMailQuota\nga b@example.test zimbraMailQuota\n')
        self.assertEqual(data['b@example.test']['zimbraMailQuota'],'10')
    def test_batch_invalid_target_never_executes(self):
        with patch('bridge.subprocess.run') as run:
            with self.assertRaises(ValueError): Carbonio().batch('ga',['a@example.test\nma bad'],['zimbraMailQuota'])
            run.assert_not_called()
    def test_no_fallback_to_slow_partial_results(self):
        with patch('bridge.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='ERROR: failure',stdout='')):
            with self.assertRaises(RuntimeError): Carbonio().batch('ga',['a@example.test'],['zimbraMailQuota'])
    def test_inspect_reads_only_target_and_effective_value(self):
        c=Carbonio(); calls=[]
        def run(*args,**kwargs):
            calls.append(args)
            if args[0]=='-l': return 'zimbraMailHost: mail.example.test\n'
            return 'zimbraMailQuota: 200\n'
        with patch.object(c,'run',side_effect=run),patch('bridge.subprocess.check_output',return_value='mail.example.test\n'):
            data=c.inspect('account','a@example.test')
        self.assertEqual(data,{'name':'a@example.test','quota':200,'override':None})
        self.assertEqual(len(calls),2)
    def test_inspect_rejects_remote_mailbox(self):
        with patch.object(Carbonio,'run',return_value='zimbraMailHost: remote.example.test\n'),patch('bridge.subprocess.check_output',return_value='mail.example.test\n'):
            with self.assertRaises(ValueError): Carbonio().inspect('account','a@example.test')

    def test_eighty_accounts_use_five_java_processes(self):
        names=[f'user{i}@example.test' for i in range(80)]
        def execute(args,**kwargs):
            if 'gqu' in args: text=''.join(f'{name} 42\n' for name in names)
            elif 'gac' in args: text='default\n'
            else:
                blocks=[]
                for line in kwargs['input'].splitlines():
                    command,name,*attributes=line.split()
                    if command=='gc': values={'zimbraId':'id1','zimbraMailQuota':'100'}
                    elif '-l' in args: values={'zimbraMailQuota':'100','zimbraCOSId':'id1','zimbraMailHost':'mail.example.test'}
                    else: values={'zimbraMailQuota':'100'}
                    blocks.append('prov> # name '+name+'\n'+''.join(k+': '+v+'\n' for k,v in values.items()))
                text=''.join(blocks)+'prov> '
            return SimpleNamespace(returncode=0,stderr='',stdout=text)
        with patch('bridge.subprocess.run',side_effect=execute) as process,patch('bridge.subprocess.check_output',return_value='mail.example.test\n'):
            data=Carbonio().snapshot()
        self.assertEqual(len(data['accounts']),80)
        self.assertEqual(process.call_count,5)
        self.assertEqual(data['accounts'][-1]['quota'],100)
