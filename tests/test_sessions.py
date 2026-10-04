import json
import os
import tempfile
import unittest
import unittest.mock

from claude_logbook import sessions as S

from .fixtures import ai_title, assistant, simple_tree, ts, user, write_session


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "projects")
        os.makedirs(self.root)
        self.cache = os.path.join(self._tmp.name, "cache.json")
        self.addCleanup(self._tmp.cleanup)

    def load(self, **kw):
        kw.setdefault("cache_path", self.cache)
        return S.load_sessions(root=self.root, **kw)


class TestReadSession(TempRoot):
    def test_basic_conversation(self):
        path = write_session(self.root, "-p", "11111111-1111-1111-1111-111111111111", [
            user("why does it fail?", at=ts(0)),
            assistant("Looking.", tools=[("Bash", {"command": "make test"})], at=ts(5)),
        ])
        rec = S.read_session(path)

        self.assertEqual(rec["u"], 1)
        self.assertEqual(rec["a"], 1)
        self.assertEqual(rec["d"], 5)
        self.assertEqual(rec["p"], "/home/u/proj")
        self.assertEqual(rec["b"], "main")
        self.assertFalse(rec["e"])
        self.assertFalse(rec["ai"])
        self.assertEqual(rec["t"], "why does it fail?")
        self.assertEqual([m["r"] for m in rec["c"]], ["u", "a", "t"])
        self.assertEqual(rec["c"][2]["x"], "Bash: make test")

    def test_claude_title_beats_the_first_message(self):
        path = write_session(self.root, "-p", "22222222-0000-0000-0000-000000000000", [
            user("fix this", at=ts(0)),
            ai_title("First attempt"),
            ai_title("Final title"),
        ])
        rec = S.read_session(path)
        self.assertEqual(rec["t"], "Final title")
        self.assertTrue(rec["ai"])

    def test_ignores_harness_noise(self):
        path = write_session(self.root, "-p", "33333333-0000-0000-0000-000000000000", [
            user("<command-name>/clear</command-name>", at=ts(0)),
            user("<system-reminder>note</system-reminder>", at=ts(1)),
            user("real text <system-reminder>note</system-reminder>", at=ts(2)),
            user("meta", at=ts(2), isMeta=True),
            user("from a subagent", at=ts(3), isSidechain=True),
            assistant("subagent reply", at=ts(4), isSidechain=True),
        ])
        rec = S.read_session(path)
        self.assertEqual(rec["u"], 1)
        self.assertEqual(rec["a"], 0)
        self.assertEqual(rec["c"][0]["x"], "real text")

    def test_tolerates_a_line_cut_in_half(self):
        path = write_session(self.root, "-p", "44444444-0000-0000-0000-000000000000", [
            user("first", at=ts(0)),
        ])
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"type": "user", "message": {"content": [{"type": "te')
        rec = S.read_session(path)
        self.assertEqual(rec["u"], 1)

    def test_session_without_messages(self):
        path = write_session(self.root, "-p", "55555555-0000-0000-0000-000000000000", [
            {"type": "system", "timestamp": ts(0), "cwd": "/home/u/proj"},
        ])
        rec = S.read_session(path)
        self.assertTrue(rec["e"])
        self.assertIsNone(rec["t"])
        self.assertEqual(rec["c"], [])

    def test_single_huge_message_is_claude_p(self):
        largo = "x" * (S.NONINTERACTIVE_CHARS + 1)
        path = write_session(self.root, "-p", "66666666-0000-0000-0000-000000000000", [
            user(largo, at=ts(0)),
        ])
        self.assertTrue(S.read_session(path)["n"])

    def test_short_chat_is_not_claude_p(self):
        path = write_session(self.root, "-p", "77777777-0000-0000-0000-000000000000", [
            user("hello", at=ts(0)),
        ])
        self.assertFalse(S.read_session(path)["n"])


class TestTitlesCompactionDuration(TempRoot):
    def test_rename_beats_the_claude_title(self):
        path = write_session(self.root, "-p", "22222222-0000-0000-0000-000000000001", [
            ai_title("What Claude thinks"),
            user("hi there", at=ts(0)),
            {"type": "custom-title", "customTitle": "Old name"},
            {"type": "custom-title", "customTitle": "Lo grave"},
            ai_title("A later Claude title"),
        ])
        rec = S.read_session(path)
        self.assertEqual(rec["t"], "Lo grave")
        self.assertTrue(rec["ai"])

    def test_compact_summary_is_not_a_message_of_yours(self):
        path = write_session(self.root, "-p", "22222222-0000-0000-0000-000000000002", [
            {"type": "system", "subtype": "compact_boundary", "timestamp": ts(0)},
            user("This session is being continued from a previous conversation. "
                 "Summary: we fixed the build.", at=ts(0), isCompactSummary=True,
                 isVisibleInTranscriptOnly=True),
            user("now the tests", at=ts(2)),
            assistant("On it.", at=ts(3)),
        ])
        rec = S.read_session(path)
        self.assertEqual([m["r"] for m in rec["c"]], ["c", "u", "a"])
        self.assertIn("we fixed the build", rec["c"][0]["x"])
        self.assertEqual(rec["u"], 1)
        self.assertEqual(rec["t"], "now the tests")
        self.assertFalse(rec["n"])

    def test_duration_leaves_out_long_pauses(self):
        path = write_session(self.root, "-p", "22222222-0000-0000-0000-000000000003", [
            user("start", at=ts(0)),
            assistant("ok", at=ts(10)),
            user("next day", at=ts(0, day=15)),
            assistant("ok", at=ts(20, day=15)),
            {"type": "system", "timestamp": ts(0, day=20)},  # not a message
        ])
        self.assertEqual(S.read_session(path)["d"], 30)

    def test_active_minutes(self):
        self.assertIsNone(S.active_minutes([]))
        self.assertEqual(S.active_minutes([ts(0)]), 0)
        self.assertEqual(S.active_minutes([ts(0), ts(30), ts(31, hour=11)]), 30)


class TestBranchesAndDirectories(TempRoot):
    ORIGIN = "33333333-0000-0000-0000-000000000001"

    def branch(self, own=True):
        fork = {"forkedFrom": {"sessionId": self.ORIGIN, "messageUuid": "x"}}
        events = [
            user("the original question", at=ts(0, hour=8), **fork),
            assistant("the original answer", at=ts(5, hour=8), **fork),
            {"type": "custom-title", "customTitle": "Try another way (Branch)"},
        ]
        if own:
            events += [user("and now this", at=ts(0)), assistant("ok", at=ts(10))]
        return write_session(self.root, "-home-u-proj",
                             "33333333-0000-0000-0000-000000000002", events)

    def test_the_copied_history_is_inherited(self):
        rec = S.read_session(self.branch())
        self.assertEqual(rec["o"], self.ORIGIN)
        self.assertEqual(rec["h"], 2)
        self.assertEqual([m["x"] for m in rec["c"][2:]], ["and now this", "ok"])
        self.assertEqual((rec["u"], rec["a"], rec["d"]), (1, 1, 10))
        self.assertEqual(rec["f"], ts(0))
        self.assertEqual(rec["t"], "Try another way (Branch)")

    def test_a_branch_with_nothing_of_its_own(self):
        rec = S.read_session(self.branch(own=False))
        self.assertEqual((rec["h"], rec["u"], rec["a"]), (2, 0, 0))
        self.assertFalse(rec["e"])
        self.assertEqual(rec["f"], ts(0, hour=8))

    def test_not_a_branch(self):
        path = write_session(self.root, "-p", "33333333-0000-0000-0000-000000000003", [
            user("hello", at=ts(0))])
        rec = S.read_session(path)
        self.assertEqual((rec["h"], rec["o"]), (0, None))

    def test_the_origin_title_is_filled_in(self):
        self.branch()
        write_session(self.root, "-home-u-proj", self.ORIGIN, [
            ai_title("The original"), user("the original question", at=ts(0, hour=8))])
        by_id = {s["id"]: s for s in S.load_sessions(self.root, use_cache=False)}
        self.assertEqual(by_id["33333333-0000-0000-0000-000000000002"]["ot"], "The original")
        self.assertIsNone(by_id[self.ORIGIN]["ot"])

    def test_directory_changes_are_marked_and_filtered(self):
        path = write_session(self.root, "-home-u-proj", "33333333-0000-0000-0000-000000000004", [
            {"type": "system", "timestamp": ts(0), "cwd": "/home/u/proj"},
            user("build it", at=ts(1)),
            assistant("ok", at=ts(2), cwd="/home/u/proj/server"),
            assistant("again", at=ts(3), cwd="/home/u/proj/server"),
            assistant("isSidechain", at=ts(3), cwd="/elsewhere", isSidechain=True),
            user("back", at=ts(4)),
        ])
        rec = S.read_session(path)
        self.assertEqual(rec["p"], "/home/u/proj")
        self.assertEqual([(m["r"], m["x"]) for m in rec["c"]], [
            ("u", "build it"), ("d", "/home/u/proj/server"), ("a", "ok"),
            ("a", "again"), ("d", "/home/u/proj"), ("u", "back")])
        S._fill_gaps([rec])
        self.assertEqual(S.apply_filters([rec], project="proj/server"), [rec])
        self.assertEqual(S.apply_filters([rec], project="/elsewhere"), [])


class TestToolSummary(unittest.TestCase):
    def test_uses_the_representative_parameter(self):
        self.assertEqual(
            S.tool_summary({"name": "Read", "input": {"file_path": "/a/b.py", "limit": 5}}),
            "Read: /a/b.py")

    def test_falls_back_to_first_string_for_unknown_tool(self):
        self.assertEqual(
            S.tool_summary({"name": "Odd", "input": {"n": 1, "q": "something"}}),
            "Odd: something")

    def test_truncates_long_arguments(self):
        out = S.tool_summary({"name": "Bash", "input": {"command": "a" * 500}})
        self.assertTrue(out.endswith("…"))
        self.assertEqual(len(out), len("Bash: ") + S.TOOL_ARG_MAX + 1)

    def test_no_usable_arguments(self):
        self.assertEqual(S.tool_summary({"name": "X", "input": {"n": 1}}), "X")
        self.assertEqual(S.tool_summary({"name": "X", "input": "not a dict"}), "X")


class TestLoad(TempRoot):
    def test_sorts_by_last_activity(self):
        simple_tree(self.root)
        got = [s["id"][:8] for s in self.load()]
        self.assertEqual(got, ["aaaaaaaa", "bbbbbbbb", "cccccccc"])

    def test_infers_the_path_from_another_session_of_the_project(self):
        write_session(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001",
                      [user("with cwd", at=ts(0))])
        write_session(self.root, "-home-u-proj", "dddddddd-0000-0000-0000-000000000004",
                      [{"type": "system", "timestamp": ts(30)}])
        orphan = next(s for s in self.load() if s["id"].startswith("dddddddd"))
        self.assertEqual(orphan["p"], "/home/u/proj")
        self.assertTrue(orphan["i"])

    def test_no_known_path_keeps_the_directory_name(self):
        write_session(self.root, "-no-cwd", "eeeeeeee-0000-0000-0000-000000000005",
                      [{"type": "system", "timestamp": ts(0)}])
        s = self.load()[0]
        self.assertEqual(s["p"], "-no-cwd")
        self.assertTrue(s["i"])

    def test_ignores_subagent_jsonl_files(self):
        simple_tree(self.root)
        sub = os.path.join(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001", "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-1.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(user("I am a subagent")) + "\n")
        self.assertEqual(len(self.load()), 3)


class TestCache(TempRoot):
    def test_reuses_what_did_not_change(self):
        simple_tree(self.root)
        self.load()

        # Dirty the cache by hand: if the second run returns the fake
        # title, it did not read the file again.
        with open(self.cache, encoding="utf-8") as f:
            blob = json.load(f)
        for entry in blob["entries"].values():
            entry["rec"]["t"] = "came from the cache"
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump(blob, f)

        self.assertEqual(self.load()[0]["t"], "came from the cache")

    def test_reparses_if_the_file_changed(self):
        path = write_session(self.root, "-p", "99999999-0000-0000-0000-000000000009",
                             [user("original", at=ts(0))])
        self.load()
        write_session(self.root, "-p", "99999999-0000-0000-0000-000000000009",
                      [user("changed", at=ts(0)), user("and another", at=ts(1))])
        self.assertEqual(self.load()[0]["u"], 2)
        self.assertTrue(os.path.exists(path))

    def test_cache_from_another_version_is_discarded(self):
        simple_tree(self.root)
        self.load()
        with open(self.cache, encoding="utf-8") as f:
            blob = json.load(f)
        blob["v"] = S.CACHE_VERSION - 1
        for entry in blob["entries"].values():
            entry["rec"]["t"] = "should not show up"
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump(blob, f)

        self.assertEqual(self.load()[0]["t"], "Fix the build")

    def test_broken_cache_breaks_nothing(self):
        simple_tree(self.root)
        with open(self.cache, "w", encoding="utf-8") as f:
            f.write("{this is not json")
        self.assertEqual(len(self.load()), 3)

    def test_no_cache_writes_nothing(self):
        simple_tree(self.root)
        self.load(use_cache=False)
        self.assertFalse(os.path.exists(self.cache))

    def test_cache_stores_the_path_without_inferring(self):
        write_session(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001",
                      [user("with cwd", at=ts(0))])
        write_session(self.root, "-home-u-proj", "dddddddd-0000-0000-0000-000000000004",
                      [{"type": "system", "timestamp": ts(30)}])
        self.load()
        with open(self.cache, encoding="utf-8") as f:
            blob = json.load(f)
        recs = {os.path.basename(k): v["rec"] for k, v in blob["entries"].items()}
        self.assertIsNone(recs["dddddddd-0000-0000-0000-000000000004.jsonl"]["p"])

    def test_drop_from_cache_removes_deleted_ones(self):
        simple_tree(self.root)
        self.load()
        with open(self.cache, encoding="utf-8") as f:
            paths = list(json.load(f)["entries"])
        S.drop_from_cache(paths[:1], cache_path=self.cache)
        with open(self.cache, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["entries"]), len(paths) - 1)


class TestFilters(TempRoot):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        self.sessions = self.load()

    def test_by_project(self):
        out = S.apply_filters(self.sessions, project="/home/u/other")
        self.assertEqual(len(out), 1)

    def test_by_conversation_content(self):
        out = S.apply_filters(self.sessions, grep="build")
        self.assertEqual([s["id"][:8] for s in out], ["aaaaaaaa"])

    def test_by_title_path_branch_or_uuid(self):
        self.assertEqual(len(S.apply_filters(self.sessions, query="fix the")), 1)
        self.assertEqual(len(S.apply_filters(self.sessions, query="main")), 2)
        self.assertEqual(len(S.apply_filters(self.sessions, query="cccccccc")), 1)

    def test_hide_empty(self):
        out = S.apply_filters(self.sessions, hide_empty=True)
        self.assertTrue(all(not s["e"] for s in out))
        self.assertEqual(len(out), 2)


class TestPick(TempRoot):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        self.sessions = self.load()

    def test_by_index(self):
        self.assertEqual(S.pick(self.sessions, "1")["id"][:8], "aaaaaaaa")

    def test_by_uuid_prefix(self):
        self.assertEqual(S.pick(self.sessions, "cccc")["id"][:8], "cccccccc")

    def test_index_out_of_range(self):
        with self.assertRaises(S.SessionError):
            S.pick(self.sessions, "99")

    def test_unknown_prefix(self):
        with self.assertRaises(S.SessionError):
            S.pick(self.sessions, "zzzz")

    def test_ambiguous_prefix(self):
        write_session(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-0000000000ff",
                      [user("one more", at=ts(50))])
        with self.assertRaises(S.SessionError):
            S.pick(self.load(), "aaaa")


class TestPublicRecords(TempRoot):
    def test_drops_internal_keys_without_touching_the_original(self):
        simple_tree(self.root)
        sessions = self.load()
        pub = S.public_records(sessions)
        for r in pub:
            self.assertNotIn("project_dir", r)
            self.assertNotIn("mtime", r)
        self.assertIn("project_dir", sessions[0])


class TestParseTs(unittest.TestCase):
    def test_accepts_z_and_offset(self):
        self.assertIsNotNone(S.parse_ts("2025-08-14T10:00:00.000Z"))
        self.assertIsNotNone(S.parse_ts("2025-08-14T10:00:00+02:00"))

    def test_returns_none_if_unreadable(self):
        self.assertIsNone(S.parse_ts(None))
        self.assertIsNone(S.parse_ts(""))
        self.assertIsNone(S.parse_ts("yesterday afternoon"))


class TestRoots(unittest.TestCase):
    def test_claude_config_dir_wins(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/x/cfg"}):
            self.assertEqual(S.default_root(), os.path.join("/x/cfg", "projects"))

    def test_no_variable_falls_back_to_home(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(S.default_root().endswith(os.path.join(".claude", "projects")))


if __name__ == "__main__":
    unittest.main()
