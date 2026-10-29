#!/bin/bash
# Add only /cuotas/ to an existing Apache installation; leave listeners/sites intact.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $EUID -ne 0 ]]; then echo 'Ejecutar como root'; exit 1; fi
for tool in apache2ctl a2enmod a2enconf a2disconf systemctl; do command -v "$tool" >/dev/null; done
apache2ctl configtest
config=/etc/apache2/conf-available/apache-cuotas.conf
backup=$(mktemp -d)
existed=0
was_enabled=0
[[ ! -f $config ]] || { cp -a "$config" "$backup/original.conf"; existed=1; }
[[ ! -e /etc/apache2/conf-enabled/apache-cuotas.conf ]] || was_enabled=1
trap 'rm -rf "$backup"' EXIT
rollback() {
  if [[ $was_enabled -eq 0 ]]; then a2disconf apache-cuotas >/dev/null || true; fi
  if [[ $existed -eq 1 ]]; then
    cp -a "$backup/original.conf" "$config"
  else
    rm -f "$config"
  fi
}
a2enmod proxy proxy_http
install -m 0644 -o root -g root deploy/apache-cuotas.conf "$config"
a2enconf apache-cuotas
if ! apache2ctl configtest; then
  rollback
  echo 'Configuración inválida: se restauró el archivo anterior y no se recargó Apache.' >&2
  exit 1
fi
if ! systemctl reload apache2; then
  rollback
  echo 'No se pudo recargar Apache; se restauró el archivo anterior. Revisá journalctl -u apache2.' >&2
  exit 1
fi
echo 'Ruta /cuotas/ activada. Se conservan los sitios, /webui/ y los puertos existentes.'
