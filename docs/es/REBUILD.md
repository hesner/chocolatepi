# Manual de reconstrucción (para un agente de IA)

*[Read in English](../../REBUILD.md)*

Una guía de arranque en frío, ordenada por ejecución, para reproducir
el estado funcional completo de este proyecto —checkout del código,
una Raspberry Pi flasheada y configurada, el pedal corriendo como
appliance de arranque automático— en un PC nuevo y una Raspberry Pi
nueva, sin acceso al historial de conversación que originalmente lo
construyó.

**Esto es un secuenciador, no un duplicado de la documentación real.**
Cada fase dice qué hacer y qué archivo tiene el cómo/por qué real; lee
ese archivo antes de actuar, no adivines solo con este resumen. Si el
resultado de una fase no coincide con su checkpoint, detente y
diagnostica antes de seguir — ver `TROUBLESHOOTING.md`.

## Antes de empezar

Confirma que realmente tienes:

- Una Raspberry Pi (este proyecto apunta a una **Pi 2**; otros modelos
  deberían funcionar pero no están validados — anótalo explícitamente
  si usas uno distinto).
- Una tarjeta microSD en blanco (8GB+), una forma de grabarla (esta
  guía asume Raspberry Pi Imager en el PC desde el que trabajas).
- Un controlador MIDI de pedalera USB. Si no es un M-VAVE PD41, todavía
  no tienes un Adapter validado — ver "Si el controlador no es un
  M-VAVE PD41" abajo antes de asumir que
  `src/adapter/mvave_adapter.py` aplica.
- Una interfaz de audio USB compatible con la clase estándar (validada
  contra una Behringer U-PHORIA UM2; cualquier interfaz compatible con
  la clase debería funcionar, según `MASTER_SPECIFICATION.md` sección
  2).
- Un USB para la biblioteca (cualquier sistema de archivos que `mount`
  soporte en Linux; el despliegue de referencia de este proyecto usa
  NTFS, de ahí el `ntfs-3g` de abajo — sustituye el driver correcto
  para el tuyo).
- Una pantalla HDMI.
- Acceso de red a la Pi (Ethernet fuertemente preferido para la
  configuración — este proyecto tuvo problemas reales y repetidos de
  WiFi/mDNS durante su propio desarrollo; ver `TROUBLESHOOTING.md`).
- Acceso shell/SSH desde el PC de trabajo, y suficiente permiso para
  correr `sudo` en la Pi.

No avances más allá de una fase cuyo checkpoint falle. No te saltes una
fase porque "debería" estar bien — cada trampa nombrada en
`TROUBLESHOOTING.md` fue una falla real que este proyecto ya tuvo una
vez.

## Fase 1 — Obtener el código fuente

```
git clone https://github.com/hesner/chocolatepi
cd chocolatepi
python3 -m unittest discover -s tests -v
```

**Checkpoint**: pasan los 27 tests, sin hardware de por medio. Si esto
falla, detente — nada más allá de este punto se puede confiar hasta que
el código base en sí quede verificado como sano en esta máquina.

Lee `MASTER_SPECIFICATION.md` secciones 1-4 ahora (las secciones 5-9
son sobre el proceso original de desarrollo asistido por IA, no hacen
falta para reconstruir). Ese es el registro de decisiones real — no
tomes la paráfrasis de esta guía como sustituto de eso.

## Fase 2 — Flashear la Pi y obtener acceso SSH

Sigue la sección 0 de `systemd/README.md` exactamente (elección de
imagen del SO, opciones avanzadas de Imager para hostname/SSH/usuario/
WiFi). Elige un hostname y recuérdalo — esta guía usa `pedal` para sus
propios ejemplos, igual que el resto de la documentación de este repo,
pero cualquier valor funciona mientras sustituyas consistentemente.

**Checkpoint**: `ssh <usuario>@<hostname>.local` (o por IP, si `.local`
no resuelve — esperado a veces, ver `TROUBLESHOOTING.md`) obtiene una
shell.

## Fase 3 — Instalar los prerequisitos de software

Sigue la sección 1 de `systemd/README.md`.

**Checkpoint**: `mpv --version`, `ffmpeg -version`, y (si usas NTFS)
`mount.ntfs-3g --version` funcionan todos.

## Fase 4 — Configurar el USB de biblioteca

1. Prepara el USB con la estructura que describe `LIBRARY.md`
   (`active_show.txt`, al menos un `<Nombre del Show>/Set 1/` con una
   pista de prueba — sigue el patrón de nombres de `LIBRARY.md`
   exactamente, especialmente la regla del espacio único alrededor del
   guion).
2. Obtén su UUID: `sudo blkid /dev/sda1` (o el dispositivo que
   corresponda — `lsblk` primero si no estás seguro).
3. Sigue la sección 2 de `systemd/README.md` para agregar la línea de
   `/etc/fstab` con ese UUID.

**Checkpoint**: `sudo mount -a && mount | grep /media/usb` lo muestra
montado `ro`.

## Fase 5 — Adaptar el código a este despliegue específico

Dos archivos necesitan los valores reales de esta Pi/USB, no los
placeholders del despliegue de referencia del propio repo:

- `systemd/pedal-core.service`: reemplaza `<YOUR_USER>` y
  `<YOUR_USB_UUID>` (ver `systemd/README.md` sección 3 para dónde y por
  qué exactamente).
- Confirma que `src/main.py --usb-uuid` en esa misma línea `ExecStart=`
  coincida con el UUID de la Fase 4.

**Si el controlador no es un M-VAVE PD41**: detente acá y no escribas
un `Adapter` nuevo adivinando. `MAVAVE_ANALYSIS.md` no es solo una
especificación para el PD41 — es un ejemplo trabajado de la
*metodología* (modos MIDI disponibles, rango/comportamiento de Program
Change, validación empírica contra hardware real, la corrección que
atrapó una suposición equivocada — 8 grupos, no 32) para caracterizar
un controlador desconocido antes de escribirle un Adapter. Repite esa
metodología contra el dispositivo real primero. Un Adapter nuevo debe
seguir emitiendo únicamente lo que `src/mapper/mapper.py` ya espera
(`SelectTrack`, `Stop`) — ver la regla de límite Adapter/Mapper/Core de
`CONTRIBUTING.md` antes de tocar nada fuera de `src/adapter/`.

## Fase 6 — Instalar e iniciar el servicio

Sigue la sección 3 de `systemd/README.md`.

**Checkpoint**: `sudo systemctl status pedal-core` muestra `active
(running)`; el video de standby es visible por HDMI; `journalctl -u
pedal-core -f` muestra `Core started, standby playing.` y `Connected to
the controller. Listening for actions...` sin un ciclo repetido de
caída/reinicio.

## Fase 7 — Validación funcional completa

No des esto por terminado hasta que cada uno de estos se haya
observado realmente, no asumido:

1. **Cada footswitch del controlador** dispara la pista/acción correcta
   (confirma contra el contenido real de tu propia carpeta Set, no solo
   que *algo* suene).
2. **STOP** funciona instantáneo desde cualquier estado.
3. **Las pistas de video y de solo audio** ambas se reproducen
   correctamente (un `.mp3`/`.wav` debería dejar el standby en loop
   debajo; un video debería reemplazarlo).
4. **Desconecta el USB de biblioteca, reinicia**: se reproduce el
   standby de respaldo local ("Please insert the USB..."), no emergency
   mode. Si obtienes emergency mode, todavía no hiciste el paso
   `recurse=0` de la Fase 8 — no te lo saltes asumiendo que es
   opcional, este checkpoint es exactamente para lo que existe.
5. **Reconecta el USB, reinicia**: el contenido real suena de nuevo.
6. **Corta la energía abruptamente** (sin apagado limpio) al menos una
   vez en reposo, y otra a mitad de reproducción, luego enciende de
   nuevo: arranca limpio, sin errores de sistema de archivos. Haz esta
   prueba *antes* de la Fase 8 también (la SD todavía no está protegida
   en ese punto) para tener una línea base, y de nuevo después, para
   confirmar realmente que el overlay es lo que la está protegiendo.

## Fase 8 — Blindarla (raíz de solo lectura, último paso a propósito)

Sigue la sección 4 de `systemd/README.md` — **incluyendo el paso
`recurse=0`**, no solo activar el overlay. Esto no es pulido opcional:
el valor por defecto (`recurse=1`) envuelve `/media/usb` en un overlay
sin `nofail`, lo que rompe el checkpoint 4 de la Fase 7 (arrancar sin
USB cae en emergency mode irrecuperable en vez del standby de
respaldo).

**Checkpoint**: vuelve a correr los checkpoints 4-6 de la Fase 7 ahora
que el overlay está activo, para confirmar que el blindaje no rompió
silenciosamente ninguno de ellos.

## Listo

En este punto la reconstrucción coincide con el estado de referencia
validado de este proyecto. Ten `LIBRARY.md` a mano para la gestión del
contenido día a día (no es un documento de configuración de una sola
vez, gobierna cada edición futura al USB de biblioteca) y
`TROUBLESHOOTING.md` para cualquier cosa que no coincida con un
checkpoint de arriba.
