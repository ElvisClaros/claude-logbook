"""Command-line interface."""

import argparse
import io
import os
import sys
import textwrap
import time
import webbrowser

from . import __version__
from .sessions import (
    SessionError, apply_filters, count_images, default_root, drop_from_cache,
    latest_activity, load_sessions, pick, public_records, session_path, with_images,
)
from .terminal import (
    Style, clip, fmt_date, fmt_size, plural, print_audit, print_chat,
    print_memories, print_memory, print_permissions, print_table, resume_cmd,
    short_home,
)
from . import config as cfg
from . import memory as mem
from . import share
from . import webpage

DEFAULT_HTML = "sessions.html"

# A session written less than this long ago may be open in another terminal.
RECENT_SECONDS = 300

EPILOG = """\
examples:
  claude-logbook                     table of every session
  claude-logbook docker              filter by title, path or branch
  claude-logbook -s 3                read chat #3 from the table
  claude-logbook -s 5d10f1ee         same, by UUID prefix
  claude-logbook -g "port already"   search inside the conversations
  claude-logbook -r 3                command to resume #3
  eval "$(claude-logbook -r 3)"      resume it right away
  claude-logbook --html --open       write sessions.html and open it
  claude-logbook -s 3 --html         export only #3 (session-<id>.html)
  claude-logbook -p api --json       export only that project's sessions

the # is the position in the table you are looking at, so if you filtered
you have to repeat the filter to read that row:

  claude-logbook docker              shows 3 results
  claude-logbook docker -s 2         reads the 2nd of those three

deleting (irreversible; asks first unless -y):
  claude-logbook --delete-empty --dry-run   what it would delete
  claude-logbook --delete-empty             delete the empty ones
  claude-logbook -D 101 -D e0a4300e         delete specific sessions
  claude-logbook -p /tmp --delete-empty     only the empty ones in that project

project memory (-m switches from sessions to memories and reuses the same
verbs: filter, -s to read, -D to delete):
  claude-logbook -m                  table of memories
  claude-logbook -m docker           search name, description and body
  claude-logbook -m -s 3             read memory #3
  claude-logbook -m -s deadlock      same, by name
  claude-logbook -m --check          audit indexes, links and sources
  claude-logbook -m -D 3             delete it and drop it from MEMORY.md

permissions (-P lists them; any change flag implies it). Rules go to the
user settings unless -p names a project, then to its settings.local.json;
--scope project writes the shared .claude/settings.json instead:
  claude-logbook -P                         user rules and every project with rules
  claude-logbook -P -p logbook              one project, trusted or not
  claude-logbook --allow "Bash(npm test:*)" -p .
  claude-logbook --deny "Read(./.env)" --scope project -p .
  claude-logbook --remove-rule WebFetch     drop it from allow, ask and deny
  claude-logbook --add-dir ~/shared -p .    extra directory for that project
  claude-logbook --trust -p ~/repo          accept the trust dialog for it
  claude-logbook --untrust -p ~/repo --dry-run

sharing (one session, readable by anyone with the link; asks first unless -y):
  claude-logbook -s 3 --share               upload #3, prints its link
  claude-logbook -s 3 --share --expire 7d   gone in a week (default 30d)
  claude-logbook -s 3 --share --images      with the screenshots and pictures
  claude-logbook --shares                   what this machine has shared
  claude-logbook --unshare 5d10f1ee         delete it (share id, URL or session)
"""


def build_parser():
    ap = argparse.ArgumentParser(
        prog="claude-logbook",
        description="Claude Code session browser for the terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(EPILOG),
    )
    ap.add_argument("query", nargs="*", help="text to search in title, path or branch")
    ap.add_argument("-s", "--show", metavar="REF",
                    help="show the chat: table index or UUID prefix")
    ap.add_argument("-r", "--resume", metavar="REF",
                    help="print the command to resume that session")
    ap.add_argument("-g", "--grep", metavar="TEXT",
                    help="filter by conversation content")
    ap.add_argument("-p", "--project", metavar="PATH",
                    help="filter by project path")
    ap.add_argument("-n", "--limit", type=int, metavar="N",
                    help="show only the N most recent")
    ap.add_argument("-E", "--hide-empty", action="store_true",
                    help="hide sessions with no messages")
    ap.add_argument("--no-tools", action="store_true",
                    help="hide tool calls in the chat")
    ap.add_argument("--no-pager", action="store_true",
                    help="do not use $PAGER for the chat")
    ap.add_argument("--no-color", action="store_true", help="plain output, no color")

    memories_list = ap.add_argument_group("project memory")
    memories_list.add_argument("-m", "--memory", action="store_true",
                           help="work on memories instead of sessions")
    memories_list.add_argument("--type", metavar="TYPE", choices=mem.TYPES,
                           help="filter by type: " + " | ".join(mem.TYPES))
    memories_list.add_argument("--check", action="store_true",
                           help="audit indexes, links and source sessions")

    perms = ap.add_argument_group("permissions")
    perms.add_argument("-P", "--perms", action="store_true",
                       help="work on permissions instead of sessions")
    for key, what in (("allow", "allowed without asking"),
                      ("ask", "always asked"), ("deny", "denied")):
        perms.add_argument(f"--{key}", metavar="RULE", nargs="+", action="extend",
                           help=f"add a rule to {key}: {what}")
    perms.add_argument("--remove-rule", metavar="RULE", nargs="+", action="extend",
                       help="remove a rule from allow, ask and deny")
    perms.add_argument("--add-dir", metavar="DIR", nargs="+", action="extend",
                       help="add to additionalDirectories")
    perms.add_argument("--remove-dir", metavar="DIR", nargs="+", action="extend",
                       help="remove from additionalDirectories")
    trust = perms.add_mutually_exclusive_group()
    trust.add_argument("--trust", action="store_true",
                       help="mark the -p project as trusted in ~/.claude.json")
    trust.add_argument("--untrust", action="store_true",
                       help="make Claude Code ask again whether to trust it")
    perms.add_argument("--scope", choices=cfg.SCOPES,
                       help="settings file to change (default: local with -p, "
                            "user without)")

    output_path = ap.add_argument_group("export")
    output_path.add_argument("--json", action="store_true",
                        help="dump the sessions as JSON (all, or what -s and "
                             "the filters select)")
    output_path.add_argument("--html", nargs="?", const="", metavar="FILE",
                        help=f"write a self-contained page (default {DEFAULT_HTML}, "
                             f"or session-<id>.html with -s)")
    output_path.add_argument("--template", metavar="FILE",
                        help="use another template for --html")
    output_path.add_argument("--open", action="store_true",
                        help="open what --html writes in the browser")
    output_path.add_argument("--images", action="store_true",
                        help="with -s: include the session's images in --html, "
                             "--json or --share")

    sharing = ap.add_argument_group("share")
    sharing.add_argument("--share", action="store_true",
                         help="publish the -s session and print its link")
    sharing.add_argument("--expire", choices=share.EXPIRES, default=share.DEFAULT_EXPIRE,
                         help=f"how long the share lives (default {share.DEFAULT_EXPIRE})")
    sharing.add_argument("--shares", action="store_true",
                         help="list what this machine has shared")
    sharing.add_argument("--unshare", metavar="REF",
                         help="delete a share: its id, its URL or the session UUID prefix")
    sharing.add_argument("--server", metavar="URL",
                         help=f"share server (default ${share.SERVER_ENV} or "
                              f"{share.DEFAULT_SERVER})")

    delete_items = ap.add_argument_group("delete")
    delete_items.add_argument("-D", "--delete", metavar="REF", nargs="+",
                        help="delete those sessions (index or UUID prefix)")
    delete_items.add_argument("--delete-empty", action="store_true",
                        help="delete every session with no messages")
    delete_items.add_argument("-y", "--yes", action="store_true",
                        help="do not ask before deleting or sharing")
    delete_items.add_argument("--dry-run", action="store_true",
                        help="show what would change and touch nothing")

    ap.add_argument("--no-cache", action="store_true",
                    help="ignore the cache and re-parse everything")
    ap.add_argument("--version", action="version",
                    version=f"claude-logbook {__version__}")
    return ap


def filtered(sessions, args):
    return apply_filters(
        sessions,
        project=args.project,
        grep=args.grep,
        query=" ".join(args.query) if args.query else None,
        hide_empty=args.hide_empty,
    )


# ──────────────────────────────── deletion ───────────────────────────────

def confirm(question):
    """Asks y/N. Without a terminal no confirmation is possible: returns False."""
    try:
        tty = open("/dev/tty")
    except OSError:
        return False
    try:
        sys.stderr.write(question)
        sys.stderr.flush()
        return tty.readline().strip().lower() in ("y", "yes")
    except (OSError, KeyboardInterrupt):
        return False
    finally:
        tty.close()


def delete_sessions(targets, args, st):
    """Deletes the given sessions. Returns the exit code."""
    if not targets:
        print("No sessions to delete with those criteria.", file=sys.stderr)
        return 0

    print(f"{st.bold}About to delete "
          f"{plural(len(targets), 'session', 'sessions')}:{st.reset}\n")

    total_kb = 0
    recent = []
    for s in targets:
        path = session_path(s)
        total_kb += s["k"]
        title = s["t"] or "session opened with no messages"
        flag = ""
        try:
            if time.time() - os.stat(path).st_mtime < RECENT_SECONDS:
                recent.append(s)
                flag = f" {st.copper}← modified less than 5 min ago{st.reset}"
        except OSError:
            flag = f" {st.copper}← no longer exists{st.reset}"
        print(f"  {st.faint}{s['id'][:8]}{st.reset} {clip(title, 52):<52} "
              f"{st.grey}{clip(s['p'], 34):<34}{st.reset} "
              f"{fmt_date(s['l'])} {st.faint}{s['k']:>7.1f} KB{st.reset}{flag}")

    print(f"\n{st.faint}{fmt_size(total_kb)} in total{st.reset}")

    if recent:
        verb = "was" if len(recent) == 1 else "were"
        print(f"\n{st.copper}Careful: {len(recent)} of these {verb} written less than "
              f"5 minutes ago. If one is a session open right now, Claude Code is "
              f"still using it and will write it again when it closes.{st.reset}")

    if args.dry_run:
        print(f"\n{st.faint}--dry-run: nothing was touched.{st.reset}")
        return 0

    if not args.yes:
        print(f"\n{st.copper}This cannot be undone.{st.reset}")
        if not confirm("Confirm? [y/N] "):
            print("Cancelled.", file=sys.stderr)
            return 1

    done, failed, paths = 0, 0, []
    for s in targets:
        path = session_path(s)
        try:
            os.remove(path)
            paths.append(path)
            done += 1
        except OSError as e:
            print(f"error: {s['id'][:8]}: {e}", file=sys.stderr)
            failed += 1

    drop_from_cache(paths)

    print(f"\n{plural(done, 'session deleted', 'sessions deleted')}.")
    return 1 if failed else 0


def delete_targets(pool, args):
    """The sessions the user asked to delete, without duplicates and in the requested order."""
    targets, seen = [], set()

    if args.delete_empty:
        for s in pool:
            if s["e"]:
                targets.append(s)
                seen.add(s["id"])

    for ref in args.delete or []:
        s = pick(pool, ref)
        if s["id"] not in seen:
            seen.add(s["id"])
            targets.append(s)

    return targets


# ──────────────────────────────── commands ────────────────────────────────

def export_selection(sessions, args):
    """What --json and --html export: the -s session, or what the filters and
    -n leave. With no filter at all, everything, memories included; otherwise
    only the memories of the projects that made it. A single session (-s) goes
    alone, as it would be shared: no memories."""
    if args.show:
        s = pick(filtered(sessions, args), args.show)
        return [with_images(s) if args.images else s], []
    else:
        chosen = filtered(sessions, args)
        if args.limit:
            chosen = chosen[: args.limit]

    memories = mem.load_memories(sessions)
    if len(chosen) != len(sessions):
        dirs = {s["project_dir"] for s in chosen}
        memories = [m for m in memories if m["project_dir"] in dirs]
    return chosen, memories


def cmd_json(sessions, memories):
    import json
    payload = webpage.build_payload(
        public_records(sessions), mem.public_records(memories))
    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def html_path(chosen, args):
    if args.html:
        return args.html
    if args.show:
        return f"session-{chosen[0]['id'][:8]}.html"
    return DEFAULT_HTML


def cmd_html(sessions, memories, args):
    out = html_path(sessions, args)
    memories = mem.public_records(memories)
    stats = webpage.write(public_records(sessions), out, memories=memories,
                          template=webpage.template_text(args.template))
    print(f"{stats['sessions']} sessions · {stats['projects']} projects · "
          f"{stats['messages']} messages · {stats['blocks']} transcript "
          f"blocks · {stats['memories']} memories → {out}",
          file=sys.stderr)
    if args.open:
        webbrowser.open("file://" + os.path.abspath(out))
    return 0


def cmd_show(sessions, args, st):
    s = pick(filtered(sessions, args), args.show)
    buf = io.StringIO()
    print_chat(s, st, buf, show_tools=not args.no_tools)
    text = buf.getvalue()
    if args.no_pager:
        sys.stdout.write(text)
    else:
        from .terminal import pager
        pager(text)
    return 0


def cmd_table(sessions, args, st):
    shown = filtered(sessions, args)
    if not shown:
        print("No session matches that filter.", file=sys.stderr)
        return 1
    if args.limit:
        shown = shown[: args.limit]

    print_table(shown, st, latest_activity(sessions), sys.stdout)

    total, projects = len(sessions), len({s["p"] for s in sessions})
    tail = (f"{len(shown)} of {total} sessions" if len(shown) != total
            else f"{plural(total, 'session', 'sessions')} · "
                 f"{plural(projects, 'project', 'projects')}")
    print(f"\n{st.faint}{tail} · -s <#> to read one{st.reset}")
    return 0


def mem_filtered(memories, args):
    return mem.apply_filters(memories, project=args.project,
                             query=" ".join(args.query) or None,
                             kind=args.type)


def cmd_mem_show(memories, args, st):
    m = mem.pick(mem_filtered(memories, args), args.show)
    buf = io.StringIO()
    print_memory(m, st, buf, path=mem.memory_path(m))
    text = buf.getvalue()
    if args.no_pager:
        sys.stdout.write(text)
    else:
        from .terminal import pager
        pager(text)
    return 0


def cmd_mem_check(memories, sessions, st):
    report = mem.audit(memories, sessions)
    total = print_audit(report, st, sys.stdout)
    if total:
        print(f"{st.faint}{plural(total, 'thing to look at', 'things to look at')} "
              f"across {plural(len(memories), 'memory', 'memories')}.{st.reset}")
        return 1
    print(f"{st.amber}All good: "
          f"{plural(len(memories), 'memory', 'memories')}, "
          f"indexes and links consistent.{st.reset}")
    return 0


def delete_memories(targets, args, st):
    if not targets:
        print("No memories to delete with those criteria.", file=sys.stderr)
        return 0

    print(f"{st.bold}About to delete "
          f"{plural(len(targets), 'memory', 'memories')}:{st.reset}\n")
    total_kb = 0
    for m in targets:
        total_kb += m["k"]
        print(f"  {st.ink}{clip(m['name'], 38):<38}{st.reset} "
              f"{clip(m['ty'], 9):<9} "
              f"{st.grey}{clip(m['p'], 34):<34}{st.reset} "
              f"{st.faint}{fmt_size(m['k']):>9}{st.reset}")
        if m["desc"]:
            print(f"    {st.faint}{clip(m['desc'], 86)}{st.reset}")

    print(f"\n{st.faint}{fmt_size(total_kb)} in total · "
          f"their MEMORY.md lines are removed too{st.reset}")

    if args.dry_run:
        print(f"\n{st.faint}--dry-run: nothing was touched.{st.reset}")
        return 0

    if not args.yes:
        print(f"\n{st.copper}This cannot be undone.{st.reset}")
        if not confirm("Confirm? [y/N] "):
            print("Cancelled.", file=sys.stderr)
            return 1

    done = failed = unlisted = 0
    for m in targets:
        try:
            if mem.delete(m):
                unlisted += 1
            done += 1
        except OSError as e:
            print(f"error: {m['name']}: {e}", file=sys.stderr)
            failed += 1

    extra = f", {unlisted} removed from the index" if unlisted else ""
    print(f"\n{plural(done, 'memory deleted', 'memories deleted')}{extra}.")
    return 1 if failed else 0


def cmd_mem_table(memories, args, st, total):
    if not memories:
        print("No memory matches that filter.", file=sys.stderr)
        return 1
    shown = memories[: args.limit] if args.limit else memories

    print_memories(shown, st, latest_activity(shown), sys.stdout)

    projects = len({m["p"] for m in memories})
    tail = (f"{len(shown)} of {total} memories" if len(shown) != total
            else f"{plural(total, 'memory', 'memories')} · "
                 f"{plural(projects, 'project', 'projects')}")
    print(f"\n{st.faint}{tail} · -m -s <#> to read one{st.reset}")
    return 0


def run_memory(sessions, args, st):
    memories = mem.load_memories(sessions)
    if not memories:
        print("No project has memories yet.", file=sys.stderr)
        return 1

    if args.check:
        return cmd_mem_check(memories, sessions, st)

    if args.delete:
        pool = mem_filtered(memories, args)
        targets, seen = [], set()
        for ref in args.delete:
            m = mem.pick(pool, ref)
            if m["name"] not in seen:
                seen.add(m["name"])
                targets.append(m)
        return delete_memories(targets, args, st)

    if args.show:
        return cmd_mem_show(memories, args, st)

    return cmd_mem_table(mem_filtered(memories, args), args, st, len(memories))


# ──────────────────────────────── permissions ─────────────────────────────

PERM_EDITS = ("allow", "ask", "deny", "remove_rule", "add_dir", "remove_dir",
              "trust", "untrust")


def wants_perms(args):
    return args.perms or any(getattr(args, k) for k in PERM_EDITS)


def known_projects(sessions):
    return {s["p"] for s in sessions} | set(cfg.trusted_projects())


def cmd_perms_list(sessions, args, st):
    view = cfg.overview({s["p"] for s in sessions})
    needles = [n.lower() for n in
               ([os.path.expanduser(args.project).rstrip("/")] if args.project else [])
               + list(args.query)]
    if needles:
        view["projects"] = [p for p in view["projects"]
                            if all(n in p["path"].lower() for n in needles)]
    shown = print_permissions(view, st, sys.stdout, show_all=bool(needles))

    trusted = sum(1 for p in view["projects"] if p["trusted"])
    if needles and not view["projects"]:
        print(f"\n{st.faint}no project matches that filter{st.reset}")
        return 1
    hidden = len(view["projects"]) - shown
    tail = f"{trusted} of {plural(len(view['projects']), 'project', 'projects')} trusted"
    if hidden:
        tail += f" · {hidden} without rules not shown (-p to see one)"
    print(f"\n{st.faint}{tail}{st.reset}")
    return 0


def cmd_perms_edit(sessions, args, st):
    project = None
    if args.project:
        project = cfg.resolve_project(args.project, known_projects(sessions))
    if (args.trust or args.untrust) and not project:
        raise SessionError("--trust and --untrust need a project: -p PATH (-p . for here)")

    changes = []
    for key in cfg.LISTS:
        changes += [("add", key, cfg.check_rule(r)) for r in getattr(args, key) or []]
    changes += [("forget", r.strip()) for r in args.remove_rule or []]
    changes += [("add-dir", cfg.normalize_dir(d)) for d in args.add_dir or []]
    changes += [("remove-dir", cfg.normalize_dir(d)) for d in args.remove_dir or []]

    for d in args.add_dir or []:
        if not os.path.isdir(cfg.normalize_dir(d)):
            print(f"{st.copper}warning: {d} is not a directory (added anyway){st.reset}",
                  file=sys.stderr)

    verb = "would change" if args.dry_run else "changed"
    touched = False

    if changes:
        scope = args.scope or ("local" if project else "user")
        path = cfg.settings_path(scope, project)
        steps = cfg.edit_settings(path, changes, dry_run=args.dry_run)
        if steps:
            touched = True
            print(f"{st.bold}{scope}{st.reset}  {st.faint}{short_home(path)}{st.reset}")
            for step in steps:
                print(f"  {step}")
        else:
            print(f"{st.faint}{short_home(path)}: already like that{st.reset}")

    if args.trust or args.untrust:
        value = bool(args.trust)
        state = short_home(cfg.global_state_path())
        if cfg.set_trust(project, value, dry_run=args.dry_run):
            touched = True
            word = "trusted" if value else "not trusted"
            print(f"{st.bold}trust{st.reset}  {st.faint}{state}{st.reset}")
            print(f"  {short_home(project)} → {word}")
        else:
            print(f"{st.faint}{state}: {short_home(project)} already "
                  f"{'trusted' if value else 'not trusted'}{st.reset}")

    if args.dry_run and touched:
        print(f"\n{st.faint}--dry-run: nothing was touched.{st.reset}")
    elif touched:
        print(f"\n{st.faint}{verb}; Claude Code sessions already open may need "
              f"a restart to see it.{st.reset}")
    return 0


def run_perms(args, st):
    root = default_root()
    sessions = (load_sessions(root=root, use_cache=not args.no_cache)
                if os.path.isdir(root) else [])
    if any(getattr(args, k) for k in PERM_EDITS):
        return cmd_perms_edit(sessions, args, st)
    return cmd_perms_list(sessions, args, st)


# ──────────────────────────────── sharing ─────────────────────────────────

def cmd_share(sessions, args, st):
    import json
    if not args.show:
        raise SessionError("--share needs a session (-s REF): one at a time")
    s = pick(filtered(sessions, args), args.show)
    if s["e"]:
        raise SessionError("that session has no messages, there is nothing to share")
    server = share.server_url(args.server)
    if args.images:
        s = with_images(s)
    images, with_src = count_images(s)
    payload = webpage.build_payload(public_records([s]), [])
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    old = share.entry_for_session(share.load_registry(), s["id"], server)

    err = sys.stderr
    print(f"{st.bold}{s['t'] or 'Untitled session'}{st.reset}", file=err)
    print(f"  {short_home(s['p'])}  ·  {s['u']} yours / {s['a']} from Claude  ·  "
          f"{len(s['c'])} blocks  ·  {fmt_size(size / 1024)}", file=err)
    if with_src:
        print(f"  {plural(with_src, 'image', 'images')} included; they are not "
              f"checked for secrets, look at them first", file=err)
    elif images:
        print(f"  {plural(images, 'image', 'images')} left out (add --images "
              f"to include them)", file=err)
    where = f"updates {old['url']}" if old else f"new link on {server}"
    print(f"  {where}, expires in {args.expire}", file=err)
    for kind, blocks in share.scan_secrets(payload):
        places = ["the title" if b == 0 else f"block {b}" for b in blocks[:8]]
        shown = ", ".join(places) + (" …" if len(blocks) > 8 else "")
        print(f"  {st.copper}warning:{st.reset} possible {kind} in {shown} "
              f"(see it with -s {args.show})", file=err)
    print(f"{st.faint}  Anyone with the link can read the whole conversation, "
          f"tool calls and paths included.{st.reset}", file=err)

    if args.dry_run:
        print("--dry-run: nothing was uploaded.", file=err)
        return 0
    if not args.yes and not confirm("Upload it? [y/N] "):
        print("Nothing was uploaded.", file=err)
        return 1

    try:
        entry, created = share.publish(server, payload, args.expire, s["id"], s["t"])
    except SessionError as e:
        if with_src and "too large" in str(e):
            raise SessionError(f"{e}; try it without --images") from None
        raise
    print(f"{'Shared' if created else 'Updated'} · expires {fmt_expiry(entry)}", file=err)
    print(entry["url"])
    print(f"{st.faint}  {entry['url']}.txt  ·  {entry['url']}.json{st.reset}", file=err)
    return 0


def fmt_expiry(entry):
    exp = entry.get("expires") or "?"
    return exp[:16].replace("T", " ") + " UTC" if len(exp) >= 16 else exp


def run_shares(args, st):
    entries = share.load_registry()
    if args.unshare:
        entry = share.find_entry(entries, args.unshare)
        if args.dry_run:
            print(f"--dry-run: would delete {entry['url']}", file=sys.stderr)
            return 0
        if share.unpublish(entry):
            print(f"Deleted {entry['url']}")
        else:
            print(f"{entry['url']} was already gone; forgotten here too.")
        return 0

    if not entries:
        print("Nothing shared from this machine yet.", file=sys.stderr)
        return 0
    for e in sorted(entries, key=lambda e: e.get("expires") or ""):
        state = (f"{st.copper}expired{st.reset}" if share.is_expired(e)
                 else f"{st.faint}until {fmt_expiry(e)}{st.reset}")
        print(f"{st.bold}{clip(e.get('title') or 'Untitled session', 60)}{st.reset}  {state}")
        print(f"  {e['url']}  {st.faint}session {(e.get('session') or '?')[:8]}{st.reset}")
    print(f"\n{plural(len(entries), 'share', 'shares')} · "
          f"secrets in {short_home(share.registry_path())}")
    return 0


def run(args):
    if args.shares or args.unshare:
        return run_shares(args, Style.from_stream(sys.stdout, args.no_color))

    if wants_perms(args):
        return run_perms(args, Style.from_stream(sys.stdout, args.no_color))

    root = default_root()
    if not os.path.isdir(root):
        print(f"error: {root} does not exist — have you used Claude Code on this machine?",
              file=sys.stderr)
        return 2

    sessions = load_sessions(root=root, use_cache=not args.no_cache)
    if not sessions:
        print("No sessions recorded yet.", file=sys.stderr)
        return 1

    st = Style.from_stream(sys.stdout, args.no_color)

    if args.memory:
        return run_memory(sessions, args, st)

    if args.images and not args.show:
        raise SessionError("--images needs a session (-s REF)")

    if args.share:
        return cmd_share(sessions, args, st)

    if args.json or args.html is not None:
        chosen, memories = export_selection(sessions, args)
        if not chosen:
            print("No session matches that filter.", file=sys.stderr)
            return 1
        if args.json:
            return cmd_json(chosen, memories)
        return cmd_html(chosen, memories, args)

    if args.delete or args.delete_empty:
        targets = delete_targets(filtered(sessions, args), args)
        return delete_sessions(targets, args, st)

    if args.resume:
        print(resume_cmd(pick(filtered(sessions, args), args.resume)))
        return 0

    if args.show:
        return cmd_show(sessions, args, st)

    return cmd_table(sessions, args, st)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except SessionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (BrokenPipeError, KeyboardInterrupt):
        # The pipe is already closed: silence the output flush at exit.
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 130
