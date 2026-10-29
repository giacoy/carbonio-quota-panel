#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $EUID -ne 0 ]]; then echo 'Ejecutar como root: sudo bash deploy/install.sh'; exit 1; fi
if [[ ! -x /opt/zextras/bin/carbonio || ! -x /opt/zextras/bin/zmhostname ]]; then
  echo 'No se encontró Carbonio en /opt/zextras/bin. No se instaló nada.'; exit 1
fi
command -v sudo >/dev/null
command -v python3 >/dev/null
command -v visudo >/dev/null
id zextras >/dev/null
if [[ -f /etc/carbonio-quota-panel.env ]]; then
  echo 'Ya existe una instalación. Seguí la actualización manual del README; no se sobrescriben credenciales.'; exit 1
fi
# These paths must not be writable by either the panel user or zextras.
install -d -m 0755 -o root -g root /opt/carbonio-quota-panel /opt/carbonio-quota-panel/static /usr/local/libexec
install -m 0644 -o root -g root server.py bridge.py launch.py /opt/carbonio-quota-panel/
install -m 0644 -o root -g root static/* /opt/carbonio-quota-panel/static/
install -m 0755 -o root -g root bridge.py /usr/local/libexec/carbonio-quota-bridge
id carbonio-quota >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin carbonio-quota
sudoers_tmp=$(mktemp)
trap 'rm -f "$sudoers_tmp"' EXIT
printf '%s\n' 'carbonio-quota ALL=(zextras) NOPASSWD: /usr/local/libexec/carbonio-quota-bridge ""' > "$sudoers_tmp"
visudo -cf "$sudoers_tmp"
install -m 0440 -o root -g root "$sudoers_tmp" /etc/sudoers.d/carbonio-quota-panel
# Input uses the terminal; only a salted password hash is stored.
password_hash=$(/usr/bin/python3 /opt/carbonio-quota-panel/server.py --hash-password)
umask 077
cat > /etc/carbonio-quota-panel.env <<CONFIG
QUOTA_USER=admin
QUOTA_PASSWORD_HASH=$password_hash
QUOTA_BIND=127.0.0.1
QUOTA_PORT=8787
QUOTA_READ_ONLY=1
QUOTA_AUDIT_DB=/var/lib/carbonio-quota-panel/audit.db
CONFIG
unset password_hash
install -m 0644 -o root -g root deploy/carbonio-quota-panel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now carbonio-quota-panel
systemctl --no-pager --full status carbonio-quota-panel
echo 'Panel instalado en 127.0.0.1:8787, solo lectura. Usuario: admin. Ver README para acceso y validación.'
