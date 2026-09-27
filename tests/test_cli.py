import io
import json
import os
import re
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout

from claude_logbook import cli

from .fixtures import (
    memory_tree, simple_tree, ts, user, write_memory, write_session,
)

PAYLOAD_RE = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>', re.S)


class CliCase(unittest.TestCase):
    """Each test runs against a fake ~/.claude and cache."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = self._tmp.name
        self.root = os.path.join(self.home, ".claude", "projects")
        os.makedirs(self.root)
        env = unittest.mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": os.path.join(self.home, ".claude"),
            "XDG_CACHE_HOME": os.path.join(self.home, "cache"),
            "NO_COLOR": "1",
        })
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class TestTabla(CliCase):
    def test_lists_the_sessions(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Arreglar el build", out)
        self.assertIn("3 sesiones · 2 proyectos", out)

    def test_filters_by_text(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("arreglar")
        self.assertEqual(code, 0)
        self.assertIn("1 de 3 sesiones", out)

    def test_limits_the_count(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-n", "1")
        self.assertIn("1 de 3 sesiones", out)

    def test_filter_without_results_exits_with_1(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("no-existe-esto")
        self.assertEqual(code, 1)
        self.assertIn("Ninguna sesión coincide", err)

    def test_no_claude_directory_exits_with_2(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/no/existe"}):
            code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("no existe", err)

    def test_no_session_exits_with_1(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("No hay ninguna sesión", err)


class TestExport(CliCase):
    def test_json(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(len(data["s"]), 3)
        self.assertEqual(data["m"], [])
        self.assertNotIn("project_dir", data["s"][0])

    def test_html(self):
        simple_tree(self.root)
        out_path = os.path.join(self.home, "s.html")
        code, _, err = self.run_cli("--html", out_path)
        self.assertEqual(code, 0)
        self.assertIn("3 sesiones", err)
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        payload = json.loads(PAYLOAD_RE.findall(html)[0])
        self.assertEqual(len(payload["s"]), 3)
        self.assertEqual(payload["m"], [])

    def test_html_leaves_stdout_alone(self):
        # The summary goes to stderr so `--html /dev/stdout` keeps working.
        simple_tree(self.root)
        _, out, _ = self.run_cli("--html", os.path.join(self.home, "s.html"))
        self.assertEqual(out, "")


class TestReading(CliCase):
    def test_show_by_index(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("-s", "1", "--no-pager")
        self.assertEqual(code, 0)
        self.assertIn("¿por qué falla el build?", out)

    def test_show_by_uuid_prefix(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-s", "cccccccc", "--no-pager")
        self.assertIn("hola", out)

    def test_show_honours_the_previous_filter(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-p", "/home/u/otro", "-s", "1", "--no-pager")
        self.assertIn("hola", out)

    def test_missing_reference_exits_with_2(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("-s", "99")
        self.assertEqual(code, 2)
        self.assertIn("fuera de rango", err)

    def test_resume_prints_the_command(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("-r", "1")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(),
                         "cd /home/u/proj && claude --resume "
                         "aaaaaaaa-0000-0000-0000-000000000001")


class TestDeletion(CliCase):
    def paths(self):
        return sorted(os.listdir(os.path.join(self.root, "-home-u-proj")))

    def test_dry_run_touches_nothing(self):
        simple_tree(self.root)
        antes = self.paths()
        code, out, _ = self.run_cli("--delete-empty", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("no se tocó nada", out)
        self.assertEqual(self.paths(), antes)

    def test_deletes_the_empty_ones(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 sesión borrada", out)
        self.assertEqual(self.paths(),
                         ["aaaaaaaa-0000-0000-0000-000000000001.jsonl"])

    def test_deletes_a_single_one_by_prefix(self):
        simple_tree(self.root)
        code, _, _ = self.run_cli("-D", "aaaaaaaa", "-y")
        self.assertEqual(code, 0)
        self.assertEqual(self.paths(),
                         ["bbbbbbbb-0000-0000-0000-000000000002.jsonl"])

    def test_no_repeat_if_requested_twice(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("-D", "aaaaaaaa", "1", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 sesión borrada", out)

    def test_deleted_one_does_not_come_back_from_cache(self):
        simple_tree(self.root)
        self.run_cli()                       # fills the cache
        self.run_cli("--delete-empty", "-y")
        _, out, _ = self.run_cli()
        self.assertIn("2 sesiones", out)
        self.assertNotIn("bbbbbbbb", out)

    def test_filter_limits_what_is_deleted(self):
        write_session(self.root, "-home-u-otro", "ffffffff-0000-0000-0000-000000000006",
                      [{"type": "system", "timestamp": ts(0)}])
        simple_tree(self.root)
        code, out, _ = self.run_cli("-p", "/home/u/proj", "--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 sesión borrada", out)
        self.assertTrue(os.path.exists(os.path.join(
            self.root, "-home-u-otro", "ffffffff-0000-0000-0000-000000000006.jsonl")))

    def test_nothing_to_delete_warns(self):
        write_session(self.root, "-p", "aaaaaaaa-0000-0000-0000-000000000001",
                      [user("hola", at=ts(0))])
        code, _, err = self.run_cli("--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("No hay sesiones que borrar", err)


class TestParser(unittest.TestCase):
    def test_html_without_value_uses_the_default_name(self):
        args = cli.build_parser().parse_args(["--html"])
        self.assertEqual(args.html, cli.DEFAULT_HTML)

    def test_html_con_valor(self):
        self.assertEqual(cli.build_parser().parse_args(["--html", "x.html"]).html,
                         "x.html")

    def test_query_joins_the_words(self):
        args = cli.build_parser().parse_args(["dos", "palabras"])
        self.assertEqual(args.query, ["dos", "palabras"])


class TestMemory(CliCase):
    def test_tabla(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, out, _ = self.run_cli("-m")
        self.assertEqual(code, 0)
        self.assertIn("deploy-docker", out)
        self.assertIn("4 memorias", out)

    def test_no_memories_warns(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("-m")
        self.assertEqual(code, 1)
        self.assertIn("memorias", err)

    def test_filters_by_type(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, out, _ = self.run_cli("-m", "--type", "reference")
        self.assertEqual(code, 0)
        self.assertIn("roles-db", out)
        self.assertNotIn("deploy-docker", out)

    def test_query_searches_the_body(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, out, _ = self.run_cli("-m", "make up")
        self.assertEqual(code, 0)
        self.assertIn("deploy-docker", out)
        self.assertNotIn("roles-db", out)

    def test_show_by_name(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, out, _ = self.run_cli("-m", "-s", "deploy", "--no-pager")
        self.assertEqual(code, 0)
        self.assertIn("Se despliega con", out)
        self.assertIn("deploy-docker", out)

    def test_show_warns_if_not_indexed(self):
        simple_tree(self.root)
        memory_tree(self.root)
        _, out, _ = self.run_cli("-m", "-s", "suelta", "--no-pager")
        self.assertIn("MEMORY.md", out)

    def test_check_lists_the_problems(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, out, _ = self.run_cli("-m", "--check")
        self.assertEqual(code, 1)  # there are things to look at
        self.assertIn("sin MEMORY.md", out)
        self.assertIn("no-existe", out)

    def test_clean_check_exits_zero(self):
        simple_tree(self.root)
        write_memory(self.root, "-home-u-proj", "sola", body="sin enlaces")
        from .fixtures import write_index
        write_index(self.root, "-home-u-proj", ["sola"])
        code, out, _ = self.run_cli("-m", "--check")
        self.assertEqual(code, 0)
        self.assertIn("Todo en orden", out)

    def test_dry_run_deletion_touches_nothing(self):
        simple_tree(self.root)
        memory_tree(self.root)
        path = os.path.join(self.root, "-home-u-proj", "memory",
                            "deploy-docker.md")
        code, out, _ = self.run_cli("-m", "-D", "deploy", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("no se tocó nada", out)
        self.assertTrue(os.path.exists(path))

    def test_deletes_and_unindexes(self):
        simple_tree(self.root)
        memory_tree(self.root)
        path = os.path.join(self.root, "-home-u-proj", "memory",
                            "deploy-docker.md")
        code, out, _ = self.run_cli("-m", "-D", "deploy", "-y")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(path))
        with open(os.path.join(self.root, "-home-u-proj", "memory",
                               "MEMORY.md"), encoding="utf-8") as f:
            index = f.read()
        self.assertNotIn("deploy-docker.md", index)
        self.assertIn("roles-db.md", index)
        self.assertIn("sacadas del índice", out)

    def test_unconfirmed_deletion_cancels(self):
        simple_tree(self.root)
        memory_tree(self.root)
        path = os.path.join(self.root, "-home-u-proj", "memory",
                            "deploy-docker.md")
        with unittest.mock.patch.object(cli, "confirm", return_value=False):
            code, _, err = self.run_cli("-m", "-D", "deploy")
        self.assertEqual(code, 1)
        self.assertIn("Cancelado", err)
        self.assertTrue(os.path.exists(path))

    def test_missing_reference(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, _, err = self.run_cli("-m", "-s", "no-existe-nada")
        self.assertEqual(code, 2)
        self.assertIn("ninguna memoria", err)

    def test_html_embeds_the_memories(self):
        simple_tree(self.root)
        memory_tree(self.root)
        out_path = os.path.join(self.home, "s.html")
        code, _, err = self.run_cli("--html", out_path)
        self.assertEqual(code, 0)
        self.assertIn("4 memorias", err)
        with open(out_path, encoding="utf-8") as f:
            payload = json.loads(PAYLOAD_RE.findall(f.read())[0])
        self.assertEqual(len(payload["m"]), 4)
        self.assertIn("deploy-docker", {m["name"] for m in payload["m"]})


if __name__ == "__main__":
    unittest.main()
