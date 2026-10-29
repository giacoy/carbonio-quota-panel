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

def parse_blocks(output,expected):
    blocks={}; current=None
    for raw in output.splitlines():
        line=re.sub(r'^(?:prov>\s*)+','',raw)
        if not line.strip(): continue
        if line.startswith('ERROR:'):
            raise RuntimeError('Falló una consulta del lote: '+line[:300])
        if line.startswith('# name '):
            current=line[len('# name '):].strip()
            if current not in expected or current in blocks:
                raise RuntimeError('Respuesta del lote inesperada o duplicada')
            blocks[current]={}
        elif current is not None and ': ' in line and not line.startswith('#'):
            key,value=line.split(': ',1); blocks[current][key]=value
    if set(blocks)!=set(expected):
        raise RuntimeError('El lote no devolvió todas las cuentas o clases solicitadas')
    return blocks

class Carbonio:
    def run(self,*args,input_text=None,timeout=30):
        p=subprocess.run([BIN,'prov',*args],input=input_text,text=True,capture_output=True,timeout=timeout,
                         env={'HOME':'/opt/zextras','USER':'zextras','LOGNAME':'zextras',
                              'PATH':'/opt/zextras/bin:/usr/bin:/bin','LANG':'C.UTF-8'})
        if p.returncode or (input_text is not None and re.search(r'^ERROR:',p.stderr,re.MULTILINE)):
            raise RuntimeError('Carbonio rechazó la operación: '+p.stderr.strip()[:300])
        return p.stdout

    def batch(self,command,names,attributes,ldap=False):
        if command not in ('ga','gc','gd'):
            raise ValueError('Comando de lectura no permitido')
        allowed={'zimbraId','zimbraMailQuota','zimbraCOSId','displayName',
                 'zimbraMailHost','zimbraDomainDefaultCOSId'}
        if not attributes or not set(attributes)<=allowed:
            raise ValueError('Atributos no permitidos')
        names=list(dict.fromkeys(validate(name) for name in names))
        if not names: return {}
        lines=''.join(' '.join([command,name,*attributes])+'\n' for name in names)
        args=['-l'] if ldap else []
        output=self.run(*args,'-f','/dev/stdin',input_text=lines,timeout=300)
        return parse_blocks(output,names)

    def snapshot(self):
        host=validate(subprocess.check_output([HOSTNAME],text=True,timeout=10).strip())
        usage=parse_usage(self.run('gqu',host))
        names=[validate(name.strip()) for name in self.run('gac').splitlines() if name.strip()]
        class_data=self.batch('gc',names,['zimbraId','zimbraMailQuota'])
        classes=[]; by_id={}
        for name in names:
            data=class_data[name]
            if 'zimbraMailQuota' not in data or 'zimbraId' not in data:
                raise RuntimeError('COS incompleta en la respuesta de Carbonio: '+name)
            entry={'name':name,'id':data['zimbraId'],'quota':int(data['zimbraMailQuota'])}
            classes.append(entry); by_id[entry['id']]=entry
        default=next((c for c in classes if c['name']=='default'),None)
        own_data=self.batch('ga',usage,['zimbraMailQuota','zimbraCOSId','displayName','zimbraMailHost'],ldap=True)
        effective_data=self.batch('ga',usage,['zimbraMailQuota'])
        domains=sorted({name.rsplit('@',1)[-1] for name in usage if not own_data[name].get('zimbraCOSId')})
        domain_data=self.batch('gd',domains,['zimbraDomainDefaultCOSId'])
        accounts=[]
        for name,used in usage.items():
            own=own_data[name]
            cos_id=own.get('zimbraCOSId') or domain_data.get(name.rsplit('@',1)[-1],{}).get('zimbraDomainDefaultCOSId')
            cos=by_id.get(cos_id,default)
            raw=own.get('zimbraMailQuota')
            limit=effective_data[name].get('zimbraMailQuota')
            if limit is None:
                raise RuntimeError('Carbonio no devolvió cuota efectiva para '+name)
            accounts.append({'name':name,'display':own.get('displayName',name),
                'used':used,'quota':int(limit),'override':int(raw) if raw is not None else None,
                'cos':cos['name'] if cos else 'Desconocida','host':own.get('zimbraMailHost',host)})
        return {'accounts':accounts,'classes':classes,'host':host}

    def inspect(self,kind,target):
        validate(target)
        if kind=='cos':
            data=attrs(self.run('gc',target,'zimbraMailQuota'))
            if 'zimbraMailQuota' not in data: raise RuntimeError('Carbonio no devolvió cuota de la COS')
            return {'name':target,'quota':int(data['zimbraMailQuota'])}
        if kind!='account': raise ValueError('Tipo no válido')
        own=attrs(self.run('-l','ga',target,'zimbraMailQuota','zimbraMailHost'))
        host=subprocess.check_output([HOSTNAME],text=True,timeout=10).strip()
        if own.get('zimbraMailHost','').lower()!=host.lower():
            raise ValueError('La cuenta no pertenece al servidor local')
        effective=attrs(self.run('ga',target,'zimbraMailQuota'))
        if 'zimbraMailQuota' not in effective: raise RuntimeError('Carbonio no devolvió cuota efectiva')
        raw=own.get('zimbraMailQuota')
        return {'name':target,'quota':int(effective['zimbraMailQuota']),
                'override':int(raw) if raw is not None else None}

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
    elif set(request)=={'action','kind','target'} and request['action']=='inspect':
        result=c.inspect(request['kind'],request['target'])
    elif set(request)=={'action','kind','target','gib'} and request['action']=='change':
        result=c.change(request['kind'],request['target'],request['gib'])
    else: raise ValueError('Operación no permitida')
    print(json.dumps(result))

if __name__=='__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'error':str(error)})); sys.exit(1)
