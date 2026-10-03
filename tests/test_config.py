import json
import os
import stat

from claude_logbook import config as cfg
from claude_logbook.sessions import SessionError

from .fixtures import simple_tree
from .test_cli import CliCase


class ConfigCase(CliCase):
    """A fake ~/.claude (with its .claude.json) plus a real project directory."""

    def setUp(self):
        super().setUp()
        self.claude = os.path.join(self.home, ".claude")
        self.state = os.path.join(self.claude, ".claude.json")
        self.proj = os.path.join(self.home, "work", "proj")
        os.makedirs(self.proj)

    def write(self, path, data, newline=True):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2) + ("\n" if newline else ""))

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def local(self):
        return os.path.join(self.proj, ".claude", "settings.local.json")


class TestLocations(ConfigCase):
    def test_paths_follow_claude_config_dir(self):
        self.assertEqual(cfg.global_state_path(), self.state)
        self.assertEqual(cfg.settings_path("user"),
                         os.path.join(self.claude, "settings.json"))
        self.assertEqual(cfg.settings_path("project", "/x"), "/x/.claude/settings.json")
        self.assertEqual(cfg.settings_path("local", "/x"),
                         "/x/.claude/settings.local.json")

    def test_project_scopes_need_a_project(self):
        with self.assertRaises(SessionError):
            cfg.settings_path("local")


class TestApplyRules(ConfigCase):
    def test_adds_without_duplicates(self):
        data = {"permissions": {"allow": ["Read"]}}
        steps = cfg.apply_rules(data, [("add", "allow", "Read"),
                                       ("add", "allow", "Bash(ls)")])
        self.assertEqual(data["permissions"]["allow"], ["Read", "Bash(ls)"])
        self.assertEqual(steps, ["allow Bash(ls)"])

    def test_a_rule_lives_in_one_list(self):
        data = {"permissions": {"allow": ["WebFetch", "Read"]}}
        steps = cfg.apply_rules(data, [("add", "deny", "WebFetch")])
        self.assertEqual(data["permissions"], {"allow": ["Read"], "deny": ["WebFetch"]})
        self.assertIn("WebFetch leaves allow", steps)

    def test_forget_drops_empty_lists_and_object(self):
        data = {"model": "x", "permissions": {"ask": ["Edit"]}}
        cfg.apply_rules(data, [("forget", "Edit")])
        self.assertEqual(data, {"model": "x"})

    def test_keeps_unknown_keys(self):
        data = {"permissions": {"defaultMode": "acceptEdits", "allow": ["A"]}}
        cfg.apply_rules(data, [("forget", "A")])
        self.assertEqual(data, {"permissions": {"defaultMode": "acceptEdits"}})

    def test_directories(self):
        data = {"permissions": {"additionalDirectories": ["~/shared"]}}
        home_shared = cfg.normalize_dir("~/shared")
        steps = cfg.apply_rules(data, [("add-dir", "/data"),
                                       ("remove-dir", home_shared)])
        self.assertEqual(data["permissions"]["additionalDirectories"], ["/data"])
        self.assertEqual(len(steps), 2)

    def test_nothing_to_do(self):
        data = {}
        self.assertEqual(cfg.apply_rules(data, [("forget", "X")]), [])
        self.assertEqual(data, {})


class TestRules(ConfigCase):
    def test_accepts_the_usual_shapes(self):
        for r in ("WebFetch", "Bash(npm test:*)", "Read(./.env)",
                  "mcp__github__create_issue", "WebFetch(domain:example.com)"):
            self.assertEqual(cfg.check_rule(r), r)

    def test_rejects_junk(self):
        for r in ("", "Bash(foo", "(x)", "rm -rf /"):
            with self.assertRaises(SessionError):
                cfg.check_rule(r)


class TestFiles(ConfigCase):
    def test_keeps_mode_and_missing_newline(self):
        self.write(self.state, {"oauthAccount": {"a": 1}, "projects": {}}, newline=False)
        os.chmod(self.state, 0o600)
        cfg.set_trust(self.proj, True)
        with open(self.state, encoding="utf-8") as fh:
            text = fh.read()
        self.assertFalse(text.endswith("\n"))
        self.assertEqual(stat.S_IMODE(os.stat(self.state).st_mode), 0o600)
        data = json.loads(text)
        self.assertEqual(data["oauthAccount"], {"a": 1})
        self.assertTrue(data["projects"][self.proj]["hasTrustDialogAccepted"])

    def test_broken_json_is_not_overwritten(self):
        os.makedirs(os.path.dirname(self.local()))
        with open(self.local(), "w") as fh:
            fh.write("{ nope")
        with self.assertRaises(SessionError):
            cfg.edit_settings(self.local(), [("add", "allow", "Read")])
        with open(self.local()) as fh:
            self.assertEqual(fh.read(), "{ nope")

    def test_no_temporary_files_left(self):
        cfg.edit_settings(self.local(), [("add", "allow", "Read")])
        self.assertEqual(os.listdir(os.path.dirname(self.local())),
                         ["settings.local.json"])


class TestTrust(ConfigCase):
    def test_trust_keeps_the_rest_of_the_entry(self):
        self.write(self.state, {"projects": {self.proj: {
            "allowedTools": [], "hasTrustDialogAccepted": False}}})
        self.assertTrue(cfg.set_trust(self.proj, True))
        self.assertEqual(self.read(self.state)["projects"][self.proj],
                         {"allowedTools": [], "hasTrustDialogAccepted": True})
        self.assertFalse(cfg.set_trust(self.proj, True))

    def test_untrust_of_unknown_project_writes_nothing(self):
        self.assertFalse(cfg.set_trust(self.proj, False))
        self.assertFalse(os.path.exists(self.state))

    def test_dry_run_writes_nothing(self):
        self.write(self.state, {"projects": {}})
        self.assertTrue(cfg.set_trust(self.proj, True, dry_run=True))
        self.assertEqual(self.read(self.state), {"projects": {}})

    def test_trusted_parent(self):
        trust = {"/a": True, "/a/b": False}
        self.assertEqual(cfg.trusted_parent("/a/b/c", trust), "/a")
        self.assertIsNone(cfg.trusted_parent("/z", trust))


class TestResolveProject(ConfigCase):
    def test_existing_directory(self):
        self.assertEqual(cfg.resolve_project(self.proj + "/", set()), self.proj)

    def test_unique_known_project(self):
        self.assertEqual(cfg.resolve_project("bar", {"/gone/foobar", "/x"}),
                         "/gone/foobar")

    def test_ambiguous_or_unknown(self):
        with self.assertRaises(SessionError):
            cfg.resolve_project("o", {"/foo", "/boo"})
        with self.assertRaises(SessionError):
            cfg.resolve_project("nothing-like-it", {"/foo"})


class TestCli(ConfigCase):
    def test_allow_goes_to_local_settings_of_the_project(self):
        code, out, _ = self.run_cli("--allow", "Bash(make:*)", "Read", "-p", self.proj)
        self.assertEqual(code, 0)
        self.assertEqual(self.read(self.local()),
                         {"permissions": {"allow": ["Bash(make:*)", "Read"]}})
        self.assertIn("allow Bash(make:*)", out)

    def test_without_project_goes_to_user_settings(self):
        self.write(os.path.join(self.claude, "settings.json"), {"theme": "dark"})
        self.run_cli("--deny", "WebFetch")
        self.assertEqual(self.read(os.path.join(self.claude, "settings.json")),
                         {"theme": "dark", "permissions": {"deny": ["WebFetch"]}})

    def test_project_scope(self):
        self.run_cli("--ask", "Edit", "--scope", "project", "-p", self.proj)
        self.assertEqual(
            self.read(os.path.join(self.proj, ".claude", "settings.json")),
            {"permissions": {"ask": ["Edit"]}})

    def test_project_scope_without_project_fails(self):
        code, _, err = self.run_cli("--ask", "Edit", "--scope", "local")
        self.assertEqual(code, 2)
        self.assertIn("needs a project", err)

    def test_dirs_and_remove_rule(self):
        self.run_cli("--allow", "Read", "--add-dir", self.home, "-p", self.proj)
        self.run_cli("--remove-rule", "Read", "--remove-dir", self.home, "-p", self.proj)
        self.assertEqual(self.read(self.local()), {})

    def test_dry_run_touches_nothing(self):
        code, out, _ = self.run_cli("--allow", "Read", "--trust", "-p", self.proj,
                                    "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("nothing was touched", out)
        self.assertFalse(os.path.exists(self.local()))
        self.assertFalse(os.path.exists(self.state))

    def test_trust_and_untrust(self):
        self.write(self.state, {"numStartups": 3})
        self.run_cli("--trust", "-p", self.proj)
        self.assertTrue(self.read(self.state)["projects"][self.proj][cfg.TRUST_KEY])
        _, out, _ = self.run_cli("--trust", "-p", self.proj)
        self.assertIn("already trusted", out)
        self.run_cli("--untrust", "-p", self.proj)
        state = self.read(self.state)
        self.assertFalse(state["projects"][self.proj][cfg.TRUST_KEY])
        self.assertEqual(state["numStartups"], 3)

    def test_trust_needs_a_project(self):
        code, _, err = self.run_cli("--trust")
        self.assertEqual(code, 2)
        self.assertIn("need a project", err)

    def test_bad_rule(self):
        code, _, err = self.run_cli("--allow", "Bash(oops", "-p", self.proj)
        self.assertEqual(code, 2)
        self.assertIn("does not look like a rule", err)

    def test_listing(self):
        simple_tree(self.root)
        self.write(self.local(), {"permissions": {"allow": ["Bash(make:*)"],
                                                  "additionalDirectories": ["/data"]}})
        self.write(self.state, {"projects": {self.proj: {cfg.TRUST_KEY: True},
                                             "/home/u/proj": {cfg.TRUST_KEY: False}}})
        code, out, _ = self.run_cli("-P")
        self.assertEqual(code, 0)
        self.assertIn("Bash(make:*)", out)
        self.assertIn("/data", out)
        self.assertIn("trusted", out)
        self.assertNotIn("/home/u/proj", out)  # no rules: hidden
        self.assertIn("1 of 3 projects trusted", out)

        _, out, _ = self.run_cli("-P", "-p", "/home/u/proj")
        self.assertIn("/home/u/proj  not trusted", out)

    def test_listing_works_without_sessions(self):
        os.rmdir(self.root)
        code, out, _ = self.run_cli("-P")
        self.assertEqual(code, 0)
        self.assertIn("no rules", out)
