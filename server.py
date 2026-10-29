#!/usr/bin/python3
"""Internal Carbonio quota panel. Python 3.10+, no third-party dependencies."""
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from bridge import validate, quota_bytes

ROOT=Path(__file__).resolve().parent
BRIDGE='/usr/local/libexec/carbonio-quota-bridge'

def password_hash(password):
    salt=secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),300000).hex()

def check_password(password,stored):
    salt,digest=stored.split(':',1)
    actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),300000).hex()
    return hmac.compare_digest(actual,digest)

def bridge(request):
    result=subprocess.run(['/usr/bin/sudo','-n','-u','zextras',BRIDGE],input=json.dumps(request),
                          capture_output=True,text=True,timeout=600)
    try: data=json.loads(result.stdout)
    except ValueError:
        logging.getLogger(__name__).error('Puente Carbonio: salida no válida; código=%s; stderr=%s',
                                         result.returncode,result.stderr.strip()[:1500])
        raise RuntimeError('No se pudo consultar Carbonio. El error del puente está en journalctl -u carbonio-quota-panel.')
    if result.returncode or 'error' in data: raise RuntimeError(data.get('error','Falló la consulta a Carbonio'))
    return data

def utc(): return datetime.now(timezone.utc).isoformat()

def audit(server,operation,**fields):
    with sqlite3.connect(server.audit_db) as db:
        if operation=='start':
            cur=db.execute('INSERT INTO audit (at,actor,kind,target,old,new,status,detail) VALUES (?,?,?,?,?,?,?,?)',
                (utc(),server.username,fields['kind'],fields['target'],json.dumps(fields['old']),
                 json.dumps(fields['new']),'pending',''))
            return cur.lastrowid
        db.execute('UPDATE audit SET status=?,detail=? WHERE id=?',
                   (fields['status'],fields.get('detail',''),fields['id']))

class BoundedServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(8)
        super().__init__(*args,**kwargs)
    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally: self.shutdown_request(request)
            return
        try: super().process_request(request,client_address)
        except BaseException:
            self.slots.release(); raise
    def process_request_thread(self,request,client_address):
        try: super().process_request_thread(request,client_address)
        finally: self.slots.release()

class Handler(BaseHTTPRequestHandler):
    server_version='QuotaPanel/1.0'
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def log_message(self,*args): pass  # Avoid retaining request headers or secrets.
    def send(self,status,data,content_type='application/json'):
        if isinstance(data,(dict,list)): data=json.dumps(data,ensure_ascii=False).encode()
        elif isinstance(data,str): data=data.encode()
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if status==401: self.send_header('WWW-Authenticate','Basic realm="Carbonio cuotas", charset="UTF-8"')
        self.end_headers(); self.wfile.write(data)
    def authorized(self):
        # PBKDF is deliberately expensive; cap parallel requests via server workers.
        try:
            scheme,encoded=self.headers.get('Authorization','').split(' ',1)
            user,password=base64.b64decode(encoded,validate=True).decode().split(':',1)
            return (scheme=='Basic' and hmac.compare_digest(user,self.server.username)
                    and check_password(password,self.server.password))
        except (ValueError,UnicodeError): return False
    def do_GET(self):
        if not self.authorized(): return self.send(401,{'error':'Ingresá con el administrador del panel'})
        path=urlsplit(self.path).path
        try:
            if path=='/api/state':
                with self.server.lock:
                    if parse_qs(urlsplit(self.path).query).get('refresh')==['1'] or not self.server.cache or time.monotonic()-self.server.cached_at>60:
                        data=bridge({'action':'snapshot'})
                        data['updated']=utc(); self.server.cache=data; self.server.cached_at=time.monotonic()
                    return self.send(200,{**self.server.cache,'csrf':self.server.csrf,'readOnly':os.environ.get('QUOTA_READ_ONLY','1')!='0'})
            if path=='/api/audit':
                with sqlite3.connect(self.server.audit_db) as db:
                    db.row_factory=sqlite3.Row
                    rows=[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]
                return self.send(200,rows)
            files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
            if path not in files: return self.send(404,{'error':'No encontrado'})
            mime={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}
            return self.send(200,(ROOT/'static'/files[path]).read_bytes(),mime[path])
        except Exception as error: return self.send(502,{'error':str(error)})
    def do_POST(self):
        if not self.authorized(): return self.send(401,{'error':'Acceso requerido'})
        origin=self.headers.get('Origin','')
        expected_origin=os.environ.get('QUOTA_ORIGIN') or 'http://'+self.headers.get('Host','')
        if origin!=expected_origin or not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),self.server.csrf):
            return self.send(403,{'error':'Solicitud inválida. Recargá el panel.'})
        if self.path!='/api/change': return self.send(404,{'error':'No encontrado'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>4096: raise ValueError('Solicitud demasiado grande o vacía')
            data=json.loads(self.rfile.read(size))
            kind=data['kind']; target=validate(data['target']); gib=data['gib']
            if kind not in ('account','cos'): raise ValueError('Tipo no válido')
            if gib is None and kind!='account': raise ValueError('La COS no puede heredar')
            if gib is not None: quota_bytes(gib)
            with self.server.lock:
                # Fresh server read, never authorize a write from cached browser data.
                entry=bridge({'action':'inspect','kind':kind,'target':target})
                old={key:entry[key] for key in ('quota','override') if key in entry}
                if old!=data.get('expected'): return self.send(409,{'error':'La cuota cambió desde que abriste el panel. Actualizá y revisá el nuevo valor.'})
                if os.environ.get('QUOTA_READ_ONLY','1')!='0':
                    return self.send(403,{'error':'Modo de solo lectura. Habilitá escritura después de validar la consulta.'})
                row=audit(self.server,'start',kind=kind,target=target,old=old,new=gib)
                self.server.cache=None
                try:
                    result=bridge({'action':'change','kind':kind,'target':target,'gib':gib})
                    audit(self.server,'finish',id=row,status='verified')
                except Exception as error:
                    audit(self.server,'finish',id=row,status='uncertain',detail=str(error))
                    raise
            return self.send(200,result)
        except (ValueError,KeyError,TypeError) as error: return self.send(400,{'error':str(error)})
        except Exception as error: return self.send(502,{'error':str(error)})

def make_server(host,port,user,password,db):
    server=BoundedServer((host,port),Handler)
    server.username=user; server.password=password; server.audit_db=db
    server.csrf=secrets.token_urlsafe(32); server.lock=threading.Lock(); server.cache=None; server.cached_at=0
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY,at TEXT,actor TEXT,kind TEXT,target TEXT,old TEXT,new TEXT,status TEXT,detail TEXT)')
    return server

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--hash-password',action='store_true'); args=parser.parse_args()
    if args.hash_password:
        password=getpass.getpass('Contraseña del panel (mínimo 12 caracteres): ')
        if len(password)<12: parser.error('Usá al menos 12 caracteres')
        print(password_hash(password)); return
    user=os.environ.get('QUOTA_USER','admin'); password=os.environ.get('QUOTA_PASSWORD_HASH','')
    if not password or ':' not in password: raise SystemExit('Falta QUOTA_PASSWORD_HASH; usá --hash-password')
    make_server(os.environ.get('QUOTA_BIND','127.0.0.1'),int(os.environ.get('QUOTA_PORT','8787')),
                user,password,os.environ.get('QUOTA_AUDIT_DB','/var/lib/carbonio-quota-panel/audit.db')).serve_forever()

if __name__=='__main__': main()
