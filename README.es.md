# claude-logbook

Explorá todas las conversaciones de [Claude Code](https://claude.com/claude-code)
que tenés guardadas en la máquina: como tabla en la terminal, o como una página
HTML autocontenida que se abre con doble clic.

Español · **[English](README.md)** · Sin dependencias, solo biblioteca estándar.

```
  #   SESSION                        PATH                  DATE   WHEN       MSG    DUR ID
  1 | Migrate the connection pool t… /home/ana/api         16 Aug today        4     9m 5d10f1ee
  2 | Intermittent timeouts in the … /home/ana/api         16 Aug today        2     3m 0f60f37a
  3 | Rewrite search with Fuse.js    /home/ana/web         15 Aug yesterday    7    18m b69c1fc2
  4 | why is npm ci so slow          /home/ana/web         13 Aug 3d ago       1    <1m d4d2a5be
  5 | session opened with n… [empty] /home/ana/infra       08 Aug 1w ago       —    <1m e0a4300e

5 sessions · 3 projects · -s <#> to read one
```

> **La CLI, su salida y su ayuda están en inglés.** Este README es solo una
> traducción. El comando lee archivos locales y nunca envía nada a ningún lado.

## ⚠️ Tus transcripciones son privadas

`--json` y `--html` escriben **el texto completo de tus conversaciones y de las
memorias de tus proyectos**:
prompts, respuestas, rutas de archivos, nombres de ramas. El `sessions.html` que
sale es una copia legible de todo lo que escribiste alguna vez en Claude Code.
Exportar una sola sesión (`-s 3 --html`) sigue siendo esa conversación entera:
leela antes de compartirla.

`--share` sube una conversación a propósito, a un link público: ver
[Compartir una sesión](#compartir-una-sesión).

No lo commitees, no lo subas, no lo pegues en un issue. El `.gitignore` del repo
ya excluye `sessions.html` y `data.json`, pero el archivo lo cuidás vos.

## Instalación

Necesita Python 3.9 o más nuevo. Nada más.

```bash
pipx install claude-logbook
```

O con pip, o desde el último commit, o directamente desde un clon:

```bash
pip install claude-logbook

pipx install git+https://github.com/ElvisClaros/claude-logbook   # sin publicar

git clone https://github.com/ElvisClaros/claude-logbook && cd claude-logbook
python3 -m claude_logbook          # sin instalar nada
```

## Uso

```bash
claude-logbook                     # tabla de todas las sesiones
claude-logbook docker              # filtra por título, ruta o rama
claude-logbook -s 3                # lee el chat nº 3 de la tabla
claude-logbook -s 5d10f1ee         # lo mismo, por prefijo de UUID
claude-logbook -g "port already"   # busca dentro de las conversaciones
claude-logbook -r 3                # imprime el comando para reanudarla
eval "$(claude-logbook -r 3)"      # …o la reanuda directamente
claude-logbook --html --open       # genera sessions.html y lo abre
claude-logbook -s 3 --html         # exporta solo la #3 → session-<id>.html
claude-logbook -m                  # las memorias de tus proyectos
claude-logbook -P                  # permisos, directorios extra y confianza
```

El número es la posición de la fila **en la tabla que estás viendo**, así que si
filtraste hay que repetir el filtro para leer esa fila:

```bash
claude-logbook docker              # muestra 3 resultados
claude-logbook docker -s 2         # lee el 2º de esos tres
```

### Opciones

| Flag | Qué hace |
| --- | --- |
| `-s`, `--show REF` | Muestra un chat (índice de la tabla o prefijo de UUID). |
| `-r`, `--resume REF` | Imprime `cd <proyecto> && claude --resume <uuid>`. |
| `-g`, `--grep TEXT` | Deja las sesiones cuya transcripción contenga `TEXT`. |
| `-p`, `--project PATH` | Deja las sesiones cuya ruta de proyecto contenga `PATH`. |
| `-n`, `--limit N` | Solo las N más recientes. |
| `-E`, `--hide-empty` | Oculta las sesiones sin mensajes. |
| `--no-tools` | En el chat, oculta las llamadas a herramientas. |
| `--no-pager` | No manda el chat a `$PAGER`. |
| `--no-color` | Salida sin color (también respeta `NO_COLOR`). |
| `--json` | Vuelca las sesiones en JSON por stdout: todas, o solo `-s` / lo que dejen los filtros. |
| `--html [FILE]` | Genera la página autocontenida con la misma selección que `--json` (por defecto `sessions.html`, o `session-<id>.html` con `-s`). |
| `--template FILE` | Usa tu propio template para `--html`. |
| `--open` | Abre en el navegador lo que haya generado `--html`. |
| `--images` | Con `-s`: incluye las imágenes de la sesión en `--html`, `--json` o `--share`. |
| `--no-cache` | Ignora el caché y re-parsea todo. |
| `-m`, `--memory` | Trabaja sobre las memorias en vez de las sesiones. |
| `--type TYPE` | Con `-m`: filtra por `project`, `user`, `feedback` o `reference`. |
| `--check` | Con `-m`: audita índices, enlaces y sesiones de origen. |
| `-P`, `--perms` | Lista reglas de permisos, directorios extra y confianza. |
| `--allow`, `--ask`, `--deny RULE` | Agrega una regla de permisos (ver abajo). |
| `--remove-rule RULE` | Saca una regla de `allow`, `ask` y `deny`. |
| `--add-dir`, `--remove-dir DIR` | Edita `additionalDirectories`. |
| `--trust`, `--untrust` | Acepta o reinicia el diálogo de confianza del proyecto `-p`. |
| `--scope SCOPE` | Archivo de settings a cambiar: `user`, `project` o `local`. |
| `--share` | Con `-s`: publica esa sesión e imprime su link (pregunta antes, salvo `-y`). |
| `--expire TTL` | Cuánto vive el share: `1d`, `7d`, `30d` (default) o `90d`. |
| `--shares` | Lista lo que compartió esta máquina. |
| `--unshare REF` | Borra un share: su id, su URL o el prefijo de UUID de la sesión. |
| `--server URL` | Servidor de shares (default `$CLAUDE_LOGBOOK_SERVER` o `https://claude-logbook.all.ar`). |

### Borrar sesiones

Es irreversible y pregunta antes, salvo que pases `-y`:

```bash
claude-logbook --delete-empty --dry-run   # qué borraría
claude-logbook --delete-empty             # borra las vacías
claude-logbook -D 101 -D e0a4300e         # borra sesiones puntuales
claude-logbook -p /tmp --delete-empty     # solo las vacías de ese proyecto
```

Avisa si alguno de los archivos se escribió en los últimos cinco minutos: es muy
probable que sea una sesión que Claude Code todavía tiene abierta, y que la
vuelva a escribir al cerrarse.

## Memoria de los proyectos

Claude Code guarda recuerdos por proyecto en
`~/.claude/projects/<proyecto>/memory/`: un `.md` por memoria, con frontmatter
YAML y cuerpo markdown, más un `MEMORY.md` que los indexa.

**El índice es lo único que se carga en contexto al arrancar una sesión.** Una
memoria que está en disco pero no figura en `MEMORY.md` deja de recordarse
aunque el archivo siga ahí, así que la diferencia entre ambos conviene mirarla.

`-m` cambia el sustantivo y reusa los mismos verbos que ya conocés:

```bash
claude-logbook -m                  # tabla de memorias
claude-logbook -m docker           # busca en nombre, descripción y cuerpo
claude-logbook -m --type user      # solo las de un tipo
claude-logbook -m -s 3             # lee la memoria nº 3
claude-logbook -m -s deadlock      # lo mismo, por nombre
claude-logbook -m -p /home/u/proj  # las de un proyecto
```

Los tipos los define Claude al escribirlas: **project** es trabajo en curso,
**user** quién sos y cómo trabajás, **feedback** correcciones tuyas, y
**reference** punteros a recursos externos.

### Auditar

```bash
claude-logbook -m --check
```

Sale con código 1 si encuentra algo, y reporta:

- proyectos con memorias pero sin `MEMORY.md`;
- memorias que no figuran en el índice de su proyecto;
- entradas del índice que apuntan a un archivo que ya no existe;
- enlaces `[[...]]` sin destino — el formato los permite, marcan algo que
  todavía no se escribió;
- memorias cuya sesión de origen ya no está en disco: la memoria sobrevivió a
  la conversación que la creó.

### Borrar memorias

Igual que con las sesiones: irreversible, pregunta antes salvo con `-y`. Además
de borrar el archivo, saca su línea de `MEMORY.md` para no dejar el índice
apuntando a la nada.

```bash
claude-logbook -m -D 3 --dry-run   # qué borraría
claude-logbook -m -D deploy-docker # borra esa memoria
```

## Permisos

Claude Code guarda sus reglas de permisos en archivos `settings.json` y la
respuesta a "¿confiás en esta carpeta?" en `~/.claude.json`. `-P` los muestra
juntos, y unos pocos flags los editan sin abrir ningún JSON:

```bash
claude-logbook -P                          # reglas de usuario + proyectos con reglas
claude-logbook -P -p api                   # un proyecto, tenga reglas o no
claude-logbook --allow "Bash(npm test:*)" -p .
claude-logbook --deny "Read(./.env)" --scope project -p .
claude-logbook --remove-rule WebFetch      # fuera de allow, ask y deny
claude-logbook --add-dir ~/shared -p .     # additionalDirectories
claude-logbook --trust -p ~/code/api       # marca esa carpeta como confiable
claude-logbook --untrust -p ~/code/api     # Claude Code vuelve a preguntar
```

Adónde va cada cambio:

| Qué | Archivo |
| --- | --- |
| Reglas y directorios, sin `-p` | `~/.claude/settings.json` (alcance de usuario) |
| Reglas y directorios con `-p` | `<proyecto>/.claude/settings.local.json` (personal) |
| Lo mismo, con `--scope project` | `<proyecto>/.claude/settings.json` (suele ir al repo) |
| `--trust` / `--untrust` | `hasTrustDialogAccepted` en `~/.claude.json` |

`-p` acepta un directorio, o cualquier pedazo de la ruta de un proyecto que
Claude Code haya visto, siempre que coincida con uno solo. Las reglas usan la
sintaxis de Claude Code: `Tool` o `Tool(especificador)`. Una regla vive en una
sola lista, así que `--deny X` saca `X` de `allow` y `ask`. El resto de las
claves de esos archivos queda como estaba, el archivo se reemplaza de forma
atómica conservando sus permisos, y `--dry-run` muestra el cambio sin hacerlo.
Las sesiones ya abiertas pueden necesitar reiniciarse para notarlo.

`~/.claude.json` también guarda tu cuenta y el estado de cada Claude Code en
marcha, que lo reescriben seguido: claude-logbook lo lee justo antes de
cambiarlo y reintenta si se modificó en el medio.

## Compartir una sesión

`--share` publica **una** sesión en <https://claude-logbook.all.ar> e imprime
su link:

```bash
claude-logbook -s 3 --share               # muestra qué se sube y pregunta
claude-logbook -s 3 --share --expire 7d   # desaparece en una semana (default 30 días)
claude-logbook -s 3 --share --images      # con las capturas e imágenes
claude-logbook -s 3 --share               # otra vez más tarde: mismo link, contenido nuevo
claude-logbook --shares                   # qué compartiste y hasta cuándo
claude-logbook --unshare 5d10f1ee         # bajarlo (id, URL o sesión)
```

Cada share tiene tres formas:

| URL | Contenido |
| --- | --- |
| `/share/<id>` | La conversación como página, la misma vista que `--html`. |
| `/share/<id>.txt` | La transcripción en texto plano. |
| `/share/<id>.json` | Los datos, como los imprime `--json -s`. |

Antes de subir muestra el título, la ruta del proyecto, el tamaño y un aviso
por cualquier cosa que parezca una API key, un token o una clave privada (dónde
está, nunca el valor). `--dry-run` se detiene ahí.

Para tener en cuenta:

- **Cualquiera con el link puede leer la conversación entera**, llamadas a
  herramientas y rutas incluidas. No está cifrada; el servidor también la puede
  leer.
- Solo la máquina que creó un share puede actualizarlo o borrarlo: el servidor
  devuelve un secret que se guarda en
  `$XDG_STATE_HOME/claude-logbook/shares.json` (`~/.local/state/...`), con modo
  600. Si perdés ese archivo, el share queda hasta que vence.
- **Las imágenes van solo con `--images`**: las que pegaste y las que una
  herramienta le dio a Claude (una captura, una imagen que leyó). El aviso no
  mira dentro de ellas, así que revisalas antes. El servidor acepta hasta 20 MB
  por share.
- Las memorias nunca se comparten.

El servidor está en [`server/`](server/README.md): Go, solo biblioteca estándar,
imagen Docker `FROM scratch`. Podés correr el tuyo y apuntar
`CLAUDE_LOGBOOK_SERVER` a él.

## La página HTML

`claude-logbook --html` genera un único archivo con los datos adentro. Sin
servidor, sin red, sin paso de build: lo copiás a otra máquina y sigue andando.

- Búsqueda por título, ruta, rama o UUID, y opcionalmente dentro de las
  transcripciones, mostrando el fragmento que coincide debajo de la fila.
- Filtro por proyecto, orden por cualquier columna, ocultar las vacías.
- Clic en una fila para leer la conversación en un panel lateral, con cercas de
  código, títulos y una línea por herramienta usada.
- Botón para copiar el `cd … && claude --resume …` de cualquier sesión.
- Tema claro y oscuro, con un botón que recuerda cuál elegiste.
- Cada sesión tiene su propio fragmento de URL: `sessions.html#5d10f1ee-…` abre
  esa conversación directamente.
- Teclado: `/` o `Ctrl`+`K` enfoca el buscador, `Esc` lo limpia o cierra el lector.

Una página con una sola sesión (`-s 3 --html`, o cualquier link compartido) no
muestra la lista: es directamente esa conversación, con título, datos y la
transcripción. Una sola sesión se exporta sin memorias.

Las fechas son relativas a **cuándo se leyeron los datos**, no a tu reloj, así
que "hoy" sigue queriendo decir lo que quería decir cuando generaste la página.

## Cómo funciona

Claude Code guarda una conversación por archivo, en formato JSON Lines:

```
~/.claude/projects/<ruta-del-proyecto-codificada>/<uuid>.jsonl
```

(Si moviste ese directorio, respeta `CLAUDE_CONFIG_DIR`.)

Cada línea es un evento. `claude-logbook` los recorre y se queda con la
conversación: tus mensajes, las respuestas de Claude, y una línea por
herramienta usada, del estilo `Bash: git status`. A propósito **descarta lo que
devolvieron las herramientas**: son el 95 % de los bytes en disco y casi nada
del sentido.

Algunos detalles que conviene saber:

- **Títulos.** Gana el que pusiste con `/rename` (eventos `custom-title`); si
  no, el que genera Claude durante la sesión (`ai-title`), el más reciente de
  cada uno. Cuando faltan los dos, se usa lo primero que escribiste vos — y ahí
  se nota, porque arranca en minúscula o suena a pregunta suelta.
- **Compactación.** Cuando se acaba el contexto (o con `/compact`) Claude Code
  reemplaza la conversación anterior por un resumen. Ese resumen se muestra como
  una marca "context compacted here", no como un mensaje tuyo, y no se cuenta.
- **Ramas.** `/branch` (y `/fork`) arrancan una sesión nueva que copia el
  historial de la original. claude-logbook toma esa copia como heredada: se
  muestra colapsada bajo "Inherited history", y solo lo que vino después cuenta
  para los mensajes, la duración y la fecha de inicio. En la tabla la sesión
  lleva un chip `branch`.
- **Imágenes.** La transcripción muestra dónde estaba cada una (`▣ image
  attached`, `▣ image from the tool`). Las imágenes en sí van solo en el
  `--html`, `--json` o `--share` de una sesión, con `--images`: PNG, JPEG, GIF y
  WebP, nunca SVG.
- **Cambios de directorio.** Cuando la sesión pasa a otro directorio (un `cd`
  que queda, `/cd`, un worktree) la transcripción muestra ahí `→ /ruta/nueva`, y
  `-p` también encuentra la sesión por cualquiera de los directorios donde trabajó.
- **Duración** es tiempo activo: los intervalos entre mensajes, sin las pausas
  de más de 30 minutos. Una sesión retomada a lo largo de varios días no cuenta
  los días del medio.
- **Sesiones vacías** son las que se abrieron pero nunca recibieron un mensaje:
  un `/resume` cancelado, un `/login`.
- **No interactivas** son `claude -p` con algo piped por stdin — típicamente un
  `git diff` para redactar el mensaje de commit. Se detectan como un único
  mensaje larguísimo sin ninguna ida y vuelta.
- **Rutas inferidas.** Un `/resume` cancelado nunca registra `cwd`, y el nombre
  del directorio no se puede invertir de forma fiable (porque `/` y `.` se
  codifican los dos como `-`), así que la ruta se toma prestada de otra sesión
  del mismo proyecto y queda marcada.
- **Sidechains** (transcripciones de subagentes) se saltean.
- **Caché.** Lo parseado se guarda en
  `$XDG_CACHE_HOME/claude-logbook/cache.json`, indexado por tamaño y mtime. Es
  solo una optimización: si falta, quedó viejo o está roto, se re-parsea todo.
  `--no-cache` lo saltea por completo.

### Esquema del JSON

`--json` imprime un objeto con dos arreglos: `s` son las sesiones, de la más
recientemente activa a la más vieja, y `m` las memorias, de la más recién
modificada a la más vieja.

```json
{"s": [ … ], "m": [ … ]}
```

Las claves son de una letra porque esos mismos registros van embebidos en el
HTML, donde el costo se paga una vez por registro.

Cada sesión de `s`:

| Clave | Qué es |
| --- | --- |
| `id` | UUID de la sesión (el nombre del archivo). |
| `p` | Ruta del proyecto (`cwd`). |
| `b` | Rama de git. |
| `t` | Título. |
| `ai` | `true` si el título lo pusiste con `/rename` o lo generó Claude. |
| `n` | `true` si parece un `claude -p` no interactivo. |
| `e` | `true` si la sesión no tiene mensajes. |
| `i` | `true` si `p` se dedujo de otra sesión del mismo proyecto. |
| `f` / `l` | Timestamp del primer y del último evento (ISO 8601). |
| `d` | Minutos activos (sin las pausas de más de 30 minutos). En una rama, solo su parte propia. |
| `u` / `a` | Cantidad de mensajes tuyos / de Claude. En una rama, solo su parte propia. |
| `k` | Tamaño del archivo en KB. |
| `v` | Versión de Claude Code. |
| `c` | Transcripción: `[{"r": "u"｜"a"｜"t"｜"c"｜"d"｜"i"｜"v", "x": texto}]`; `t` es una llamada a herramienta, `c` un resumen de compactación, `d` un cambio de directorio de trabajo, `i` una imagen que adjuntaste y `v` una que una herramienta le dio a Claude. Con `--images` esas dos llevan `src`, la imagen como URL `data:`. |
| `h` | Cuántos bloques al principio de `c` se heredaron de la sesión de la que salió esta rama (0 si no es una rama). |
| `o` / `ot` | Id y título de esa sesión (`null` si no es una rama; `ot` también si ya no está en disco). |

Cada memoria de `m`:

| Clave | Qué es |
| --- | --- |
| `name` | Nombre del frontmatter (o el del archivo, si falta). |
| `file` | Nombre del archivo, con extensión. |
| `p` | Ruta del proyecto. |
| `desc` | Descripción del frontmatter. |
| `ty` | Tipo: `project`, `user`, `feedback` o `reference`. |
| `src` | UUID de la sesión que la escribió, si lo declara. |
| `body` | Cuerpo markdown, sin el frontmatter. |
| `ln` | Enlaces `[[...]]` que aparecen en el cuerpo. |
| `k` | Tamaño en KB. |
| `l` | Última modificación (ISO 8601). |
| `ix` | `true` si figura en `MEMORY.md`. |
| `hix` | `true` si el proyecto tiene `MEMORY.md`. |

## Desarrollo

```bash
git clone https://github.com/ElvisClaros/claude-logbook && cd claude-logbook
python3 -m unittest discover -s tests -t .
```

Los tests arman árboles de `.jsonl` falsos en un directorio temporal y nunca
tocan `~/.claude`. No hay nada que instalar: ni runner de tests ni dependencias.

| Módulo | De qué se ocupa |
| --- | --- |
| `claude_logbook/sessions.py` | Parsear los `.jsonl`, el caché, los filtros. |
| `claude_logbook/memory.py` | Leer los `memory/*.md` y auditarlos. |
| `claude_logbook/config.py` | Reglas de permisos, directorios extra y confianza en carpetas. |
| `claude_logbook/terminal.py` | Colores ANSI, la tabla, imprimir un chat. |
| `claude_logbook/webpage.py` | Meter los datos adentro del template. |
| `claude_logbook/share.py` | Hablar con el servidor de shares y el registro local de shares. |
| `claude_logbook/cli.py` | Los argumentos y los comandos. |
| `server/` | El servidor de shares (Go): `cd server && go generate && go test ./...`. |
| `claude_logbook/template.html` | La página: marcado, estilos y el código del navegador. |

## Licencia

[Apache-2.0](LICENSE).
