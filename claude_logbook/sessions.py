"""Parsing of the .jsonl files Claude Code leaves in ~/.claude/projects/.

Each conversation is a JSON Lines file: one line per event. From it comes one
record per session with one-letter keys, because that same record travels
embedded inside the HTML and long names are paid once per session.

Schema of the record returned by `read_session`:

    id   session uuid (the file name)
    p    project cwd
    b    git branch
    t    title
    ai   True if Claude generated the title, False if it is the first message
    n    True if it looks like a non-interactive `claude -p`
    e    True if the session has no message at all
    i    True if `p` was inferred from another session of the same project
    f/l  timestamp of the first and last event (ISO 8601)
    d    duration in minutes
    u/a  number of messages from you / from Claude
    k    size of the .jsonl in KB
    v    Claude Code version
    c    transcript: [{"r": "u" | "a" | "t" | "c" | "d", "x": text}]
         (t: tool call summary, c: compaction summary, d: the working
         directory changed to x)
    h    how many blocks at the start of `c` were copied from the session
         this one branched from (/branch); 0 if it is not a branch
    o    id of that session, or None
    ot   its title, if it is still on disk (filled in by `_fill_gaps`)

A branch starts as a copy of the original's history. Only what came after
counts towards `u`, `a`, `d` and `f`; the copy stays in `c`, first.

`project_dir` and `mtime` are internal and never leave the module:
`public_records()` drops them before the record is serialized.
"""

import glob
import json
import os
import re
from datetime import datetime, timezone

# Bump it when the record schema changes: it invalidates old caches instead of
# reading records with the previous shape.
CACHE_VERSION = 4

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

INTERNAL_KEYS = ("project_dir", "mtime")


class SessionError(Exception):
    """Usage error that the CLI turns into a message and an exit code."""


# ──────────────────────────────── locations ──────────────────────────────────

def default_root():
    """~/.claude/projects, or its equivalent if CLAUDE_CONFIG_DIR is set."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")


def default_cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "claude-logbook", "cache.json")


def session_path(s, root=None):
    """Path of the .jsonl. The file name is the UUID and the parent directory
    name is what we keep in project_dir, so it can be rebuilt."""
    return os.path.join(root or default_root(),
                        s["project_dir"], s["id"] + ".jsonl")


# ─────────────────────────── parsing the .jsonl files ───────────────────────

TAG_RE = re.compile(r"<[^>]+>")
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)

# A message starting with any of these is not user text: it is a
# block the CLI itself generates when running a local command.
SKIP_PREFIXES = (
    "<local-command-caveat", "<command-name", "<command-message",
    "<command-args", "<local-command-stdout", "<system-reminder",
)

TITLE_MAX = 160
TOOL_ARG_MAX = 140

# Threshold of the `claude -p` heuristic: a single message longer than this, with
# no back and forth, is a pipe on stdin and not a conversation.
NONINTERACTIVE_CHARS = 1500

# Active time: a pause between two messages longer than this is the session
# left open, not work, and does not count towards its duration.
IDLE_GAP_MINUTES = 30

# For each tool, the parameter that best summarizes what it did.
TOOL_KEY = {
    "Bash": "command", "Read": "file_path", "Edit": "file_path",
    "Write": "file_path", "NotebookEdit": "notebook_path", "Glob": "pattern",
    "Grep": "pattern", "WebFetch": "url", "WebSearch": "query",
    "Task": "description", "Agent": "description", "Skill": "skill",
}


def clean_text(s):
    """Returns readable user text, or None if it is harness noise."""
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
    """A line like 'Bash: git status' for a tool call."""
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
    """ISO 8601 → timezone-aware datetime, or None if it cannot be read."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def active_minutes(stamps):
    """Minutes of work: the gaps between consecutive messages, leaving out
    the pauses longer than IDLE_GAP_MINUTES. None without messages."""
    times = sorted(t for t in map(parse_ts, stamps) if t)
    if not times:
        return None
    total = 0.0
    for a, b in zip(times, times[1:]):
        gap = (b - a).total_seconds() / 60
        if gap <= IDLE_GAP_MINUTES:
            total += gap
    return round(total)


def read_session(path):
    """Parses a whole .jsonl and returns that session's record."""
    session_id = os.path.basename(path)[:-6]  # without .jsonl
    first_ts = last_ts = cwd = here = git_branch = version = None
    origin = None  # the session /branch copied the history from
    inherited = None  # blocks of c that came with that copy
    old_first_ts = None  # first timestamp of the copied rows
    ai_title = custom_title = fallback_title = None
    stamps = []  # of the messages, for the active time
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
                continue  # line truncated by a session that is still writing
            if not isinstance(obj, dict):
                continue

            kind = obj.get("type")

            if kind == "ai-title":
                if obj.get("aiTitle"):
                    ai_title = obj["aiTitle"]  # keep the most recent one
                continue
            if kind == "custom-title":
                if obj.get("customTitle"):
                    custom_title = obj["customTitle"]  # /rename, wins over the AI one
                continue

            # /branch copies the original rows into the new file, each one
            # marked with where it came from. They come first.
            forked = obj.get("forkedFrom")
            copied = isinstance(forked, dict)
            if copied and forked.get("sessionId"):
                origin = forked["sessionId"]

            ts = obj.get("timestamp")
            if ts:
                if copied:
                    old_first_ts = old_first_ts or ts
                elif first_ts is None:
                    first_ts = ts
                last_ts = ts
            if cwd is None and obj.get("cwd"):
                cwd = here = obj["cwd"]
            if git_branch is None and obj.get("gitBranch"):
                git_branch = obj["gitBranch"]
            if obj.get("version"):
                version = obj["version"]

            if kind not in ("user", "assistant") or obj.get("isSidechain"):
                continue

            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            if not copied:
                if origin and inherited is None:
                    inherited = len(convo)  # the branch's own part starts here
                if ts:
                    stamps.append(ts)
            # A `cd` that sticks, /cd or a worktree: from here on the session
            # works somewhere else. Only messages count, so a subagent or a
            # hook running elsewhere does not move it.
            if obj.get("cwd") and obj["cwd"] != here:
                here = obj["cwd"]
                convo.append({"r": "d", "x": here})

            if kind == "user":
                if obj.get("isMeta"):
                    continue
                # What /compact (or running out of context) left in place of
                # the earlier conversation: written by Claude, not by you.
                if obj.get("isCompactSummary"):
                    text = "\n".join(
                        (b.get("text") or "").strip() for b in blocks_of(message)
                        if isinstance(b, dict) and b.get("type") == "text").strip()
                    convo.append({"r": "c", "x": text})
                    continue
                for b in blocks_of(message):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        text = clean_text(b.get("text"))
                        if text:
                            user_msgs += not copied
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
                if counted and not copied:
                    assistant_msgs += 1

    st = os.stat(path)
    # A single huge message and no back and forth is the signature of a
    # `claude -p` with something piped on stdin (e.g. a git diff to write the
    # commit message), not of a conversation.
    noninteractive = (
        user_msgs == 1 and not (ai_title or custom_title) and not origin
        and len(next((b["x"] for b in convo if b["r"] == "u"), "")) > NONINTERACTIVE_CHARS
    )

    return {
        "id": session_id,
        "project_dir": os.path.basename(os.path.dirname(path)),
        "p": cwd,
        "b": git_branch,
        "t": custom_title or ai_title or fallback_title,
        "ai": bool(custom_title or ai_title),
        "n": noninteractive,
        "e": all(b["r"] == "d" for b in convo),
        "f": first_ts or old_first_ts,
        "l": last_ts,
        "d": active_minutes(stamps),
        "u": user_msgs,
        "a": assistant_msgs,
        "k": round(st.st_size / 1024, 1),
        "v": version,
        "c": convo,
        "h": (len(convo) if inherited is None else inherited) if origin else 0,
        "o": origin,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


# ──────────────────────────────── cache ────────────────────────────────

def _load_cache(path):
    """Cache entries, or {} if it does not exist, is broken or is stale."""
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
    """Writes the cache atomically. If it fails, nothing happens."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # The pid in the temporary file keeps two simultaneous runs from clobbering each other.
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": CACHE_VERSION, "entries": entries}, f,
                      ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass  # the cache is an optimization, not a requirement


def drop_from_cache(paths, cache_path=None):
    """Drops deleted sessions from the cache so they do not reappear."""
    cache_path = cache_path or default_cache_path()
    entries = _load_cache(cache_path)
    if not entries:
        return
    if any(entries.pop(p, None) is not None for p in list(paths)):
        _save_cache(cache_path, entries)


# ──────────────────────────────── loading ──────────────────────────────

def _fill_gaps(sessions):
    """Fills in what is missing after parsing every file.

    A branch gets the title of the session it came from, if it is still there.

    Some sessions (a cancelled /resume) never record a cwd. The directory name
    cannot be reliably reversed because "/" and "." are both encoded as "-", so
    the path is borrowed from another session of the same project and flagged in
    `i`.
    """
    known = {}
    for s in sessions:
        if s["p"]:
            known.setdefault(s["project_dir"], s["p"])

    titles = {s["id"]: s["t"] for s in sessions}
    for s in sessions:
        s["ot"] = titles.get(s["o"]) if s["o"] else None
        s["i"] = not s["p"]
        if not s["p"]:
            s["p"] = known.get(s["project_dir"], s["project_dir"])
        if not s["l"]:
            s["l"] = s["mtime"]
        if not s["f"]:
            s["f"] = s["mtime"]


def load_sessions(root=None, cache_path=None, use_cache=True):
    """Parses every session, reusing from the cache the ones that did not change."""
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

    # Before `_fill_gaps`, on purpose: the cache gets the record as it came out
    # of the file, without the fields inferred from the other sessions.
    if use_cache and (reparsed or len(fresh) != len(cache)):
        _save_cache(cache_path, fresh)

    _fill_gaps(sessions)
    sessions.sort(key=lambda s: parse_ts(s["l"]) or EPOCH, reverse=True)
    return sessions


def latest_activity(sessions):
    """The most recent instant in the data: the "now" relative dates are computed
    against, so they do not depend on the viewer's clock."""
    stamps = [parse_ts(s["l"]) for s in sessions]
    return max([t for t in stamps if t], default=EPOCH)


def public_records(sessions):
    """Copies without the internal keys, ready to serialize."""
    return [{k: v for k, v in s.items() if k not in INTERNAL_KEYS}
            for s in sessions]


# ──────────────────────────────── filters ────────────────────────────────

def apply_filters(sessions, project=None, grep=None, query=None,
                  hide_empty=False):
    out = sessions

    if project:
        needle = os.path.expanduser(project).rstrip("/").lower()
        # Any directory it worked in: where it started or one it moved to.
        out = [s for s in out if needle in s["p"].lower()
               or any(m["r"] == "d" and needle in m["x"].lower() for m in s["c"])]

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
    """Resolves a table index (1-based) or a UUID prefix."""
    if ref.isdigit():
        i = int(ref)
        if 1 <= i <= len(sessions):
            return sessions[i - 1]
        raise SessionError(
            f"index {i} is out of range (there are {len(sessions)})")

    hits = [s for s in sessions if s["id"].startswith(ref.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SessionError(f"no session starts with '{ref}'")
    raise SessionError(f"'{ref}' is ambiguous, it matches {len(hits)} sessions")
