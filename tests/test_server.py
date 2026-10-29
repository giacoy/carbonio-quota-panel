import base64
import http.client
import json
import os
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import tempfile
import threading
import unittest
from unittest.mock import patch
from server import make_server, password_hash

class WebTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'QUOTA_READ_ONLY':'0'}); self.env.start()
        self.temp=tempfile.TemporaryDirectory()
        self.s=make_server('127.0.0.1',0,'admin',password_hash('test-password'),self.temp.name+'/audit.db')
        self.t=threading.Thread(target=self.s.serve_forever,daemon=True); self.t.start()
        self.headers={'Authorization':'Basic '+base64.b64encode(b'admin:test-password').decode()}
    def tearDown(self):
        self.s.shutdown(); self.s.server_close(); self.temp.cleanup(); self.env.stop()
    def request(self,method,path,body=None,headers=None):
        c=http.client.HTTPConnection(*self.s.server_address,timeout=5)
        c.request(method,path,json.dumps(body) if body is not None else None,headers or {})
        r=c.getresponse(); data=r.read(); c.close(); return r.status,data
    def test_login_required(self):
        self.assertEqual(self.request('GET','/api/state')[0],401)
    def test_auth_rejects_wrong_password(self):
        self.assertEqual(self.request('GET','/',headers={'Authorization':'Basic YTpi'})[0],401)
    def test_authenticated_state(self):
        with patch('server.bridge',return_value={'accounts':[],'classes':[]}):
            status,body=self.request('GET','/api/state',headers=self.headers)
        self.assertEqual(status,200); self.assertIn('csrf',json.loads(body))
    def test_csrf_required_before_backend_access(self):
        with patch('server.bridge') as b:
            self.assertEqual(self.request('POST','/api/change',{},self.headers)[0],403)
            b.assert_not_called()
    def test_foreign_origin_rejected(self):
        h={**self.headers,'Origin':'https://evil.example','X-CSRF-Token':self.s.csrf}
        self.assertEqual(self.request('POST','/api/change',{},h)[0],403)
    def test_changed_quota_conflict_does_not_write(self):
        state={'accounts':[{'name':'a@example.test','quota':100,'override':100}],'classes':[]}
        h={**self.headers,'Origin':'http://127.0.0.1:'+str(self.s.server_port),'X-CSRF-Token':self.s.csrf}
        with patch('server.bridge',return_value=state) as b:
            status,_=self.request('POST','/api/change',{'kind':'account','target':'a@example.test','gib':'50','expected':{'quota':99,'override':99}},h)
        self.assertEqual(status,409); self.assertEqual(b.call_count,1)
    def test_verified_change_and_audit(self):
        state={'accounts':[],'classes':[{'name':'default','quota':100}]}
        h={**self.headers,'Origin':'http://127.0.0.1:'+str(self.s.server_port),'X-CSRF-Token':self.s.csrf}
        with patch('server.bridge',side_effect=[state,{'verified':True,'quota':0}]):
            status,_=self.request('POST','/api/change',{'kind':'cos','target':'default','gib':'0','expected':{'quota':100}},h)
        self.assertEqual(status,200)
        status,body=self.request('GET','/api/audit',headers=self.headers)
        self.assertEqual(json.loads(body)[0]['status'],'verified')
    def test_read_only_blocks_mutation(self):
        state={'accounts':[],'classes':[{'name':'default','quota':100}]}
        h={**self.headers,'Origin':'http://127.0.0.1:'+str(self.s.server_port),'X-CSRF-Token':self.s.csrf}
        with patch.dict(os.environ,{'QUOTA_READ_ONLY':'1'}), patch('server.bridge',return_value=state) as b:
            status,_=self.request('POST','/api/change',{'kind':'cos','target':'default','gib':'0','expected':{'quota':100}},h)
        self.assertEqual(status,403); self.assertEqual(b.call_count,1)
    def test_worker_limit_rejects_excess_requests(self):
        for _ in range(8): self.s.slots.acquire()
        try: self.assertEqual(self.request('GET','/')[0],503)
        finally:
            for _ in range(8): self.s.slots.release()

    def test_assets_resolve_under_shared_apache_prefix(self):
        class Assets(HTMLParser):
            def __init__(self): super().__init__(); self.paths=[]
            def handle_starttag(self,tag,attrs):
                values=dict(attrs)
                if tag=='script' and 'src' in values: self.paths.append(values['src'])
                if tag=='link' and values.get('rel')=='stylesheet': self.paths.append(values['href'])
        status,html=self.request('GET','/',headers=self.headers)
        parser=Assets(); parser.feed(html.decode())
        self.assertEqual(status,200); self.assertEqual(len(parser.paths),2)
        for asset in parser.paths:
            url=urljoin('http://example.test:7780/cuotas/',asset)
            path=urlsplit(url).path
            self.assertTrue(path.startswith('/cuotas/'),url)
            self.assertEqual(self.request('GET',path[len('/cuotas'):],headers=self.headers)[0],200)
        _,script=self.request('GET','/app.js',headers=self.headers)
        endpoints=re.findall(r"api\('([^']+)",script.decode())
        self.assertEqual(len(endpoints),3)
        for endpoint in endpoints:
            self.assertTrue(urlsplit(urljoin('http://example.test:7780/cuotas/',endpoint)).path.startswith('/cuotas/api/'))

    def test_static_traversal_rejected(self):
        self.assertEqual(self.request('GET','/../bridge.py',headers=self.headers)[0],404)
