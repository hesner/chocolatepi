# Registro de cambios

*[Read in English](../../CHANGELOG.md)*

El formato sigue libremente [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Versionado

Este proyecto usa **números de versión basados en fecha** (`vAAAA.MM.DD`),
no versionado semántico — no hay un contrato de compatibilidad entre
versiones que rastrear (es un aparato dedicado único desplegado en una
sola Pi, no una librería versionada con múltiples consumidores
independientes). Una versión es simplemente "el estado de este
componente a esta fecha", coincidiendo con la estructura agrupada por
fecha que este registro de cambios ya usaba antes de introducir el
versionado.

Cada componente instalable de forma independiente lleva su **propia**
versión, en su propio archivo `VERSION`, actualizado cada vez que un
cambio significativo llega a `main`:

- [`VERSION`](../../VERSION) — el sistema base del pedal (`src/`,
  `systemd/`, documentación raíz).
- [`expansions/setlist-admin-usb/VERSION`](../../expansions/setlist-admin-usb/VERSION)
- [`expansions/setlist-admin-wifi/VERSION`](../../expansions/setlist-admin-wifi/VERSION)

**Para saber qué está realmente desplegado en la Pi real**: `ssh -4
pedal "cat ~/chocolatepi-repo/VERSION
~/chocolatepi-repo/expansions/*/VERSION"` (compáralo contra el commit
de git al que está sincronizado, ya que un archivo `VERSION` solo
cambia cuando alguien se acuerda de actualizarlo — el hash del commit
siempre es la fuente de verdad definitiva; el número de versión existe
para darle a una persona una cadena memorable en vez de un hash).

Este registro de cambios sigue siendo la fuente de verdad de *qué*
cambió y *por qué*; `[Sin publicar]` agrupa cambios que todavía no se
han "cortado" en una versión con fecha debajo. Cortar una versión
significa: confirmar que el cambio realmente funciona de punta a punta
(hardware real para todo lo que lo toque, no solo pruebas unitarias),
actualizar el/los archivo(s) `VERSION` del/los componente(s) afectado(s),
y renombrar `[Sin publicar]` a esa fecha — reabriendo un `[Sin
publicar]` nuevo y vacío arriba para lo que siga.

## [Sin publicar]

- **Corregido**: un tercer incidente real de la misma sesión de
  certificación en vivo — un rechazo por validación que ocurre *antes*
  de leer el cuerpo de la petición (por ejemplo, la verificación de
  nombre duplicado de `upload_song()`, que corre antes de tocar el
  stream) mandaba su respuesta 400 sin antes drenar el cuerpo todavía
  sin leer. Para un video real de varios cientos de MB, eso dejaba la
  conexión en un estado que el propio stack TCP del cliente trataba
  como reiniciado — "Load failed" en Safari — aunque la respuesta del
  servidor, con el motivo correcto del rechazo, sí se había enviado.
  (También se descubrió por esto: el video **sí** se había subido
  exitosamente en un intento anterior, durante el caos del incidente
  del montaje roto de abajo — cada reintento desde entonces estaba
  siendo rechazado correctamente, aunque de forma confusa, por
  duplicado.) Corregido: cada manejador de subida de cuerpo crudo
  (`assign_track`, `upload_song`, las dos expansiones) ahora drena
  cualquier cuerpo sin leer en un `finally`, sin importar éxito o
  fallo, vía un nuevo `_LimitedReader.drain()`. También: las respuestas
  400 ahora quedan registradas en el servidor con su motivo exacto
  (`server.py`), no solo el código de estado — un 400 es un resultado
  esperado, no un bug, pero no registrarlo significaba no tener forma
  de saber después qué se rechazó realmente y por qué cuando no se vio
  a tiempo la alerta propia del teléfono.
- **Corregido**: un incidente real, encontrado en vivo certificando la
  nueva función de video de standby — cada escritura en las dos
  expansiones `setlist-admin` (subir, renombrar, asignar, el nuevo
  selector de standby, todo) empezó a fallar con un 500 apenas
  `pedal-core.service` corría de forma continua y se mantenía estable
  (lo cual ahora hace, gracias a la corrección de desconexión MIDI del
  mismo día de arriba — ver esa entrada). Causa raíz:
  `usb_mount.writable_usb()` remonta **todo** el volumen `/media/usb`
  en `rw` para cualquier escritura, sin importar qué archivo — Linux no
  tiene un modo de lectura/escritura por archivo dentro de un mismo
  punto de montaje, así que todo el volumen necesita quedar sin ningún
  archivo abierto en ningún lado. El `mpv` de `pedal-core.service`
  mantiene abierto de forma continua lo que esté reproduciendo en loop
  (siempre `standby.mp4` en la práctica) y nunca lo suelta solo —
  confirmado en hardware real: 30 segundos seguidos de reintentos, cero
  éxitos, con `pedal-core.service` corriendo normalmente; detenerlo
  liberó el remontaje al instante, todas las veces. El reintento
  acotado de `usb_mount._remount()` (0.3s x 5, pensado para una ventana
  de ocupación breve y transitoria) nunca iba a poder con una retención
  que no se libera en absoluto. (Explicación más probable de por qué
  funcionaba en sesiones anteriores: el bug de desconexión MIDI
  corregido hoy mismo antes solía reiniciar `mpv` con frecuencia por su
  cuenta, lo cual creaba por accidente las ventanas breves de las que
  esto dependía — la corrección de estabilidad de hoy las eliminó sin
  querer.) Corregido en `api.py` (las dos expansiones): cada método que
  modifica algo ahora pasa por `_writable_usb()`, que primero intenta
  el camino rápido normal con una prueba barata y sin efectos
  secundarios (un ciclo inmediato de `rw` y vuelta a `ro`, sin escribir
  nada) — si el volumen está libre, nada cambia, cero interrupción.
  Solo si esa prueba falla, detiene `pedal-core.service` (liberando
  todo archivo abierto, incluido el video de standby en loop — la
  reproducción se interrumpe brevemente, la pantalla queda en negro
  unos segundos, igual que cualquier otro reinicio de
  `pedal-core.service`), hace la escritura real exactamente una vez, y
  lo reinicia después. El ciclo completo de remontaje de la propia
  prueba es lo que hace seguro caer a este respaldo sin ningún riesgo
  de ejecutar la escritura real dos veces.
- **Corregido, encontrado minutos después de la corrección de arriba
  mientras se certificaba en hardware real**: la conexión de un
  teléfono se cortó a mitad de una subida (el nuevo paso de detener
  `pedal-core.service` agrega unos segundos reales antes de que empiece
  la escritura, lo cual puede disparar un timeout del lado del cliente o
  que la app pase a segundo plano), y la *recuperación* de esa
  escritura fallida — volver a montar en `ro` — a su vez expiró por
  timeout a los 10s y dejó el montaje FUSE genuinamente muerto: `mount`
  seguía listando `/media/usb` como montado, pero cualquier acceso
  devolvía `ENOTCONN` ("Transport endpoint is not connected"), porque
  el proceso `ntfs-3g` detrás había simplemente terminado. La
  corrección de arriba entonces reiniciaba `pedal-core.service`
  *contra* ese montaje roto, lo cual empeoraba las cosas — confirmado en
  vivo: `mpv` mostraba su propia pantalla de inactividad "Drop files or
  URLs to play here", sin nada cargado, hasta recuperarlo a mano por
  SSH (`umount -l` y luego un `mount -o ro` nuevo). `api.py` (las dos
  expansiones) ahora hace exactamente esa recuperación de forma
  automática: justo antes de reiniciar `pedal-core.service`, corre una
  verificación real del sistema de archivos (`ls` al punto de montaje,
  no solo confiar en lo que dice `mount`, acotado por un timeout para
  que un proceso colgado en vez de totalmente muerto no pueda bloquearlo
  indefinidamente) y se auto-repara primero si está roto. Si la
  recuperación en sí no funciona, `pedal-core.service` igual se
  reinicia (registrado como error) en vez de quedar detenido para
  siempre en un aparato sin pantalla donde nadie está disponible para
  notarlo.

## [v2026.10.01] — Resiliencia ante desconexión MIDI, gestión del video de standby

- **Revertido el mismo día**: esta versión registró brevemente el
  propio `stderr` de `mpv` en `pedal-core.log` (ver la siguiente viñeta
  para el porqué de agregarlo) — revertido unas horas después. Razón:
  `pedal-core.log` vive bajo `/home/`, que con el overlay de protección
  normal está respaldado en `tmpfs` (RAM), no en disco — y nada lo
  rota. Verificado en la Pi real: el límite efectivo del overlay es de
  ~461MB (la mitad de los 921MB de RAM de esta Pi, el tamaño por
  defecto de `tmpfs`), y **ninguno de los tres logs de larga duración de
  este proyecto tiene rotación** (`pedal-core.log`, `setlist-admin.log`,
  `usb-tether-watchdog.log`). Un crecimiento de log sin control en un
  aparato pensado para correr indefinidamente sin reiniciar es un riesgo
  real de agotar la RAM, no solo de espacio en disco. Un log que solo se
  gana su lugar durante una sesión activa de debugging no vale el costo
  permanente de dejarlo encendido siempre — `core/player.py` volvió a
  mandar tanto `stdout` como `stderr` de los dos `mpv` a `DEVNULL`. Si
  una investigación futura realmente necesita la salida de errores
  propia de `mpv`, captúrala temporalmente para esa sesión (por ejemplo,
  parchear `stderr=subprocess.PIPE` y seguirlo en vivo por SSH) en vez
  de dejarlo registrado para siempre. La entrada "El audio (y el video)
  se detienen..." de `TROUBLESHOOTING.md` refleja el estado final (ya
  revertido).
- **Corregido**: un incidente real y reproducido — que el M-VAVE
  estuviera apagado o desconectado (al arrancar, o a mitad de sesión:
  un cable flojo, un glitch del hub USB, el tipo de corte breve que un
  evento real de undervoltage puede causar, ver `TESTING.md`) se trataba
  como fatal en `src/main.py`: el proceso completo salía y dependía por
  completo de que `systemd` lo reiniciara a ciegas cada `RestartSec=5`,
  lo cual además mataba y volvía a levantar los dos procesos `mpv` en
  cada ciclo (visible como la pantalla parpadeando a negro) mientras el
  controlador siguiera ausente — silencio total, ningún pedal podía
  hacer nada, y nada en pantalla indicaba por qué. `main.py` ahora
  reintenta la conexión MIDI dentro del mismo proceso, sin tumbar
  Core/`mpv` entre intentos: el standby sigue en loop sólido todo el
  tiempo que dura la reconexión, y un pedal vuelve a funcionar en el
  instante en que el controlador reaparece. Confirmado en vivo:
  encender el M-VAVE de nuevo a mitad de sesión se detectó en el
  siguiente intento (unos segundos después), sin necesitar reiniciar.
- Tanto la corrección MIDI de arriba como el intento de registrar el
  `stderr` de `mpv` (primera viñeta, revertido el mismo día) salieron de
  investigar un reporte real de que el sonido se detuvo por completo
  tras aproximadamente una hora de pruebas intensivas en hardware real —
  ver la entrada nueva de `TROUBLESHOOTING.md` para el detalle completo.
  El hueco del M-VAVE es la pista más confirmada; no se encontró
  evidencia directa en los logs de que el Behringer mismo se quedara sin
  energía, ya que los logs de ese arranque no sobrevivieron un reinicio.
- Se agregó **gestión del video de standby** a las dos expansiones
  `setlist-admin`: un panel nuevo "Standby video" muestra qué está en
  loop ahora mismo (tamaño/última modificación de `standby.mp4`) y
  permite elegir cualquier video ya presente en la biblioteca compartida
  de canciones (`_Songs/`) para que se vuelva el nuevo. Para usar un
  archivo nuevo: súbelo primero a la biblioteca (ya soportado), luego
  elígelo aquí — reutiliza la interfaz existente de subir/renombrar/
  borrar de la biblioteca de canciones en vez de duplicarla, así que
  "guardarlo en la biblioteca, renombrarlo o borrarlo" ya funcionan para
  candidatos a standby igual que para cualquier otra canción. Nuevas
  `library_ops.set_standby_video()`/`get_standby_info()`, siempre
  escribiendo el archivo elegido con el nombre fijo `standby.mp4` sin
  importar la extensión original — mpv reproduce detectando el
  contenido, no por el nombre del archivo, igual que cualquier otra
  asignación en esta app.

## [v2026.09.27] — Renombre Set/Bank, validación en hardware real, Export Set, corrección de Set activo al reiniciar, documentación de corte de luz

- Se renombró la terminología de la biblioteca en todo el proyecto
  (código, pruebas y documentación): la carpeta de nivel superior, antes
  llamada "Show", ahora es un **Set** (un grupo de Banks + canciones
  utilizables en su totalidad en una única presentación en vivo); lo que
  antes se llamaba "Set" (la carpeta de nivel medio con hasta tres
  pistas `A`/`B`/`C`) ahora es un **Bank** (banco), en línea con la
  propia terminología de bancos/grupos del M-VAVE PD41. Las letras de
  pista (`A`/`B`/`C`) no cambian. `active_show.txt` ahora es
  `active_set.txt`; las carpetas pasan de `<Nombre del Show>/Set N/` a
  `<Nombre del Set>/Bank N/`. Las rutas REST de las dos expansiones de
  `setlist-admin` pasaron de `/api/shows` y
  `/api/shows/{show}/sets/...` a `/api/sets` y
  `/api/sets/{set}/banks/...`. El parámetro interno del protocolo
  Mapper/Core `setlist` (`Library.resolve(setlist, track)`,
  `src/core/library.py`) **no** forma parte de este renombrado a
  propósito — es un detalle interno de implementación que nunca se le
  muestra al usuario, y se mantiene igual deliberadamente. Los USB de
  biblioteca ya existentes necesitan que sus carpetas/archivos se
  renombren a mano para calzar (ver `LIBRARY.md`) antes de que el código
  de esta versión encuentre algo en ellos.
- Validación en hardware real de `expansions/setlist-admin-usb/`
  (tethering USB con iPhone), que encontró y corrigió varios bugs
  reales:
  - Fallos transitorios de `umount` (el mpv de `pedal-core.service`
    mantiene `/media/usb` abierto continuamente) ahora tienen un
    reintento acotado en vez de fallar toda la escritura.
  - Se observó que el USB de biblioteca a veces se desmonta solo, sin
    ninguna evidencia correspondiente en ningún registro — la causa raíz
    no está confirmada, pero se capturó una caída real de voltaje
    (`vcgencmd get_throttled` mostró subvoltaje) durante la misma
    sesión, la pista más fuerte hasta ahora. `usb_mount.py` ahora se
    autorepara: `_remount()` trata "ya no está montado" como éxito en
    vez de fallar, y el nuevo `usb_mount.ensure_mounted()` (usado por
    `is_first_run()`) intenta un montaje de recuperación antes de que
    una verificación de solo lectura saque una conclusión equivocada de
    un directorio vacío (antes se reportaba falsamente como "primera
    vez", pidiendo sobrescribir un PIN que ya existía).
  - Dos peticiones simultáneas (ej. un doble toque real en un botón)
    chocaban entre sí sus propios llamados crudos de `umount`/`mount`
    sin ninguna coordinación, corrompiendo ocasionalmente el estado del
    remontaje. `writable_usb()` ahora se ejecuta bajo un candado de
    todo el proceso, serializando cada escritura.
  - Que el teléfono se desconecte a mitad de una subida
    (`usb-tether-watchdog.service` detiene el servidor de admin con
    SIGTERM en el instante en que la interfaz conectada desaparece)
    nunca corrompió datos reales (el diseño de escritura atómica por
    archivo temporal funcionó), pero sí dejaba archivos huérfanos
    grandes `.part`/`.swaptmp` para siempre, ya que SIGTERM se salta el
    camino normal de limpieza por excepciones de Python. El nuevo
    `library_ops.cleanup_stale_temp_files()` los limpia en cada arranque
    del servidor.
  - `rename_song()`/`delete_song()` no verificaban que el archivo de la
    canción siguiera existiendo antes de tocarlo (a diferencia de todas
    las demás funciones de `library_ops.py`) — una referencia
    desactualizada a una canción borrada a mano directamente del USB
    producía un `FileNotFoundError` crudo, sin manejar, en vez de un
    mensaje de error claro.
  - Frontend: varios manejadores de botones no tenían ningún manejo de
    errores (un error del servidor era una promesa rechazada invisible,
    sin manejar); el manejador de subida por pista nunca revisaba el
    estado de la respuesta; recargar las listas devolvía el scroll al
    inicio de la página después de cada guardar/asignar/renombrar (causa
    raíz: el contenedor quedaba genuinamente vacío, a veces durante
    varias idas y vueltas de red seguidas, obligando al navegador a
    recortar el scroll — corregido construyendo el contenido nuevo fuera
    de pantalla primero e intercambiándolo en un solo paso); y el
    destello verde de "esto funcionó" en los botones aparecía solo
    después de que el servidor respondía en vez de en el instante en que
    se tocaba el botón, así que una subida lenta se veía sin respuesta
    durante toda su duración.
- Se agregó una vista **Export Set** a las dos expansiones de
  `setlist-admin`: una vista a pantalla completa, en letra grande, con
  el repertorio del Set seleccionado (el nombre de archivo exacto de
  cada pista + su extensión, en orden de Bank/letra), con un aviso de
  los formatos soportados y un botón "Share" que convierte la lista en
  una imagen PNG y la entrega al menú nativo de compartir del teléfono
  (alternativa en escritorio/navegador sin soporte: descarga directa).
  Se cierra con una ✕ en pantalla, con Escape, o con el gesto de
  retroceso del navegador.
- **Corregido**: en `setlist-admin-usb`, elegir un Set distinto en el
  desplegable solo cambiaba lo que la app mostraba/editaba — nunca le
  decía al pedal cuál Set tocar realmente. Solo *crear* un Set nuevo
  llamaba a la API `set_active_set`; cambiar entre Sets que ya existían
  no tenía forma de volverse "el" activo salvo borrar y recrear uno.
  Corregido haciendo que "Reboot now to apply" marque como activo el
  Set que esté seleccionado justo antes de reiniciar — el momento en
  que esta app ya le pide al usuario confirmar su intención, así que
  también es el momento correcto para confirmarlo. (Todavía no
  trasladado a `setlist-admin-wifi`, que no tiene botón propio de
  reinicio — ver `expansions/setlist-admin-usb/NEXT_STEPS.md`.)
- Documentada (en `TROUBLESHOOTING.md` en/es, más `systemd/README.md`
  sección 4) una respuesta consolidada a "¿está la Pi protegida ante un
  corte de luz, y cuáles son las ventanas de riesgo reales?": durante el
  uso normal en un show, `/`, `/boot/firmware` y `/media/usb` están
  respaldados en RAM o en solo-lectura, así que no hay nada que un corte
  de luz pueda corromper; las ventanas reales (breves) son el remontaje
  `rw` de `/media/usb` durante una edición de biblioteca, el overlay
  desactivado para desarrollo, y la edición a mano de `cmdline.txt` —
  las últimas dos son solo de mantenimiento, nunca durante un show.
  También señala que una fuente de poder insuficiente, no un desenchufe
  limpio, es el disparador más probable en la práctica, según un evento
  de under-voltage observado directamente por este proyecto.
- Se agregó una biblioteca compartida de canciones (`_Songs/` en la raíz
  del USB) a las dos expansiones de `setlist-admin`, para que una
  canción solo se suba una vez y se pueda reutilizar en cualquier
  cantidad de Sets en vez de volver a subirla en cada Set nuevo.
  Documentada como convención del proyecto base en `LIBRARY.md` (en/es)
  — también funciona a mano por SSH, no solo a través de alguna de las
  dos apps — con una advertencia explícita de no borrar canciones de
  ahí, ya que borrar solo las quita de futuras selecciones, nunca de un
  Bank donde ya estén asignadas (eso siempre es una copia independiente).
  Las funciones nuevas de `library_ops.py`
  (`list_songs`/`upload_song`/`rename_song`/`delete_song`/
  `assign_song_to_slot`/`save_track_to_library`) son idénticas entre las
  dos expansiones. `scripts/rollback.sh` ganó una bandera separada
  `--purge-library` (distinta de `--purge`, que solo tocaba el pequeño
  archivo de PIN/credenciales) ya que borrar archivos de canciones
  reales es una acción más grande y deliberada. También se arreglaron
  dos bugs reales preexistentes encontrados al construir esto (presentes
  desde el diseño original por WiFi, sin relación con la biblioteca de
  canciones en sí): `library_ops.LibraryOpsError` nunca se traducía a
  una respuesta HTTP apropiada (caía en el 500 "Internal error" genérico
  en vez del 400 con mensaje útil que debía ser), y los segmentos de
  ruta de la URL (nombres de Set, ahora también de canciones) nunca se
  decodificaban del lado del servidor pese a que el frontend sí los
  codifica, así que cualquier nombre que realmente necesitara
  codificación (cualquier espacio o tilde) fallaba en silencio.
- Se introdujo `expansions/`: un lugar a nivel raíz para addons
  opcionales, instalables/removibles de forma independiente, al
  sistema base del pedal — se movió `setlist-admin` (diseño por USB) a
  `expansions/setlist-admin-usb/` como el primero, completamente
  autocontenido (su propio `src/`, `systemd/`,
  `scripts/install.sh`+`rollback.sh`, `tests/`, documentación), para
  que instalarlo o revertirlo nunca pueda afectar de forma colateral
  al proyecto base ni a ninguna otra expansión. Ver
  `expansions/README.md` para el modelo. El intento anterior por WiFi,
  que antes solo vivía en la rama `explore/setlist-admin`, también se
  trajo a `main` como una segunda expansión igual de independiente
  (`expansions/setlist-admin-wifi/`) — todavía en pausa por su dongle
  USB de WiFi muerto, no instalada por defecto, pero ahora visible en
  el mismo checkout sin necesitar cambiar de rama para verla.
- Se agregó `setlist-admin` (diseño por USB): un segundo intento de la
  app web complementaria para administrar el USB de biblioteca
  (Sets/Banks/pistas, CRUD completo) desde el navegador de un teléfono,
  esta vez conectando el teléfono a la Pi con un cable USB (compartir
  conexión por USB en Android, o Compartir Internet por cable en
  iPhone) en vez de que la Pi necesite su propio radio WiFi — ver
  `expansions/setlist-admin-usb/SPECIFICATION.md` para el diseño y el
  porqué (el intento anterior por WiFi quedó en pausa por un dongle USB
  de WiFi muerto, no por culpa de ese diseño). Reutiliza sin cambios el
  backend de CRUD y la
  experiencia del frontend de ese diseño (`library_ops.py`,
  `usb_mount.py` incluyendo su arreglo de `ntfs-3g`, `auth.py`, las
  pantallas de CRUD) para que los dos queden convergibles más adelante.
  Un teléfono se identifica por el nombre de su driver de red USB
  (`rndis_host`/`cdc_ether`/`cdc_ncm` para Android, `ipheth` para
  iPhone), no por rango de IP, así que un cable Ethernet permanente
  nunca arranca el servidor de admin por accidente. Sin
  almacenamiento de credenciales de WiFi, sin manejo de perfiles de
  NetworkManager — toda esa capa desapareció. Aplicar un cambio de
  setlist sigue requiriendo un reinicio (este proyecto ya intentó y
  abandonó un mecanismo de recarga en vivo una vez, ver más abajo en
  este mismo archivo); la app agrega un botón "Reiniciar ahora para
  aplicar" para que eso no necesite SSH. Todavía no validado en
  hardware real.
- Se diseñó e implementó `setlist-admin` (una app web complementaria
  para administrar el USB de biblioteca y el WiFi de la Pi desde el
  navegador de un teléfono/computador), y luego se revirtió de `main`:
  la validación en hardware real (`SETLIST_ADMIN_SPECIFICATION.md`
  sección 8a) avanzó limpio por la instalación y las etapas de dry-run
  y arranque en vivo del watchdog, pero el dongle USB de WiFi (Realtek
  rtl8192cu) resultó ser hardware defectuoso — confirmado al probarlo
  en un computador aparte, donde no apareció como ningún dispositivo
  USB en absoluto. Como toda la funcionalidad depende de un adaptador
  de WiFi funcional, seguir probando queda bloqueado hasta contar con
  uno en buen estado. El diseño completo, la implementación, los tests,
  y un bug real encontrado en el camino (`ntfs-3g` no soporta `mount -o
  remount,rw` — se arregló a un ciclo real de umount+mount) quedan
  preservados en la rama `explore/setlist-admin` para un intento futuro
  con un diseño alternativo.
- Se agregó `REBUILD.md` (en/es): guía ordenada por ejecución para
  reproducir este proyecto en un PC nuevo + una Raspberry Pi nueva,
  escrita para un agente de IA trabajando en frío, sin historial de
  conversación.
- Se agregó `TROUBLESHOOTING.md` (en/es): referencia organizada por
  síntoma de cada falla real que este proyecto tuvo durante su
  desarrollo/pruebas.
- `systemd/README.md` (en/es): se agregó un capítulo de revisión
  "¿puede una persona hacer esto sola?" (se recorrió la guía como lo
  haría un músico sin programación), que encontró y corrigió varios
  huecos reales — nunca se mencionaba `git`/clonar el repo en la Pi,
  sin guía de cliente SSH, sin instrucciones de editor de texto
  (`nano`) para los dos archivos que necesitan edición manual, y el
  requisito de fuente de poder solo estaba documentado de forma
  reactiva (después del hecho, en `TESTING.md`) en vez de como
  requisito previo (ahora también en la lista de hardware de
  `README.md`).
- Se arregló un hueco de contenido real entre EN/ES en `TESTING.md`: a
  la versión en español le faltaba la sección que cierra la prueba 4.0
  (el seguimiento de la prueba en TV real), dejando a un lector solo en
  español pensando que seguía abierta cuando ya se había resuelto.
- **Arreglado**: arrancar sin el USB de biblioteca caía en systemd
  emergency mode (sin SSH, irrecuperable en un appliance sin pantalla)
  en vez del standby de respaldo local. Causa: el `recurse=1` por
  defecto del overlay envuelve todos los mounts (incluido `/media/usb`)
  en su propio overlay sin `nofail`, así que un USB ausente hacía
  fallar un mount crítico para el arranque. Arreglado con `recurse=0`
  (solo raíz) en `cmdline.txt` — ver `systemd/README.md` sección 4.
- Se agregó `LIBRARY.md` (en/es): cómo nombrar carpetas/archivos del USB
  de biblioteca, y el error exacto de espaciado en el nombre de archivo
  (`A  - x.mov` vs `A - x.mov`) que falla completamente en silencio —
  encontrado en vivo probando un video del Bank 5 que no se reproducía.
- Proyecto renombrado de "Sequence Pedal" / "Pedal de Secuencias" a
  **Chocolate Pi** -- un nombre de producto propio (juego de palabras
  con el pedal M-VAVE Chocolate + la Raspberry Pi que realmente se usan)
  en vez de una descripción literal. Repo, badges y documentación
  actualizados; GitHub redirige automáticamente la URL vieja del repo.

## 2026-09-05 -- Primera publicación open source

Primer release open source. En uso activo y validado contra hardware
real (Raspberry Pi 2, interfaz de audio USB Behringer U-PHORIA UM2,
controlador MIDI M-VAVE PD41, USB de biblioteca).

- Arquitectura por capas (Adapter → Mapper → Core) para que el código
  específico de un controlador nunca se filtre a la lógica de
  reproducción.
- `Adapter` validado contra un M-VAVE PD41 en modo Program Change A (ver
  `MAVAVE_ANALYSIS.md` para el mapeo empírico y su corrección: 8 grupos,
  no 32).
- `Core`: resolución de biblioteca desde un USB, video manejado por
  `mpv` con loop de standby, un carril de audio dedicado para pistas de
  solo audio, y audio siempre priorizado sobre video.
- Video de standby de respaldo local para cuando el USB de biblioteca no
  está presente al arrancar.
- Servicio de `systemd` para arranque automático; la presencia del USB
  se revisa una sola vez al arrancar (sin hot-swap en vivo — hace falta
  reiniciar para tomar cambios de biblioteca).
- Sistema de archivos raíz de solo lectura (overlay de Raspberry Pi OS)
  para poder apagar la Pi en cualquier momento sin riesgo de corrupción
  del sistema de archivos.
- Licencia MIT, documentación bilingüe (inglés primero, español en
  `docs/es/`), GitHub Sponsors.
