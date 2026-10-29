#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $EUID -ne 0 ]]; then echo 'Ejecutar como root'; exit 1; fi
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --apache ) ]]; then
  echo 'Uso: bash deploy/update.sh [--apache]'; exit 1
fi
if [[ ! -f /etc/carbonio-quota-panel.env ]]; then
  echo 'No hay instalación. Usá bash deploy/install.sh [--apache]'; exit 1
fi
for source in server.py bridge.py launch.py static/index.html static/app.js static/style.css deploy/carbonio-quota-panel.service deploy/healthcheck.py; do
  [[ -r $source ]] || { echo "Falta archivo: $source"; exit 1; }
done
/usr/bin/python3 -m py_compile server.py bridge.py launch.py
# Backups stay private and outside the repository; never rewrite the user's env.
umask 077
mkdir -p /var/backups
backup=$(mktemp -d /var/backups/carbonio-quota-panel.XXXXXXXX)
cp -a /opt/carbonio-quota-panel "$backup/application"
cp -a /usr/local/libexec/carbonio-quota-bridge "$backup/bridge"
cp -a /etc/systemd/system/carbonio-quota-panel.service "$backup/service"
cp -a /etc/carbonio-quota-panel.env "$backup/config.env"
audit_source=$(/usr/bin/python3 deploy/healthcheck.py --audit-path)
systemctl stop carbonio-quota-panel
restore() {
  echo "Falló la actualización. Restaurando desde $backup" >&2
  systemctl stop carbonio-quota-panel || true
  cp -a "$backup/application/." /opt/carbonio-quota-panel/
  install -m 0755 -o root -g root "$backup/bridge" /usr/local/libexec/carbonio-quota-bridge
  install -m 0644 -o root -g root "$backup/service" /etc/systemd/system/carbonio-quota-panel.service
  systemctl daemon-reload
  systemctl start carbonio-quota-panel
}
trap restore ERR
if [[ -f $audit_source ]]; then
  cp -a -- "$audit_source" "$backup/audit.db"
fi
install -m 0644 -o root -g root server.py bridge.py launch.py /opt/carbonio-quota-panel/
install -m 0644 -o root -g root static/* /opt/carbonio-quota-panel/static/
install -m 0755 -o root -g root bridge.py /usr/local/libexec/carbonio-quota-bridge
install -m 0644 -o root -g root deploy/carbonio-quota-panel.service /etc/systemd/system/
systemctl daemon-reload
systemctl start carbonio-quota-panel
/usr/bin/python3 deploy/healthcheck.py
if [[ ${1:-} == --apache ]]; then bash deploy/configure-apache.sh; fi
trap - ERR
echo "Actualizado. Respaldo: $backup"
echo 'Se conservaron contraseña, origen, modo de edición y auditoría. Recargá la página.'
