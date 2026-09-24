# Setlist Admin — guía de uso

*[Read in English](../../SETLIST_ADMIN_APP.md)*

La app web opcional para administrar el USB de biblioteca y el WiFi de
la Pi desde el navegador de un teléfono o computador, en vez de SSH +
`nano` + copiar archivos a mano. Diseño y razonamiento:
`SETLIST_ADMIN_SPECIFICATION.md`. No se instala por defecto — ver
"Instalación" abajo.

**Solo pre/post-show.** Esto no está diseñado ni probado para editar la
biblioteca con un show en curso — la app muestra una advertencia si
detecta que el pedal está reproduciendo activamente, pero no bloquea;
trata esa advertencia como real, no como formalidad.

## Instalación

Opcional, y separada de la instalación base del pedal
(`systemd/README.md`). Requiere desactivar temporalmente el overlay de
solo lectura primero, igual que cualquier otro paso de instalación que
escriba en `/etc/systemd/system` (`systemd/README.md` sección 4):

```
sudo raspi-config nonint do_overlayfs 1
sudo reboot
```

Luego, desde la raíz del repo en la Pi:

```
sh scripts/install_setlist_admin.sh <tu-usb-uuid>
```

`<tu-usb-uuid>` es el mismo UUID que ya usa `--usb-uuid` de
`pedal-core.service` (`systemd/README.md` sección 3). Esto inicia
`setlist-network-watchdog.service`, que decide por sí solo cuándo debe
estar corriendo `setlist-admin.service` (ver "Cómo funciona el lado de
red" abajo) — no arrancas el servidor de administración directamente.

Reactiva el overlay cuando termines:

```
sudo raspi-config nonint do_overlayfs 0
```

Luego edita `/boot/firmware/cmdline.txt` y vuelve a agregar
`:recurse=0` — ver `systemd/README.md` sección 4, el mismo paso
requerido después de cualquier reactivación del overlay.

## Primer uso

1. Conecta tu teléfono al hotspot de la Pi (o tu computador a la misma
   red en la que está la Pi).
2. Visita `http://<hostname-o-ip-de-la-pi>:8080`.
3. Primera visita: define un PIN (mínimo 4 caracteres). Es
   autenticación compartida de un solo PIN
   (`SETLIST_ADMIN_SPECIFICATION.md` sección 2) — no cuentas por
   persona.
4. De ahí en adelante, visitar la app pide ese PIN.

**¿Olvidaste el PIN?** No hay flujo de email/link de reseteo — esto es
un appliance local sin sistema de cuentas. Recupéralo por SSH:

```
ssh pedal
sudo mount -o remount,rw /media/usb
rm /media/usb/.setlist-admin/pin.hash
sudo mount -o remount,ro /media/usb
```

La siguiente visita a la app lo trata como primera vez de nuevo y pide
definir un PIN nuevo.

## Usándola

**Pestaña Library**: elige o crea un show, crea/borra carpetas `Set`, y
para cada espacio de pista (A/B/C):
- **Upload** reemplaza lo que haya en esa letra.
- **Rename** cambia solo el nombre visible (la letra —su posición— y la
  extensión del archivo se mantienen).
- **Delete** vacía el espacio.

No hay un botón separado de "reordenar" — para cambiar qué canción está
en qué posición, sube/renombra para que el archivo correcto quede bajo
la letra correcta, o usa la acción de intercambio (reordenar arrastrando
puede agregarse más adelante; hoy es letra por letra).

Cada subida se valida de códec (`ffprobe`) — un video que no sea H.264
recibe una advertencia, no un bloqueo, apuntando a la guía de
codificación de `LIBRARY.md`. Igual se sube; puede que no se reproduzca
hasta que lo re-codifiques, igual que si lo hubieras copiado a mano.

Los cambios hechos a través de la app aplican al pedal en vivo en la
siguiente pulsación del footswitch — sin necesitar reiniciar
(confirmado en hardware real según el plan de pruebas de la sección 6
de `SETLIST_ADMIN_SPECIFICATION.md`).

**Pestaña WiFi**: opcionalmente define el WiFi de casa de la Pi (SSID +
contraseña). Si está definido y alcanzable, la Pi lo prefiere sobre el
hotspot del celular; si no es alcanzable, cae al hotspot
automáticamente. Ver "Cómo funciona el lado de red" abajo para qué hace
esto exactamente por debajo.

## Cómo funciona el lado de red

Se rastrean dos perfiles de WiFi: el hotspot del celular (el
default/respaldo de este proyecto, configurado una vez durante la
instalación) y una red de casa opcional (definida desde la pestaña
WiFi, en cualquier momento). Ambos se guardan cifrados en el USB de
biblioteca, atados a esta Pi específica + este USB específico — copiar
el archivo a otro par lo vuelve indescifrable, a propósito
(`SETLIST_ADMIN_SPECIFICATION.md` sección 5).

`setlist-network-watchdog.service` reaplica ambos perfiles a
NetworkManager en cada arranque (no sobreviven bajo el overlay de solo
lectura de la raíz de otra forma) y revisa la conectividad cada 30
segundos, arrancando `setlist-admin.service` solo mientras hay una IP
utilizable — correrlo sin ninguna red alcanzable solo desperdiciaría
RAM/CPU para nada.

## Desinstalar / revertir

Si esto alguna vez necesita salir —un bug, o simplemente decidir no
usarlo— `pedal-core.service`, el pedal en vivo realmente crítico, nunca
se toca al instalar o quitar esto:

```
sh scripts/rollback_setlist_admin.sh
```

Agrega `--purge` para también borrar el PIN y las credenciales de WiFi
guardadas del USB; omítelo para conservarlos así una futura
reinstalación no necesita reconfigurarse desde cero. Ver la sección 11
de `SETLIST_ADMIN_SPECIFICATION.md` para exactamente qué toca y qué no.
