# Próximos pasos para setlist-admin-usb

*[Read in English](../../NEXT_STEPS.md)*

**Lee esto primero si vas a retomar este proyecto** — seas Claude,
cualquier otro agente de IA, un colaborador humano, o yo mismo en el
futuro. Está escrito para entenderse en frío, sin necesitar el
historial de la conversación que lo produjo.

## Dónde están las cosas (al commit `9209a29`, 2026-09-27 — revisa el
log de git por si hay algo más nuevo, este archivo se queda un poco
atrás de los commits por naturaleza)

El renombramiento de terminología Show/Set/Bank (ver la entrada
"Renamed the library's terminology..." de `CHANGELOG.md`) y una
validación completa en hardware real de `setlist-admin-usb` ya están
**comiteados, subidos a `main`, y confirmados como persistentes en el
Pi real** (sobrevivieron un reinicio real después de desplegarse
correctamente — ver "Desplegar al Pi" más abajo sobre por qué eso no es
automático). `setlist-admin-wifi` recibió los mismos cambios de código
por paridad, pero **no** se ha probado en hardware propio (sigue
bloqueada por un dongle USB de WiFi muerto — ver su propio
`SPECIFICATION.md`).

Los bugs reales encontrados y corregidos durante esta ronda están
detallados en la sección "Sin publicar" de `docs/es/CHANGELOG.md` y en
`SPECIFICATION.md` secciones 0/14 (en inglés) — no los vuelvas a
descubrir de cero:
- Fallo transitorio de `umount` (EBUSY) → ahora reintenta.
- El USB de biblioteca se ha observado desmontándose solo, sin ninguna
  evidencia correspondiente en ningún registro — causa raíz **no
  confirmada**, pero se capturó una caída real de voltaje
  (`vcgencmd get_throttled` mostró subvoltaje) durante esta sesión, la
  pista más fuerte hasta ahora. `usb_mount.py` ahora se autorepara de
  todas formas.
- Un doble toque podía hacer chocar dos ciclos de remontaje →
  `writable_usb()` ahora es un candado de todo el proceso.
- Que el teléfono se desconecte a mitad de una subida dejaba archivos
  huérfanos `.part`/`.swaptmp` para siempre → ahora se limpian en cada
  arranque del servidor.
- `rename_song()`/`delete_song()` no verificaban que el archivo
  siguiera existiendo → corregido, ya sigue el mismo patrón que el
  resto de `library_ops.py`.
- Frontend: faltaba manejo de errores, el scroll saltaba al recargar
  listas, y el destello de confirmación en los botones aparecía al
  recibir respuesta en vez de al tocar → todo corregido. Ver los
  comentarios de `flashSuccess()`/`clearFlash()`/
  `beginScrollPreservation()` en `static/app.js` para el razonamiento —
  sigue ese mismo patrón para cualquier botón nuevo que agregues.

Se agregó **Export Set**: una vista a pantalla completa, en letra
grande, con el repertorio del Set seleccionado, con un botón "Share"
que la convierte en PNG y la entrega al menú nativo de compartir del
teléfono. Ver `SPECIFICATION.md` sección 14 (en inglés) para el diseño.

**Corregido y confirmado por el usuario (2026-09-27, después de lo
anterior)**: seleccionar un Set en el desplegable nunca marcaba
realmente ese Set como el activo para el pedal — solo *crear* un Set
nuevo lo hacía, vía `set_active_set`. Cambiar entre Sets que ya
existían no hacía nada para la reproducción, sin importar cuántas veces
seleccionaras uno distinto. Corregido: "Reboot now to apply" ahora
llama a `POST /api/sets/active` con el Set que esté seleccionado justo
antes de reiniciar. **No trasladado a `setlist-admin-wifi`** — esa
expansión no tiene botón propio de reinicio (su `USAGE.md` ya le dice
al usuario que haga `ssh pedal sudo reboot` a mano), así que la
corrección equivalente ahí necesitaría su propia decisión de diseño
(ej. marcar como activo de inmediato al seleccionar en el desplegable,
ya que no hay un momento de "aplicar" del cual colgarse) — todavía no
diseñada, ni mucho menos construida.

**También documentado (2026-09-27, sin cambio de código)**: una
respuesta consolidada a "¿está la Pi protegida ante un corte de luz, y
cuáles son las ventanas de riesgo reales?" en `TROUBLESHOOTING.md`/
`docs/es/TROUBLESHOOTING.md` (sección nueva cerca del inicio) y
`systemd/README.md` sección 4. Versión corta: segura durante el uso
normal en un show (root/`boot`/USB están respaldados en RAM o en
solo-lectura en ese momento); las ventanas reales son el remontaje `rw`
breve de `/media/usb` durante una edición de biblioteca, el overlay
desactivado para desarrollo, y la edición a mano de `cmdline.txt` — las
últimas dos solo de mantenimiento. Se señala una fuente de poder
insuficiente (no un desenchufe limpio) como el disparador más probable
en la práctica, según un evento de under-voltage observado directamente
por este proyecto.

**2026-10-01, incidente real investigado y corregido (cambio de código,
todavía no desplegado a la Pi al momento de escribir esto — revisa
`VERSION`/el log de git para saber si ya llegó ahí)**: el usuario
reportó que el audio se detuvo por completo tras aproximadamente una
hora de pruebas intensivas en hardware real. Investigando en vivo por
SSH, resultó que el M-VAVE estaba apagado, y `pedal-core.service` se
sorprendió a mitad de un bucle de crasheos (el contador de reinicios
subiendo cada ~10s) — `main.py` trataba "controlador MIDI no
encontrado" como fatal, saliendo y dependiendo por completo de que
`systemd` reiniciara el proceso entero a ciegas (tumbando y volviendo a
levantar los dos procesos `mpv` en cada ciclo — parpadeo visible,
silencio total, cero explicación en pantalla) mientras el controlador
siguiera ausente. Corregido: ver la entrada de `CHANGELOG.md` en "Sin
publicar" y la nueva sección de `TROUBLESHOOTING.md` "El audio (y el
video) se detienen..." para el detalle completo: `main.py` ahora
reintenta la conexión MIDI dentro del mismo proceso sin tumbar `mpv`.
(Una segunda corrección llegó en la misma tanda — registrar el propio
stderr de `mpv` en vez de descartarlo — pero se **revirtió el mismo
día**: ese log vive en el overlay de raíz respaldado en RAM sin
rotación, así que dejarlo encendido permanentemente se consideró que no
valía el riesgo constante de agotar la RAM por un beneficio que solo
sirve durante una sesión activa de debugging. Captúralo temporalmente,
a mano, la próxima vez que de verdad haga falta — no vuelvas a
desplegar ese parche de forma permanente. Ver la entrada `v2026.10.01`
de `CHANGELOG.md` para el razonamiento completo.)
**También agregado, misma sesión, a pedido explícito del usuario**:
gestión del video de standby en las dos apps
`setlist-admin` (elegir cualquier video de la biblioteca como el nuevo
`standby.mp4` — `USAGE.md`, `library_ops.set_standby_video()`). **Desplegado y verificado en la Pi real (2026-10-01, commit `886d4d0`,
cortado como `v2026.10.01`)**: se completó el procedimiento completo de
desactivar overlay/desplegar/probar/reactivar/reiniciar; los 324 tests
(27+139+158) pasaron en la Pi misma; `pedal-core.service` reinició
limpio con el M-VAVE conectado y quedó confirmado persistente después
del reinicio final; `get_standby()` confirmó leer correctamente el
`standby.mp4` real del USB montado. **No confirmado de forma
independiente**: tocar realmente "Set as standby" desde un teléfono y
ver visualmente el nuevo video en loop — eso habría sobrescrito el
`standby.mp4` real y actualmente en uso de la banda (754MB), así que no
se hizo en vivo sin que el usuario estuviera presente para confirmar el
resultado y restaurar si hiciera falta. Haz esto primero, igual que el
precedente de Export Set más abajo.

**2026-10-01, más tarde el mismo día — botón "Optimize" a nivel de
biblioteca, construido, desplegado y probado en hardware real
(commits `e1fafe6`, `8f187fb`)**: pedido real del usuario, justo
después de la conversión manual del video de standby de arriba — en
vez de re-codificar un video marcado a mano por SSH cada vez, la
biblioteca de canciones ahora muestra un botón "Optimize" junto a
cualquier archivo que `codec_check.is_optimized()` marque, respaldado
por un nuevo daemon siempre activo, `library-optimizer.service`, y una
cola de trabajos persistente basada en archivos (`optimize_queue.py`)
para que un trabajo largo sobreviva a que el teléfono que lo encoló se
desconecte. Ver la entrada "Sin publicar" de `CHANGELOG.md` y la
sección 15 de `SPECIFICATION.md` (en inglés) para el diseño completo.
Trasladado a las dos expansiones, 181 (USB) + 200 (WiFi) pruebas
pasando.

Desplegado en la Pi real la misma sesión, ciclo completo de overlay
(ver "Notas operativas" abajo — `raspi-config nonint do_overlayfs 1`
por sí solo **no** quitó el sufijo personalizado `:recurse=0` de
`cmdline.txt`, hizo falta un `sed` manual encima, igual que al
desactivarlo; vale la pena recordarlo la próxima vez en vez de
redescubrirlo). Se encontró y corrigió un bug real en el proceso:
`library-optimizer.service` entraba en bucle de fallos bajo `systemd`
(`ModuleNotFoundError: No module named 'admin'`) porque
`library_optimizer.py` nunca agregaba `src/` al `sys.path` como sí
hace `server.py` — invisible para la suite de pruebas, que ya pone
`src/` en el path ella misma. Corregido, redesplegado, confirmado
corriendo de verdad (no solo "active" en medio de un bucle de fallos).

Después se hizo una prueba real de punta a punta por SSH: un clip
HEVC sintético pequeño (`ffmpeg -f lavfi testsrc`, 3s) subido vía
`AdminAPI.upload_song()`, encolado con `request_song_optimization()`,
recogido por el daemon en pocos segundos, confirmado re-codificado a
H.264 y la cola limpia (`needs_optimization: False` después).
`pedal-core.service` y la reproducción de `standby.mp4` no se vieron
afectados en ningún momento. La canción de prueba se borró después.
**Todavía sin confirmar**: el flujo real desde la app del celular —
tocar "Optimize" desde la app misma, ver el botón decir
"Optimizing...", y en particular desconectar/reconectar el celular a
mitad del trabajo para confirmar que el estado de verdad persiste
visualmente, no solo a nivel de `AdminAPI`/archivo de cola como ya se
probó arriba. **Haz esto a continuación** — el usuario está a punto de
hacerlo justo al momento de escribir esto.

**2026-10-01, más tarde el mismo día — un incidente real de pérdida de
datos en `standby.mp4`, encontrado y recuperado**: el usuario reportó
que el video real de standby de la banda (~55 minutos, ~754MB) había
desaparecido — reemplazado esa misma tarde desde el propio selector
"Set as standby" de la app, sin forma de volver atrás. Causa raíz,
confirmada en el código: `library_ops.set_standby_video()` simplemente
copia la canción elegida directo sobre `standby.mp4`, sin preguntar
nada. Funciona bien hasta que alguien elige el video equivocado, que
es exactamente lo que pasó: el standby real de ~55 minutos de la banda
desapareció, irrecuperable desde la propia Pi, y solo volvió porque
por suerte todavía existía una copia en otro lado. Al usuario se le
preguntó en el momento si quería agregar un respaldo automático y dijo
que sí a recuperar el video perdido específicamente, pero la función
de respaldo en sí nunca se construyó en la sesión que siguió —
retómalo explícitamente en vez de asumir que ya está hecho. Una forma
razonable: antes de copiar, mover el `standby.mp4` actual a algo como
`backup/standby-previous.mp4` (un solo cupo, que se sobrescribe cada
vez, no un historial que crece sin límite — este USB tiene espacio
limitado y la meta no es un historial completo, solo "no perder el de
antes de este"). Usa el mismo mecanismo de `_atomic_copy_file()`/
`writable_usb()` ya usado en otros lados, así que es un cambio pequeño
y autocontenido una vez que alguien decida la forma exacta del nombre/
retención del respaldo. Ver "Decisiones de producto pendientes" abajo.

Se recuperó solo porque el usuario todavía tenía el archivo fuente
original, sin convertir (`nofuturo-visuales-julio10.mp4`, 6.68GB,
H.264 1080p pero a ~15.7Mbps — demasiado pesado para usar directo), en
otro computador. Se re-codificó a ~1.8Mbps (coincide casi exacto con el
bitrate del original perdido: 754MB en 55.66 minutos son ~1.8Mbps)
usando `h264_v4l2m2m` tanto para decodificar como para codificar —
confirmado en vivo a ~0.87x en tiempo real, muchísimo más rápido que el
~0.1x que este proyecto vio antes con decodificación HEVC solo por
software, ya que la fuente aquí ya era H.264 y el códec por hardware
de esta Pi lo maneja nativo en ambos sentidos. El resultado (~800MB) se
subió a la biblioteca como "Standby Original.mp4" (`AdminAPI.upload_song()`
simple, deliberadamente no `set_standby_video()` — el usuario quería
decidir él mismo si y cuándo volver a hacerlo standby, no que se
forzara). Después lo hizo exactamente así, desde una sesión web
temporal (ver abajo) y reinició para aplicarlo — confirmado por el
propio socket IPC de `mpv` que `standby.mp4` ya es ese archivo exacto.
**`set_standby_video()` sigue sin ningún paso de respaldo — ver
"Decisiones de producto pendientes" abajo.**

La misma investigación también mostró un detalle a recordar sobre
transferencias: se conectó un dongle WiFi USB nuevo mientras un archivo
de 6.68GB se transfería por `scp` a la Pi, y el usuario pidió apagar el
Ethernet en cuanto fuera seguro — confirmado que la resolución
`mDNS`/`pedal.local` se vuelve inestable con dos interfaces activas a
la vez (`eth0`+`wlan0`) — la misma causa raíz que la versión ya
documentada de este problema con `eth0`+`eth1`, solo que ahora con una
interfaz WiFi en vez de otra cableada/tethered. Usar la IP directa del
WiFi con `-i ~/.ssh/id_ed25519_pedal -o IdentitiesOnly=yes` lo resolvió
cada vez.

También encontrado en vivo, vale la pena recordarlo tal cual:
**`pkill -f '<patrón>'` corrido por SSH puede matar su propia sesión de
SSH** si el texto del patrón que pasas aparece en la línea de comando
del propio shell que lo invoca (y va a aparecer, de forma trivial, ya
que acabas de escribir exactamente ese string como argumento) —
`pkill -f` compara contra la línea de comando completa, no solo la del
proceso que buscas. Mató el wrapper de bash remoto en vez de `ffmpeg`,
y se vio como un simple exit 255 de SSH sin ningún error del lado
remoto. Arreglo: compara por nombre exacto de proceso
(`pkill -TERM ffmpeg`, sin `-f`), o haz que el patrón sea lo bastante
específico para que no pueda coincidir también con su propia
invocación.

**También en esta misma investigación**: un arreglo de código que solo
se había "desplegado rápido" (traído mientras el overlay protector
estaba activo, así que solo vivió en la capa superior respaldada en
RAM) se perdió en silencio cuando el overlay se desactivó y reinició
después por una razón *no relacionada* (necesitar espacio real en
disco para la conversión de 6.68GB de arriba) — el checkout de git
volvió al último commit que de verdad se había desplegado de forma
durable. Se volvió a traer en cuanto se notó (confirma con
`git log --oneline -1` después de cualquier reinicio, cualquiera, no
solo los de tu propio trabajo de despliegue — no asumas que un commit
desplegado rápido sobrevivió solo porque nada de lo que *tú* hiciste
debía reiniciar la Pi).

## 2026-10-02: Optimize/Cancel confirmado en vivo, un día completo de
bugs de hardware real, y un selector de idioma

**El flujo real en la app del celular para el botón "Optimize" (punto
1 de abajo, tal como estaba al final del 2026-10-01) ya quedó
confirmado a fondo** — no solo una vez, sino a lo largo de una sesión
extendida de uso real: se tocó "Optimize" desde el celular varias
veces, se vio la ventana de advertencia, se vio el botón verde
permanente "Optimizando" junto a "Cancel", se tocó "Cancel" mismo
(incluyendo mientras `ffmpeg` estaba codificando activamente,
confirmado con cronometraje directo vía `AdminAPI`: la llamada
devolvió en ~0.02s y el proceso real de `ffmpeg` desapareció en
~10s), y se confirmó que la canción vuelve a un estado limpio, sin
optimizar, listo para un nuevo toque de "Optimize". La persistencia al
desconectar/reconectar que pedía este punto es inherente al diseño (la
cola es basada en archivos, el demonio es una unidad systemd separada)
y se puso a prueba de forma incidental durante todas las pruebas del
día sin problema.

Se encontró y corrigió una cadena larga de bugs reales el mismo día,
cada uno a partir de un reporte real del usuario mientras usaba la app
activamente, no de una revisión de código — el detalle completo, una
entrada por corrección, está en la sección `[Sin publicar]` de
`CHANGELOG.md` (más reciente primero): un bug de centrado de
formularios solo visible en tablet; una demora de ~37s entre iniciar
sesión y que aparecieran las canciones (llamadas a `ffprobe` seriales,
sin caché); un timeout transitorio de `ffprobe` bajo carga que se
guardaba *permanentemente* como "no optimizado"; `ffmpeg` manteniendo
abierta la fuente montada en el USB durante *toda* la codificación,
bloqueando cualquier otra escritura de la biblioteca (por ejemplo,
"crear Bank" sin relación) todo ese tiempo; un aviso obsoleto quedado
dentro de la imagen para compartir de Export Set específicamente (el
de pantalla ya se había quitado); falta de `Cache-Control` en archivos
estáticos, dejando que una combinación vieja de `app.js`/`index.html`
mostrara una página que parecía atascada mostrando solo la barra
superior; el mismo hueco para `GET /api/songs` en particular, mostrando
una canción como ya optimizada mientras un trabajo seguía corriendo de
verdad; y, encontrado al final, cancelar un trabajo podía arrojar error
500 si se tocaba dentro de aproximadamente el primer minuto (mientras
el nuevo paso de copia a scratch todavía leía la fuente del USB) —
arreglado moviendo el marcador de cancelación fuera del USB por
completo, a almacenamiento local de la Pi
(`optimize_queue.DEFAULT_STATE_DIR`), ya que nunca necesitó vivir ahí
en primer lugar. **Confirmado en vivo** con una llamada directa y
cronometrada a `AdminAPI.cancel_song_optimization()` contra un trabajo
real, activamente codificando.

**También se agregó, el mismo día, por pedido explícito del usuario**:
un selector de idioma ES/EN completo (`static/i18n.js`, ambas
expansiones) — un menú desplegable en la barra superior (que ahora
dice "ChocolatePi - Setlist Admin") cambia cada etiqueta, botón,
confirmación, alerta y notificación entre inglés y español, guardado
por navegador vía `localStorage`. Los nombres de canciones, pistas,
Sets y Banks explícitamente nunca se traducen (son datos del usuario,
no texto de interfaz) — cada función de renderizado en `app.js` deja
esos valores fuera de las llamadas de traducción a propósito. Los
mensajes de error que vienen del servidor siguen en inglés por ahora,
un trabajo aparte, explícitamente diferido si alguna vez se quiere. Se
agregó también una actualización automática (`GET /api/songs` cada 5s
mientras algo esté en cola o corriendo, deteniéndose sola si no) para
que el estado del botón Cancelar/Optimizar nunca necesite un refresco
manual para ponerse al día.

**Todavía sin hacer, vale la pena pronto**: `USAGE.md`/`docs/es/USAGE.md`
(ambas expansiones) y `CHANGELOG.md`/`docs/es/CHANGELOG.md` se
actualizaron con todo lo anterior al momento de escribir esto — pero
`VERSION` **no** se actualizó (no se "cortó" ninguna versión esta
sesión; todo lo anterior sigue en `[Sin publicar]`). Si se quiere un
punto de control limpio, ese es el siguiente paso pequeño: confirmar
que nada se regresionó, subir el `VERSION` de ambas expansiones,
renombrar `[Sin publicar]` a la fecha de hoy.

## Lo que sigue genuinamente sin confirmar — haz esto antes de confiar en ello

1. **La corrección visual de Export Set está desplegada pero no
   reconfirmada.** Salió por primera vez con un bug real de CSS
   (`.export-view` tenía un `display: flex` incondicional que
   sobreescribía la regla propia del navegador `[hidden] { display:
   none }`, así que la vista aparecía, vacía, en cada carga de página —
   ver el último párrafo de la sección 14 de `SPECIFICATION.md`). Eso
   se corrigió y se desplegó, pero nunca se le pidió al usuario que
   volviera a abrir "Export Set" y confirmara que ahora se ve bien de
   punta a punta (título con contenido, lista numerada con contenido,
   cierre por ✕/Escape/atrás funcionando). **Haz esto primero.**
2. **La segunda corrección del salto de scroll (el "destello de ~1
   segundo al top") se desplegó pero tampoco se reconfirmó
   explícitamente** — el usuario pasó a pedir Export Set justo después
   de desplegarla, sin confirmar. Pídele que renombre o borre una
   canción estando desplazado hacia abajo en un Bank posterior y
   confirma que ya no hay ningún salto visible.
3. **El soporte de navegador de escritorio/PC para el botón "Share" de
   Export Set está explícitamente sin certificar** — `navigator.share()`
   con archivos adjuntos tiene poco soporte en navegadores de
   escritorio; el código cae a una descarga simple, pero esto nunca se
   ha probado desde un PC real. Hazlo cuando llegue el trabajo de
   accesibilidad por PC de `setlist-admin-wifi` (ver la lista ordenada
   abajo), ya que esa es la expansión pensada para usarse desde un
   computador en la red de casa.

## Plan de pruebas ordenado — continúa acá

Es la misma lista que el usuario pidió seguir "paso a paso" en esta
sesión. Los puntos 1-2 están hechos; retoma en el 3:

1. ~~Reboot-to-apply~~ — hecho, validado con un reinicio real.
2. ~~Resistencia a desconexión a mitad de edición~~ — hecho; se
   encontró y corrigió el bug de archivos temporales huérfanos (ver
   arriba).
3. **Renombrar/borrar una canción de la biblioteca desde la app** —
   confirmado funcionalmente por el usuario, pero ver el punto #2 de
   "sin confirmar" arriba (la corrección del salto de scroll en este
   flujo exacto necesita una revisión fresca).
4. **Desinstalar / rollback** — no iniciado. Correr
   `expansions/setlist-admin-usb/scripts/rollback.sh` en el Pi real y
   confirmar: `pedal-core.service` nunca se detiene/reinicia/toca, las
   dos unidades systemd de setlist-admin desaparecen, y (sin
   `--purge`/`--purge-library`) el PIN y `_Songs/` sobreviven para una
   futura reinstalación. Ver la sección 11 de `SPECIFICATION.md` para
   exactamente qué debería y no debería tocarse.
5. *(Opcional, no bloqueante)* Probar con un segundo teléfono
   (idealmente Android, para ejercitar los drivers
   `rndis_host`/`cdc_ether`/`cdc_ncm` que esta sesión solo probó con un
   iPhone y su `ipheth`).

## Decisiones de producto pendientes — no construidas aún, necesitan decisión primero

**La de mayor prioridad de las tres de abajo, dado que ya costó datos
reales una vez**: respaldar el `standby.mp4` anterior antes de
reemplazarlo. `library_ops.set_standby_video()` hoy simplemente copia
la canción elegida directo sobre `standby.mp4`, sin preguntar nada —
funciona bien hasta que alguien elige el video equivocado, que es
exactamente lo que pasó el 2026-10-01 (ver "Dónde están las cosas"
arriba): el standby real de ~55 minutos de la banda desapareció,
irrecuperable desde la propia Pi, y solo volvió porque por suerte
todavía existía una copia en otro lado. Ver la sección de arriba para
la forma razonable sugerida (un solo cupo de respaldo,
`backup/standby-previous.mp4`, sobrescrito cada vez).

Dos cosas más que el usuario planteó y pidió explícitamente dejar para
después:

- **Mostrar el nombre de archivo crudo tal cual está guardado (ej. "A -
  Perro.wav") en vez del nombre visible en las tarjetas principales de
  Bank/track** (no en Export Set, que ya hace esto por diseño — ver
  sección 14). Se discutió a fondo; se identificaron riesgos reales
  (redundante con el círculo de letra que ya se muestra, el texto más
  largo se corta más agresivamente, las mayúsculas de la extensión se
  vuelven visibles/inconsistentes, y **no** revela realmente un nombre
  de archivo mal formado en el USB, ya que esos son invisibles para
  `list_tracks()`/`list_songs()` de todas formas). Si se retoma: debería
  ser un cambio **solo visual** — el flujo de "Renombrar" debe seguir
  editando únicamente la parte del nombre visible, nunca la
  letra/extensión directamente, o se reabre exactamente el riesgo de
  fallo silencioso de nombres de archivo que `library_ops.py` fue
  construido para hacer estructuralmente imposible (ver el docstring
  del propio módulo).
- **Una recomendación formal en la app/documentación contra editar el
  USB a mano una vez que una expansión está instalada.** El usuario
  preguntó cómo maneja la app actualmente que alguien renombre/borre
  archivos directamente en el USB fuera de la app. Respuesta (verificada
  en el código, esta sesión): **ya es mayormente seguro** — nada queda
  en caché, cada pantalla relee el USB de nuevo, y
  `list_tracks()`/`_require_set()`/`_require_bank()`/
  `assign_song_to_slot()` todos revisan el estado actual de forma
  defensiva. El único hueco real encontrado (`rename_song()`/
  `delete_song()` sin verificar existencia) ya está corregido. Lo que
  **no** se hizo: escribir de verdad una recomendación de "no edites el
  USB a mano una vez que uses la app" en `LIBRARY.md`/`USAGE.md`. Vale
  la pena hacerlo si el usuario todavía lo quiere, pero es una adición
  de documentación, no una corrección de código — nada está actualmente
  roto por ediciones manuales más allá de ese hueco ya corregido.

## Notas operativas para quien despliegue al Pi después

Estas costaron tiempo real descubrirlas esta sesión — no las
reaprendas por las malas:

- **Verificar versiones**: este proyecto y cada expansión ahora llevan
  un archivo `VERSION` basado en fecha (`vAAAA.MM.DD`) — ver la sección
  "Versionado" del `CHANGELOG.md` raíz para el esquema. En la Pi real:
  `ssh -4 pedal "cat ~/chocolatepi-repo/VERSION ~/chocolatepi-repo/expansions/*/VERSION"`.
  Recuerda que un archivo `VERSION` solo refleja la realidad si alguien
  lo actualizó en el mismo commit que el cambio — el hash del commit al
  que está sincronizado siempre es la fuente de verdad definitiva.
- **SSH**: siempre `ssh -4 pedal` / `scp -4 ... pedal:...` (forzar
  IPv4; tener `eth0`+`eth1`+mDNS mezclados causa cuelgues de varios
  minutos en comandos triviales si no).
- **El Pi tiene DOS interfaces de red independientes que importan**:
  `eth0` es el Ethernet/LAN de casa (lo que usa SSH); `eth1` es el
  teléfono que esté conectado por USB en ese momento (ej.
  `172.20.10.2/28` para un iPhone con Personal Hotspot). Son totalmente
  independientes — desconectar el Ethernet **no** afecta la capacidad
  de un teléfono conectado de llegar a `setlist-admin`, y viceversa.
- **`pedal-core.service` NO corre desde el checkout de git.** Su
  `ExecStart` apunta a `/home/hesner/pedal_src_test/src/main.py`, una
  copia de archivos planos separada. Cualquier cambio a
  `src/core/library.py`/`core.py`/`main.py` debe copiarse a **ambos**
  `~/chocolatepi-repo/src/` y `~/pedal_src_test/src/` (y limpiar
  `__pycache__` bajo `pedal_src_test/src/*/`) — actualizar solo el
  checkout de git no hace nada para el pedal en vivo, en silencio. Esta
  inconsistencia probablemente debería limpiarse en algún momento
  (apuntar `pedal-core.service` al checkout de git en su lugar), pero
  no se hizo, para evitar un cambio riesgoso no relacionado a mitad de
  sesión.
- **CRÍTICO: la raíz del sistema de archivos del Pi es un overlay
  respaldado en RAM por defecto** (`overlayroot=tmpfs:recurse=0` en
  `cmdline.txt`, según la sección 4 de `systemd/README.md`). Cualquier
  cosa escrita bajo `/home/` (el checkout de git, `pedal_src_test`, lo
  que sea) mientras el overlay está activo — un simple `scp`/`tar
  xzf`/`git pull` — funciona para el arranque *actual* pero **se borra
  en silencio en el siguiente reinicio**. Esto nos afectó de verdad
  esta sesión (horas de trabajo "desplegado" desaparecieron tras un
  reinicio no planeado). Para desplegar algo que deba sobrevivir un
  reinicio:
  1. `ssh -4 pedal "sudo mount -o remount,rw /boot/firmware && sudo sed -i 's/overlayroot=tmpfs:recurse=0 //' /boot/firmware/cmdline.txt && sudo mount -o remount,ro /boot/firmware && sudo reboot"`
     (confirmado otra vez el 2026-10-01: `sudo raspi-config nonint
     do_overlayfs 1` por sí solo **no** funciona aquí — su lógica de
     coincidencia no reconoce el sufijo personalizado `:recurse=0`, así
     que deja `cmdline.txt` completamente intacto y el overlay sigue
     montado después del reinicio. Usa siempre el `sed` directo de
     arriba, no `do_overlayfs 1`, para desactivarlo.)
  2. Espera a que vuelva (`until ssh -4 pedal "echo up" 2>/dev/null; do sleep 3; done`), luego confirma con `mount | grep -E ' / '` que la raíz es un montaje `ext4 rw` normal, no `overlay`.
  3. Despliega (ver abajo), corre las pruebas en el propio Pi, reinicia
     los servicios systemd afectados, verifica.
  4. Reactiva: `ssh -4 pedal "sudo raspi-config nonint do_overlayfs 0 && sudo mount -o remount,rw /boot/firmware && sudo sed -i 's/overlayroot=tmpfs /overlayroot=tmpfs:recurse=0 /' /boot/firmware/cmdline.txt && sudo mount -o remount,ro /boot/firmware && sudo reboot"`
     (nota: `do_overlayfs 0` vuelve a quitar `:recurse=0` cada vez —
     siempre reagrégalo a mano antes de este reinicio, o te encontrarás
     con el viejo bug de modo de emergencia por USB faltante de
     `TROUBLESHOOTING.md`).
  5. Espera a que vuelva, y luego verifica que la persistencia
     realmente funcionó: `git status --porcelain` en
     `~/chocolatepi-repo` debería mostrar limpio lo que acabas de
     comitear (o tu diff esperado si aún no lo comiteas), y los
     servicios afectados ya deberían estar corriendo el código nuevo
     (arrancan solos al reiniciar).
  - Un despliegue rápido y de bajo riesgo que solo estás probando (sin
    intentar hacerlo durable todavía) puede saltarse todo esto y solo
    hacer `scp`/`tar` directo al overlay ya activo — solo recuerda que
    no sobrevivirá un reinicio hasta que hagas el paso a paso de arriba.
- **Agrupa despliegues de varios archivos en un tarball, no en un ciclo
  de `scp` individuales.** Un ciclo de `scp` por archivo se probó una
  vez y falló en silencio en transferir la mayoría de los archivos (sin
  ningún error mostrado). Patrón confiable:
  `tar czf /tmp/x.tar.gz <archivos>`, `scp -4 /tmp/x.tar.gz pedal:/tmp/`,
  luego `ssh -4 pedal "cd ~/chocolatepi-repo && tar xzf /tmp/x.tar.gz && rm /tmp/x.tar.gz"`.
- **`ntfs-3g` (el sistema de archivos del USB de biblioteca) no soporta
  `mount -o remount,rw/ro`** — se rehúsa directamente. Todo remontaje,
  automatizado o manual por SSH, debe ser un `umount` real seguido de
  un `mount -o <modo>` fresco.
- **Claude específicamente no tiene ninguna herramienta de
  navegador/automatización visual en este entorno.** La lógica del lado
  del servidor (llamadas HTTP, tiempos, respuestas de error) se puede y
  se debe verificar directamente — ya sea con peticiones HTTP reales
  contra el servicio corriendo, o importando `AdminAPI` directamente en
  un script de Python puntual por SSH contra el USB real montado
  (usando un Set de prueba desechable, limpiado después). Pero
  cualquier cosa visual — colores de botones, posición de una
  notificación, si una vista a pantalla completa realmente se
  renderiza — necesita que el usuario mire su teléfono y reporte de
  vuelta. No afirmes que una corrección visual está confirmada
  funcionando sin eso.
