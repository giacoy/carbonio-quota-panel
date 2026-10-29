#!/usr/bin/python3 -I
"""Root-owned, allowlisted bridge. Run as zextras, never as root."""
import json
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation

BIN = '/opt/zextras/bin/carbonio'
HOSTNAME = '/opt/zextras/bin/zmhostname'
GIB = 1073741824

def validate(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@+\-]{0,253}',value):
        raise ValueError('Identificador no válido')
    return value

def quota_bytes(value):
    if isinstance(value,bool): raise ValueError('Cuota no válida')
    try:
        n=Decimal(str(value))
        if not n.is_finite() or n<0 or n>1048576: raise ValueError('Cuota fuera de rango')
        converted=int(n*GIB)
        if n>0 and converted==0: raise ValueError('La cuota mínima positiva es un byte')
        return converted
    except (InvalidOperation,TypeError): raise ValueError('Cuota no válida')

def attrs(output):
    return dict(line.split(': ',1) for line in output.splitlines() if ': ' in line and not line.startswith('#'))

def parse_usage(output):
    result={}
    for line in output.splitlines():
        if not line.strip() or line.startswith('WARNING:'): continue
        parts=line.split()
        if len(parts)!=2 or not parts[1].isdigit():
            raise ValueError('Formato gqu inesperado; se espera cuenta y bytes utilizados')
        result[validate(parts[0])]=int(parts[1])
    return result

class Carbonio:
    def run(self,*args):
        p=subprocess.run([BIN,'prov',*args],text=True,capture_output=True,timeout=30,
                         env={'HOME':'/opt/zextras','USER':'zextras','LOGNAME':'zextras',
                              'PATH':'/opt/zextras/bin:/usr/bin:/bin','LANG':'C.UTF-8'})
        if p.returncode: raise RuntimeError('Carbonio rechazó la operación: '+p.stderr.strip()[:300])
        return p.stdout

    def snapshot(self):
        host=subprocess.check_output([HOSTNAME],text=True,timeout=10).strip()
        usage=parse_usage(self.run('gqu',validate(host)))
        classes=[]; by_id={}
        for name in self.run('gac').splitlines():
            if not name.strip(): continue
            name=validate(name.strip())
            data=attrs(self.run('gc',name,'zimbraId','zimbraMailQuota'))
            entry={'name':name,'id':data.get('zimbraId',''),
                   'quota':int(data.get('zimbraMailQuota','0'))}
            classes.append(entry); by_id[entry['id']]=entry
        default=next((c for c in classes if c['name']=='default'),None)
        domain_defaults={}
        accounts=[]
        for name,used in usage.items():
            # LDAP read: explicit account value only, without COS inheritance.
            own=attrs(self.run('-l','ga',name,'zimbraMailQuota','zimbraCOSId','displayName','zimbraMailHost'))
            # Normal provisioning read supplies the effective inherited value.
            effective=attrs(self.run('ga',name,'zimbraMailQuota'))
            cos_id=own.get('zimbraCOSId')
            if not cos_id:
                domain=name.rsplit('@',1)[-1]
                if domain not in domain_defaults:
                    domain_defaults[domain]=attrs(self.run('gd',validate(domain),'zimbraDomainDefaultCOSId')).get('zimbraDomainDefaultCOSId')
                cos_id=domain_defaults[domain]
            cos=by_id.get(cos_id,default)
            raw=own.get('zimbraMailQuota')
            limit=effective.get('zimbraMailQuota')
            if limit is None:
                raise RuntimeError('Carbonio no devolvió cuota efectiva para '+name)
            accounts.append({'name':name,'display':own.get('displayName',name),
                'used':used,'quota':int(limit),'override':int(raw) if raw is not None else None,
                'cos':cos['name'] if cos else 'Desconocida','host':own.get('zimbraMailHost',host)})
        return {'accounts':accounts,'classes':classes,'host':host}

    def change(self,kind,target,gib):
        validate(target)
        if kind not in ('account','cos'): raise ValueError('Tipo no válido')
        if gib is None and kind!='account': raise ValueError('Solo las cuentas pueden heredar')
        value='' if gib is None else str(quota_bytes(gib))
        self.run('ma' if kind=='account' else 'mc',target,'zimbraMailQuota',value)
        data=attrs(self.run('-l','ga' if kind=='account' else 'gc',target,'zimbraMailQuota'))
        actual=data.get('zimbraMailQuota')
        if (gib is None and actual is not None) or (gib is not None and actual!=value):
            raise RuntimeError('Se envió el cambio, pero la verificación no coincide. Consultá el estado antes de reintentar.')
        return {'verified':True,'quota':None if gib is None else int(value)}

def main():
    request=json.loads(sys.stdin.read(4097))
    c=Carbonio()
    if request=={'action':'snapshot'}: result=c.snapshot()
    elif set(request)=={'action','kind','target','gib'} and request['action']=='change':
        result=c.change(request['kind'],request['target'],request['gib'])
    else: raise ValueError('Operación no permitida')
    print(json.dumps(result))

if __name__=='__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'error':str(error)})); sys.exit(1)
