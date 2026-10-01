"""Fake .jsonl sessions for the tests."""

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
    """Writes a .jsonl and returns its path."""
    d = os.path.join(root, project_dir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, session_id + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def simple_tree(root):
    """A small, varied tree: a chat, an empty one and one without cwd."""
    write_session(root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001", [
        ai_title("Fix the build"),
        user("why does the build fail?", at=ts(0)),
        assistant("Checking the log.", tools=[("Bash", {"command": "make"})], at=ts(3)),
        user("thanks", at=ts(12)),
    ])
    write_session(root, "-home-u-proj", "bbbbbbbb-0000-0000-0000-000000000002", [
        {"type": "system", "timestamp": ts(0, hour=9), "cwd": "/home/u/proj"},
    ])
    write_session(root, "-home-u-other", "cccccccc-0000-0000-0000-000000000003", [
        user("hello", at=ts(0, hour=8), cwd="/home/u/other"),
    ])
    return root


# ──────────────────────────────── memories ────────────────────────────────

def write_memory(root, project_dir, name, body="body text", desc=None,
                 kind="project", origin=None, frontmatter=True):
    """Writes <project>/memory/<name>.md and returns its path."""
    d = os.path.join(root, project_dir, "memory")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name + ".md")

    parts = []
    if frontmatter:
        fields = ["---", f"name: {name}"]
        if desc is not None:
            fields.append(f"description: {desc}")
        fields += ["metadata:", "  node_type: memory", f"  type: {kind}"]
        if origin:
            fields.append(f"  originSessionId: {origin}")
        fields.append("---")
        parts.append("\n".join(fields))
    parts.append(body)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    return path


def write_index(root, project_dir, names, extra=()):
    """Writes the MEMORY.md that links those names."""
    d = os.path.join(root, project_dir, "memory")
    os.makedirs(d, exist_ok=True)
    lines = ["# Memory Index", ""]
    for n in list(names) + list(extra):
        lines.append(f"- [{n}]({n}.md) — hint for {n}")
    path = os.path.join(d, "MEMORY.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def memory_tree(root):
    """Varied memories: indexed, unlisted, and a project without an index."""
    write_memory(root, "-home-u-proj", "deploy-docker",
                 body="Deployed with `make up`.\nSee [[roles-db]] and [[missing]].",
                 desc="How the project is deployed",
                 origin="aaaaaaaa-0000-0000-0000-000000000001")
    write_memory(root, "-home-u-proj", "roles-db", body="Database roles.",
                 desc="Roles", kind="reference")
    write_memory(root, "-home-u-proj", "stray", body="Not in the index.",
                 desc="Orphan")
    # The index lists two real ones and one that no longer exists.
    write_index(root, "-home-u-proj", ["deploy-docker", "roles-db"],
                extra=["deleted-long-ago"])

    # Another project with memory but no MEMORY.md.
    write_memory(root, "-home-u-other", "no-index", body="Nobody indexes me.",
                 desc="No index", kind="user",
                 origin="ffffffff-0000-0000-0000-00000000000f")

    # An empty memory/ does not count as a project with memory.
    os.makedirs(os.path.join(root, "-home-u-empty", "memory"), exist_ok=True)
    return root
