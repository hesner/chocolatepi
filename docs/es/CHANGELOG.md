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

- **`library-optimizer.service` ahora limpia automáticamente los
  archivos temporales sobrantes de un trabajo interrumpido, pedido real
  del usuario después de notar que se habían acumulado ~470MB en un
  solo día de pruebas (2026-10-03)**: un reinicio del servicio a mitad
  de un trabajo (manual, un fallo, un reinicio de la Pi) abandona lo
  que `_process_job()` estuviera copiando o codificando —
  `recover_orphaned_jobs()` ya reseteaba el estado de la *cola* de
  vuelta a "queued" en ese caso, pero no tenía idea de que existieran
  los archivos `scratch_input`/`scratch_output` abandonados bajo
  `~/pedal-optimizer-scratch/`, así que simplemente se quedaban ahí
  para siempre (antes solo se borraban con `rollback.sh`, es decir,
  solo al desinstalar por completo). `run_forever()` ahora limpia todo
  el directorio de archivos temporales una vez, sin condiciones, en
  cada arranque, antes del primer ciclo — siempre seguro, ya que un
  trabajo que vuelve a "queued" recibe una copia temporal nueva con un
  nombre de archivo aleatorio distinto la próxima vez que se procese,
  así que nada que ya esté en disco al arrancar puede volver a
  reanudarse ni referenciarse. Replica el mismo patrón ya usado para
  los archivos `.part` del propio USB y para el directorio de subida
  temporal de la app admin (ver la entrada de abajo). 5 tests nuevos en
  `tests/test_library_optimizer.py`.
- **Corregido: una subida lenta dejaba a `pedal-core.service` detenido
  (sin standby, sin ninguna reproducción) durante toda la transferencia
  de red, incidente real encontrado probando en vivo la nueva
  funcionalidad de WiFi de arriba (2026-10-03)**:
  `upload_song()`/`assign_track()`
  (`expansions/setlist-admin-usb/src/admin/api.py`) leían el flujo
  crudo de red de la subida directamente dentro de `_writable_usb()` —
  así que la ventana en la que `pedal-core.service` quedaba detenido
  dependía de la *velocidad de la propia conexión de quien sube el
  archivo*, no de la escritura al USB en sí. Confirmado en vivo: una
  subida de 76MB por una conexión WiFi débil dejó el pedal apagado
  durante aproximadamente 15 minutos. Se corrigió recibiendo la subida
  primero a almacenamiento local de la propia Pi
  (`AdminAPI._receive_to_scratch()`, nuevo `--upload-scratch-dir`,
  limpiado al inicio igual que ya se hacía con los archivos `.part` del
  USB) y envolviendo en `_writable_usb()` solo la copia corta, a
  velocidad de disco local, desde ahí hacia el USB — el mismo patrón de
  "copiar local primero, luego copiar" que `library_optimizer.py` ya
  usa para su propia salida de `ffmpeg`, a menudo más grande. 4 tests
  nuevos en `tests/test_admin_api.py`, dos de los cuales fallan de
  inmediato (a propósito) si algún cambio futuro vuelve a leer el flujo
  de la subida dentro de la ventana de escritura del USB.
- **`setlist-admin-usb` ahora también se puede alcanzar por WiFi, sin
  necesitar un teléfono, pedido real del usuario (2026-10-03)**:
  `usb-tether-watchdog.service`
  (`expansions/setlist-admin-usb/src/admin/usb_tether_watchdog.py`)
  ganó una segunda condición, independiente de la detección de
  teléfono por cable — `wifi_connected_to_profile()` revisa vía `nmcli`
  si la conexión WiFi activa de la Pi coincide exactamente con un
  perfil específico y nombrado de NetworkManager (por defecto
  `"preconfigured"`, el que guarda el Raspberry Pi Imager durante la
  configuración inicial — confirmado en vivo vía `nmcli` que así es
  exactamente como la Pi ya se reconecta a la red de WiFi de casa de la
  banda sin configuración adicional cada vez que se conecta un dongle
  USB de WiFi). `setlist-admin.service` ahora arranca si *o bien* hay
  un teléfono conectado por cable *o* la Pi está en esa red WiFi de
  confianza, pudiendo ser ambas verdaderas a la vez sin conflicto;
  perder ambas detiene el servicio, igual que antes. Deliberadamente
  solo confía en ese perfil nombrado específico, nunca en "cualquier
  WiFi con una IP usable" — una red ajena (el WiFi de invitados de un
  lugar donde tocan, por ejemplo) nunca debe exponer la app admin
  protegida por PIN. Ver la sección 16 del `SPECIFICATION.md` de esa
  expansión y "Reaching the app over WiFi" en su `USAGE.md` para el
  diseño y uso completos. 10 tests nuevos en
  `expansions/setlist-admin-usb/tests/test_admin_usb_tether_watchdog.py`.

  Como parte del mismo trabajo, `setlist-admin-wifi` (la expansión
  separada y más compleja, con su propia interfaz de configuración de
  hotspot y almacenamiento cifrado de credenciales en el USB) ahora se
  replantea formalmente en su propia documentación como un ítem de
  roadmap, no de corto plazo — está implementada y con tests
  unitarios, y su bloqueo de hardware original (un dongle USB de WiFi
  muerto) se resolvió el 2026-10-01, pero una revivificación completa
  no vale la pena ahora que la funcionalidad más simple de arriba
  cubre la necesidad real. No cambió nada de código en esa expansión.
  También se documentó: el procedimiento real para cambiar a qué red
  WiFi se conecta la Pi después de su configuración inicial (la nueva
  sección "Cambiar a qué red WiFi se conecta la Pi" en
  `systemd/README.md`, referenciada desde `TROUBLESHOOTING.md` y el
  `USAGE.md` de `setlist-admin-usb`) — no existía ninguna en ningún
  lado antes de esto.
- **Se agregó una línea de video consciente de recursos, pedido real
  del usuario (2026-10-03)**: se midió en vivo que el proceso `mpv` de
  la línea de video costaba un core completo de CPU (~106%) y ~300MB
  de RAM (34% del total de ~921MB de la Pi 2 de referencia) de forma
  continua, solo para repetir el standby — un costo real y constante
  por nada si no hay ninguna pantalla físicamente conectada para
  mostrarlo. Un nuevo `DisplayMonitor` (`src/core/display_monitor.py`)
  sondea el `status` en sysfs del conector DRM (con antirrebote, para
  que un cable suelto o intermitente no haga parpadear la línea
  encendida/apagada) y `Core.set_display_connected()` arranca/detiene
  la línea de video según corresponda, incluyendo una vez al inicio
  con el estado real al arrancar. Sin ninguna pantalla conectada, una
  pista de video reproduce solo su audio (por la misma línea que ya
  usa una pista de solo-audio) en vez de no hacer nada — el sistema
  sigue funcionando completo. Deliberadamente nunca interrumpe lo que
  ya está sonando: un clip que ya estaba sonando cuando la pantalla se
  desconecta sigue sonando, audio y todo, hasta que termina solo o se
  presiona STOP; se consideró y se rechazó un traspaso en vivo a mitad
  de clip entre líneas (riesgo real de clic de audio al sincronizar
  posición entre dos procesos `mpv` independientes). Ver la entrada
  "Línea de video consciente de recursos" de `MASTER_SPECIFICATION.md`
  para el registro completo de la decisión. 20 tests nuevos
  (`tests/test_core.py`, `tests/test_display_monitor.py` — `core.py` y
  `player.py` antes no tenían ningún test automatizado, solo el
  `core_smoke_test.py` manual; la lógica nueva aquí es de
  enrutamiento/estado puro, genuinamente testeable con `Player`/
  `AudioPlayer` simulados).

  Como efecto colateral, esto también autocorrige un incidente real
  del mismo día: conectar el cable HDMI *después* de encender solía
  dejar la Pi sin mostrar ningún video hasta un `systemctl restart
  pedal-core.service` manual — la propia detección de hotplug DRM del
  kernel funcionaba, pero el proceso `mpv` que ya estaba corriendo
  nunca se re-vinculaba a ella. Ahora la línea de video simplemente
  todavía no estaba corriendo en ese caso, y arranca de cero
  (vinculándose correctamente a la pantalla ya conectada) a los pocos
  segundos de que el monitor detecte el cable — ver la entrada
  actualizada en `TROUBLESHOOTING.md`.
- **Corregido un lote de problemas reales encontrados durante una
  ronda completa de pruebas de usuario (2026-10-02)**, ambas
  expansiones salvo que se indique lo contrario:
  - `pedal-core.service` podía entrar en un ciclo de caídas durante
    varios minutos bajo carga pesada de CPU: una escritura cuyo
    remontaje de limpieza perdía la carrera contra el propio `mpv` de
    `pedal-core.service` (un mecanismo de respaldo ya existente y
    legítimo — detenerlo, forzar el remontaje, reiniciarlo) implica
    que un `mpv` recién creado tiene que abrir su socket de control
    desde cero, y eso tardaba más de los 5s de margen mientras el
    `ffmpeg` de un trabajo de "Optimize" concurrente saturaba la CPU —
    confirmado en vivo, el pedal mostró la pantalla de inactividad de
    `mpv` durante un par de minutos. Se subió a 20s en
    `src/core/player.py` (sistema base del pedal, no una expansión) —
    el arranque normal no se ve afectado (bien por debajo de 1s sin
    contención).
  - `list_sets()` listaba carpetas reservadas del sistema de archivos
    (p. ej. una carpeta que crea NTFS) como Sets seleccionables —
    confirmado en vivo en el USB real de la biblioteca.
  - Los estados "Optimizando"/"En cola" se mostraban idénticos (ambos
    en verde "Optimizando") — con dos trabajos a la vez, no había forma
    de saber cuál estaba realmente corriendo y cuál solo esperaba su
    turno. Confirmado en vivo: esto causó cancelar el equivocado por
    error. Ahora son visualmente distintos.
  - Subir una canción a la biblioteca siempre mandaba el archivo
    completo antes de enterarse de un nombre duplicado — normalmente
    rápido, pero puede tardar minutos si el USB está ocupado con una
    copia a scratch sin relación. Ahora revisa la lista de canciones ya
    cargada del lado del cliente primero, al instante, para el caso
    común.
  - Una Pi lenta o sobrecargada podía abortar una solicitud a nivel de
    red, mostrando un "TypeError" crudo y sin traducir en vez de un
    mensaje claro.
  - Los botones "Set as standby"/"Unlock"/"Set PIN" no daban ninguna
    retroalimentación al tocarlos, y el selector de standby se quedaba
    mostrando el video recién aplicado después, como si no hubiera
    terminado.
  - Crear un Bank nuevo pedía un número a mano — los Banks son espacios
    secuenciales que un controlador MIDI recorre uno a la vez, así que
    ahora se asigna automáticamente el siguiente. No tiene tope según
    la cantidad física de bancos de ningún controlador en particular.
- **Corregido, incidente real (2026-10-02)**: iniciar un segundo
  trabajo de "Optimize" mientras la fuente de otro todavía se estaba
  copiando desde el USB podía arrojar error 500 (`RemountError`) —
  `setlist-admin.service` y `library-optimizer.service` son dos
  procesos de sistema operativo independientes con memoria separada,
  así que el `threading.Lock()` dentro de un solo proceso que ya tenía
  `usb_mount.py` no hacía nada para evitar que una escritura en uno
  compitiera con una lectura larga en el otro. Se agregó un candado
  real entre procesos (`flock()` sobre una ruta conocida, omitido en
  Windows donde `fcntl` no existe — las pruebas locales siguen
  dependiendo solo del candado dentro del proceso) que ahora comparten
  cada escritura y el paso de copia a scratch, vía una nueva
  `usb_mount.exclusive_read()` — una escritura concurrente ahora
  simplemente espera su turno (acotado a 5 minutos) en vez de competir
  contra un `umount` con un descriptor de archivo abierto y perder.
- **Corregido, incidente real (2026-10-02)**: cancelar un trabajo de
  "Optimize" podía arrojar error 500 (`RemountError`) si se tocaba
  dentro del primer tramo de vida del trabajo — el marcador de
  cancelación vivía en el USB junto a cualquier otro marcador del
  trabajo, así que escribirlo necesitaba el mismo remontaje de USB en
  modo escritura que cualquier otra escritura, pero el paso de copia a
  scratch que corre antes de cada codificación (ver el arreglo de
  bloqueo de escrituras más abajo) mantiene abierto un identificador de
  lectura sobre el montaje durante toda esa copia, mucho más de lo que
  cubre el reintento acotado del propio montaje (ajustado para una
  colisión breve con mpv de `pedal-core.service`, no una copia de
  archivo de varios segundos a minutos). Se movió el marcador de
  cancelación a almacenamiento local de la Pi
  (`optimize_queue.DEFAULT_STATE_DIR`, `~/.pedal-optimizer-state/`) —
  solo necesita llegar al propio proceso `library_optimizer.py` de esta
  Pi, nunca a la memoria USB, y nunca necesita sobrevivir un reinicio
  (un trabajo que sobrevive un reinicio se vuelve a encolar limpio vía
  `recover_orphaned_jobs()` de todos modos, así que un marcador de
  cancelación obsoleto que sobreviviera habría cancelado
  incorrectamente la *siguiente* corrida). `cancel_song_optimization()`
  ya no necesita ninguna ventana de escritura en el USB. Ambas
  expansiones.
- **Se agregó un selector de idioma ES/EN, en ambas expansiones**: un
  menú desplegable en la barra superior (que ahora dice "ChocolatePi -
  Setlist Admin") cambia todo el texto de la interfaz — etiquetas,
  botones, confirmaciones, alertas, notificaciones — entre inglés y
  español, guardado por navegador vía `localStorage`
  (`static/i18n.js`). Los nombres de canciones, pistas, Sets y Banks
  son datos del usuario y nunca se traducen, a propósito — cada función
  de renderizado deja esos valores fuera de las llamadas de traducción
  deliberadamente. Los mensajes de error que vienen del servidor
  siguen en inglés por ahora, un trabajo aparte, explícitamente
  diferido.
- **Se agregó actualización automática del estado de optimizar/cancelar,
  en ambas expansiones**: cancelar o iniciar un trabajo se resuelve en
  el servidor en segundos, pero la app solo volvía a consultar el
  estado de las canciones ante una acción explícita, así que el botón
  Optimizar/Cancelar se quedaba mostrando el estado viejo hasta un
  refresco manual. Ahora consulta `GET /api/songs` cada 5s solo
  mientras algo esté realmente en cola o corriendo, y se detiene sola
  en cuanto no hay nada activo.
- **Corregido, incidente real (2026-10-02)**: el estado "Optimizar"/
  "Cancelar" de una canción podía mostrarse desactualizado (por
  ejemplo, "ya optimizado" mientras un trabajo seguía corriendo de
  verdad) después de un refresco — `GET /api/songs` es un GET plano
  sin encabezado `Cache-Control`, así que el cacheo heurístico del
  navegador servía una respuesta vieja. Mismo arreglo que el de
  archivos estáticos más abajo, aplicado también a cada respuesta JSON
  (`_send_json()`). Ambas expansiones.
- **Se agregó una advertencia de pérdida de electricidad y un botón real
  de Cancelar para "Optimize"**, en ambas expansiones, tras una
  pregunta real sobre qué le pasa a la Pi y al archivo si se corta la
  luz a mitad de un trabajo: al tocar "Optimize" ahora aparece una
  advertencia explícita de no desconectar la Pi mientras esté corriendo,
  y una vez que un trabajo inicia, aparece un botón "Cancel" junto a él
  (`optimize_queue.request_cancel()`/`is_cancel_requested()`,
  revisado por `library_optimizer.py` entre sondeos de ffmpeg y antes
  de iniciar un trabajo en cola). El indicador en curso dice
  "Optimizando" (mostrado como un botón verde permanente, no oculto,
  junto a "Cancel") en vez de desaparecer a favor del botón de
  Cancelar.
- **Corregido, incidente real (2026-10-02)**: un desajuste obsoleto
  entre `app.js`/`index.html` podía dejar un refresco mostrando solo la
  barra superior, nada más — no había encabezado `Cache-Control` en
  absoluto en los archivos estáticos, así que una copia vieja cacheada
  de un archivo podía servirse junto a una copia fresca de otro. Se
  agregó `Cache-Control: no-cache, no-store, must-revalidate` a
  `_serve_static()`. Ambas expansiones.
- **Corregido, incidente real (2026-10-02)**: la imagen para compartir/
  descargar de Export Set todavía tenía el viejo aviso de "formatos
  soportados" dibujado dentro del propio PNG, incluso después de que un
  commit anterior lo quitara de la vista en pantalla — una copia
  separada, dibujada en el canvas dentro de `renderSetlistToPngBlob()`,
  que ese arreglo anterior no alcanzó. Se eliminó por completo
  (`SUPPORTED_FORMATS_DISCLAIMER`/`wrapTextLines()` borrados). Ambas
  expansiones.
- **Corregido, incidente real (2026-10-02)**: un trabajo de "Optimize"
  que corría `ffmpeg` directo contra la fuente montada en el USB
  mantenía ese archivo abierto durante *todo* el proceso de
  codificación (confirmado en vivo, 45+ minutos para una fuente 4K) —
  `umount` se niega rotundamente mientras algo mantenga un archivo
  abierto en ese montaje, incluyendo lectura, así que cualquier otra
  escritura de la biblioteca (incluso un "crear Bank" sin relación)
  fallaba con error 500 durante todo ese tiempo. Arreglado:
  `library_optimizer.py` ahora copia la fuente a scratch local *antes*
  de codificar; `ffmpeg` solo toca la copia local. El montaje USB solo
  se mantiene abierto durante la breve copia, no durante toda la
  codificación.
- **Corregido, incidente real (2026-10-02)**: un timeout transitorio de
  `ffprobe` bajo carga concurrente alta (varias verificaciones de codec
  en paralelo más un trabajo de `ffmpeg` largo corriendo) se guardaba
  como resultado permanente de "no optimizado" en la caché por archivo
  de codecs (`codec_check.py`, nueva en ese momento) — tres archivos
  quedaron atascados mostrando "Optimize" para siempre, incluso después
  de que la carga bajara. Arreglado: la caché ahora solo guarda una
  verificación *exitosa*, nunca un fallo.
- **Corregido, incidentes reales (2026-10-02)**: los formularios
  (ingreso de PIN, etc.) no quedaban centrados en pantallas anchas —
  `main` se centra con `margin: 0 auto`, pero un `form` más angosto
  adentro nunca lo hacía, invisible en un teléfono, evidente en una
  tablet. También se corrigió una demora de ~37 segundos entre iniciar
  sesión y que la biblioteca de canciones realmente apareciera
  (confirmado en vivo, ~24 canciones, varios videos de varios GB):
  `list_songs()` corría `ffprobe` de forma secuencial, en cada llamada,
  para cada canción — ahora se cachea por `(ruta, mtime, tamaño)` y se
  paraleliza entre hasta 4 workers (limitado por I/O, no por CPU).
- **Corregido, incidente real (2026-10-02)**: un trabajo de "Optimize"
  que quedaba atascado "running" para siempre en la interfaz, sin
  opción de "retry", después de reiniciar la Pi a mitad de un trabajo —
  `list_queued()` deliberadamente nunca vuelve a tomar trabajos
  "running" (asumiendo que un ciclo distinto, todavía vivo, ya lo está
  procesando), suposición que se rompe justo cuando el *propio demonio*
  es el que murió. `library_optimizer.py` ahora llama a
  `optimize_queue.recover_orphaned_jobs()` una vez al iniciar,
  reiniciando cualquier marcador "running" huérfano de vuelta a
  "queued".
- **Incidente real de pérdida de datos (2026-10-01) y el hueco que
  dejó ver**: el video real de standby de la banda (una grabación de
  ~55 minutos, ~754MB) quedó sobrescrito para siempre, sin ninguna
  copia, al reemplazarlo desde el propio selector "Set as standby" de
  la app — `library_ops.set_standby_video()` hace un simple
  `_atomic_copy_file()` directo sobre `standby.mp4`, sin guardar copia
  de lo que esté reemplazando. Se recuperó solo porque el usuario
  todavía tenía el archivo fuente original, sin convertir, en otro
  computador; se re-codificó con H.264 acelerado por hardware
  (`h264_v4l2m2m` tanto para decodificar como para codificar —
  confirmado en vivo, cerca de 0.87x en tiempo real para una fuente
  1080p/25fps ya en H.264, contra el ~0.1x que este proyecto vio antes
  con decodificación HEVC solo por software) hasta ~800MB, se volvió a
  agregar a la biblioteca, y el usuario lo volvió a elegir como
  standby. **Todavía sin corregir en el código**: `set_standby_video()`
  sigue sin ningún paso de respaldo — un hueco real, ahora confirmado
  como costoso. Decisión de producto pendiente, ver `NEXT_STEPS.md`.
- **Se encontró y probó un dongle WiFi USB que sí funciona
  (2026-10-01)**: un chipset distinto (Ralink/MediaTek `MT7601U`) al
  que originalmente dejó pausada `setlist-admin-wifi` (Realtek
  `rtl8192cu`, muerto). Confirmado en hardware real: el driver
  `mt7601u` del kernel se cargó limpio, `wlan0` subió y se asoció a la
  red de casa solo, vía un perfil de NetworkManager ya guardado, y SSH
  funcionó por ahí con `eth0` totalmente desconectado. **Esto es solo
  conectividad WiFi a nivel de sistema operativo** — desbloquea
  retomar la validación propia de hardware de `setlist-admin-wifi`
  (ver la nota de estado de `SPECIFICATION.md` de esa expansión), pero
  la expansión en sí (sus propias unidades de systemd, los flujos de
  lectura/escritura de `nmcli`) todavía no se ha instalado ni probado
  con este dongle. Mientras tanto, el servidor de `setlist-admin-usb`
  también se alcanzó directo por este WiFi, como solución manual
  temporal (ya escucha en `0.0.0.0:8080`, así que no hizo falta nada
  específico de USB — solo arrancarlo a mano con
  `usb-tether-watchdog.service` detenido para que no lo volviera a
  apagar de inmediato).
- **Corregido, encontrado al desplegar la función "Optimize" de abajo
  en la Pi real**: `library-optimizer.service` entraba en bucle de
  fallos de inmediato (`ModuleNotFoundError: No module named 'admin'`)
  — `library_optimizer.py` vive bajo `src/admin/` y hace `from admin
  import ...`, igual que `server.py`, pero a diferencia de `server.py`
  nunca agregaba `src/` al `sys.path` primero. Invisible para las
  pruebas unitarias, porque esas ya ponen `src/` en el `sys.path` antes
  de importarlo — solo correrlo exactamente como lo hace `systemd` (un
  `python3 library_optimizer.py` sin más) lo hizo salir a la luz.
  Corregido con la misma línea `sys.path.insert(0, "..")` que
  `server.py` ya tenía. Las dos expansiones.
- **Desplegado y verificado en la Pi real (2026-10-01)**: ciclo
  completo de deshabilitar overlay/desplegar/probar/rehabilitar
  overlay/reiniciar; 181 pruebas (USB) + 200 (WiFi) pasaron en la
  propia Pi; `library-optimizer.service` instalado y confirmado
  realmente corriendo (no solo "active" en medio de un bucle de
  fallos, que fue justo como se detectó el error de arriba); una
  prueba real de punta a punta — un clip HEVC sintético y pequeño
  subido directamente con `AdminAPI.upload_song()`, encolado con
  `request_song_optimization()`, recogido por el daemon en pocos
  segundos, y reportado como H.264/`needs_optimization: False` al
  terminar — confirmó que todo el flujo (cola, recogida del daemon,
  codificación en temporal, copia atómica final, respaldo de
  `pedal_core_guard`, limpieza de la cola) funciona de verdad, no solo
  bajo mocks. `pedal-core.service` se mantuvo activo y `standby.mp4`
  siguió reproduciéndose todo el tiempo. **Todavía sin confirmar**: el
  flujo real desde la app del celular (tocar "Optimize", ver el botón
  decir "Optimizing...", desconectar/reconectar el celular a mitad del
  trabajo) — esa parte se probó con llamadas directas a `AdminAPI` por
  SSH, no desde la app misma. Ver
  `expansions/setlist-admin-usb/NEXT_STEPS.md`.
- Se agregó un **botón "Optimize"** a nivel de toda la biblioteca, en
  las dos expansiones `setlist-admin`. Pedido real del usuario: las
  subidas ya avisaban si un video no era H.264 (sección 9,
  `codec_check.py`), pero arreglarlo significaba re-codificar
  manualmente por SSH — el mismo proceso de ~90 minutos, hecho a mano
  una sola vez, que este proyecto acababa de hacer para el video de
  standby. Ahora la biblioteca de canciones muestra un botón "Optimize"
  junto a cualquier archivo (`codec_check.is_optimized()`) que no esté
  ya en el formato recomendado; al tocarlo se encola la misma
  re-codificación (`scale=-2:1080,fps=25`, H.264 high@4.0, AAC 128k,
  documentada en `LIBRARY.md`) sin bloquear la interfaz. Limitado a la
  biblioteca únicamente — los archivos de `_Songs/` no se cargan a
  ningún Set en vivo ni al standby hasta que el usuario los asigna por
  separado, así que una optimización en curso nunca afecta lo que
  realmente se puede reproducir en este momento.
  - La cola de trabajos es un pequeño archivo JSON por canción bajo
    `.setlist-admin/optimize-queue/` en el propio USB
    (`optimize_queue.py`), no en memoria — así que "Optimizing..."
    (que se muestra en vez del botón mientras un trabajo está activo,
    confirmado sondeando `GET /api/songs`) sobrevive a que el celular
    que lo encoló se desconecte y se vuelva a conectar más tarde, tal
    como se pidió. Un trabajo que falla (archivo fuente dañado o
    ilegible, o un timeout después de 4 horas) muestra "Optimize
    (retry)" con el motivo en el tooltip del botón.
  - La codificación en sí corre en una unidad de systemd nueva y
    siempre activa, `library-optimizer.service`, deliberadamente
    independiente del ciclo de vida de `setlist-admin.service`: un
    trabajo tan largo tiene que sobrevivir a que el watchdog de
    USB/red detenga la interfaz de administración en el momento en que
    un celular se desconecta, algo que un subproceso simple de ese
    servicio no lograría. Revisa la cola cada 5s y procesa un trabajo
    a la vez (este hardware no puede correr dos codificaciones de
    ffmpeg a la vez de forma útil).
  - A diferencia de la conversión manual del video de standby (que
    mantuvo `pedal-core.service` detenido, y la reproducción en negro,
    durante toda la codificación de ~90 minutos), el daemon lee el
    archivo fuente con el USB aún montado en modo lectura y codifica a
    un directorio local temporal (`~/pedal-optimizer-scratch/`, fuera
    del USB por completo) — el mecanismo compartido
    `pedal_core_guard.writable_usb()` (ahora su propio módulo, extraído
    de `api.py` cuando este daemon necesitó la misma lógica de detener-
    pedal-core/recuperar-montaje-roto como segundo llamador) solo se
    invoca durante los pocos segundos que toma copiar el resultado ya
    terminado, y mucho más pequeño, a su lugar final. `Nice=15`/
    `CPUWeight=10` (más agresivo que el propio `Nice=10`/`CPUWeight=20`
    de `setlist-admin.service`) evita que una codificación en curso le
    quite recursos a la reproducción en vivo.
  - `install.sh`/`rollback.sh` (las dos expansiones) ahora instalan/
    quitan `library-optimizer.service` junto con las unidades
    existentes, y `rollback.sh` también limpia el directorio temporal.
- Se movió el aviso de "formatos soportados" (audio MP3/WAV, video
  MP4/MOV/MPEG/MPG con audio incrustado, más la guía de video
  H.264/1080p/~8-12 Mbps) de la pantalla de Export Set — donde era
  ruido inútil en una vista pensada para leerse en el escenario, no
  para subir archivos — a justo al lado del control de subida real en
  la sección de biblioteca de canciones, donde sí sirve antes de elegir
  un archivo. Pedido real del usuario, las dos expansiones.
- **Corregido**: encontrado en vivo certificando la función de
  reemplazo por duplicado de arriba — volver a montar `/media/usb` en
  `ro` justo después de una escritura grande (un video de varios
  cientos de MB) expiró por timeout a los 10s más de una vez, aunque la
  escritura misma ya había terminado exitosamente. El archivo nunca
  corrió riesgo (confirmado: llegó bien las dos veces que pasó esto),
  pero la petición igual falló con un 500, y la auto-recuperación de
  montaje roto de arriba ni siquiera hizo falta (el montaje se mantuvo
  intacto — esto fue un simple timeout, no el incidente de montaje FUSE
  muerto de antes). Causa raíz: la capa FUSE parece seguir volcando
  datos en buffer al dispositivo físico en ese momento, lo cual puede
  durar más que la propia llamada de escritura que ya había retornado.
  `usb_mount._remount()` ahora corre un `sync -f <montaje>` de mejor
  esfuerzo antes del par umount/mount, forzando ese volcado por
  adelantado en vez de dejar que bloquee dentro de las llamadas con
  tiempo límite que siguen. Las dos expansiones, mantenidas
  convergentes.
- Agregado: subir una canción a la biblioteca compartida con un nombre
  que ya está ocupado ahora ofrece **"... already exists in the
  library. Replace it?"** en vez de simplemente fallar — confirma para
  reemplazarla en el mismo lugar (`_atomic_write_stream()` ya hace que
  eso sea seguro por sí mismo, igual que cualquier otra escritura acá),
  o cancela para dejar la existente sin tocar. Pedido real del usuario,
  hecho justo después de toparse con el rechazo por nombre duplicado
  durante la misma sesión de pruebas en vivo que encontró los dos
  incidentes de abajo. `library_ops.upload_song()` ganó un parámetro
  `overwrite` y un `SongAlreadyExistsError` más específico (una
  subclase de `LibraryOpsError`); `api.py` lo traduce específicamente a
  `ApiError(409)` en vez de un 400 genérico, así el frontend puede
  ofrecer la confirmación de reemplazo sin comparar el texto del error.
  Las dos expansiones, mantenidas convergentes.
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
