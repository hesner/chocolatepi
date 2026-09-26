# Setlist Admin (WiFi) — guía de uso

*[Read in English](../../USAGE.md)*

Esta es una **expansión** (`expansions/setlist-admin-wifi/`) — ver el
`expansions/README.md` en la raíz del repo para qué significa eso. Es
la app web opcional para administrar el USB de biblioteca y el WiFi de
la Pi desde el navegador de un teléfono o computador, en vez de SSH +
`nano` + copiar archivos a mano. Diseño y razonamiento:
[`SPECIFICATION.md`](SPECIFICATION.md). No se instala por defecto —
ver "Instalación" abajo.

**Estado**: en pausa por un bloqueo de hardware (un dongle USB de WiFi
muerto, no un problema de diseño/código — ver la nota de estado en
`SPECIFICATION.md` y el `CHANGELOG.md` en la raíz del repo). Instala
esto cuando haya un adaptador de WiFi en buen estado con el cual
probar.

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

Luego, desde cualquier parte dentro del checkout del repo en la Pi:

```
sh expansions/setlist-admin-wifi/scripts/install.sh <tu-usb-uuid>
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
   (`SPECIFICATION.md` sección 2) — no cuentas por
   persona.
4. De ahí en adelante, visitar la app pide ese PIN.

**¿Olvidaste el PIN?** No hay flujo de email/link de reseteo — esto es
un appliance local sin sistema de cuentas. Recupéralo por SSH:

```
ssh pedal
sudo umount /media/usb && sudo mount -o rw /media/usb
rm /media/usb/.setlist-admin/pin.hash
sudo umount /media/usb && sudo mount -o ro /media/usb
```

La siguiente visita a la app lo trata como primera vez de nuevo y pide
definir un PIN nuevo.

## Usándola

**Pestaña Library**: elige o crea un show, crea/borra carpetas `Set`, y
para cada espacio de pista (A/B/C):
- **Upload new** sube un archivo directo a esa letra, reemplazando lo
  que hubiera. También se agrega automáticamente a la **biblioteca de
  canciones** (ver abajo), lista para reutilizarse en un show futuro
  sin volver a subirla.
- **Assign** (junto al selector desplegable de canciones) pone una
  canción existente de la biblioteca en esa letra, sin subir nada — una
  copia instantánea dentro del mismo USB.
- **Rename** cambia solo el nombre visible (la letra —su posición— y la
  extensión del archivo se mantienen).
- **Delete** vacía el espacio. Esto **no** borra la canción de la
  biblioteca — es una copia independiente (ver abajo).
- **Save to library**, visible cuando la casilla ya tiene algo, agrega
  esa copia específica a la biblioteca si todavía no estaba — útil para
  canciones asignadas antes de que existiera esta función, o desde otro
  dispositivo.

No hay un botón separado de "reordenar" — para cambiar qué canción está
en qué posición, sube/renombra para que el archivo correcto quede bajo
la letra correcta, o usa la acción de intercambio (reordenar arrastrando
puede agregarse más adelante; hoy es letra por letra).

Cada subida se valida de códec (`ffprobe`) — un video que no sea H.264
recibe una advertencia, no un bloqueo, apuntando a la guía de
codificación de `LIBRARY.md`. Igual se sube; puede que no se reproduzca
hasta que lo re-codifiques, igual que si lo hubieras copiado a mano.

### Biblioteca de canciones: reutilizar canciones entre setlists

La sección **"Song library"** al inicio de la pestaña Library (toca
para desplegarla) lista todas las canciones disponibles para
reutilizar — es la carpeta `_Songs/` en la raíz del USB (`LIBRARY.md`
documenta la misma convención para editar el USB a mano, sin esta app).
Está pensada para tener **todas las canciones que tiene la banda**, no
solo las del setlist que estás armando ahora, para que empezar el
setlist del próximo show sea cuestión de elegir entre lo que ya existe,
en vez de volver a subir todo.

Desde ahí puedes subir una canción nueva directo a la biblioteca (sin
asignarla a ningún Set todavía), renombrarla, o borrarla. **Borrar una
canción de la biblioteca no se recomienda — si tienes dudas, no la
borres.** `LIBRARY.md` recomienda tratarla como un registro permanente
de todo lo que tiene la banda, incluso canciones que no se usan en
ningún show en este momento, para que la biblioteca sea siempre una
respuesta honesta a "¿cuántas canciones tenemos realmente?". Una vez
borrada, la canción ya no se puede elegir al armar un Set (no aparecerá
en el selector para ningún show futuro) — pero borrarla **no** la quita
de ningún Set donde ya esté asignada; esos siguen sonando normal,
porque asignarla ya hizo una copia independiente. La confirmación de
borrado de la app lo explica así también. Desinstalar cualquiera de las
expansiones de `setlist-admin` tampoco borra `_Songs/` por defecto —
solo lo hace la bandera explícita `--purge-library` (ver "Desinstalar"
abajo). Y en la otra dirección: asignar una canción a un Set nunca la
quita de la biblioteca — cada asignación es una copia, la biblioteca
siempre conserva la suya.

**Los cambios necesitan un reinicio para aplicarse.** El pedal solo lee
la estructura de la biblioteca cuando arranca (`MASTER_SPECIFICATION.md`)
— esta app no cambia eso; edita todo lo que necesites, luego `ssh pedal
sudo reboot` cuando termines (la interfaz de esta expansión no tiene un
botón de reinicio integrado como sí tiene `setlist-admin-usb`).

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
(`SPECIFICATION.md` sección 5).

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
sh expansions/setlist-admin-wifi/scripts/rollback.sh
```

Agrega `--purge` para también borrar el PIN y las credenciales de WiFi
guardadas del USB; omítelo para conservarlos así una futura
reinstalación no necesita reconfigurarse desde cero. Agrega
`--purge-library` (aparte) para también borrar `_Songs/`, la biblioteca
compartida de canciones — no incluida en `--purge` porque borra
archivos de canciones reales, un paso más grande que reiniciar un PIN;
ver la recomendación de `LIBRARY.md` de tratar esa biblioteca como
permanente antes de usar esto. Ver las secciones 11-12 de
`SPECIFICATION.md` para exactamente qué toca cada bandera y qué no.
