#!/usr/bin/python3
"""Check panel readiness without passwords, quota reads or privileged bridge calls."""
import argparse
import http.client
from pathlib import Path
import time


def read_config(path):
    values={}
    for line in Path(path).read_text().splitlines():
        key,separator,value=line.partition('=')
        if separator and key.strip() in ('QUOTA_BIND','QUOTA_PORT','QUOTA_AUDIT_DB'):
            values[key.strip()]=value.strip().strip('\"\'')
    host=values.get('QUOTA_BIND','127.0.0.1')
    if host=='0.0.0.0': host='127.0.0.1'
    if host=='::': host='::1'
    audit=values.get('QUOTA_AUDIT_DB','/var/lib/carbonio-quota-panel/audit.db')
    if not Path(audit).is_absolute() or '\n' in audit:
        raise ValueError('QUOTA_AUDIT_DB debe ser una ruta absoluta')
    return {'host':host,'port':int(values.get('QUOTA_PORT','8787')),'audit':audit}


def check(host,port,attempts=10):
    for attempt in range(attempts):
        connection=http.client.HTTPConnection(host,port,timeout=2)
        try:
            connection.request('GET','/')
            response=connection.getresponse()
            if response.status==401 and 'realm="Carbonio cuotas"' in response.getheader('WWW-Authenticate',''):
                return
        except OSError:
            pass
        finally:
            connection.close()
        if attempt+1<attempts: time.sleep(0.5)
    raise RuntimeError('El panel no respondió con su autenticación esperada. Revisá journalctl -u carbonio-quota-panel.')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--audit-path',action='store_true'); args=parser.parse_args()
    config=read_config('/etc/carbonio-quota-panel.env')
    if args.audit_path: print(config['audit']); return
    check(config['host'],config['port'])
    print('Panel HTTP activo; autenticación requerida. No se consultaron ni modificaron cuotas.')

if __name__=='__main__': main()
