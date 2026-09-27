"""Project memories: the .md files Claude Code leaves in <project>/memory/.

Each project can accumulate memories in

    ~/.claude/projects/<project>/memory/<name>.md

One file per memory, with YAML frontmatter (`name`, `description`,
`metadata.type`, `metadata.originSessionId`) and a markdown body. Next to them
lives `MEMORY.md`, the index: one line per memory, and the only thing loaded
into context when a session starts. A memory missing from it is still on disk
but is no longer remembered, so the difference between both is worth checking.

Schema of the record returned by `read_memory`, with the same short keys as
`sessions` because it also travels embedded in the HTML:

    name  frontmatter name (or the file name if missing)
    file  file name, with extension
    p     project cwd
    desc  frontmatter description
    ty    declared type: project | user | feedback | reference
    src   uuid of the session that created it, if declared
    body  markdown body, without the frontmatter
    ln    [[...]] links that appear in the body
    k     size in KB
    l     file mtime (ISO 8601)
    ix    True if listed in MEMORY.md
    hix   True if the project has a MEMORY.md

`project_dir` is internal and `public_records()` drops it before serializing.
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
# In the index each line is "- [Title](file.md) — hint".
INDEX_LINK_RE = re.compile(r"\(([^)\n]+)\.md\)")


def memory_dir(project_dir, root=None):
    return os.path.join(root or default_root(), project_dir, "memory")


def memory_path(m, root=None):
    return os.path.join(memory_dir(m["project_dir"], root), m["file"])


def index_path(project_dir, root=None):
    return os.path.join(memory_dir(project_dir, root), INDEX_NAME)


# ──────────────────────────────── parsing ───────────────────────────────

def _field(front, key):
    """Value of a frontmatter key. Flat: enough for what Claude Code writes,
    which nests `type` and `originSessionId` but without repeating them."""
    hit = re.search(r"^\s*%s:\s*(.+?)\s*$" % re.escape(key), front, re.M)
    if not hit:
        return None
    value = hit.group(1).strip()
    # One-line YAML: if it comes quoted, the inner quotes are
    # escaped and have to be restored as they were.
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
    """Names (without .md) that the project's MEMORY.md links to."""
    try:
        with open(index_path(project_dir, root), "r",
                  encoding="utf-8", errors="ignore") as f:
            return set(INDEX_LINK_RE.findall(f.read()))
    except OSError:
        return set()


# ──────────────────────────────── loading ──────────────────────────────

def load_memories(sessions, root=None):
    """Reads the memories of every project.

    The real project path comes from the sessions: the directory name encodes
    "/" and "." both as "-" and cannot be reversed.
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
            continue  # an empty memory/ is not a project with memory

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
    """Copy without the internal keys, ready to serialize."""
    out = []
    for m in memories:
        clean = dict(m)
        for key in INTERNAL_KEYS:
            clean.pop(key, None)
        out.append(clean)
    return out


# ──────────────────────────────── filters ────────────────────────────────

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
    """Resolves a table index (1-based) or a name prefix."""
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
    name_list = ", ".join(m["name"] for m in hits[:4])
    raise SessionError(
        f"'{ref}' es ambiguo, coincide con {len(hits)}: {name_list}"
        + (", …" if len(hits) > 4 else ""))


# ──────────────────────────────── audit ────────────────────────────────────

def audit(memories, sessions, root=None):
    """Inconsistencies between files, indexes, links and origin sessions."""
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


# ──────────────────────────────── deletion ───────────────────────────────

def unindex(m, root=None):
    """Removes the line pointing to this memory from MEMORY.md.

    Returns True if the index changed. It is not an error if it does not: the
    memory may not have been listed.
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
    """Deletes the file and removes it from the index. Returns whether it was unindexed."""
    os.remove(memory_path(m, root))
    return unindex(m, root)
