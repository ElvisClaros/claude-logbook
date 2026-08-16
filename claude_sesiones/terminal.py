"""Salida para la terminal: colores, tabla y lectura de una conversación."""

import os
import re
import shutil
import subprocess
import sys
import textwrap

from .sessions import parse_ts

MES = ["ene", "feb", "mar", "abr", "may", "jun",
       "jul", "ago", "sep", "oct", "nov", "dic"]

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Anchos mínimos de terminal para mostrar cada columna opcional.
MIN_COLS_PATH = 92
MIN_COLS_DUR = 74


class Style:
    """Códigos ANSI, o cadenas vacías si la salida no es una terminal."""

    CODES = {
        "reset": "0", "bold": "1", "dim": "2", "italic": "3",
        "amber": "38;5;179", "copper": "38;5;173", "grey": "38;5;245",
        "faint": "38;5;240", "ink": "38;5;252", "blue": "38;5;110",
        # barra de antigüedad, del ámbar vivo al gris
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
        """Color solo si hay terminal, no lo desactivaron y no hay NO_COLOR."""
        return cls(bool(getattr(stream, "isatty", lambda: False)())
                   and not no_color
                   and not os.environ.get("NO_COLOR"))


# ──────────────────────────────── formato ────────────────────────────────

def visible_len(s):
    return len(ANSI_RE.sub("", s))


def clip(s, width):
    """Recorta a `width` columnas, con … si no entra."""
    s = s.replace("\n", " ")
    if len(s) <= width:
        return s
    return s[: max(0, width - 1)] + "…"


def fmt_date(iso):
    d = parse_ts(iso).astimezone()
    return f"{d.day:02d} {MES[d.month - 1]}"


def fmt_time(iso):
    return parse_ts(iso).astimezone().strftime("%H:%M")


def fmt_rel(iso, now):
    n = (now - parse_ts(iso)).total_seconds() / 86400
    if n < 1:
        return "hoy"
    if n < 2:
        return "ayer"
    if n < 7:
        return f"hace {int(n)}d"
    if n < 30:
        return f"hace {int(n // 7)}sem"
    return f"hace {int(n // 30)}mes"


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
    """Barra de antigüedad a la izquierda de cada fila."""
    if not st.on:
        return "|"
    n = (now - parse_ts(iso)).total_seconds() / 86400
    color = st.age0 if n < 2 else st.age1 if n < 7 else st.age2 if n < 14 else st.age3
    return f"{color}▌{st.reset}"


# ──────────────────────────────── tabla ────────────────────────────────

def print_table(sessions, st, now, out, width=None):
    width = width or shutil.get_terminal_size((100, 24)).columns
    show_path = width >= MIN_COLS_PATH
    show_dur = width >= MIN_COLS_DUR

    # columnas fijas: idx(3) barra(1) fecha(6) rel(9) msgs(4) dur(6) id(8) + gaps
    fixed = 3 + 1 + 6 + 9 + 4 + (6 if show_dur else 0) + 8
    gaps = 7 if show_dur else 6
    flex = max(24, width - fixed - gaps)
    w_title = int(flex * 0.58) if show_path else flex
    w_path = flex - w_title - 1 if show_path else 0

    head = [
        f"{'#':>3}", " ",
        f"{st.faint}{'SESIÓN':<{w_title}}{st.reset}",
    ]
    if show_path:
        head.append(f"{st.faint}{'RUTA':<{w_path}}{st.reset}")
    head.append(f"{st.faint}{'FECHA':<6} {'CUÁNDO':<9}{st.reset}")
    head.append(f"{st.faint}{'MSG':>4}{st.reset}")
    if show_dur:
        head.append(f"{st.faint}{'DUR':>6}{st.reset}")
    head.append(f"{st.faint}{'ID':<8}{st.reset}")
    print(" ".join(head), file=out)

    for i, s in enumerate(sessions, 1):
        title = s["t"] or "sesión abierta sin mensajes"
        tcolor = st.dim + st.italic if s["e"] else (st.ink if s["ai"] else "")
        tags = ""
        if s["e"]:
            tags = f" {st.faint}[vacía]{st.reset}"
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


# ──────────────────────────── una conversación ────────────────────────────

def strip_md(text):
    """Markdown mínimo para la terminal: saca ** y marcadores de título."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    return re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)


def render_block(text, st, width, code_color):
    """Formatea un mensaje respetando las cercas de código."""
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

    print(f"{st.amber}{st.bold}{s['t'] or 'Sesión sin título'}{st.reset}", file=out)
    meta = (f"{s['p']}  ·  {fmt_date(s['l'])} {fmt_time(s['l'])}  ·  "
            f"{s['u']} tuyos / {s['a']} de Claude  ·  {fmt_dur(s['d'])}")
    print(f"{st.faint}{meta}{st.reset}", file=out)
    print(f"{st.faint}{resume_cmd(s)}{st.reset}", file=out)
    print(f"{st.faint}{'─' * min(width, 80)}{st.reset}\n", file=out)

    if not s["c"]:
        print(f"{st.dim}Esta sesión no tiene mensajes.{st.reset}", file=out)
        return

    first = True
    for m in s["c"]:
        if m["r"] == "t":
            if show_tools:
                print(f"  {st.faint}⚒ {clip(m['x'], body - 4)}{st.reset}", file=out)
                first = False
            continue

        # La separación va antes de cada turno: así una tanda de herramientas
        # queda pegada al mensaje que la lanzó y separada del siguiente.
        if not first:
            print(file=out)
        first = False

        who = "vos" if m["r"] == "u" else "claude"
        color = st.amber if m["r"] == "u" else st.blue
        print(f"{color}{who}{st.reset}", file=out)
        for line in render_block(m["x"], st, body, st.grey):
            print(line, file=out)


def resume_cmd(s):
    """El --resume solo encuentra la sesión desde su directorio original."""
    return f"cd {s['p']} && claude --resume {s['id']}"


def pager(text):
    """Manda el texto a $PAGER si hay terminal; si no, a stdout."""
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
