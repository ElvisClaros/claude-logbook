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


class TestTable(CliCase):
    def test_lists_the_sessions(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Fix the build", out)
        self.assertIn("3 sessions · 2 projects", out)

    def test_filters_by_text(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("fix the")
        self.assertEqual(code, 0)
        self.assertIn("1 of 3 sessions", out)

    def test_limits_the_count(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-n", "1")
        self.assertIn("1 of 3 sessions", out)

    def test_filter_without_results_exits_with_1(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("nothing-like-this")
        self.assertEqual(code, 1)
        self.assertIn("No session matches", err)

    def test_no_claude_directory_exits_with_2(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/does/not/exist"}):
            code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)

    def test_no_session_exits_with_1(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("No sessions recorded", err)


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
        self.assertIn("3 sessions", err)
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        payload = json.loads(PAYLOAD_RE.findall(html)[0])
        self.assertEqual(len(payload["s"]), 3)
        self.assertEqual(payload["m"], [])

    def test_json_of_one_session(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("-s", "cccccccc", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual([r["id"][:8] for r in data["s"]], ["cccccccc"])

    def test_json_honours_filters_and_limit(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-p", "/home/u/proj", "--json")
        self.assertTrue(all(r["p"] == "/home/u/proj" for r in json.loads(out)["s"]))
        _, out, _ = self.run_cli("-n", "1", "--json")
        self.assertEqual(len(json.loads(out)["s"]), 1)

    def test_export_with_no_match(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("nothing-like-this", "--json")
        self.assertEqual(code, 1)
        self.assertIn("No session matches", err)

    def test_html_of_one_session_gets_its_own_name(self):
        simple_tree(self.root)
        cwd = os.getcwd()
        os.chdir(self.home)
        self.addCleanup(os.chdir, cwd)
        code, _, err = self.run_cli("-s", "aaaaaaaa", "--html")
        self.assertEqual(code, 0)
        self.assertIn("1 sessions", err)
        with open("session-aaaaaaaa.html", encoding="utf-8") as f:
            payload = json.loads(PAYLOAD_RE.findall(f.read())[0])
        self.assertEqual(len(payload["s"]), 1)

    def test_default_html_name_without_show(self):
        simple_tree(self.root)
        cwd = os.getcwd()
        os.chdir(self.home)
        self.addCleanup(os.chdir, cwd)
        self.run_cli("--html")
        self.assertTrue(os.path.exists("sessions.html"))

    def test_memories_follow_the_selection(self):
        simple_tree(self.root)
        memory_tree(self.root)
        _, out, _ = self.run_cli("--json")
        everything = json.loads(out)["m"]
        _, out, _ = self.run_cli("-p", "/home/u/proj", "--json")
        some = json.loads(out)["m"]
        self.assertTrue(everything)
        self.assertTrue(all(m["p"] == "/home/u/proj" for m in some))
        self.assertLess(len(some), len(everything))

    def test_a_single_session_goes_without_memories(self):
        simple_tree(self.root)
        memory_tree(self.root)
        _, out, _ = self.run_cli("-s", "aaaaaaaa", "--json")
        data = json.loads(out)
        self.assertEqual(len(data["s"]), 1)
        self.assertEqual(data["m"], [])

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
        self.assertIn("why does the build fail?", out)

    def test_show_by_uuid_prefix(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-s", "cccccccc", "--no-pager")
        self.assertIn("hello", out)

    def test_show_honours_the_previous_filter(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-p", "/home/u/other", "-s", "1", "--no-pager")
        self.assertIn("hello", out)

    def test_missing_reference_exits_with_2(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("-s", "99")
        self.assertEqual(code, 2)
        self.assertIn("out of range", err)

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
        before = self.paths()
        code, out, _ = self.run_cli("--delete-empty", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("nothing was touched", out)
        self.assertEqual(self.paths(), before)

    def test_deletes_the_empty_ones(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 session deleted", out)
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
        self.assertIn("1 session deleted", out)

    def test_deleted_one_does_not_come_back_from_cache(self):
        simple_tree(self.root)
        self.run_cli()                       # fills the cache
        self.run_cli("--delete-empty", "-y")
        _, out, _ = self.run_cli()
        self.assertIn("2 sessions", out)
        self.assertNotIn("bbbbbbbb", out)

    def test_filter_limits_what_is_deleted(self):
        write_session(self.root, "-home-u-other", "ffffffff-0000-0000-0000-000000000006",
                      [{"type": "system", "timestamp": ts(0)}])
        simple_tree(self.root)
        code, out, _ = self.run_cli("-p", "/home/u/proj", "--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 session deleted", out)
        self.assertTrue(os.path.exists(os.path.join(
            self.root, "-home-u-other", "ffffffff-0000-0000-0000-000000000006.jsonl")))

    def test_nothing_to_delete_warns(self):
        write_session(self.root, "-p", "aaaaaaaa-0000-0000-0000-000000000001",
                      [user("hello", at=ts(0))])
        code, _, err = self.run_cli("--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("No sessions to delete", err)


class TestParser(unittest.TestCase):
    def test_html_without_value_uses_the_default_name(self):
        args = cli.build_parser().parse_args(["--html"])
        self.assertEqual(cli.html_path([{"id": "abcdef0123"}], args), cli.DEFAULT_HTML)
        args = cli.build_parser().parse_args(["--html", "-s", "1"])
        self.assertEqual(cli.html_path([{"id": "abcdef0123"}], args),
                         "session-abcdef01.html")

    def test_html_with_value(self):
        self.assertEqual(cli.build_parser().parse_args(["--html", "x.html"]).html,
                         "x.html")

    def test_query_joins_the_words(self):
        args = cli.build_parser().parse_args(["two", "words"])
        self.assertEqual(args.query, ["two", "words"])


class TestMemory(CliCase):
    def test_table(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, out, _ = self.run_cli("-m")
        self.assertEqual(code, 0)
        self.assertIn("deploy-docker", out)
        self.assertIn("4 memories", out)

    def test_no_memories_warns(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("-m")
        self.assertEqual(code, 1)
        self.assertIn("memories", err)

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
        self.assertIn("Deployed with", out)
        self.assertIn("deploy-docker", out)

    def test_show_warns_if_not_indexed(self):
        simple_tree(self.root)
        memory_tree(self.root)
        _, out, _ = self.run_cli("-m", "-s", "stray", "--no-pager")
        self.assertIn("MEMORY.md", out)

    def test_check_lists_the_problems(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, out, _ = self.run_cli("-m", "--check")
        self.assertEqual(code, 1)  # there are things to look at
        self.assertIn("no MEMORY.md", out)
        self.assertIn("missing", out)

    def test_clean_check_exits_zero(self):
        simple_tree(self.root)
        write_memory(self.root, "-home-u-proj", "lone", body="no links")
        from .fixtures import write_index
        write_index(self.root, "-home-u-proj", ["lone"])
        code, out, _ = self.run_cli("-m", "--check")
        self.assertEqual(code, 0)
        self.assertIn("All good", out)

    def test_dry_run_deletion_touches_nothing(self):
        simple_tree(self.root)
        memory_tree(self.root)
        path = os.path.join(self.root, "-home-u-proj", "memory",
                            "deploy-docker.md")
        code, out, _ = self.run_cli("-m", "-D", "deploy", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("nothing was touched", out)
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
        self.assertIn("removed from the index", out)

    def test_unconfirmed_deletion_cancels(self):
        simple_tree(self.root)
        memory_tree(self.root)
        path = os.path.join(self.root, "-home-u-proj", "memory",
                            "deploy-docker.md")
        with unittest.mock.patch.object(cli, "confirm", return_value=False):
            code, _, err = self.run_cli("-m", "-D", "deploy")
        self.assertEqual(code, 1)
        self.assertIn("Cancelled", err)
        self.assertTrue(os.path.exists(path))

    def test_missing_reference(self):
        simple_tree(self.root)
        memory_tree(self.root)
        code, _, err = self.run_cli("-m", "-s", "no-such-memory")
        self.assertEqual(code, 2)
        self.assertIn("no memory matches", err)

    def test_html_embeds_the_memories(self):
        simple_tree(self.root)
        memory_tree(self.root)
        out_path = os.path.join(self.home, "s.html")
        code, _, err = self.run_cli("--html", out_path)
        self.assertEqual(code, 0)
        self.assertIn("4 memories", err)
        with open(out_path, encoding="utf-8") as f:
            payload = json.loads(PAYLOAD_RE.findall(f.read())[0])
        self.assertEqual(len(payload["m"]), 4)
        self.assertIn("deploy-docker", {m["name"] for m in payload["m"]})


if __name__ == "__main__":
    unittest.main()
