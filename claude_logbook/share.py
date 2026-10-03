"""Publishing one session on a share server (claude-logbook.all.ar by default).

The server takes the same JSON `--json -s` prints and serves it at
/share/<id> (page), /share/<id>.txt and /share/<id>.json. Creating a share
returns a secret; only with it can the share be replaced or deleted, so it is
kept in a local registry readable by its owner alone:

    $XDG_STATE_HOME/claude-logbook/shares.json   (~/.local/state/... by default)

Only the standard library: urllib for HTTP.
"""

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import __version__
from .config import read_json, write_json
from .sessions import SessionError

DEFAULT_SERVER = "https://claude-logbook.all.ar"
SERVER_ENV = "CLAUDE_LOGBOOK_SERVER"
EXPIRES = ("1d", "7d", "30d", "90d")
DEFAULT_EXPIRE = "30d"
TIMEOUT = 60

# Things that should not leave the machine by accident. Only the kind and
# where it is are reported, never the match itself.
SECRET_PATTERNS = (
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI-style API key", re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{20,})")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("password or token assignment", re.compile(
        r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*['\"]?[^\s'\"]{8,}")),
)


class NotFound(SessionError):
    """The server no longer has that share (expired or deleted)."""


# ──────────────────────────────── local registry ─────────────────────────

def server_url(arg=None):
    return (arg or os.environ.get(SERVER_ENV) or DEFAULT_SERVER).rstrip("/")


def registry_path():
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "claude-logbook", "shares.json")


def load_registry():
    shares = read_json(registry_path()).get("shares")
    return [e for e in shares if isinstance(e, dict)] if isinstance(shares, list) else []


def save_registry(entries):
    path = registry_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    write_json(path, {"shares": entries}, mode=0o600)


def entry_for_session(entries, session_id, server):
    for e in entries:
        if e.get("session") == session_id and e.get("server") == server:
            return e
    return None


def find_entry(entries, ref):
    """By share id, by its URL or by a prefix of the session UUID."""
    ref = ref.strip().rstrip("/")
    if "/share/" in ref:
        ref = ref.rsplit("/share/", 1)[1].split(".")[0]
    hits = [e for e in entries if e.get("id") == ref]
    if not hits and len(ref) >= 4:
        hits = [e for e in entries if (e.get("session") or "").startswith(ref.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SessionError(f"no share of yours matches '{ref}' (see --shares)")
    raise SessionError(f"'{ref}' is ambiguous, it matches {len(hits)} shares")


def is_expired(entry, now=None):
    try:
        exp = datetime.fromisoformat(entry["expires"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError):
        return False
    return exp <= (now or datetime.now(timezone.utc))


# ──────────────────────────────── content check ──────────────────────────

def scan_secrets(payload):
    """[(kind, [block numbers])] for what looks like a credential. Block 0 is
    the title; the rest count from 1 as the conversation goes."""
    found = {}
    for s in payload.get("s", ()):
        texts = [(0, s.get("t") or "")] + [
            (i, b.get("x") or "") for i, b in enumerate(s.get("c", ()), 1)]
        for where, text in texts:
            for kind, rx in SECRET_PATTERNS:
                if rx.search(text):
                    found.setdefault(kind, []).append(where)
    return [(kind, found[kind]) for kind, _ in SECRET_PATTERNS if kind in found]


# ──────────────────────────────── http ───────────────────────────────────

def _request(method, url, body=None, secret=None):
    data = None if body is None else json.dumps(
        body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": f"claude-logbook/{__version__}",
        "Accept": "application/json",
    })
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if secret:
        req.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise _http_error(e)
    except urllib.error.URLError as e:
        raise SessionError(f"cannot reach {url.split('/api/')[0]}: {e.reason}")
    except (TimeoutError, OSError) as e:
        raise SessionError(f"cannot reach {url.split('/api/')[0]}: {e}")
    return json.loads(raw) if raw.strip() else {}


def _http_error(e):
    try:
        msg = json.loads(e.read() or b"{}").get("error") or e.reason
    except (ValueError, AttributeError, OSError):
        msg = e.reason
    if e.code == 404:
        return NotFound("the server no longer has that share (expired or deleted)")
    if e.code == 413:
        return SessionError(f"the session is too large for the server ({msg})")
    if e.code == 429:
        return SessionError("the server is limiting requests from your address; try again later")
    if e.code == 403:
        return SessionError("the server rejected the secret of that share")
    return SessionError(f"the server answered {e.code}: {msg}")


def create(server, payload, expire):
    return _request("POST", f"{server}/api/shares",
                    {"payload": payload, "expire": expire})


def update(server, entry, payload, expire):
    return _request("PUT", f"{server}/api/shares/{entry['id']}",
                    {"payload": payload, "expire": expire}, secret=entry["secret"])


def delete(server, entry):
    _request("DELETE", f"{server}/api/shares/{entry['id']}", secret=entry["secret"])


def publish(server, payload, expire, session, title):
    """Creates the share, or updates the one this machine already made for
    that session (the link stays the same). Returns (entry, created)."""
    entries = load_registry()
    old = entry_for_session(entries, session, server)
    created = True
    if old:
        try:
            resp = update(server, old, payload, expire)
            resp["secret"] = old["secret"]
            created = False
        except NotFound:
            resp = create(server, payload, expire)
        entries.remove(old)
    else:
        resp = create(server, payload, expire)
    entry = {
        "id": resp["id"], "url": resp["url"], "secret": resp["secret"],
        "server": server, "session": session, "title": title,
        "created": (old or {}).get("created") if not created else
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "expires": resp.get("expires"),
    }
    entries.append(entry)
    save_registry(entries)
    return entry, created


def unpublish(entry):
    """Deletes it on its server and forgets it. A share the server no longer
    has is forgotten all the same. Returns False in that case."""
    gone = True
    try:
        delete(entry["server"], entry)
    except NotFound:
        gone = False
    entries = [e for e in load_registry()
               if not (e.get("id") == entry["id"] and e.get("server") == entry["server"])]
    save_registry(entries)
    return gone
