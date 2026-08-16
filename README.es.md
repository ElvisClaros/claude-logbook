# claude-sesiones

Explorá todas las conversaciones de [Claude Code](https://claude.com/claude-code)
que tenés guardadas en la máquina: como tabla en la terminal, o como una página
HTML autocontenida que se abre con doble clic.

Español · **[English](README.md)** · Sin dependencias, solo biblioteca estándar.

```
  #   SESIÓN                           RUTA                    FECHA  CUÁNDO     MSG    DUR ID
  1 | Migrar el pool de conexiones a … /home/ana/api           16 ago hoy          4     9m 5d10f1ee
  2 | Timeouts intermitentes en el he… /home/ana/api           16 ago hoy          2     3m 0f60f37a
  3 | Reescribir el buscador con Fuse… /home/ana/web           15 ago ayer         7    18m b69c1fc2
  4 | por qué tarda tanto npm ci       /home/ana/web           13 ago hace 3d      1    <1m d4d2a5be
  5 | sesión abierta sin mens… [vacía] /home/ana/infra         08 ago hace 1sem    —    <1m e0a4300e

5 sesiones · 3 proyectos · -s <nº> para leer una
```

## ⚠️ Tus transcripciones son privadas

`--json` y `--html` escriben **el texto completo de tus conversaciones**:
prompts, respuestas, rutas de archivos, nombres de ramas. El `sesiones.html` que
sale es una copia legible de todo lo que escribiste alguna vez en Claude Code.

No lo commitees, no lo subas, no lo pegues en un issue. El `.gitignore` del repo
ya excluye `sesiones.html` y `data.json`, pero el archivo lo cuidás vos.

## Instalación

Necesita Python 3.9 o más nuevo. Nada más.

```bash
pipx install git+https://github.com/ElvisClaros/claude-sesiones
```

O con pip, o directamente desde un clon:

```bash
pip install git+https://github.com/ElvisClaros/claude-sesiones

git clone https://github.com/ElvisClaros/claude-sesiones && cd claude-sesiones
python3 -m claude_sesiones          # sin instalar nada
```

## Uso

```bash
claude-sesiones                     # tabla de todas las sesiones
claude-sesiones docker              # filtra por título, ruta o rama
claude-sesiones -s 3                # lee el chat nº 3 de la tabla
claude-sesiones -s 5d10f1ee         # lo mismo, por prefijo de UUID
claude-sesiones -g "port already"   # busca dentro de las conversaciones
claude-sesiones -r 3                # imprime el comando para reanudarla
eval "$(claude-sesiones -r 3)"      # …o la reanuda directamente
claude-sesiones --html --open       # genera sesiones.html y lo abre
```

El número es la posición de la fila **en la tabla que estás viendo**, así que si
filtraste hay que repetir el filtro para leer esa fila:

```bash
claude-sesiones docker              # muestra 3 resultados
claude-sesiones docker -s 2         # lee el 2º de esos tres
```

### Opciones

| Flag | Qué hace |
| --- | --- |
| `-s`, `--show REF` | Muestra un chat (índice de la tabla o prefijo de UUID). |
| `-r`, `--resume REF` | Imprime `cd <proyecto> && claude --resume <uuid>`. |
| `-g`, `--grep TEXTO` | Deja las sesiones cuya transcripción contenga `TEXTO`. |
| `-p`, `--project RUTA` | Deja las sesiones cuya ruta de proyecto contenga `RUTA`. |
| `-n`, `--limit N` | Solo las N más recientes. |
| `-E`, `--hide-empty` | Oculta las sesiones sin mensajes. |
| `--no-tools` | En el chat, oculta las llamadas a herramientas. |
| `--no-pager` | No manda el chat a `$PAGER`. |
| `--no-color` | Salida sin color (también respeta `NO_COLOR`). |
| `--json` | Vuelca todas las sesiones en JSON por stdout. |
| `--html [ARCHIVO]` | Genera la página autocontenida (por defecto `sesiones.html`). |
| `--template ARCHIVO` | Usa tu propio template para `--html`. |
| `--open` | Abre en el navegador lo que haya generado `--html`. |
| `--no-cache` | Ignora el caché y re-parsea todo. |

### Borrar sesiones

Es irreversible y pregunta antes, salvo que pases `-y`:

```bash
claude-sesiones --delete-empty --dry-run   # qué borraría
claude-sesiones --delete-empty             # borra las vacías
claude-sesiones -D 101 -D e0a4300e         # borra sesiones puntuales
claude-sesiones -p /tmp --delete-empty     # solo las vacías de ese proyecto
```

Avisa si alguno de los archivos se escribió en los últimos cinco minutos: es muy
probable que sea una sesión que Claude Code todavía tiene abierta, y que la
vuelva a escribir al cerrarse.

## La página HTML

`claude-sesiones --html` genera un único archivo con los datos adentro. Sin
servidor, sin red, sin paso de build: lo copiás a otra máquina y sigue andando.

- Búsqueda por título, ruta, rama o UUID, y opcionalmente dentro de las
  transcripciones, mostrando el fragmento que coincide debajo de la fila.
- Filtro por proyecto, orden por cualquier columna, ocultar las vacías.
- Clic en una fila para leer la conversación en un panel lateral, con cercas de
  código, títulos y una línea por herramienta usada.
- Botón para copiar el `cd … && claude --resume …` de cualquier sesión.
- Tema claro y oscuro, con un botón que recuerda cuál elegiste.
- Cada sesión tiene su propio fragmento de URL: `sesiones.html#5d10f1ee-…` abre
  esa conversación directamente.
- Teclado: `/` o `Ctrl`+`K` enfoca el buscador, `Esc` lo limpia o cierra el lector.

Las fechas son relativas a **cuándo se leyeron los datos**, no a tu reloj, así
que "hoy" sigue queriendo decir lo que quería decir cuando generaste la página.

## Cómo funciona

Claude Code guarda una conversación por archivo, en formato JSON Lines:

```
~/.claude/projects/<ruta-del-proyecto-codificada>/<uuid>.jsonl
```

(Si moviste ese directorio, respeta `CLAUDE_CONFIG_DIR`.)

Cada línea es un evento. `claude-sesiones` los recorre y se queda con la
conversación: tus mensajes, las respuestas de Claude, y una línea por
herramienta usada, del estilo `Bash: git status`. A propósito **descarta lo que
devolvieron las herramientas**: son el 95 % de los bytes en disco y casi nada
del sentido.

Algunos detalles que conviene saber:

- **Títulos.** Claude genera uno durante la sesión (eventos `ai-title`); gana el
  más reciente. Cuando falta, se usa lo primero que escribiste vos — y ahí se
  nota, porque arranca en minúscula o suena a pregunta suelta.
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
  `$XDG_CACHE_HOME/claude-sesiones/cache.json`, indexado por tamaño y mtime. Es
  solo una optimización: si falta, quedó viejo o está roto, se re-parsea todo.
  `--no-cache` lo saltea por completo.

### Esquema del JSON

`--json` imprime un arreglo, de la sesión más recientemente activa a la más
vieja. Las claves son de una letra porque esos mismos registros van embebidos en
el HTML, donde el costo se paga una vez por sesión:

| Clave | Qué es |
| --- | --- |
| `id` | UUID de la sesión (el nombre del archivo). |
| `p` | Ruta del proyecto (`cwd`). |
| `b` | Rama de git. |
| `t` | Título. |
| `ai` | `true` si el título lo generó Claude. |
| `n` | `true` si parece un `claude -p` no interactivo. |
| `e` | `true` si la sesión no tiene mensajes. |
| `i` | `true` si `p` se dedujo de otra sesión del mismo proyecto. |
| `f` / `l` | Timestamp del primer y del último evento (ISO 8601). |
| `d` | Duración en minutos. |
| `u` / `a` | Cantidad de mensajes tuyos / de Claude. |
| `k` | Tamaño del archivo en KB. |
| `v` | Versión de Claude Code. |
| `c` | Transcripción: `[{"r": "u"｜"a"｜"t", "x": texto}]`. |

## Desarrollo

```bash
git clone https://github.com/ElvisClaros/claude-sesiones && cd claude-sesiones
python3 -m unittest discover -s tests -t .
```

Los tests arman árboles de `.jsonl` falsos en un directorio temporal y nunca
tocan `~/.claude`. No hay nada que instalar: ni runner de tests ni dependencias.

| Módulo | De qué se ocupa |
| --- | --- |
| `claude_sesiones/sessions.py` | Parsear los `.jsonl`, el caché, los filtros. |
| `claude_sesiones/terminal.py` | Colores ANSI, la tabla, imprimir un chat. |
| `claude_sesiones/webpage.py` | Meter los datos adentro del template. |
| `claude_sesiones/cli.py` | Los argumentos y los comandos. |
| `claude_sesiones/template.html` | La página: marcado, estilos y el código del navegador. |

## Licencia

[Apache-2.0](LICENSE).
