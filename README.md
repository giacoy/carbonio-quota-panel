# Carbonio Quota Panel

Web interna sencilla para recuperar la consulta de uso y la administración de cuotas de correo en Carbonio CE. Se instala **en el servidor Carbonio**, separada de sus archivos y de su interfaz oficial.

## Qué permite

- Ver buzones del servidor local, bytes utilizados, límite efectivo, porcentaje y origen de la cuota (propia o heredada).
- Buscar y ordenar por consumo, porcentaje o nombre; exportar CSV.
- Modificar la cuota de una cuenta o quitar su valor propio para heredar de la COS.
- Modificar la cuota de cualquier COS, con aviso de alcance.
- Mostrar cuota ilimitada correctamente (0); no confundirla con uso cero.
- Confirmar cada cambio, volver a leer el valor en Carbonio y registrar anterior/nuevo/resultado en SQLite.
- Rechazar cambios si el límite cambió desde que se abrió la pantalla.

El uso proviene de `carbonio prov gqu`: **correo, calendarios y contactos**, sin Carbonio Files, copias de seguridad ni tamaño físico del disco. En multiserver solo lista buzones devueltos por `gqu` para el host local; una COS puede afectar cuentas de toda la instalación. No administra cuotas de dominio ni inventa equivalencias entre cuota de correo y cuota total.

## Estado de validación

Pruebas automatizadas locales para validación de entradas, autenticación, protección CSRF, conflictos de edición, lectura posterior y auditoría. **La integración real con Carbonio todavía debe validarse en modo lectura.** La interfaz y los comandos apuntan al entorno informado: Ubuntu 22.04, appserver 4.5.3, webui 4.5.14, admin-console-ui 0.20.4, shell-ui 15.3.5. Estos son datos de referencia, no una certificación de compatibilidad.

## Instalación (Ubuntu 22.04 / Python 3.10 o superior)

Copiá este repositorio al servidor. Necesitás `python3`, `sudo` y `systemd`; no hay paquetes Python ni Node para instalar. Como root, desde la carpeta del proyecto:

```bash
sudo bash deploy/install.sh
```

El instalador solicita **una contraseña nueva del panel**, independiente de la de Carbonio. Crea un usuario de sistema sin login, un servicio, un puente limitado hacia los comandos de Carbonio y un archivo de configuración con solo el hash de la contraseña. No modifica cuotas ni configura el proxy de Carbonio. No reinicia servicios de correo.

Por defecto escucha **solo en 127.0.0.1:8787 y en modo lectura**.

### Entrar desde tu equipo

Abrí un túnel SSH (reemplazá el host y usuario por los tuyos):

```bash
ssh -N -L 8787:127.0.0.1:8787 usuario@servidor-carbonio
```

Visitá **http://127.0.0.1:8787** y entrá con `admin` y la contraseña elegida. El navegador usa autenticación básica; para cerrar la sesión completamente cerrá sus ventanas o usá un perfil separado. No transmite la contraseña de Carbonio al navegador.

Para un acceso compartido sin túnel, colocá un **proxy HTTPS interno independiente** delante de este servicio, limitado a LAN/VPN. Mantené `QUOTA_BIND=127.0.0.1` y configurá `QUOTA_ORIGIN=https://cuotas.ejemplo.interno` con el origen exacto que abrirán los navegadores (sin barra final). El proxy debe conservar `Authorization`, `Origin`, `X-CSRF-Token` y permitir hasta 600 segundos de lectura. No expongas autenticación básica por HTTP en la red ni edites a mano el nginx administrado por Carbonio. Este repositorio no instala ni altera proxies ni certificados.

### Compartir Apache HTTP en el puerto 7780 con PolicyD

Para el despliegue interno solicitado: PolicyD permanece en `/webui/` y el panel en **`http://10.0.0.242:7780/cuotas/`**. Las rutas de recursos y API son relativas, así que también se conserva el acceso directo por túnel a la raíz del backend. No se agrega otro listener, no se habilita SSL y no se reemplaza el sitio de PolicyD.

Después de instalar el panel, como root desde este repositorio:

```bash
a2enmod proxy proxy_http
install -m 0644 deploy/apache-cuotas.conf /etc/apache2/conf-available/apache-cuotas.conf
a2enconf apache-cuotas
```

En `/etc/carbonio-quota-panel.env`, agregá o actualizá esta línea (sin la ruta `/cuotas/` ni barra final):

```ini
QUOTA_ORIGIN=http://10.0.0.242:7780
```

Conservá `QUOTA_BIND=127.0.0.1`. Reiniciá el panel y validá Apache **antes** de recargarlo:

```bash
systemctl restart carbonio-quota-panel
apache2ctl configtest
```

Solo si la validación termina con `Syntax OK`:

```bash
systemctl reload apache2
```

Abrí `/cuotas/` y comprobá que `/webui/` sigue funcionando. El HTTP es la opción interna solicitada; la contraseña del panel viaja sin cifrar por la LAN, así que usá una contraseña exclusiva. Para acceso desde fuera de esa red usá VPN, túnel SSH o HTTPS.

Si el panel ya estaba instalado antes de esta adaptación, ejecutá primero la sección **Actualizar** para copiar los recursos con rutas relativas; `git pull` solo actualiza el repositorio, no los archivos instalados en `/opt`.

Para quitar únicamente el proxy del panel: `a2disconf apache-cuotas`, comprobá con `apache2ctl configtest` y recargá Apache. PolicyD permanece en su ruta.

### Validar antes de habilitar edición

1. Comprobá que el número de buzones corresponde al servidor local. La primera carga y cada refresco vencido consultan los atributos por cuenta y pueden tardar; los datos se guardan hasta 60 segundos en memoria.
2. Compará varios consumos con `carbonio prov gqu "$(zmhostname)"`, ejecutado como `zextras`.
3. Compará límites y COS con `carbonio prov ga cuenta@ejemplo.test zimbraMailQuota zimbraCOSId` y `carbonio prov gc default zimbraMailQuota`.
4. Compará si hay valor propio con `carbonio prov -l ga cuenta@ejemplo.test zimbraMailQuota`. Si se omite ese atributo, el panel muestra herencia; el límite efectivo se consulta por separado sin `-l`.
5. Cuando esos datos coincidan, editá `/etc/carbonio-quota-panel.env`, cambiá `QUOTA_READ_ONLY=1` a `QUOTA_READ_ONLY=0` y reiniciá **solo el panel**:

```bash
sudo systemctl restart carbonio-quota-panel
```

Probá primero en una cuenta de prueba. La lectura previa a cada cambio es siempre nueva. En la interfaz se usan **GiB = 1073741824 bytes**: 45 GiB = 48318382080 bytes. Un límite de **0 significa ilimitado**. Una cuota por debajo del uso actual no borra correo, pero puede impedir operaciones normales del buzón.

Al cambiar una COS, se afectan las cuentas que heredan su límite. Las cuentas con un valor propio permanecen iguales. Para quitar una excepción de cuenta, usá “Heredar la cuota de la clase de servicio”. El panel verifica el atributo escrito; la propagación a otras sesiones y la aplicación operativa del límite se deben comprobar en Carbonio.

## Operación y diagnóstico

```bash
sudo systemctl status carbonio-quota-panel
sudo journalctl -u carbonio-quota-panel -n 50 --no-pager
```

En Ubuntu 22.04 (systemd 249), `RestrictAddressFamilies=` implica `NoNewPrivileges`, aunque `systemctl show` pueda mostrar el valor original. Eso impide que `sudo` ejecute el puente como `zextras`. El servicio distribuido evita esa directiva y declara `NoNewPrivileges=false`, conservando el usuario dedicado y las restricciones del sistema de archivos. No agregues filtros que vuelvan a impedir esa transición sin cambiar primero la arquitectura del puente.

Si instalaste una versión anterior, actualizá también la unidad (además del código):

```bash
sudo install -m 0644 -o root -g root deploy/carbonio-quota-panel.service /etc/systemd/system/carbonio-quota-panel.service
sudo systemctl daemon-reload
sudo systemctl restart carbonio-quota-panel
```

La protección efectiva puede consultarse con `grep '^NoNewPrivs:' /proc/$(systemctl show carbonio-quota-panel -p MainPID --value)/status`. Para el puente actual debe ser `0`. Los errores de ejecución sin una respuesta JSON válida ahora se registran en el journal sin volcar la lista de buzones.

Registro persistente: `/var/lib/carbonio-quota-panel/audit.db`. Incluye intentos pendientes, cambios verificados y resultados inciertos. Ante un timeout o “Revisar estado”, **consultá de nuevo antes de reintentar**: un cambio puede haberse aplicado aunque fallara la lectura posterior. El historial muestra los últimos 100 eventos. La interfaz no ofrece borrarlos.

La consulta rechaza formatos `gqu` desconocidos en vez de interpretar columnas ambiguas. El formato esperado es una cuenta y sus bytes utilizados por línea, más el aviso `WARNING:` observado en Carbonio CE. Si otra versión devuelve tres columnas, adaptá el parser con una muestra anonimizada antes de habilitarlo.

El servicio no ejecuta texto de la web como comandos de shell. El puente solo acepta consulta o cambio de `zimbraMailQuota`, usa argumentos separados y valida identificadores y cantidades. Se ejecuta como `zextras` mediante una única regla sudo sin argumentos. Su código y el de la aplicación pertenecen a root. El modo lectura bloquea escrituras HTTP; el puente conserva capacidad de escribir para cuando se habilite el panel. Protegé el acceso al usuario de sistema.

No sustituye una administración completa de Carbonio ni limita cambios hechos simultáneamente por otras herramientas entre la última consulta y la escritura. Hay un solo administrador del panel; para varios operadores con identidad individual hace falta agregar gestión de usuarios.

## Actualizar

Guardá copia de `/etc/carbonio-quota-panel.env` y `audit.db`. Detené el servicio, instalá los archivos nuevos con propietario root, conservando configuración y auditoría:

```bash
sudo systemctl stop carbonio-quota-panel
sudo install -m 0644 -o root -g root server.py bridge.py launch.py /opt/carbonio-quota-panel/
sudo install -m 0644 -o root -g root static/* /opt/carbonio-quota-panel/static/
sudo install -m 0755 -o root -g root bridge.py /usr/local/libexec/carbonio-quota-bridge
sudo systemctl start carbonio-quota-panel
```

## Desactivar

```bash
sudo systemctl disable --now carbonio-quota-panel
```

Esto deja Carbonio como estaba; las cuotas que ya se cambiaron permanecen. Para volver a una cuota anterior, consultá el historial y aplicá explícitamente ese valor.

## Desarrollo y pruebas

```bash
python3 -m unittest discover -s tests -v
```

Las pruebas web abren un puerto temporal en loopback, usan respuestas simuladas y nunca llaman al servidor Carbonio. No hay telemetría, CDN, fuentes externas ni envío de datos a terceros.
