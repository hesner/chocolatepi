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
desplegar ese parche de forma permanente. Ver la entrada posterior de
"Sin publicar" en `CHANGELOG.md` para el razonamiento completo.)
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

Dos cosas que el usuario planteó y pidió explícitamente dejar para
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
