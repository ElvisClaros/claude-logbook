"""Sesiones .jsonl de mentira para los tests."""

import json
import os

BASE_TS = "2025-08-14T10:00:00.000Z"


def ts(minute=0, hour=10, day=14):
    return f"2025-08-{day:02d}T{hour:02d}:{minute:02d}:00.000Z"


def user(text, at=BASE_TS, **extra):
    ev = {
        "type": "user",
        "timestamp": at,
        "cwd": "/home/u/proj",
        "gitBranch": "main",
        "version": "1.0.0",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    ev.update(extra)
    return ev


def assistant(text=None, tools=(), at=BASE_TS, **extra):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    for name, args in tools:
        content.append({"type": "tool_use", "name": name, "input": args})
    ev = {
        "type": "assistant",
        "timestamp": at,
        "message": {"role": "assistant", "content": content},
    }
    ev.update(extra)
    return ev


def ai_title(title, at=BASE_TS):
    return {"type": "ai-title", "aiTitle": title, "timestamp": at}


def write_session(root, project_dir, session_id, events):
    """Escribe un .jsonl y devuelve su ruta."""
    d = os.path.join(root, project_dir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, session_id + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def simple_tree(root):
    """Un árbol chico y variado: una charla, una vacía y una sin cwd."""
    write_session(root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001", [
        ai_title("Arreglar el build"),
        user("¿por qué falla el build?", at=ts(0)),
        assistant("Miro el log.", tools=[("Bash", {"command": "make"})], at=ts(3)),
        user("gracias", at=ts(12)),
    ])
    write_session(root, "-home-u-proj", "bbbbbbbb-0000-0000-0000-000000000002", [
        {"type": "system", "timestamp": ts(0, hour=9), "cwd": "/home/u/proj"},
    ])
    write_session(root, "-home-u-otro", "cccccccc-0000-0000-0000-000000000003", [
        user("hola", at=ts(0, hour=8), cwd="/home/u/otro"),
    ])
    return root


# ──────────────────────────────── memorias ────────────────────────────────

def write_memory(root, project_dir, name, body="cuerpo", desc=None,
                 kind="project", origin=None, frontmatter=True):
    """Escribe <proyecto>/memory/<name>.md y devuelve su ruta."""
    d = os.path.join(root, project_dir, "memory")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name + ".md")

    partes = []
    if frontmatter:
        campos = ["---", f"name: {name}"]
        if desc is not None:
            campos.append(f"description: {desc}")
        campos += ["metadata:", "  node_type: memory", f"  type: {kind}"]
        if origin:
            campos.append(f"  originSessionId: {origin}")
        campos.append("---")
        partes.append("\n".join(campos))
    partes.append(body)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(partes) + "\n")
    return path


def write_index(root, project_dir, names, extra=()):
    """Escribe el MEMORY.md que enlaza esos nombres."""
    d = os.path.join(root, project_dir, "memory")
    os.makedirs(d, exist_ok=True)
    lines = ["# Memory Index", ""]
    for n in list(names) + list(extra):
        lines.append(f"- [{n}]({n}.md) — pista de {n}")
    path = os.path.join(d, "MEMORY.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def memory_tree(root):
    """Memorias variadas: indexada, sin listar, y un proyecto sin índice."""
    write_memory(root, "-home-u-proj", "deploy-docker",
                 body="Se despliega con `make up`.\nVer [[roles-db]] y [[no-existe]].",
                 desc="Cómo se despliega el proyecto",
                 origin="aaaaaaaa-0000-0000-0000-000000000001")
    write_memory(root, "-home-u-proj", "roles-db", body="Roles de la base.",
                 desc="Roles", kind="reference")
    write_memory(root, "-home-u-proj", "suelta", body="No está en el índice.",
                 desc="Huérfana")
    # El índice lista dos reales y una que ya no existe.
    write_index(root, "-home-u-proj", ["deploy-docker", "roles-db"],
                extra=["borrada-hace-rato"])

    # Otro proyecto con memoria pero sin MEMORY.md.
    write_memory(root, "-home-u-otro", "sin-indice", body="Nadie me indexa.",
                 desc="Sin índice", kind="user",
                 origin="ffffffff-0000-0000-0000-00000000000f")

    # Un memory/ vacío no cuenta como proyecto con memoria.
    os.makedirs(os.path.join(root, "-home-u-vacio", "memory"), exist_ok=True)
    return root
