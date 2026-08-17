"""Parseo de los .jsonl que Claude Code deja en ~/.claude/projects/.

Cada conversación es un archivo JSON Lines: una línea por evento. De ahí sale un
registro por sesión con claves de una letra, porque ese mismo registro viaja
embebido dentro del HTML y los nombres largos se pagan una vez por sesión.

Esquema del registro que devuelve `read_session`:

    id   uuid de la sesión (el nombre del archivo)
    p    cwd del proyecto
    b    rama de git
    t    título
    ai   True si el título lo generó Claude, False si es el primer mensaje
    n    True si parece un `claude -p` no interactivo
    e    True si la sesión no tiene ningún mensaje
    i    True si `p` se dedujo de otra sesión del mismo proyecto
    f/l  timestamp del primer y del último evento (ISO 8601)
    d    duración en minutos
    u/a  cantidad de mensajes tuyos / de Claude
    k    tamaño del .jsonl en KB
    v    versión de Claude Code
    c    transcripción: [{"r": "u" | "a" | "t", "x": texto}]

`project_dir` y `mtime` son internos y no salen del módulo: `public_records()`
los saca antes de que el registro se serialice.
"""

import glob
import json
import os
import re
from datetime import datetime, timezone

# Sube si cambia el esquema del registro: invalida los cachés viejos en vez de
# leer registros con la forma anterior.
CACHE_VERSION = 2

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

INTERNAL_KEYS = ("project_dir", "mtime")


class SessionError(Exception):
    """Error de uso que la CLI convierte en un mensaje y un código de salida."""


# ──────────────────────────────── ubicaciones ────────────────────────────────

def default_root():
    """~/.claude/projects, o el equivalente si CLAUDE_CONFIG_DIR está seteada."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")


def default_cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "claude-logbook", "cache.json")


def session_path(s, root=None):
    """Ruta del .jsonl. El nombre del archivo es el UUID y el del directorio
    padre es lo que guardamos en project_dir, así que es reconstruible."""
    return os.path.join(root or default_root(),
                        s["project_dir"], s["id"] + ".jsonl")


# ─────────────────────────── parseo de los .jsonl ───────────────────────────

TAG_RE = re.compile(r"<[^>]+>")
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)

# Un mensaje que empieza con alguno de estos no es texto del usuario: es un
# bloque que genera la propia CLI al ejecutar un comando local.
SKIP_PREFIXES = (
    "<local-command-caveat", "<command-name", "<command-message",
    "<command-args", "<local-command-stdout", "<system-reminder",
)

TITLE_MAX = 160
TOOL_ARG_MAX = 140

# Umbral del heurístico de `claude -p`: un único mensaje más largo que esto, sin
# ninguna ida y vuelta, es un pipe por stdin y no una conversación.
NONINTERACTIVE_CHARS = 1500

# Para cada herramienta, el parámetro que mejor resume qué hizo.
TOOL_KEY = {
    "Bash": "command", "Read": "file_path", "Edit": "file_path",
    "Write": "file_path", "NotebookEdit": "notebook_path", "Glob": "pattern",
    "Grep": "pattern", "WebFetch": "url", "WebSearch": "query",
    "Task": "description", "Agent": "description", "Skill": "skill",
}


def clean_text(s):
    """Devuelve texto de usuario legible, o None si es ruido del harness."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s or s.startswith(SKIP_PREFIXES):
        return None
    s = REMINDER_RE.sub(" ", s)
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) >= 3 else None


def tool_summary(block):
    """Una línea del estilo 'Bash: git status' para una llamada a herramienta."""
    name = block.get("name") or "tool"
    args = block.get("input") or {}
    if not isinstance(args, dict):
        return name
    val = args.get(TOOL_KEY.get(name, ""))
    if val is None:
        val = next((v for v in args.values() if isinstance(v, str)), None)
    if not isinstance(val, str):
        return name
    val = re.sub(r"\s+", " ", val).strip()
    if len(val) > TOOL_ARG_MAX:
        val = val[:TOOL_ARG_MAX] + "…"
    return f"{name}: {val}" if val else name


def blocks_of(message):
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def parse_ts(ts):
    """ISO 8601 → datetime con zona, o None si no se puede leer."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def read_session(path):
    """Parsea un .jsonl entero y devuelve el registro de esa sesión."""
    session_id = os.path.basename(path)[:-6]  # sin .jsonl
    first_ts = last_ts = cwd = git_branch = version = None
    ai_title = fallback_title = None
    user_msgs = assistant_msgs = 0
    convo = []

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # línea truncada por una sesión que sigue escribiendo
            if not isinstance(obj, dict):
                continue

            kind = obj.get("type")

            if kind == "ai-title":
                if obj.get("aiTitle"):
                    ai_title = obj["aiTitle"]  # nos quedamos con el más reciente
                continue

            ts = obj.get("timestamp")
            if ts:
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
            if cwd is None and obj.get("cwd"):
                cwd = obj["cwd"]
            if git_branch is None and obj.get("gitBranch"):
                git_branch = obj["gitBranch"]
            if obj.get("version"):
                version = obj["version"]

            if kind not in ("user", "assistant") or obj.get("isSidechain"):
                continue

            message = obj.get("message")
            if not isinstance(message, dict):
                continue

            if kind == "user":
                if obj.get("isMeta"):
                    continue
                for b in blocks_of(message):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        text = clean_text(b.get("text"))
                        if text:
                            user_msgs += 1
                            if fallback_title is None:
                                fallback_title = text[:TITLE_MAX]
                            convo.append({"r": "u", "x": text})
                    elif b.get("type") == "image":
                        convo.append({"r": "u", "x": "[imagen adjunta]"})
            else:
                counted = False
                for b in blocks_of(message):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        text = (b.get("text") or "").strip()
                        if text:
                            convo.append({"r": "a", "x": text})
                            counted = True
                    elif b.get("type") == "tool_use":
                        convo.append({"r": "t", "x": tool_summary(b)})
                if counted:
                    assistant_msgs += 1

    st = os.stat(path)
    ft, lt = parse_ts(first_ts), parse_ts(last_ts)

    # Un único mensaje enorme y ninguna ida y vuelta es la firma de un
    # `claude -p` con algo piped por stdin (p. ej. un git diff para redactar el
    # mensaje de commit), no de una conversación.
    noninteractive = (
        user_msgs == 1 and not ai_title and bool(convo)
        and len(convo[0]["x"]) > NONINTERACTIVE_CHARS
    )

    return {
        "id": session_id,
        "project_dir": os.path.basename(os.path.dirname(path)),
        "p": cwd,
        "b": git_branch,
        "t": ai_title or fallback_title,
        "ai": bool(ai_title),
        "n": noninteractive,
        "e": not convo,
        "f": first_ts,
        "l": last_ts,
        "d": round((lt - ft).total_seconds() / 60) if ft and lt else None,
        "u": user_msgs,
        "a": assistant_msgs,
        "k": round(st.st_size / 1024, 1),
        "v": version,
        "c": convo,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


# ──────────────────────────────── caché ────────────────────────────────

def _load_cache(path):
    """Entradas del caché, o {} si no existe, está roto o quedó viejo."""
    try:
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(blob, dict) or blob.get("v") != CACHE_VERSION:
        return {}
    entries = blob.get("entries")
    return entries if isinstance(entries, dict) else {}


def _save_cache(path, entries):
    """Escribe el caché de forma atómica. Si falla, no pasa nada."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # El pid en el temporal evita que dos corridas simultáneas se pisen.
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": CACHE_VERSION, "entries": entries}, f,
                      ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass  # el caché es una optimización, no una condición de uso


def drop_from_cache(paths, cache_path=None):
    """Saca del caché las sesiones borradas para que no reaparezcan."""
    cache_path = cache_path or default_cache_path()
    entries = _load_cache(cache_path)
    if not entries:
        return
    if any(entries.pop(p, None) is not None for p in list(paths)):
        _save_cache(cache_path, entries)


# ──────────────────────────────── carga ────────────────────────────────

def _fill_gaps(sessions):
    """Completa lo que falta después de parsear todos los archivos.

    Algunas sesiones (un /resume cancelado) nunca registran cwd. El nombre del
    directorio no se puede invertir de forma fiable porque "/" y "." se
    codifican los dos como "-", así que tomamos la ruta prestada de otra sesión
    del mismo proyecto y lo dejamos marcado en `i`.
    """
    known = {}
    for s in sessions:
        if s["p"]:
            known.setdefault(s["project_dir"], s["p"])

    for s in sessions:
        s["i"] = not s["p"]
        if not s["p"]:
            s["p"] = known.get(s["project_dir"], s["project_dir"])
        if not s["l"]:
            s["l"] = s["mtime"]
        if not s["f"]:
            s["f"] = s["mtime"]


def load_sessions(root=None, cache_path=None, use_cache=True):
    """Parsea todas las sesiones, reusando del caché las que no cambiaron."""
    root = root or default_root()
    cache_path = cache_path or default_cache_path()
    paths = sorted(glob.glob(os.path.join(root, "*", "*.jsonl")))

    cache = _load_cache(cache_path) if use_cache else {}

    sessions, fresh, reparsed = [], {}, False
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        stamp = f"{st.st_mtime_ns}:{st.st_size}"
        hit = cache.get(path)
        if (isinstance(hit, dict) and hit.get("stamp") == stamp
                and isinstance(hit.get("rec"), dict)):
            rec = hit["rec"]
        else:
            try:
                rec = read_session(path)
            except OSError:
                continue
            reparsed = True
        fresh[path] = {"stamp": stamp, "rec": rec}
        sessions.append(rec)

    # Antes de `_fill_gaps`, a propósito: al caché va el registro tal como salió
    # del archivo, sin los campos deducidos a partir de las otras sesiones.
    if use_cache and (reparsed or len(fresh) != len(cache)):
        _save_cache(cache_path, fresh)

    _fill_gaps(sessions)
    sessions.sort(key=lambda s: parse_ts(s["l"]) or EPOCH, reverse=True)
    return sessions


def latest_activity(sessions):
    """El instante más reciente de los datos: el "ahora" contra el que se
    calculan las fechas relativas, para que no dependan del reloj de quien mira."""
    stamps = [parse_ts(s["l"]) for s in sessions]
    return max([t for t in stamps if t], default=EPOCH)


def public_records(sessions):
    """Copias sin las claves internas, listas para serializar."""
    return [{k: v for k, v in s.items() if k not in INTERNAL_KEYS}
            for s in sessions]


# ──────────────────────────────── filtros ────────────────────────────────

def apply_filters(sessions, project=None, grep=None, query=None,
                  hide_empty=False):
    out = sessions

    if project:
        needle = os.path.expanduser(project).rstrip("/").lower()
        out = [s for s in out if needle in s["p"].lower()]

    if grep:
        needle = grep.lower()
        out = [s for s in out
               if any(needle in m["x"].lower() for m in s["c"])]

    if query:
        needle = query.lower()
        out = [s for s in out
               if needle in (s["t"] or "").lower()
               or needle in s["p"].lower()
               or needle in (s["b"] or "").lower()
               or s["id"].startswith(needle)]

    if hide_empty:
        out = [s for s in out if not s["e"]]

    return out


def pick(sessions, ref):
    """Resuelve un índice de la tabla (1-based) o un prefijo de UUID."""
    if ref.isdigit():
        i = int(ref)
        if 1 <= i <= len(sessions):
            return sessions[i - 1]
        raise SessionError(
            f"el índice {i} está fuera de rango (hay {len(sessions)})")

    hits = [s for s in sessions if s["id"].startswith(ref.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SessionError(f"ninguna sesión empieza con '{ref}'")
    raise SessionError(f"'{ref}' es ambiguo, coincide con {len(hits)} sesiones")
