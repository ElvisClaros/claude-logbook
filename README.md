# claude-sesiones

Browse every [Claude Code](https://claude.com/claude-code) conversation stored on
your machine — as a table in your terminal, or as a single self-contained HTML
page you open with a double click.

**[Español](README.es.md)** · English · No dependencies, standard library only.

> **The CLI, its output and its help text are in Spanish.** Only this README is
> translated. The command reads local files and never sends anything anywhere.

```
  #   SESIÓN                           RUTA                    FECHA  CUÁNDO     MSG    DUR ID
  1 | Migrar el pool de conexiones a … /home/ana/api           16 ago hoy          4     9m 5d10f1ee
  2 | Timeouts intermitentes en el he… /home/ana/api           16 ago hoy          2     3m 0f60f37a
  3 | Reescribir el buscador con Fuse… /home/ana/web           15 ago ayer         7    18m b69c1fc2
  4 | por qué tarda tanto npm ci       /home/ana/web           13 ago hace 3d      1    <1m d4d2a5be
  5 | sesión abierta sin mens… [vacía] /home/ana/infra         08 ago hace 1sem    —    <1m e0a4300e

5 sesiones · 3 proyectos · -s <nº> para leer una
```

## ⚠️ Your transcripts are private

`--json` and `--html` write out **the full text of your conversations**: prompts,
answers, file paths, branch names. The generated `sesiones.html` is a complete,
readable copy of everything you ever typed into Claude Code.

Do not commit it, do not upload it, do not paste it into a bug report. The
repository's `.gitignore` already excludes `sesiones.html` and `data.json`, but
the file itself is yours to look after.

## Install

Requires Python 3.9 or newer. Nothing else.

```bash
pipx install git+https://github.com/ElvisClaros/claude-sesiones
```

Or with pip, or straight from a clone:

```bash
pip install git+https://github.com/ElvisClaros/claude-sesiones

git clone https://github.com/ElvisClaros/claude-sesiones && cd claude-sesiones
python3 -m claude_sesiones          # no install needed
```

## Usage

```bash
claude-sesiones                     # table of every session
claude-sesiones docker              # filter by title, path or branch
claude-sesiones -s 3                # read conversation #3 from the table
claude-sesiones -s 5d10f1ee         # same, by UUID prefix
claude-sesiones -g "port already"   # search inside the conversations
claude-sesiones -r 3                # print the command that resumes it
eval "$(claude-sesiones -r 3)"      # …or resume it right away
claude-sesiones --html --open       # build sesiones.html and open it
```

The number is the row's position **in the table you are looking at**, so if you
filtered, repeat the filter to read that row:

```bash
claude-sesiones docker              # shows 3 results
claude-sesiones docker -s 2         # reads the 2nd of those three
```

### Options

| Flag | What it does |
| --- | --- |
| `-s`, `--show REF` | Print a conversation (table index or UUID prefix). |
| `-r`, `--resume REF` | Print `cd <project> && claude --resume <uuid>`. |
| `-g`, `--grep TEXT` | Keep sessions whose transcript contains `TEXT`. |
| `-p`, `--project PATH` | Keep sessions whose project path contains `PATH`. |
| `-n`, `--limit N` | Only the N most recent. |
| `-E`, `--hide-empty` | Hide sessions with no messages. |
| `--no-tools` | Hide tool calls when printing a conversation. |
| `--no-pager` | Do not pipe the conversation through `$PAGER`. |
| `--no-color` | Plain output (`NO_COLOR` is honoured too). |
| `--json` | Dump every session as JSON on stdout. |
| `--html [FILE]` | Build the standalone page (default `sesiones.html`). |
| `--template FILE` | Use your own template for `--html`. |
| `--open` | Open whatever `--html` produced in your browser. |
| `--no-cache` | Ignore the cache and re-parse everything. |

### Deleting sessions

Irreversible, and it asks first unless you pass `-y`:

```bash
claude-sesiones --delete-empty --dry-run   # what it would delete
claude-sesiones --delete-empty             # delete the empty ones
claude-sesiones -D 101 -D e0a4300e         # delete specific sessions
claude-sesiones -p /tmp --delete-empty     # only the empty ones of that project
```

It warns you about any file written in the last five minutes: that is very
likely a session Claude Code still has open, and it will write it back on exit.

## The HTML page

`claude-sesiones --html` produces one file with the data embedded inside it. No
server, no network, no build step — copy it to another machine and it still
works.

- Search by title, path, branch or UUID, and optionally inside the transcripts,
  with the matching snippet shown under the row.
- Filter by project, sort by any column, hide empty sessions.
- Click a row to read the conversation in a side panel, with code fences,
  headings and one line per tool call.
- Copy the `cd … && claude --resume …` command for any session.
- Light and dark themes, with a toggle that remembers your choice.
- Each session gets its own URL fragment, so `sesiones.html#5d10f1ee-…` opens
  that conversation directly.
- Keyboard: `/` or `Ctrl`+`K` focuses the search box, `Esc` clears it or closes
  the reader.

Dates are relative to **when the data was read**, not to your clock, so "today"
keeps meaning what it meant when you generated the page.

## How it works

Claude Code writes one JSON Lines file per conversation:

```
~/.claude/projects/<url-encoded-project-path>/<uuid>.jsonl
```

(`CLAUDE_CONFIG_DIR` is honoured if you moved that directory.)

Every line is an event. `claude-sesiones` walks them and keeps the conversation
itself — your messages, Claude's replies, and a one-line summary per tool call
such as `Bash: git status`. It deliberately **drops tool results**, which are
about 95% of the bytes on disk and almost none of the meaning.

A few details worth knowing:

- **Titles.** Claude generates one during the session (`ai-title` events); the
  most recent wins. Without one, the first thing you typed is used instead —
  which is visible, because it starts in lowercase or reads like a loose
  question.
- **Empty sessions** were opened but never received a message: a cancelled
  `/resume`, a `/login`.
- **Non-interactive** sessions are `claude -p` with something piped into stdin —
  typically a `git diff` to write a commit message. They are detected as a
  single very long message with no back and forth.
- **Inferred paths.** A cancelled `/resume` never records a `cwd`, and the
  directory name cannot be reversed reliably (both `/` and `.` encode as `-`),
  so the path is borrowed from another session of the same project and flagged.
- **Sidechains** (subagent transcripts) are skipped.
- **Cache.** Parsed sessions are cached in
  `$XDG_CACHE_HOME/claude-sesiones/cache.json`, keyed by size and mtime. It is
  only an optimisation: if it is missing, stale or corrupt, everything is
  re-parsed. `--no-cache` skips it entirely.

### JSON schema

`--json` prints an array, most recently active first. Keys are one letter
because the same records are embedded in the HTML, where the cost is paid once
per session:

| Key | Meaning |
| --- | --- |
| `id` | Session UUID (the file name). |
| `p` | Project path (`cwd`). |
| `b` | Git branch. |
| `t` | Title. |
| `ai` | `true` if Claude generated the title. |
| `n` | `true` if it looks like a non-interactive `claude -p`. |
| `e` | `true` if the session has no messages. |
| `i` | `true` if `p` was inferred from a sibling session. |
| `f` / `l` | First and last event timestamps (ISO 8601). |
| `d` | Duration in minutes. |
| `u` / `a` | Message counts, yours / Claude's. |
| `k` | File size in KB. |
| `v` | Claude Code version. |
| `c` | Transcript: `[{"r": "u"｜"a"｜"t", "x": text}]`. |

## Development

```bash
git clone https://github.com/ElvisClaros/claude-sesiones && cd claude-sesiones
python3 -m unittest discover -s tests -t .
```

The tests build fake `.jsonl` trees in a temporary directory and never touch
`~/.claude`. There is nothing to install: no test runner, no dependencies.

| Module | Responsibility |
| --- | --- |
| `claude_sesiones/sessions.py` | Parsing the `.jsonl` files, the cache, filters. |
| `claude_sesiones/terminal.py` | ANSI colours, the table, printing a conversation. |
| `claude_sesiones/webpage.py` | Embedding the data into the template. |
| `claude_sesiones/cli.py` | Argument parsing and the commands. |
| `claude_sesiones/template.html` | The page: markup, styles and the browser-side code. |

## License

[Apache-2.0](LICENSE).
