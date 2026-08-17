"""Memorias de proyecto: los .md que Claude Code deja en <proyecto>/memory/.

Cada proyecto puede acumular recuerdos en

    ~/.claude/projects/<proyecto>/memory/<nombre>.md

Un archivo por recuerdo, con frontmatter YAML (`name`, `description`,
`metadata.type`, `metadata.originSessionId`) y cuerpo markdown. Al lado vive
`MEMORY.md`, el índice: una línea por memoria, y es lo único que se carga en
contexto al arrancar una sesión. Una memoria que no figura ahí sigue en disco
pero deja de recordarse, así que la diferencia entre ambos vale la pena mirarla.

Esquema del registro que devuelve `read_memory`, con las mismas claves cortas
que `sessions` porque también viaja embebido en el HTML:

    name  nombre del frontmatter (o el del archivo si falta)
    file  nombre del archivo, con extensión
    p     cwd del proyecto
    desc  descripción del frontmatter
    ty    tipo declarado: project | user | feedback | reference
    src   uuid de la sesión que la creó, si lo declara
    body  cuerpo markdown, sin el frontmatter
    ln    enlaces [[...]] que aparecen en el cuerpo
    k     tamaño en KB
    l     mtime del archivo (ISO 8601)
    ix    True si figura en MEMORY.md
    hix   True si el proyecto tiene MEMORY.md

`project_dir` es interno y `public_records()` lo saca antes de serializar.
"""

import glob
import os
import re
from datetime import datetime, timezone

from .sessions import SessionError, default_root

INDEX_NAME = "MEMORY.md"

INTERNAL_KEYS = ("project_dir",)

TYPES = ("project", "user", "feedback", "reference")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
LINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
# En el índice cada línea es "- [Título](archivo.md) — pista".
INDEX_LINK_RE = re.compile(r"\(([^)\n]+)\.md\)")


def memory_dir(project_dir, root=None):
    return os.path.join(root or default_root(), project_dir, "memory")


def memory_path(m, root=None):
    return os.path.join(memory_dir(m["project_dir"], root), m["file"])


def index_path(project_dir, root=None):
    return os.path.join(memory_dir(project_dir, root), INDEX_NAME)


# ──────────────────────────────── parseo ────────────────────────────────

def _field(front, key):
    """Valor de una clave del frontmatter. Plano: alcanza para lo que escribe
    Claude Code, que anida `type` y `originSessionId` pero sin repetirlas."""
    hit = re.search(r"^\s*%s:\s*(.+?)\s*$" % re.escape(key), front, re.M)
    if not hit:
        return None
    value = hit.group(1).strip()
    # YAML de una línea: si viene entrecomillado, las comillas internas están
    # escapadas y hay que devolverlas como estaban.
    for quote in ('"', "'"):
        if len(value) >= 2 and value[0] == quote and value[-1] == quote:
            value = value[1:-1]
            if quote == '"':
                value = value.replace('\\"', '"').replace("\\\\", "\\")
            break
    return value or None


def read_memory(path, project_dir):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()

    match = FRONTMATTER_RE.match(raw)
    front, body = (match.group(1), raw[match.end():]) if match else ("", raw)
    stat = os.stat(path)
    filename = os.path.basename(path)

    return {
        "name": _field(front, "name") or filename[:-3],
        "file": filename,
        "project_dir": project_dir,
        "desc": _field(front, "description") or "",
        "ty": _field(front, "type") or "—",
        "src": _field(front, "originSessionId"),
        "body": body.strip(),
        "ln": sorted(set(LINK_RE.findall(body))),
        "k": round(stat.st_size / 1024, 1),
        "l": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def read_index(project_dir, root=None):
    """Nombres (sin .md) que el MEMORY.md del proyecto enlaza."""
    try:
        with open(index_path(project_dir, root), "r",
                  encoding="utf-8", errors="ignore") as f:
            return set(INDEX_LINK_RE.findall(f.read()))
    except OSError:
        return set()


# ──────────────────────────────── carga ────────────────────────────────

def load_memories(sessions, root=None):
    """Lee las memorias de todos los proyectos.

    La ruta real del proyecto sale de las sesiones: el nombre del directorio
    codifica "/" y "." los dos como "-" y no se puede invertir.
    """
    root = root or default_root()
    cwd_by_dir = {}
    for s in sessions:
        cwd_by_dir.setdefault(s.get("project_dir"), s.get("p"))

    memories = []
    for d in sorted(glob.glob(os.path.join(root, "*", "memory"))):
        project_dir = os.path.basename(os.path.dirname(d))
        files = sorted(f for f in glob.glob(os.path.join(d, "*.md"))
                       if os.path.basename(f) != INDEX_NAME)
        if not files:
            continue  # un memory/ vacío no es un proyecto con memoria

        has_index = os.path.exists(os.path.join(d, INDEX_NAME))
        listed = read_index(project_dir, root) if has_index else set()

        for path in files:
            try:
                m = read_memory(path, project_dir)
            except OSError:
                continue
            m["p"] = cwd_by_dir.get(project_dir) or project_dir
            m["hix"] = has_index
            m["ix"] = m["file"][:-3] in listed
            memories.append(m)

    memories.sort(key=lambda m: m["l"], reverse=True)
    return memories


def public_records(memories):
    """Copia sin las claves internas, lista para serializar."""
    out = []
    for m in memories:
        clean = dict(m)
        for key in INTERNAL_KEYS:
            clean.pop(key, None)
        out.append(clean)
    return out


# ──────────────────────────────── filtros ────────────────────────────────

def apply_filters(memories, project=None, query=None, kind=None):
    out = memories

    if project:
        needle = os.path.expanduser(project).rstrip("/").lower()
        out = [m for m in out if needle in m["p"].lower()]

    if kind:
        out = [m for m in out if m["ty"].lower() == kind.lower()]

    if query:
        needle = query.lower()
        out = [m for m in out
               if needle in m["name"].lower()
               or needle in m["desc"].lower()
               or needle in m["p"].lower()
               or needle in m["body"].lower()]

    return out


def pick(memories, ref):
    """Resuelve un índice de la tabla (1-based) o un prefijo del nombre."""
    if ref.isdigit():
        i = int(ref)
        if 1 <= i <= len(memories):
            return memories[i - 1]
        raise SessionError(
            f"el índice {i} está fuera de rango (hay {len(memories)} memorias)")

    needle = ref.lower()
    hits = [m for m in memories if m["name"].lower().startswith(needle)]
    if not hits:
        hits = [m for m in memories if needle in m["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SessionError(f"ninguna memoria coincide con '{ref}'")
    nombres = ", ".join(m["name"] for m in hits[:4])
    raise SessionError(
        f"'{ref}' es ambiguo, coincide con {len(hits)}: {nombres}"
        + (", …" if len(hits) > 4 else ""))


# ──────────────────────────────── auditoría ────────────────────────────────

def audit(memories, sessions, root=None):
    """Inconsistencias entre archivos, índices, enlaces y sesiones de origen."""
    known = {m["name"] for m in memories} | {m["file"][:-3] for m in memories}
    session_ids = {s["id"] for s in sessions}

    report = {
        "sin_indice": [m for m in memories if not m["hix"]],
        "sin_listar": [m for m in memories if m["hix"] and not m["ix"]],
        "enlaces_rotos": [(m, link) for m in memories
                          for link in m["ln"] if link not in known],
        "origen_perdido": [m for m in memories
                           if m["src"] and m["src"] not in session_ids],
        "indice_fantasma": [],
    }

    for project_dir in sorted({m["project_dir"] for m in memories if m["hix"]}):
        real = {m["file"][:-3] for m in memories
                if m["project_dir"] == project_dir}
        for missing in sorted(read_index(project_dir, root) - real):
            report["indice_fantasma"].append((project_dir, missing))

    return report


def audit_total(report):
    return sum(len(v) for v in report.values())


# ──────────────────────────────── borrado ────────────────────────────────

def unindex(m, root=None):
    """Saca del MEMORY.md la línea que apunta a esta memoria.

    Devuelve True si el índice cambió. No es un error que no cambie: la memoria
    podía no estar listada.
    """
    path = index_path(m["project_dir"], root)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return False

    needle = "(%s)" % m["file"]
    kept = [ln for ln in lines if needle not in ln]
    if len(kept) == len(lines):
        return False

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(kept)
    except OSError:
        return False
    return True


def delete(m, root=None):
    """Borra el archivo y lo saca del índice. Devuelve si se desindexó."""
    os.remove(memory_path(m, root))
    return unindex(m, root)
