# Expansiones

*[Read in English](../../../expansions/README.md)*

Una **expansión** es un addon opcional y autocontenido al sistema base
del pedal (`src/core/`, `src/adapter/`, `src/mapper/`,
`pedal-core.service` — todo lo descrito en `MASTER_SPECIFICATION.md`).
El sistema base funciona idéntico sin importar si alguna expansión
está instalada o no. Instalar o quitar una expansión nunca toca,
depende de, ni se ve afectada por ninguna otra expansión.

## El modelo

Cada expansión vive completamente bajo `expansions/<nombre>/`, con lo
suyo:

```
expansions/<nombre>/
├── SPECIFICATION.md       Documento de diseño: arquitectura, decisiones, porqué
├── USAGE.md                Guía de uso para el usuario final (en)
├── docs/es/USAGE.md         ...y su traducción al español
├── src/                    Su propio código
├── systemd/                 Sus propios archivos de unidad systemd (con placeholders)
├── scripts/
│   ├── install.sh           La instala -- nunca se corre automáticamente
│   └── rollback.sh          La desinstala -- solo detiene/quita sus servicios
└── tests/                   Sus propios tests, corren independiente de la suite base
```

Consecuencias de esta forma, a propósito:

- **Nada en `src/core/`, `src/adapter/`, `src/mapper/`, ni
  `pedal-core.service` importa de, referencia, o depende de nada bajo
  `expansions/`.** El sistema base no tiene idea de que existe ninguna
  expansión.
- **Una expansión puede depender del propio `src/` del proyecto base**
  (por ejemplo, leer las constantes de extensión de archivo de
  `core.library` como fuente única de verdad) — esa es una relación
  normal de addon-depende-de-la-app-anfitriona. **Una expansión nunca
  debe depender de otra expansión.** Si dos expansiones resuelven
  problemas que se superponen, duplican el código que necesitan en vez
  de referenciar la carpeta de la otra.
- **Nada se instala automáticamente.** La instalación base de
  `systemd/README.md` nunca habilita los servicios de una expansión;
  eso siempre es un paso aparte y deliberado:
  `sh expansions/<nombre>/scripts/install.sh`.
- **`rollback.sh` nunca toca el estado de git.** Solo detiene/deshabilita
  los propios servicios systemd de la expansión y quita sus archivos de
  unidad. Deliberadamente **no** hace `git checkout` de nada — hacerlo
  podría revertir de forma colateral otra expansión o trabajo del
  proyecto base no relacionado, agregado después de que empezó el
  historial de esta expansión. Los archivos fuente de una expansión
  quedan inertes en disco una vez que sus servicios desaparecen; borrar
  la carpeta (`rm -rf expansions/<nombre>`) es un paso aparte, opcional
  y manual si además quieres que desaparezca del checkout.
- **Los tests de cada expansión corren de forma independiente**:
  `python -m unittest discover -s expansions/<nombre>/tests`. El CI
  (`.github/workflows/tests.yml`) corre la suite base y la suite de
  cada expansión como pasos separados, así que los tests fallidos de
  una expansión no esconden una regresión del proyecto base, ni al
  revés.

## Expansiones actuales

| Expansión | Qué hace | Estado |
|---|---|---|
| [`setlist-admin-usb`](../../../expansions/setlist-admin-usb/docs/es/USAGE.md) | Administra el USB de biblioteca (shows/Sets/pistas) desde el navegador de un teléfono, conectando el teléfono a la Pi por USB (tethering de Android / Personal Hotspot por cable en iPhone) | Implementada, todavía no validada en hardware real |
| [`setlist-admin-wifi`](../../../expansions/setlist-admin-wifi/docs/es/USAGE.md) | La misma administración de biblioteca, más configuración del WiFi de la Pi (red de casa / respaldo de hotspot del celular), alcanzable por WiFi | Implementada y con tests unitarios; validación en hardware real en pausa por un dongle USB de WiFi muerto (hardware, no diseño/código) |

Ambas se diseñaron para quedar convergibles: `setlist-admin-usb`
reutiliza sin cambios el backend de CRUD y la experiencia del frontend
de `setlist-admin-wifi`, solo reemplazando la capa de conectividad por
debajo. Ver el `SPECIFICATION.md` de cada una para el razonamiento
completo.
