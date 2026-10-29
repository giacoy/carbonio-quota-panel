# Carbonio Quota Panel

Panel interno sencillo para consultar uso y administrar cuotas de correo en Carbonio CE. Se instala en el servidor Carbonio como una aplicación independiente, con archivos propios y autenticación de administrador.

**Las instalaciones nuevas permiten modificar cuotas por defecto.** Cada cambio requiere confirmación y se verifica volviendo a consultar Carbonio. La instalación no cambia cuotas por sí sola.

## Funciones

- Buzones del servidor local: uso, límite efectivo, porcentaje y cuota propia o heredada.
- Búsqueda, orden por consumo/porcentaje/nombre y exportación CSV.
- Modificar cuota por cuenta o volver a heredar de la COS.
- Modificar cuota de una COS, conservando las excepciones por cuenta.
- Cuota ilimitada con valor 0.
- Historial persistente con valor anterior, nuevo y resultado de la verificación.
- Detección de cambios concurrentes desde que se abrió la pantalla.
- Consulta por lotes: una prueba con 80 cuentas verifica 5 arranques de Java, frente a más de 160 del diseño inicial.

El uso incluye correo, calendarios y contactos devueltos por `gqu`; no incluye Files, backups ni ocupación física del disco. Solo se listan buzones del servidor local. Las COS pueden afectar cuentas de toda una instalación multiserver. No administra cuotas de dominio ni reemplaza la administración completa de Carbonio.

## Instalar en otro servidor

Ubuntu 22.04 o compatible, Python **3.10+**, `sudo`, `git` y `systemd`. Carbonio debe existir en `/opt/zextras`, con usuario `zextras`. No necesita paquetes Python, Node, Docker ni credenciales de Carbonio en el navegador.

Como root:

```bash
mkdir -p /usr/local/src
cd /usr/local/src
git clone https://github.com/giacoy/carbonio-quota-panel.git
cd carbonio-quota-panel
bash deploy/install.sh --apache
```

El repositorio es público; no pide usuario ni token de GitHub. El instalador solicita una contraseña exclusiva del panel de al menos 12 caracteres. Usuario web: **admin**.

La opción `--apache` requiere Apache ya instalado y funcionando. Agrega únicamente `/cuotas/`, valida la configuración y recarga Apache. No cambia `ports.conf`, listeners, certificados, el sitio existente ni `/webui/` de PolicyD. No instala Apache ni reinicia Carbonio. En el despliegue compartido en puerto 7780, entrá a:

```text
http://IP_O_NOMBRE_DEL_SERVIDOR:7780/cuotas/
```

**No hay una IP fija en el instalador.** La configuración conserva el encabezado `Host` únicamente para `/cuotas/`, de modo que la comprobación de origen y el token CSRF funcionan con el nombre o IP usado en cada servidor. No se deshabilita la protección CSRF. La ruta debe terminar en `/`; `/cuotas` redirige a `/cuotas/`.

Con HTTP, la contraseña del panel viaja sin cifrar por la LAN. Usá una clave exclusiva. Para otra exposición, utilizá VPN, túnel o HTTPS.

### Sin Apache

```bash
bash deploy/install.sh
```

El backend escucha solo en `127.0.0.1:8787`. Desde tu equipo:

```bash
ssh -N -L 8787:127.0.0.1:8787 usuario@servidor-carbonio
```

Entrá a `http://127.0.0.1:8787/`. Para agregarlo luego al Apache existente:

```bash
bash deploy/configure-apache.sh
```

El navegador usa autenticación básica. Para cerrar completamente la sesión, cerrá las ventanas de ese perfil o utilizá un perfil separado.

## Qué instala

- Código propiedad de root en `/opt/carbonio-quota-panel`.
- Usuario de sistema `carbonio-quota`, sin login, para la web.
- Puente propiedad de root en `/usr/local/libexec/carbonio-quota-bridge`.
- Una regla sudo sin argumentos que permite solo ejecutar ese puente como `zextras`.
- Configuración privada en `/etc/carbonio-quota-panel.env`, con hash salado de contraseña.
- Servicio `carbonio-quota-panel`, habilitado al arrancar el servidor.
- Auditoría en `/var/lib/carbonio-quota-panel/audit.db`.
- Con `--apache`, `/etc/apache2/conf-available/apache-cuotas.conf` y su habilitación.

No ejecuta comandos arbitrarios recibidos de la web. El puente solo admite consulta, inspección y cambio de `zimbraMailQuota`; valida identificadores y usa argumentos separados. La cuenta de servicio puede invocar ese puente para escribir, por lo que debe protegerse su acceso.

## Actualizar una instalación existente

No ejecutes el instalador otra vez. Sin cambios de cuota en curso, como root:

```bash
cd /usr/local/src/carbonio-quota-panel
git pull
bash deploy/update.sh --apache
```

Si no usás Apache, omití `--apache`.

El actualizador copia backend, puente, recursos y unidad de systemd. Conserva contraseña, configuración de origen, modo de edición y auditoría. Crea un respaldo privado en `/var/backups/carbonio-quota-panel.*`, incluyendo la base de auditoría en la ruta configurada; detiene brevemente solo el panel y restaura los archivos de aplicación anteriores si falla la actualización. Antes de confirmar el resultado comprueba que el panel responda con su autenticación HTTP, sin consultar ni modificar cuotas. El respaldo contiene el hash de contraseña y la auditoría: no lo publiques.

**Actualizar no cambia un `QUOTA_READ_ONLY=1` elegido anteriormente.** Para habilitar edición en una instalación antigua, editá `/etc/carbonio-quota-panel.env` y dejá `QUOTA_READ_ONLY=0`, luego reiniciá únicamente el panel.

Tras una actualización o reinicio, recargá completamente el navegador para obtener el nuevo token CSRF.

## Configuración

Archivo `/etc/carbonio-quota-panel.env`:

| Variable | Instalación nueva |
| --- | --- |
| `QUOTA_USER` | `admin` |
| `QUOTA_PASSWORD_HASH` | Hash generado durante la instalación |
| `QUOTA_BIND` | `127.0.0.1` |
| `QUOTA_PORT` | `8787` |
| `QUOTA_READ_ONLY` | `0`: edición habilitada |
| `QUOTA_AUDIT_DB` | `/var/lib/carbonio-quota-panel/audit.db` |
| `QUOTA_ORIGIN` | Sin definir: HTTP con el `Host` conservado por Apache |

Para acceso por un origen exclusivo o HTTPS, agregá el origen exacto, sin ruta ni barra final:

```ini
QUOTA_ORIGIN=https://cuotas.ejemplo.interno:7780
```

Para solo lectura, `QUOTA_READ_ONLY=1`. Después de modificar el archivo:

```bash
systemctl restart carbonio-quota-panel
```

No publiques el contenido de `QUOTA_PASSWORD_HASH`. No copies el archivo `.env` de un servidor a otro: cada instalación debe tener su propia contraseña. Si conservás un `QUOTA_ORIGIN` explícito en una instalación existente, debe coincidir con la dirección usada en el navegador; el actualizador no lo sobrescribe.

## Verificar cuotas

Como `zextras`:

```bash
carbonio prov gqu "$(zmhostname)"
carbonio prov ga cuenta@ejemplo.test zimbraMailQuota zimbraCOSId
carbonio prov -l ga cuenta@ejemplo.test zimbraMailQuota
carbonio prov gc default zimbraMailQuota
```

El panel usa **GiB = 1073741824 bytes**. Ejemplo: 45 GiB = 48318382080 bytes. Cuota **0 = ilimitada**. La lectura LDAP (`-l`) permite distinguir la excepción propia de la cuota heredada; el límite efectivo se consulta por separado.

Una cuota inferior al uso no borra mensajes, pero puede impedir operaciones normales. Cambiar una COS afecta a sus cuentas con cuota heredada; no modifica las excepciones propias. El cambio por consola y el panel se verificaron en la instalación del usuario; otras instalaciones/versiones deben comprobarse con una cuenta de prueba. No se certifica compatibilidad con todas las versiones.

## Rendimiento

Las lecturas de atributos usan el modo oficial `carbonio prov -f /dev/stdin`: un proceso atiende varias consultas. Solo se solicitan atributos concretos; no se exporta LDAP completo. La prueba con 80 cuentas y COS explícita verifica 5 procesos Java. Resolver COS predeterminadas de dominio agrega otro lote. El tiempo real depende del servidor; no se promete un tiempo fijo.

Los datos se reutilizan en memoria durante 60 segundos. “Actualizar” fuerza una consulta nueva. Antes de editar se consulta solo la cuenta o COS afectada y después se verifica el atributo escrito. No hay una transacción global que impida cambios externos en el intervalo entre comprobación y escritura.

## Diagnóstico

```bash
systemctl status carbonio-quota-panel --no-pager
journalctl -u carbonio-quota-panel -n 50 --no-pager
apache2ctl configtest
```

El puente registra errores de ejecución en el journal sin volcar la lista de buzones. La consulta rechaza lotes incompletos, duplicados o con formato desconocido. Se espera `gqu` con dos columnas (cuenta y bytes usados), más el aviso `WARNING:` observado en CE.

En Ubuntu 22.04/systemd 249, `RestrictAddressFamilies` activa implícitamente `NoNewPrivileges` y bloquea el cambio a `zextras` mediante sudo. La unidad distribuida evita esa directiva y declara `NoNewPrivileges=false`, conservando el usuario dedicado y las protecciones del sistema de archivos. Comprobación:

```bash
grep '^NoNewPrivs:' /proc/$(systemctl show carbonio-quota-panel -p MainPID --value)/status
```

Debe mostrar `0` para este diseño. No agregues filtros incompatibles con sudo sin cambiar primero el puente.

“Solicitud inválida”: recargá la página después de reiniciar; comprobá que Apache conserva `Host` con la configuración actual y, si definiste `QUOTA_ORIGIN`, que coincide con protocolo, nombre/IP y puerto del navegador. No quites la protección CSRF.

Historial: últimos 100 eventos, sin opción de borrado desde la web. Ante timeout o resultado “Revisar estado”, consultá la cuota antes de reintentar: la escritura podría haberse aplicado aunque fallara su verificación. Auditoría y configuración deben incluirse en los backups del servidor. Solo hay un administrador del panel; no hay identidad separada para cada operador.

## Desactivar

```bash
systemctl disable --now carbonio-quota-panel
```

Las cuotas ya aplicadas se conservan. Para quitar solo la ruta de Apache:

```bash
a2disconf apache-cuotas
apache2ctl configtest
```

Si muestra `Syntax OK`, `systemctl reload apache2`. PolicyD conserva `/webui/`.

## Desarrollo y pruebas

```bash
python3 -m unittest discover -s tests -v
bash -n deploy/install.sh
bash -n deploy/update.sh
bash -n deploy/configure-apache.sh
```

Las pruebas HTTP abren puertos temporales locales y usan respuestas simuladas; no modifican Carbonio. Los scripts de instalación se comprueban por sintaxis y contratos de configuración; no se ejecutan contra un sistema productivo durante estas pruebas. Sin telemetría, CDN, fuentes externas ni envío de buzones a terceros.
