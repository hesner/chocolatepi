# Solución de problemas

*[Read in English](../../TROUBLESHOOTING.md)*

Referencia organizada por síntoma. Encuentra lo que estás viendo, salta
directo ahí. Cada entrada acá es una falla real que este proyecto tuvo
alguna vez durante su propio desarrollo o pruebas — no algo hipotético.

## No se puede conectar a la Pi por SSH

**`ssh: Could not resolve hostname <nombre>.local`, de forma
intermitente** — la resolución `.local` (mDNS) no es totalmente
confiable en la práctica, especialmente por WiFi o después de mover la
Pi de lugar físicamente. No es un error de configuración que perseguir;
simplemente reintenta, o saca la IP real de la Pi de la lista de
clientes DHCP de tu router y conéctate por IP en su lugar. Prefiere
Ethernet sobre WiFi para sesiones de configuración/debugging si esto
sigue pasando.

**WiFi lento, con alta latencia, o inestable en general** — este
proyecto midió pérdida de paquetes real y ~200ms de latencia por WiFi a
distancia del router durante sus propias pruebas. Acércate, o cambia a
Ethernet — no hay arreglo de software para el alcance físico del WiFi.

## Arranca en "You are in emergency mode" (sin SSH, atascado)

Este es el bug del overlay de solo lectura, y es serio en un appliance
sin pantalla: emergency mode no levanta la red, así que SSH no es una
opción para arreglarlo remotamente — necesitas teclado y monitor
físicamente en la Pi, o arrancar la tarjeta SD desde otra máquina.

**Causa**: el `recurse=1` por defecto del sistema de archivos overlay
envuelve *todos* los mounts (no solo `/`) en su propio overlay,
incluido `/media/usb` — y ese overlay generado automáticamente no tiene
`nofail`. Si el USB de biblioteca está ausente al arrancar, ese mount
overlay falla, y como es crítico para el arranque, systemd cae a
emergency mode en vez de continuar.

**Arreglo**: `/boot/firmware/cmdline.txt` necesita
`overlayroot=tmpfs:recurse=0`, no `overlayroot=tmpfs` solo. Ver
`systemd/README.md` sección 4 para los pasos exactos (requiere remontar
`/boot/firmware` en lectura-escritura temporalmente para editarlo).
**Trampa**: cada vez que desactivas y reactivas el overlay
(`raspi-config nonint do_overlayfs 1` y luego `0`) para desarrollo
futuro, `do_overlayfs 0` reestablece el parámetro a `overlayroot=tmpfs`
solo — hay que rehacer la edición de `:recurse=0` cada vez, o este bug
vuelve.

## Un footswitch no hace nada — sin video, sin audio, sin error

Esto casi siempre es una falla silenciosa de "espacio vacío" en
`Library.resolve()`, no un problema de hardware o MIDI. Revisa, en
orden:

1. **`active_show.txt`** en la raíz del USB — ¿su contenido coincide
   exactamente con el nombre de una carpeta real bajo la raíz del USB?
2. **La carpeta `Set N`** — ¿existe para el grupo al que mapea ese
   footswitch? (Ver `MAVAVE_ANALYSIS.md` para la numeración de grupos
   del M-VAVE PD41 si ese es el controlador en uso.)
3. **El nombre del archivo en sí** — `LIBRARY.md` tiene la regla
   completa, pero la versión corta: debe ser exactamente `<Letra> -
   nombre.ext`, un espacio antes del guion, uno después, ni más ni
   menos. `A  - x.mp4` (dos espacios) o `A- x.mp4` (sin espacio) fallan
   en silencio de la misma forma que un espacio intencionalmente vacío
   — no hay ningún error para esto en ningún lado, por diseño (un
   espacio vacío es normal). Si tienes dudas, renombra el archivo para
   eliminar el espaciado como variable antes de asumir que algo más
   está mal.

## Un video está bien nombrado pero aun así no se reproduce

Problema de códec, no de nombre — son independientes y un archivo puede
tener ambos problemas a la vez (ver el ejemplo real en `LIBRARY.md`: un
`.MOV` con un error de espaciado que *además* era 4K 10-bit HEVC,
ninguno de los dos causado por el otro).

Revisa con `ffmpeg -i <archivo>` y mira la línea `Video:`. Este hardware
solo decodifica **H.264** por hardware. El metraje de celular
(especialmente iPhone) muy seguido es HEVC/H.265 por defecto, a veces
10-bit/HDR, a veces 4K — cualquiera de esos por sí solo puede ser
suficiente para que falle. Re-codifica según la tabla y el comando de
"Codificación recomendada para video grabado con el celular" de
`LIBRARY.md` antes de asumir que algo más está roto.

## El audio crackea/hace pops al cambiar de pista

Si esto reaparece después de haber sido arreglado antes, revisa estas
tres causas independientes (las tres fueron causa raíz real en
distintos momentos):

1. **Recargar el standby cuando ya está sonando** — `go_to_standby()`
   debe ser un no-op si el standby ya está cargado; recargarlo en cada
   pulsación del footswitch causa un glitch audible cada vez aunque
   nada cambie visiblemente.
2. **Discrepancia de tasa de muestreo** — confirma que
   `--audio-samplerate=48000 --audio-channels=stereo` se sigan forzando
   en ambas instancias de mpv (`src/core/player.py`); dejar que la
   fuente dicte la tasa causa que ALSA se reconfigure a mitad de
   sesión, lo que produce clicks.
3. **Alternar `aid=no`/`aid=auto`** en vez de `mute` — cambiar el ID de
   pista de audio activa desarma y reconstruye la conexión ALSA, lo que
   produce clicks. Usa `mute true`/`mute false` en su lugar; no toca el
   stream subyacente.

## Flash breve de pantalla negra/consola cuando cambia un clip

`mpv` necesita `--force-window=yes` en el carril de video, o la pantalla
de consola/login se hace visible brevemente por debajo durante una
transición. También revisa que `Player.play()` pre-encole el video de
standby como un ítem agregado (`loadfile ... append`) en vez de esperar
a que el clip termine naturalmente y reaccionar después — sin ese
pre-encolado, la propia pantalla de reposo de mpv ("Drop files or URLs
to play here") destella por un cuadro o dos entre que termina el clip y
empieza el standby.

## Cuelgue aleatorio, "Undervoltage detected!" en pantalla

Cargador con potencia insuficiente. Un cargador genérico de celular
(medido: un cargador de Chromecast) no necesariamente alcanza para una
Pi 2 haciendo decodificación 1080p simultánea + doble stream de audio +
un hub USB lleno de periféricos — confirmado vía `dmesg` mostrando el
hub USB desconectándose y reconectándose repetidamente al arrancar.
Arreglo: una fuente de verdad de 5V/2.5A. Revisa `vcgencmd
get_throttled` — un bit bajo distinto de cero significa que el
subvoltaje está (o estuvo recientemente) pasando de verdad, no es una
falsa alarma.

## Los cambios en la biblioteca no aparecen

Editar el USB mientras la Pi está corriendo y esperar que tome los
cambios en vivo no está soportado, por diseño (ver la sección
"Comportamiento del USB" de `systemd/README.md` para por qué se intentó
y abandonó el hot-swap automático). El flujo aprobado es: apagar,
editar el USB en otra computadora, reconectarlo, encender de nuevo. Un
reinicio **siempre** es necesario para tomar un cambio de biblioteca,
incluso uno hecho mientras la Pi ya estaba apagada.

## `mount: /media/usb: Read-only file system` al intentar editar directo en la Pi

Esperado — el USB de biblioteca está montado `ro` deliberadamente todo
el tiempo excepto durante gestión deliberada. Para editarlo directo en
la Pi (en vez de cambiarlo a otra computadora, el flujo normal): `sudo
umount /media/usb && sudo mount -o rw,nofail,x-systemd.device-timeout=10
/dev/sda1 /media/usb` (ajusta el dispositivo), haz los cambios, y vuelve
a montar `ro` de la misma forma antes de dejarlo. **Si el overlay de la
raíz está activo**, las escrituras a `/media/usb` caen en una capa de
overlay respaldada por RAM y **se descartan en el siguiente reinicio**
a menos que también desactives temporalmente el overlay de la raíz
primero (`do_overlayfs 1`, reiniciar) — si no, tus cambios van a parecer
funcionar por SSH y luego desaparecer en silencio.

## Los cambios de código/configuración en la Pi desaparecen después de reiniciar

El overlay de solo lectura de la raíz (`systemd/README.md` sección 4)
descarta cada escritura a `/` en cada reinicio, a propósito — esa es la
protección contra pérdida de energía. Si estás desarrollando activamente
en la propia Pi, desactiva el overlay primero (`sudo raspi-config
nonint do_overlayfs 1`, reiniciar), haz y verifica tus cambios, y luego
reactívalo (`do_overlayfs 0` **más la edición de `:recurse=0` a
`cmdline.txt`**, reiniciar) cuando termines. Olvidar el paso de
`:recurse=0` reintroduce el bug de emergency mode de arriba.

## El servicio falla una vez justo después de arrancar, luego se recupera solo

Esperado, no es un bug: `RuntimeError: Could not connect to mpv's IPC
socket ... No such file or directory` en el primer intento de arranque
es una carrera de orden de inicio (el proceso de Python arranca un poco
antes de que el socket de `mpv` esté listo). `Restart=always` reintenta
después de 5 segundos y normalmente tiene éxito en el segundo intento.
Solo vale la pena investigar más si sigue fallando repetidamente en vez
de recuperarse.

## `chocolatepi.org` no carga / sin HTTPS

1. Confirma que el DNS realmente propagó (https://dnschecker.org) antes
   de asumir que algo está roto — esto rutinariamente tarda 10-30
   minutos.
2. En Cloudflare, los registros DNS del dominio deben estar en **DNS
   only (nube gris)**, no Proxied (naranja) — GitHub no puede validar
   la propiedad del dominio ni emitir un certificado a través del proxy
   de Cloudflare.
3. En Settings → Pages del repo de GitHub, "Enforce HTTPS" se queda
   deshabilitado hasta que el propio chequeo de DNS de GitHub pase —
   esto es consecuencia del punto 1, no un problema aparte que
   debuggear.

## Un comando SSH con un nombre de archivo con espacios raros/múltiples falla con "No such file or directory" aunque el archivo exista

Es un artefacto de comillas del shell, no un archivo faltante — escribir
un doble espacio exacto (u otro espacio raro) dentro de comillas en una
línea de comando SSH no siempre sobrevive fielmente dependiendo del
shell local. Usa un glob en vez de intentar escribir el espaciado
exacto: `ssh host "cat /ruta/a/carpeta/*parte-del-nombre*"` en vez de
tratar de reproducir el nombre exacto a mano.
