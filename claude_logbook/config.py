"""Claude Code permissions: tool rules, extra directories and folder trust.

They live in three kinds of files:

    ~/.claude/settings.json                 user scope, every project
    <project>/.claude/settings.json         project scope, usually committed
    <project>/.claude/settings.local.json   local scope, personal, git-ignored

each with a `permissions` object:

    {"permissions": {"allow": [...], "deny": [...], "ask": [...],
                     "additionalDirectories": [...]}}

Trust is elsewhere: `~/.claude.json` keeps one entry per absolute project path,
and `hasTrustDialogAccepted` in it records that the "do you trust this folder?"
dialog was accepted. That file also holds the account and every other piece of
Claude Code state, so it is rewritten keeping all of it as it was.

Every write is read-modify-replace: the file is read again right before the
change and swapped in atomically, keeping its permissions.
"""

import json
import os
import re
import tempfile

from .sessions import SessionError

SCOPES = ("user", "project", "local")
LISTS = ("allow", "deny", "ask")
DIRS_KEY = "additionalDirectories"
TRUST_KEY = "hasTrustDialogAccepted"

# Tool, Tool(specifier) or mcp__server__tool. The specifier is free text.
RULE_RE = re.compile(r"^[A-Za-z][\w.-]*(\(.*\))?$", re.S)


# ──────────────────────────────── locations ──────────────────────────────────

def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")


def global_state_path():
    """~/.claude.json, or .claude.json inside CLAUDE_CONFIG_DIR if it is set."""
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return os.path.join(os.environ["CLAUDE_CONFIG_DIR"], ".claude.json")
    return os.path.join(os.path.expanduser("~"), ".claude.json")


def settings_path(scope, project=None):
    if scope == "user":
        return os.path.join(config_dir(), "settings.json")
    if not project:
        raise SessionError(f"the {scope} scope needs a project (-p PATH)")
    name = "settings.json" if scope == "project" else "settings.local.json"
    return os.path.join(project, ".claude", name)


# ──────────────────────────────── files ───────────────────────────────────

def read_json(path):
    """The file's object, {} if it does not exist. Broken JSON is an error:
    rewriting it would lose whatever it had."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise SessionError(f"cannot read {path}: {e.strerror}")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise SessionError(f"{path} is not valid JSON ({e}); fix it by hand first")
    if not isinstance(data, dict):
        raise SessionError(f"{path} does not hold a JSON object")
    return data


def write_json(path, data, mode=None):
    """Atomic replace that keeps the file's mode (0644 minus umask if new) and
    whether it ended in a newline, so an untouched key reads exactly the same.
    An explicit `mode` wins over both, for files that hold secrets."""
    forced = mode
    try:
        mode = os.stat(path).st_mode & 0o777
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                newline = fh.read(1) == b"\n"
            else:
                newline = True
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
        newline = True
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            if newline:
                fh.write("\n")
        os.chmod(tmp, forced if forced is not None else mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ──────────────────────────────── reading ───────────────────────────────────

def permissions_of(data):
    perms = data.get("permissions")
    return perms if isinstance(perms, dict) else {}


def rules(data):
    """{"allow": [...], "deny": [...], "ask": [...], "dirs": [...], "mode": str}"""
    perms = permissions_of(data)
    out = {k: [r for r in perms.get(k) or [] if isinstance(r, str)] for k in LISTS}
    out["dirs"] = [d for d in perms.get(DIRS_KEY) or [] if isinstance(d, str)]
    out["mode"] = perms.get("defaultMode") if isinstance(
        perms.get("defaultMode"), str) else None
    return out


def is_empty(r):
    return not any(r[k] for k in (*LISTS, "dirs", "mode"))


def trusted_projects(state=None):
    """{path: bool} for every project ~/.claude.json knows about."""
    state = read_json(global_state_path()) if state is None else state
    projects = state.get("projects")
    if not isinstance(projects, dict):
        return {}
    return {p: bool(v.get(TRUST_KEY)) for p, v in projects.items()
            if isinstance(v, dict)}


def trusted_parent(path, trust):
    """Closest trusted ancestor of `path`, or None."""
    cur = path
    while True:
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        if trust.get(parent):
            return parent
        cur = parent


def overview(project_paths):
    """User scope plus one entry per project, for the listing."""
    trust = trusted_projects()
    user_path = settings_path("user")
    projects = []
    for p in sorted(set(project_paths) | set(trust)):
        scopes = []
        for scope in ("project", "local"):
            path = settings_path(scope, p)
            scopes.append({"scope": scope, "path": path,
                           "rules": rules(read_json(path))})
        projects.append({"path": p, "trusted": trust.get(p, False),
                         "parent": trusted_parent(p, trust),
                         "exists": os.path.isdir(p), "scopes": scopes})
    return {"user": {"scope": "user", "path": user_path,
                     "rules": rules(read_json(user_path))},
            "projects": projects}


# ──────────────────────────────── targets ───────────────────────────────────

def resolve_project(ref, known):
    """An existing directory, or the only known project whose path contains `ref`."""
    expanded = os.path.expanduser(ref)
    if os.path.isdir(expanded):
        return os.path.abspath(expanded).rstrip("/") or "/"
    needle = expanded.rstrip("/").lower()
    hits = sorted({p for p in known if needle in p.lower()})
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SessionError(f"{ref} is not a directory nor a known project")
    shown = "\n  ".join(hits[:8]) + ("\n  …" if len(hits) > 8 else "")
    raise SessionError(f"{ref} is ambiguous, it matches {len(hits)} projects:\n  {shown}")


def check_rule(rule):
    rule = rule.strip()
    if not RULE_RE.match(rule) or rule.count("(") != rule.count(")"):
        raise SessionError(
            f"{rule!r} does not look like a rule: Tool or Tool(specifier), "
            f"e.g. Bash(npm test:*), Read(./secrets/**), WebFetch")
    return rule


def normalize_dir(d):
    return os.path.abspath(os.path.expanduser(d)).rstrip("/") or "/"


# ──────────────────────────────── changes ───────────────────────────────────
#
# Each change is a tuple and `plan` turns them into human-readable steps
# against the current contents, so --dry-run and the real run say the same.
#
#   ("add", list, rule)   ("forget", rule)
#   ("add-dir", path)     ("remove-dir", path)

def apply_rules(data, changes):
    """Applies the changes to `data` in place. Returns the list of steps done;
    a change that is already in effect produces no step."""
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
    steps = []

    def lst(key):
        cur = perms.get(key)
        return cur if isinstance(cur, list) else []

    for change in changes:
        kind = change[0]
        if kind == "add":
            _, target, rule = change
            for other in LISTS:
                if other != target and rule in lst(other):
                    perms[other] = [r for r in lst(other) if r != rule]
                    steps.append(f"{rule} leaves {other}")
            if rule not in lst(target):
                perms[target] = lst(target) + [rule]
                steps.append(f"{target} {rule}")
        elif kind == "forget":
            _, rule = change
            for key in LISTS:
                if rule in lst(key):
                    perms[key] = [r for r in lst(key) if r != rule]
                    steps.append(f"{rule} leaves {key}")
        elif kind == "add-dir":
            _, d = change
            if d not in lst(DIRS_KEY):
                perms[DIRS_KEY] = lst(DIRS_KEY) + [d]
                steps.append(f"directory {d}")
        elif kind == "remove-dir":
            _, d = change
            gone = [x for x in lst(DIRS_KEY) if x == d or normalize_dir(x) == d]
            if gone:
                perms[DIRS_KEY] = [x for x in lst(DIRS_KEY) if x not in gone]
                steps.append(f"directory {d} removed")

    # Lists left empty are dropped, and so is an empty permissions object.
    for key in (*LISTS, DIRS_KEY):
        if key in perms and perms[key] == []:
            del perms[key]
    if perms:
        data["permissions"] = perms
    else:
        data.pop("permissions", None)
    return steps


def edit_settings(path, changes, dry_run=False):
    data = read_json(path)
    steps = apply_rules(data, changes)
    if steps and not dry_run:
        write_json(path, data)
    return steps


def set_trust(project, value, dry_run=False):
    """Sets hasTrustDialogAccepted for that path. Returns whether it changed.

    ~/.claude.json is rewritten by every running Claude Code, so it is read
    right before writing and the write is retried if the file moved under us.
    """
    path = global_state_path()
    for _ in range(3):
        try:
            before = os.stat(path).st_mtime_ns
        except FileNotFoundError:
            before = None
        state = read_json(path)
        projects = state.setdefault("projects", {})
        if not isinstance(projects, dict):
            raise SessionError(f"{path}: 'projects' is not an object")
        entry = projects.setdefault(project, {})
        if bool(entry.get(TRUST_KEY)) == value and TRUST_KEY in entry:
            return False
        if not value and TRUST_KEY not in entry:
            if not entry:
                del projects[project]
            return False
        if dry_run:
            return True
        entry[TRUST_KEY] = value
        try:
            now = os.stat(path).st_mtime_ns
        except FileNotFoundError:
            now = None
        if now != before:
            continue
        write_json(path, state)
        return True
    raise SessionError(f"{path} keeps changing (is Claude Code writing it?); try again")
