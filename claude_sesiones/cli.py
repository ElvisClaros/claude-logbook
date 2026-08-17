"""Interfaz de línea de comandos."""

import argparse
import io
import os
import sys
import textwrap
import time
import webbrowser

from . import __version__
from .sessions import (
    SessionError, apply_filters, default_root, drop_from_cache, latest_activity,
    load_sessions, pick, public_records, session_path,
)
from .terminal import (
    Style, clip, fmt_date, fmt_size, plural, print_audit, print_chat,
    print_memories, print_memory, print_table, resume_cmd,
)
from . import memory as mem
from . import webpage

DEFAULT_HTML = "sesiones.html"

# Una sesión escrita hace menos de esto puede estar abierta en otra terminal.
RECENT_SECONDS = 300

EPILOG = """\
ejemplos:
  claude-sesiones                     tabla de todas las sesiones
  claude-sesiones docker              filtra por título, ruta o rama
  claude-sesiones -s 3                lee el chat nº 3 de la tabla
  claude-sesiones -s 5d10f1ee         lo mismo, por prefijo de UUID
  claude-sesiones -g "port already"   busca dentro de las conversaciones
  claude-sesiones -r 3                comando para reanudar la nº 3
  eval "$(claude-sesiones -r 3)"      reanudarla directamente
  claude-sesiones --html --open       genera sesiones.html y lo abre

el nº es la posición en la tabla que estás viendo, así que si filtraste
hay que repetir el filtro para leer esa fila:

  claude-sesiones docker              muestra 3 resultados
  claude-sesiones docker -s 2         lee el 2º de esos tres

borrado (irreversible; pregunta antes, salvo con -y):
  claude-sesiones --delete-empty --dry-run   qué borraría
  claude-sesiones --delete-empty             borra las vacías
  claude-sesiones -D 101 -D e0a4300e         borra sesiones puntuales
  claude-sesiones -p /tmp --delete-empty     solo las vacías de ese proyecto

memoria de los proyectos (-m cambia de sesiones a memorias y reusa los mismos
verbos: filtro, -s para leer, -D para borrar):
  claude-sesiones -m                  tabla de memorias
  claude-sesiones -m docker           busca en nombre, descripción y cuerpo
  claude-sesiones -m -s 3             lee la memoria nº 3
  claude-sesiones -m -s deadlock      lo mismo, por nombre
  claude-sesiones -m --check          audita índices, enlaces y orígenes
  claude-sesiones -m -D 3             la borra y la saca de MEMORY.md
"""


def build_parser():
    ap = argparse.ArgumentParser(
        prog="claude-sesiones",
        description="Explorador de sesiones de Claude Code para la terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(EPILOG),
    )
    ap.add_argument("query", nargs="*", help="texto a buscar en título, ruta o rama")
    ap.add_argument("-s", "--show", metavar="REF",
                    help="muestra el chat: índice de la tabla o prefijo de UUID")
    ap.add_argument("-r", "--resume", metavar="REF",
                    help="imprime el comando para reanudar esa sesión")
    ap.add_argument("-g", "--grep", metavar="TEXTO",
                    help="filtra por contenido de las conversaciones")
    ap.add_argument("-p", "--project", metavar="RUTA",
                    help="filtra por ruta del proyecto")
    ap.add_argument("-n", "--limit", type=int, metavar="N",
                    help="muestra solo las N más recientes")
    ap.add_argument("-E", "--hide-empty", action="store_true",
                    help="oculta las sesiones sin mensajes")
    ap.add_argument("--no-tools", action="store_true",
                    help="en el chat, oculta las llamadas a herramientas")
    ap.add_argument("--no-pager", action="store_true",
                    help="no usa $PAGER para el chat")
    ap.add_argument("--no-color", action="store_true", help="salida sin color")

    recuerdos = ap.add_argument_group("memoria de los proyectos")
    recuerdos.add_argument("-m", "--memory", action="store_true",
                           help="trabaja sobre las memorias en vez de las sesiones")
    recuerdos.add_argument("--type", metavar="TIPO", choices=mem.TYPES,
                           help="filtra por tipo: " + " | ".join(mem.TYPES))
    recuerdos.add_argument("--check", action="store_true",
                           help="audita índices, enlaces y sesiones de origen")

    salida = ap.add_argument_group("exportar")
    salida.add_argument("--json", action="store_true",
                        help="vuelca todas las sesiones en JSON")
    salida.add_argument("--html", nargs="?", const=DEFAULT_HTML, metavar="ARCHIVO",
                        help=f"genera una página autocontenida (por defecto {DEFAULT_HTML})")
    salida.add_argument("--template", metavar="ARCHIVO",
                        help="usa otro template para --html")
    salida.add_argument("--open", action="store_true",
                        help="abre en el navegador lo que genere --html")

    borrar = ap.add_argument_group("borrado")
    borrar.add_argument("-D", "--delete", metavar="REF", nargs="+",
                        help="borra esas sesiones (índice o prefijo de UUID)")
    borrar.add_argument("--delete-empty", action="store_true",
                        help="borra todas las sesiones sin mensajes")
    borrar.add_argument("-y", "--yes", action="store_true",
                        help="no pregunta antes de borrar")
    borrar.add_argument("--dry-run", action="store_true",
                        help="muestra qué se borraría y no toca nada")

    ap.add_argument("--no-cache", action="store_true",
                    help="ignora el caché y re-parsea todo")
    ap.add_argument("--version", action="version",
                    version=f"claude-sesiones {__version__}")
    return ap


def filtered(sessions, args):
    return apply_filters(
        sessions,
        project=args.project,
        grep=args.grep,
        query=" ".join(args.query) if args.query else None,
        hide_empty=args.hide_empty,
    )


# ──────────────────────────────── borrado ────────────────────────────────

def confirm(question):
    """Pregunta s/N. Sin terminal no hay confirmación posible: devuelve False."""
    try:
        tty = open("/dev/tty")
    except OSError:
        return False
    try:
        sys.stderr.write(question)
        sys.stderr.flush()
        return tty.readline().strip().lower() in ("s", "si", "sí", "y", "yes")
    except (OSError, KeyboardInterrupt):
        return False
    finally:
        tty.close()


def delete_sessions(targets, args, st):
    """Borra las sesiones dadas. Devuelve el código de salida."""
    if not targets:
        print("No hay sesiones que borrar con ese criterio.", file=sys.stderr)
        return 0

    print(f"{st.bold}Se van a borrar "
          f"{plural(len(targets), 'sesión', 'sesiones')}:{st.reset}\n")

    total_kb = 0
    recent = []
    for s in targets:
        path = session_path(s)
        total_kb += s["k"]
        title = s["t"] or "sesión abierta sin mensajes"
        flag = ""
        try:
            if time.time() - os.stat(path).st_mtime < RECENT_SECONDS:
                recent.append(s)
                flag = f" {st.copper}← modificada hace menos de 5 min{st.reset}"
        except OSError:
            flag = f" {st.copper}← ya no existe{st.reset}"
        print(f"  {st.faint}{s['id'][:8]}{st.reset} {clip(title, 52):<52} "
              f"{st.grey}{clip(s['p'], 34):<34}{st.reset} "
              f"{fmt_date(s['l'])} {st.faint}{s['k']:>7.1f} KB{st.reset}{flag}")

    print(f"\n{st.faint}{fmt_size(total_kb)} en total{st.reset}")

    if recent:
        verbo = "se escribió" if len(recent) == 1 else "se escribieron"
        print(f"\n{st.copper}Ojo: {len(recent)} de estas {verbo} hace menos de "
              f"5 minutos. Si es una sesión abierta ahora mismo, Claude Code la "
              f"sigue usando y va a volver a escribirla al cerrarse.{st.reset}")

    if args.dry_run:
        print(f"\n{st.faint}--dry-run: no se tocó nada.{st.reset}")
        return 0

    if not args.yes:
        print(f"\n{st.copper}Esto no se puede deshacer.{st.reset}")
        if not confirm("¿Confirmás? [s/N] "):
            print("Cancelado.", file=sys.stderr)
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

    print(f"\n{plural(done, 'sesión borrada', 'sesiones borradas')}.")
    return 1 if failed else 0


def delete_targets(pool, args):
    """Las sesiones que pidió borrar, sin repetidas y en el orden pedido."""
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


# ──────────────────────────────── comandos ────────────────────────────────

def cmd_json(sessions):
    import json
    payload = webpage.build_payload(
        public_records(sessions),
        mem.public_records(mem.load_memories(sessions)))
    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def cmd_html(sessions, args):
    out = args.html
    memories = mem.public_records(mem.load_memories(sessions))
    stats = webpage.write(public_records(sessions), out, memories=memories,
                          template=webpage.template_text(args.template))
    print(f"{stats['sesiones']} sesiones · {stats['proyectos']} proyectos · "
          f"{stats['mensajes']} mensajes · {stats['bloques']} bloques "
          f"de transcripción · {stats['memorias']} memorias → {out}",
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
        print("Ninguna sesión coincide con ese filtro.", file=sys.stderr)
        return 1
    if args.limit:
        shown = shown[: args.limit]

    print_table(shown, st, latest_activity(sessions), sys.stdout)

    total, projects = len(sessions), len({s["p"] for s in sessions})
    tail = (f"{len(shown)} de {total} sesiones" if len(shown) != total
            else f"{plural(total, 'sesión', 'sesiones')} · "
                 f"{plural(projects, 'proyecto', 'proyectos')}")
    print(f"\n{st.faint}{tail} · -s <nº> para leer una{st.reset}")
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
        print(f"{st.faint}{plural(total, 'cosa para mirar', 'cosas para mirar')} "
              f"en {plural(len(memories), 'memoria', 'memorias')}.{st.reset}")
        return 1
    print(f"{st.amber}Todo en orden: "
          f"{plural(len(memories), 'memoria', 'memorias')}, "
          f"índices y enlaces consistentes.{st.reset}")
    return 0


def delete_memories(targets, args, st):
    if not targets:
        print("No hay memorias que borrar con ese criterio.", file=sys.stderr)
        return 0

    print(f"{st.bold}Se van a borrar "
          f"{plural(len(targets), 'memoria', 'memorias')}:{st.reset}\n")
    total_kb = 0
    for m in targets:
        total_kb += m["k"]
        print(f"  {st.ink}{clip(m['name'], 38):<38}{st.reset} "
              f"{clip(m['ty'], 9):<9} "
              f"{st.grey}{clip(m['p'], 34):<34}{st.reset} "
              f"{st.faint}{fmt_size(m['k']):>9}{st.reset}")
        if m["desc"]:
            print(f"    {st.faint}{clip(m['desc'], 86)}{st.reset}")

    print(f"\n{st.faint}{fmt_size(total_kb)} en total · "
          f"también se quita su línea de MEMORY.md{st.reset}")

    if args.dry_run:
        print(f"\n{st.faint}--dry-run: no se tocó nada.{st.reset}")
        return 0

    if not args.yes:
        print(f"\n{st.copper}Esto no se puede deshacer.{st.reset}")
        if not confirm("¿Confirmás? [s/N] "):
            print("Cancelado.", file=sys.stderr)
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

    extra = f", {unlisted} sacadas del índice" if unlisted else ""
    print(f"\n{plural(done, 'memoria borrada', 'memorias borradas')}{extra}.")
    return 1 if failed else 0


def cmd_mem_table(memories, args, st, total):
    if not memories:
        print("Ninguna memoria coincide con ese filtro.", file=sys.stderr)
        return 1
    shown = memories[: args.limit] if args.limit else memories

    print_memories(shown, st, latest_activity(shown), sys.stdout)

    projects = len({m["p"] for m in memories})
    tail = (f"{len(shown)} de {total} memorias" if len(shown) != total
            else f"{plural(total, 'memoria', 'memorias')} · "
                 f"{plural(projects, 'proyecto', 'proyectos')}")
    print(f"\n{st.faint}{tail} · -m -s <nº> para leer una{st.reset}")
    return 0


def run_memory(sessions, args, st):
    memories = mem.load_memories(sessions)
    if not memories:
        print("Ningún proyecto tiene memorias todavía.", file=sys.stderr)
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


def run(args):
    root = default_root()
    if not os.path.isdir(root):
        print(f"error: no existe {root} — ¿usaste Claude Code en esta máquina?",
              file=sys.stderr)
        return 2

    sessions = load_sessions(root=root, use_cache=not args.no_cache)
    if not sessions:
        print("No hay ninguna sesión registrada todavía.", file=sys.stderr)
        return 1

    st = Style.from_stream(sys.stdout, args.no_color)

    if args.memory:
        return run_memory(sessions, args, st)

    if args.json:
        return cmd_json(sessions)
    if args.html:
        return cmd_html(sessions, args)

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
        # El pipe ya está cerrado: silenciamos el flush de salida al terminar.
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 130
