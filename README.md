# claude-logbook

Browse every [Claude Code](https://claude.com/claude-code) conversation stored on
your machine — as a table in your terminal, or as a single self-contained HTML
page you open with a double click.

**[Español](README.es.md)** · English · No dependencies, standard library only.

```
  #   SESSION                        PATH                  DATE   WHEN       MSG    DUR ID
  1 | Migrate the connection pool t… /home/ana/api         16 Aug today        4     9m 5d10f1ee
  2 | Intermittent timeouts in the … /home/ana/api         16 Aug today        2     3m 0f60f37a
  3 | Rewrite search with Fuse.js    /home/ana/web         15 Aug yesterday    7    18m b69c1fc2
  4 | why is npm ci so slow          /home/ana/web         13 Aug 3d ago       1    <1m d4d2a5be
  5 | session opened with n… [empty] /home/ana/infra       08 Aug 1w ago       —    <1m e0a4300e

5 sessions · 3 projects · -s <#> to read one
```

The command reads local files and never sends anything anywhere.

## ⚠️ Your transcripts are private

`--json` and `--html` write out **the full text of your conversations and your
projects' memories**: prompts,
answers, file paths, branch names. The generated `sessions.html` is a complete,
readable copy of everything you ever typed into Claude Code. Exporting a single
session (`-s 3 --html`) is still that whole conversation: read it before you
share it.

`--share` uploads one conversation on purpose, to a public link: see
[Sharing a session](#sharing-a-session).

Do not commit it, do not upload it, do not paste it into a bug report. The
repository's `.gitignore` already excludes `sessions.html` and `data.json`, but
the file itself is yours to look after.

## Install

Requires Python 3.9 or newer. Nothing else.

```bash
pipx install claude-logbook
```

Or with pip, from the latest commit, or straight from a clone:

```bash
pip install claude-logbook

pipx install git+https://github.com/ElvisClaros/claude-logbook   # unreleased

git clone https://github.com/ElvisClaros/claude-logbook && cd claude-logbook
python3 -m claude_logbook          # no install needed
```

## Usage

```bash
claude-logbook                     # table of every session
claude-logbook docker              # filter by title, path or branch
claude-logbook -s 3                # read conversation #3 from the table
claude-logbook -s 5d10f1ee         # same, by UUID prefix
claude-logbook -g "port already"   # search inside the conversations
claude-logbook -r 3                # print the command that resumes it
eval "$(claude-logbook -r 3)"      # …or resume it right away
claude-logbook --html --open       # build sessions.html and open it
claude-logbook -s 3 --html         # export only #3 → session-<id>.html
claude-logbook -m                  # your projects' memories
claude-logbook -P                  # permissions, extra directories and trust
```

The number is the row's position **in the table you are looking at**, so if you
filtered, repeat the filter to read that row:

```bash
claude-logbook docker              # shows 3 results
claude-logbook docker -s 2         # reads the 2nd of those three
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
| `--json` | Dump the sessions as JSON on stdout: all of them, or only `-s` / what the filters keep. |
| `--html [FILE]` | Build the standalone page with the same selection as `--json` (default `sessions.html`, or `session-<id>.html` with `-s`). |
| `--template FILE` | Use your own template for `--html`. |
| `--open` | Open whatever `--html` produced in your browser. |
| `--no-cache` | Ignore the cache and re-parse everything. |
| `-m`, `--memory` | Work on memories instead of sessions. |
| `--type KIND` | With `-m`: filter by `project`, `user`, `feedback` or `reference`. |
| `--check` | With `-m`: audit indexes, links and origin sessions. |
| `-P`, `--perms` | List permission rules, extra directories and folder trust. |
| `--allow`, `--ask`, `--deny RULE` | Add a permission rule (see below). |
| `--remove-rule RULE` | Remove a rule from `allow`, `ask` and `deny`. |
| `--add-dir`, `--remove-dir DIR` | Edit `additionalDirectories`. |
| `--trust`, `--untrust` | Accept or reset the trust dialog of the `-p` project. |
| `--scope SCOPE` | Settings file to change: `user`, `project` or `local`. |
| `--share` | With `-s`: publish that session and print its link (asks first unless `-y`). |
| `--expire TTL` | How long the share lives: `1d`, `7d`, `30d` (default) or `90d`. |
| `--shares` | List what this machine has shared. |
| `--unshare REF` | Delete a share: its id, its URL or the session UUID prefix. |
| `--server URL` | Share server (default `$CLAUDE_LOGBOOK_SERVER` or `https://claude-logbook.all.ar`). |

### Deleting sessions

Irreversible, and it asks first unless you pass `-y`:

```bash
claude-logbook --delete-empty --dry-run   # what it would delete
claude-logbook --delete-empty             # delete the empty ones
claude-logbook -D 101 -D e0a4300e         # delete specific sessions
claude-logbook -p /tmp --delete-empty     # only the empty ones of that project
```

It warns you about any file written in the last five minutes: that is very
likely a session Claude Code still has open, and it will write it back on exit.

## Project memory

Claude Code stores per-project memories in
`~/.claude/projects/<project>/memory/`: one `.md` per memory, with YAML
frontmatter and a markdown body, plus a `MEMORY.md` that indexes them.

**The index is the only part loaded into context when a session starts.** A
memory that is on disk but missing from `MEMORY.md` stops being remembered even
though the file is still there, so the gap between the two is worth watching.

`-m` swaps the noun and reuses the verbs you already know:

```bash
claude-logbook -m                  # table of memories
claude-logbook -m docker           # search name, description and body
claude-logbook -m --type user      # only one kind
claude-logbook -m -s 3             # read memory #3
claude-logbook -m -s deadlock      # same, by name
claude-logbook -m -p /home/u/proj  # only one project's
```

Claude picks the kind when it writes them: **project** is work in progress,
**user** is who you are and how you work, **feedback** is corrections you gave,
and **reference** points at external resources.

### Auditing

```bash
claude-logbook -m --check
```

Exits 1 if it finds anything, and reports:

- projects with memories but no `MEMORY.md`;
- memories missing from their project's index;
- index entries pointing at a file that no longer exists;
- `[[...]]` links with no target — the format allows them, they mark something
  not written yet;
- memories whose origin session is gone from disk: the memory outlived the
  conversation that created it.

### Deleting memories

Same as sessions: irreversible, asks first unless you pass `-y`. Besides
removing the file it drops its line from `MEMORY.md`, so the index is not left
pointing at nothing.

```bash
claude-logbook -m -D 3 --dry-run   # what it would delete
claude-logbook -m -D deploy-docker # delete that memory
```

## Permissions

Claude Code keeps its permission rules in `settings.json` files and the
"do you trust this folder?" answer in `~/.claude.json`. `-P` shows them all
together, and a handful of flags edit them without opening any JSON:

```bash
claude-logbook -P                          # user rules + every project with rules
claude-logbook -P -p api                   # one project, with or without rules
claude-logbook --allow "Bash(npm test:*)" -p .
claude-logbook --deny "Read(./.env)" --scope project -p .
claude-logbook --remove-rule WebFetch      # out of allow, ask and deny
claude-logbook --add-dir ~/shared -p .     # additionalDirectories
claude-logbook --trust -p ~/code/api       # mark that folder as trusted
claude-logbook --untrust -p ~/code/api     # Claude Code will ask again
```

Where each change goes:

| What | File |
| --- | --- |
| Rules and directories, no `-p` | `~/.claude/settings.json` (user scope) |
| Rules and directories with `-p` | `<project>/.claude/settings.local.json` (personal) |
| Same, with `--scope project` | `<project>/.claude/settings.json` (usually committed) |
| `--trust` / `--untrust` | `hasTrustDialogAccepted` in `~/.claude.json` |

`-p` takes a directory, or any piece of a project path Claude Code has seen as
long as it matches only one. Rules use Claude Code's syntax: `Tool` or
`Tool(specifier)`. A rule lives in one list only, so `--deny X` takes `X` out of
`allow` and `ask`. Every other key in those files is kept as it was, the file is
replaced atomically with its permissions intact, and `--dry-run` shows the
change without making it. Sessions that are already open may need a restart to
notice.

`~/.claude.json` also holds your account and the state of every running Claude
Code, which rewrite it often: claude-logbook reads it right before changing it,
and retries if it moves in between.

## Sharing a session

`--share` publishes **one** session on <https://claude-logbook.all.ar> and
prints its link:

```bash
claude-logbook -s 3 --share               # shows what goes up and asks
claude-logbook -s 3 --share --expire 7d   # gone in a week (default 30 days)
claude-logbook -s 3 --share               # again later: same link, new content
claude-logbook --shares                   # what you have shared, and until when
claude-logbook --unshare 5d10f1ee         # take it down (id, URL or session)
```

Each share has three forms:

| URL | Content |
| --- | --- |
| `/share/<id>` | The conversation as a page, the same view as `--html`. |
| `/share/<id>.txt` | Plain text transcript. |
| `/share/<id>.json` | The data, as `--json -s` prints it. |

Before uploading it shows the title, the project path, the size and a warning
for anything that looks like an API key, a token or a private key (where it
is, never the value). `--dry-run` stops there.

What to keep in mind:

- **Anyone with the link can read the whole conversation**, tool calls and
  paths included. It is not encrypted; the server can read it too.
- Only the machine that created a share can update or delete it: the server
  returns a secret that is kept in
  `$XDG_STATE_HOME/claude-logbook/shares.json` (`~/.local/state/...`), mode
  600. Lose that file and the share stays until it expires.
- Memories are never shared.

The server lives in [`server/`](server/README.md): Go, standard library only,
a `FROM scratch` Docker image. You can run your own and point
`CLAUDE_LOGBOOK_SERVER` at it.

## The HTML page

`claude-logbook --html` produces one file with the data embedded inside it. No
server, no network, no build step — copy it to another machine and it still
works.

- Search by title, path, branch or UUID, and optionally inside the transcripts,
  with the matching snippet shown under the row.
- Filter by project, sort by any column, hide empty sessions.
- Click a row to read the conversation in a side panel, with code fences,
  headings and one line per tool call.
- Copy the `cd … && claude --resume …` command for any session.
- Light and dark themes, with a toggle that remembers your choice.
- Each session gets its own URL fragment, so `sessions.html#5d10f1ee-…` opens
  that conversation directly.
- Keyboard: `/` or `Ctrl`+`K` focuses the search box, `Esc` clears it or closes
  the reader.

A page with a single session (`-s 3 --html`, or any shared link) skips the
list and is just that conversation: title, details and the transcript. A
single session is exported without memories.

Dates are relative to **when the data was read**, not to your clock, so "today"
keeps meaning what it meant when you generated the page.

## How it works

Claude Code writes one JSON Lines file per conversation:

```
~/.claude/projects/<url-encoded-project-path>/<uuid>.jsonl
```

(`CLAUDE_CONFIG_DIR` is honoured if you moved that directory.)

Every line is an event. `claude-logbook` walks them and keeps the conversation
itself — your messages, Claude's replies, and a one-line summary per tool call
such as `Bash: git status`. It deliberately **drops tool results**, which are
about 95% of the bytes on disk and almost none of the meaning.

A few details worth knowing:

- **Titles.** The one you set with `/rename` wins (`custom-title` events);
  otherwise the one Claude generates during the session (`ai-title`), the most
  recent of each. Without either, the first thing you typed is used instead —
  which is visible, because it starts in lowercase or reads like a loose
  question.
- **Compaction.** When the context runs out (or on `/compact`) Claude Code
  replaces the earlier conversation with a summary. That summary is shown as a
  "context compacted here" mark, not as a message of yours, and is not counted.
- **Branches.** `/branch` (and `/fork`) start a new session that copies the
  history of the original. claude-logbook reads the copy as inherited: it is
  shown collapsed under "Inherited history", and only what came after counts
  towards the messages, the duration and the start date. In the table the
  session carries a `branch` chip.
- **Directory changes.** When the session moves to another directory (a `cd`
  that sticks, `/cd`, a worktree) the transcript shows `→ /new/path` there, and
  `-p` also finds the session by any directory it worked in.
- **Duration** is active time: the gaps between messages, leaving out pauses
  longer than 30 minutes. A session resumed over several days does not count
  the days in between.
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
  `$XDG_CACHE_HOME/claude-logbook/cache.json`, keyed by size and mtime. It is
  only an optimisation: if it is missing, stale or corrupt, everything is
  re-parsed. `--no-cache` skips it entirely.

### JSON schema

`--json` prints an object with two arrays: `s` holds the sessions, most
recently active first, and `m` the memories, most recently modified first.

```json
{"s": [ … ], "m": [ … ]}
```

Keys are one letter because the same records are embedded in the HTML, where
the cost is paid once per record.

Each session in `s`:

| Key | Meaning |
| --- | --- |
| `id` | Session UUID (the file name). |
| `p` | Project path (`cwd`). |
| `b` | Git branch. |
| `t` | Title. |
| `ai` | `true` if the title was set with `/rename` or generated by Claude. |
| `n` | `true` if it looks like a non-interactive `claude -p`. |
| `e` | `true` if the session has no messages. |
| `i` | `true` if `p` was inferred from a sibling session. |
| `f` / `l` | First and last event timestamps (ISO 8601). |
| `d` | Active minutes (pauses over 30 minutes left out). In a branch, only its own part. |
| `u` / `a` | Message counts, yours / Claude's. In a branch, only its own part. |
| `k` | File size in KB. |
| `v` | Claude Code version. |
| `c` | Transcript: `[{"r": "u"｜"a"｜"t"｜"c"｜"d", "x": text}]`; `t` is a tool call, `c` a compaction summary, `d` a change of working directory. |
| `h` | How many blocks at the start of `c` were inherited from the session this one branched from (0 if not a branch). |
| `o` / `ot` | Id and title of that session (`null` if not a branch; `ot` also if it is no longer on disk). |

Each memory in `m`:

| Key | Meaning |
| --- | --- |
| `name` | Name from the frontmatter (or the filename, if missing). |
| `file` | File name, with extension. |
| `p` | Project path. |
| `desc` | Description from the frontmatter. |
| `ty` | Kind: `project`, `user`, `feedback` or `reference`. |
| `src` | UUID of the session that wrote it, when declared. |
| `body` | Markdown body, without the frontmatter. |
| `ln` | `[[...]]` links found in the body. |
| `k` | Size in KB. |
| `l` | Last modified (ISO 8601). |
| `ix` | `true` if listed in `MEMORY.md`. |
| `hix` | `true` if the project has a `MEMORY.md`. |

## Development

```bash
git clone https://github.com/ElvisClaros/claude-logbook && cd claude-logbook
python3 -m unittest discover -s tests -t .
```

The tests build fake `.jsonl` trees in a temporary directory and never touch
`~/.claude`. There is nothing to install: no test runner, no dependencies.

| Module | Responsibility |
| --- | --- |
| `claude_logbook/sessions.py` | Parsing the `.jsonl` files, the cache, filters. |
| `claude_logbook/memory.py` | Reading the `memory/*.md` files and auditing them. |
| `claude_logbook/config.py` | Permission rules, extra directories and folder trust. |
| `claude_logbook/terminal.py` | ANSI colours, the table, printing a conversation. |
| `claude_logbook/webpage.py` | Embedding the data into the template. |
| `claude_logbook/share.py` | Talking to the share server and the local registry of shares. |
| `claude_logbook/cli.py` | Argument parsing and the commands. |
| `server/` | The share server (Go): `cd server && go generate && go test ./...`. |
| `claude_logbook/template.html` | The page: markup, styles and the browser-side code. |

## License

[Apache-2.0](LICENSE).
