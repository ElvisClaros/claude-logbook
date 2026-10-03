"""Terminal output: colors, table and reading a conversation."""

import os
import re
import shutil
import subprocess
import sys
import textwrap

from .config import is_empty
from .sessions import parse_ts

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Minimum terminal widths to show each optional column.
MIN_COLS_PATH = 92
MIN_COLS_DUR = 74


class Style:
    """ANSI codes, or empty strings if the output is not a terminal."""

    CODES = {
        "reset": "0", "bold": "1", "dim": "2", "italic": "3",
        "amber": "38;5;179", "copper": "38;5;173", "grey": "38;5;245",
        "faint": "38;5;240", "ink": "38;5;252", "blue": "38;5;110",
        # age bar, from bright amber to grey
        "age0": "38;5;214", "age1": "38;5;179",
        "age2": "38;5;137", "age3": "38;5;239",
    }

    def __init__(self, enabled):
        self.on = enabled

    def __getattr__(self, name):
        try:
            code = self.CODES[name]
        except KeyError:
            raise AttributeError(name) from None
        return f"\x1b[{code}m" if self.on else ""

    @classmethod
    def from_stream(cls, stream, no_color=False):
        """Color only with a terminal, when not disabled and without NO_COLOR."""
        return cls(bool(getattr(stream, "isatty", lambda: False)())
                   and not no_color
                   and not os.environ.get("NO_COLOR"))


# ──────────────────────────────── formatting ─────────────────────────────

def visible_len(s):
    return len(ANSI_RE.sub("", s))


def clip(s, width):
    """Truncates to `width` columns, with … if it does not fit."""
    s = s.replace("\n", " ")
    if len(s) <= width:
        return s
    return s[: max(0, width - 1)] + "…"


def fmt_date(iso):
    d = parse_ts(iso).astimezone()
    return f"{d.day:02d} {MONTHS[d.month - 1]}"


def fmt_time(iso):
    return parse_ts(iso).astimezone().strftime("%H:%M")


def fmt_rel(iso, now):
    n = (now - parse_ts(iso)).total_seconds() / 86400
    if n < 1:
        return "today"
    if n < 2:
        return "yesterday"
    if n < 7:
        return f"{int(n)}d ago"
    if n < 30:
        return f"{int(n // 7)}w ago"
    return f"{int(n // 30)}mo ago"


def plural(n, singular, plural_):
    return f"{n} {singular if n == 1 else plural_}"


def fmt_dur(m):
    if m is None:
        return "—"
    if m < 1:
        return "<1m"
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h{r:02d}" if r else f"{h}h"


def fmt_size(kb):
    return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.1f} KB"


def stripe(iso, now, st):
    """Age bar to the left of each row."""
    if not st.on:
        return "|"
    n = (now - parse_ts(iso)).total_seconds() / 86400
    color = st.age0 if n < 2 else st.age1 if n < 7 else st.age2 if n < 14 else st.age3
    return f"{color}▌{st.reset}"


# ──────────────────────────────── table ────────────────────────────────

def print_table(sessions, st, now, out, width=None):
    width = width or shutil.get_terminal_size((100, 24)).columns
    show_path = width >= MIN_COLS_PATH
    show_dur = width >= MIN_COLS_DUR

    # fixed columns: idx(3) bar(1) date(6) rel(9) msgs(4) dur(6) id(8) + gaps
    fixed = 3 + 1 + 6 + 9 + 4 + (6 if show_dur else 0) + 8
    gaps = 7 if show_dur else 6
    flex = max(24, width - fixed - gaps)
    w_title = int(flex * 0.58) if show_path else flex
    w_path = flex - w_title - 1 if show_path else 0

    head = [
        f"{'#':>3}", " ",
        f"{st.faint}{'SESSION':<{w_title}}{st.reset}",
    ]
    if show_path:
        head.append(f"{st.faint}{'PATH':<{w_path}}{st.reset}")
    head.append(f"{st.faint}{'DATE':<6} {'WHEN':<9}{st.reset}")
    head.append(f"{st.faint}{'MSG':>4}{st.reset}")
    if show_dur:
        head.append(f"{st.faint}{'DUR':>6}{st.reset}")
    head.append(f"{st.faint}{'ID':<8}{st.reset}")
    print(" ".join(head), file=out)

    for i, s in enumerate(sessions, 1):
        title = s["t"] or "session opened with no messages"
        tcolor = st.dim + st.italic if s["e"] else (st.ink if s["ai"] else "")
        tags = ""
        if s["e"]:
            tags = f" {st.faint}[empty]{st.reset}"
        elif s["n"]:
            tags = f" {st.faint}[auto]{st.reset}"

        avail = w_title - visible_len(tags)
        cells = [
            f"{st.faint}{i:>3}{st.reset}",
            stripe(s["l"], now, st),
            f"{tcolor}{clip(title, avail):<{avail}}{st.reset}{tags}",
        ]
        if show_path:
            cells.append(f"{st.grey}{clip(s['p'], w_path):<{w_path}}{st.reset}")
        cells.append(
            f"{fmt_date(s['l']):<6} {st.faint}{fmt_rel(s['l'], now):<9}{st.reset}"
        )
        cells.append(f"{s['u'] or '—':>4}")
        if show_dur:
            cells.append(f"{st.grey}{fmt_dur(s['d']):>6}{st.reset}")
        cells.append(f"{st.faint}{s['id'][:8]}{st.reset}")
        print(" ".join(cells), file=out)


# ──────────────────────────── one conversation ────────────────────────────

def strip_md(text):
    """Minimal markdown for the terminal: removes ** and heading markers."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    return re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)


def render_block(text, st, width, code_color):
    """Formats a message honouring code fences."""
    lines = []
    in_code = False
    for raw in text.split("\n"):
        if raw.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            lines.append(f"  {code_color}{raw}{st.reset}")
        elif not raw.strip():
            lines.append("")
        else:
            wrapped = textwrap.wrap(
                strip_md(raw), width=width,
                break_long_words=False, break_on_hyphens=False,
            )
            lines.extend("  " + w for w in (wrapped or [""]))
    return lines


def print_chat(s, st, out, show_tools=True, width=None):
    width = min(width or shutil.get_terminal_size((100, 24)).columns, 100)
    body = width - 2

    print(f"{st.amber}{st.bold}{s['t'] or 'Untitled session'}{st.reset}", file=out)
    meta = (f"{s['p']}  ·  {fmt_date(s['l'])} {fmt_time(s['l'])}  ·  "
            f"{s['u']} yours / {s['a']} from Claude  ·  {fmt_dur(s['d'])}")
    print(f"{st.faint}{meta}{st.reset}", file=out)
    print(f"{st.faint}{resume_cmd(s)}{st.reset}", file=out)
    print(f"{st.faint}{'─' * min(width, 80)}{st.reset}\n", file=out)

    if not s["c"]:
        print(f"{st.dim}This session has no messages.{st.reset}", file=out)
        return

    first = True
    for m in s["c"]:
        if m["r"] == "c":
            # The summary is long and Claude's, not part of the dialogue:
            # only the mark of where the earlier context was folded.
            if not first:
                print(file=out)
            first = False
            label = " context compacted here "
            side = max(3, (min(width, 80) - len(label)) // 2)
            print(f"{st.faint}{'─' * side}{label}{'─' * side}{st.reset}", file=out)
            continue
        if m["r"] == "t":
            if show_tools:
                print(f"  {st.faint}⚒ {clip(m['x'], body - 4)}{st.reset}", file=out)
                first = False
            continue

        # The separator goes before each turn: that way a batch of tool calls
        # stays attached to the message that launched it and apart from the next one.
        if not first:
            print(file=out)
        first = False

        who = "you" if m["r"] == "u" else "claude"
        color = st.amber if m["r"] == "u" else st.blue
        print(f"{color}{who}{st.reset}", file=out)
        for line in render_block(m["x"], st, body, st.grey):
            print(line, file=out)


def resume_cmd(s):
    """--resume only finds the session from its original directory."""
    return f"cd {s['p']} && claude --resume {s['id']}"


def pager(text):
    """Sends the text to $PAGER with a terminal; otherwise to stdout."""
    if not sys.stdout.isatty():
        sys.stdout.write(text)
        return
    cmd = os.environ.get("PAGER", "less")
    args = [cmd, "-R", "-F", "-X"] if os.path.basename(cmd) == "less" else [cmd]
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE)
        p.communicate(text.encode())
    except (OSError, BrokenPipeError):
        sys.stdout.write(text)


# ──────────────────────────────── memories ────────────────────────────────

# Minimum widths for the optional columns of the memories table.
MIN_COLS_MEM_PROJECT = 78
MIN_COLS_MEM_DESC = 104

TYPE_COLOR = {"project": "amber", "user": "blue",
              "feedback": "copper", "reference": "grey"}


def print_memories(memories, st, now, out, width=None):
    width = width or shutil.get_terminal_size((100, 24)).columns
    show_project = width >= MIN_COLS_MEM_PROJECT
    show_desc = width >= MIN_COLS_MEM_DESC

    # fixed columns: idx(3) type(9) date(6) when(9) + separators
    fixed = 3 + 9 + 6 + 9
    gaps = 4 + (1 if show_project else 0) + (1 if show_desc else 0)
    flex = max(18, width - fixed - gaps)
    if show_desc:
        w_name, w_project = int(flex * 0.34), int(flex * 0.28)
    elif show_project:
        w_name, w_project = int(flex * 0.58), flex - int(flex * 0.58)
    else:
        w_name, w_project = flex, 0
    w_desc = flex - w_name - w_project if show_desc else 0

    head = [f"{'#':>3}", f"{st.faint}{'MEMORY':<{w_name}}{st.reset}",
            f"{st.faint}{'TYPE':<9}{st.reset}"]
    if show_project:
        head.append(f"{st.faint}{'PROJECT':<{w_project}}{st.reset}")
    if show_desc:
        head.append(f"{st.faint}{'DESCRIPTION':<{w_desc}}{st.reset}")
    head.append(f"{st.faint}{'DATE':<6} {'WHEN':<9}{st.reset}")
    print(" ".join(head), file=out)

    for i, m in enumerate(memories, 1):
        # The asterisk marks what is not in MEMORY.md: it exists but is not loaded.
        tag = "" if m["ix"] else f" {st.copper}*{st.reset}"
        avail = w_name - visible_len(tag)
        cells = [
            f"{st.faint}{i:>3}{st.reset}",
            f"{st.ink}{clip(m['name'], avail):<{avail}}{st.reset}{tag}",
            f"{getattr(st, TYPE_COLOR.get(m['ty'], 'grey'))}"
            f"{clip(m['ty'], 9):<9}{st.reset}",
        ]
        if show_project:
            cells.append(f"{st.grey}{clip(m['p'], w_project):<{w_project}}{st.reset}")
        if show_desc:
            cells.append(f"{st.grey}{clip(m['desc'], w_desc):<{w_desc}}{st.reset}")
        cells.append(f"{fmt_date(m['l']):<6} "
                     f"{st.faint}{fmt_rel(m['l'], now):<9}{st.reset}")
        print(" ".join(cells), file=out)


def print_memory(m, st, out, path=None, width=None):
    width = min(width or shutil.get_terminal_size((100, 24)).columns, 100)

    print(f"{st.amber}{st.bold}{m['name']}{st.reset}", file=out)
    if m["desc"]:
        for line in textwrap.wrap(m["desc"], width=width - 2):
            print(f"{st.grey}{line}{st.reset}", file=out)

    meta = (f"{m['ty']}  ·  {m['p']}  ·  "
            f"{fmt_date(m['l'])} {fmt_time(m['l'])}  ·  {fmt_size(m['k'])}")
    print(f"{st.faint}{meta}{st.reset}", file=out)
    if path:
        print(f"{st.faint}{path}{st.reset}", file=out)

    if not m["ix"]:
        warning = ("this project has no MEMORY.md" if not m["hix"]
                 else "not listed in MEMORY.md, so it is not loaded into context")
        print(f"{st.copper}* {warning}{st.reset}", file=out)

    print(f"{st.faint}{'─' * min(width, 80)}{st.reset}\n", file=out)

    for line in render_block(m["body"], st, width - 2, st.grey):
        print(line, file=out)

    if m["ln"]:
        print(f"\n{st.faint}links: {', '.join(m['ln'])}{st.reset}", file=out)
    if m["src"]:
        print(f"{st.faint}created by session {m['src'][:8]}  "
              f"(claude-logbook -s {m['src'][:8]}){st.reset}", file=out)


def print_audit(report, st, out):
    """Inconsistency report. Returns how many were listed."""
    blocks = (
        ("no_index", "Projects with memories but no MEMORY.md",
         "without an index none of their memories are loaded",
         lambda m: f"{clip(m['name'], 38):<38} {st.grey}{m['p']}{st.reset}"),
        ("unlisted", "Memories not listed in their MEMORY.md",
         "the index is what gets read at startup: if it is not there, it is not remembered",
         lambda m: f"{clip(m['name'], 38):<38} {st.grey}{m['p']}{st.reset}"),
        ("ghost_entries", "Index entries without a file",
         "they point to a memory that no longer exists",
         lambda t: f"{clip(t[1], 38):<38} {st.grey}{t[0]}{st.reset}"),
        ("broken_links", "[[...]] links without a target",
         "the format allows them: they mark something not written yet",
         lambda t: f"{clip(t[0]['name'], 38):<38} {st.grey}→ [[{t[1]}]]{st.reset}"),
        ("lost_source", "Memories whose source session no longer exists",
         "the memory outlived the conversation that created it",
         lambda m: f"{clip(m['name'], 38):<38} {st.grey}{m['src'][:8]}{st.reset}"),
    )

    total = 0
    for key, title_text, note, fmt in blocks:
        items = report.get(key) or []
        if not items:
            continue
        total += len(items)
        print(f"{st.copper}{title_text} ({len(items)}){st.reset}", file=out)
        print(f"{st.faint}  {note}{st.reset}", file=out)
        for item in items:
            print(f"  {fmt(item)}", file=out)
        print(file=out)

    return total


# ──────────────────────────────── permissions ────────────────────────────

RULE_COLOR = {"allow": "amber", "ask": "blue", "deny": "copper", "dirs": "grey",
              "mode": "grey"}


def _print_rules(r, st, out, indent):
    for key in ("allow", "ask", "deny", "dirs"):
        color = getattr(st, RULE_COLOR[key])
        for i, item in enumerate(r[key]):
            label = key if i == 0 else ""
            print(f"{indent}{st.faint}{label:<6}{st.reset} {color}{item}{st.reset}",
                  file=out)
    if r["mode"]:
        print(f"{indent}{st.faint}{'mode':<6}{st.reset} {r['mode']}", file=out)


def short_home(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def trust_label(p, st):
    if p["trusted"]:
        return f"{st.amber}trusted{st.reset}"
    if p["parent"]:
        return f"{st.faint}not trusted · parent {short_home(p['parent'])} is{st.reset}"
    return f"{st.copper}not trusted{st.reset}"


def print_permissions(view, st, out, show_all=False):
    """User scope, then each project with rules (or every one if show_all)."""
    user = view["user"]
    print(f"{st.bold}user{st.reset}  {st.faint}{short_home(user['path'])}{st.reset}",
          file=out)
    if is_empty(user["rules"]):
        print(f"  {st.faint}no rules{st.reset}", file=out)
    else:
        _print_rules(user["rules"], st, out, "  ")

    shown = 0
    for p in view["projects"]:
        with_rules = [s for s in p["scopes"] if not is_empty(s["rules"])]
        if not with_rules and not show_all:
            continue
        shown += 1
        gone = "" if p["exists"] else f"  {st.faint}(directory gone){st.reset}"
        print(f"\n{st.ink}{short_home(p['path'])}{st.reset}  {trust_label(p, st)}{gone}",
              file=out)
        for s in with_rules:
            name = os.path.relpath(s["path"], p["path"])
            print(f"  {st.grey}{s['scope']:<7}{st.reset} {st.faint}{name}{st.reset}",
                  file=out)
            _print_rules(s["rules"], st, out, "    ")
    return shown
