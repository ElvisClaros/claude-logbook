import os
import tempfile
import unittest

from claude_logbook import memory, sessions

from .fixtures import (
    memory_tree, simple_tree, write_index, write_memory,
)


class MemoryCase(unittest.TestCase):
    """Each test runs against a fake ~/.claude/projects."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "projects")
        os.makedirs(self.root)

    def load_items(self):
        """Sessions + memories of the tree, as the CLI sees them."""
        ss = sessions.load_sessions(root=self.root, use_cache=False)
        return ss, memory.load_memories(ss, root=self.root)


class TestParsing(MemoryCase):
    def test_reads_frontmatter_and_body(self):
        path = write_memory(self.root, "-home-u-proj", "one",
                            body="the body", desc="what it is", kind="feedback",
                            origin="abc123")
        m = memory.read_memory(path, "-home-u-proj")
        self.assertEqual(m["name"], "one")
        self.assertEqual(m["desc"], "what it is")
        self.assertEqual(m["ty"], "feedback")
        self.assertEqual(m["src"], "abc123")
        self.assertEqual(m["body"], "the body")

    def test_quoted_description_loses_the_escapes(self):
        # Claude writes the description as a YAML string when it contains quotes.
        path = write_memory(self.root, "-home-u-proj", "q",
                            desc=r'"the \"legion\" machine and more"')
        self.assertEqual(memory.read_memory(path, "-home-u-proj")["desc"],
                         'the "legion" machine and more')

    def test_no_frontmatter_falls_back_to_the_file_name(self):
        path = write_memory(self.root, "-home-u-proj", "bare",
                            body="just text", frontmatter=False)
        m = memory.read_memory(path, "-home-u-proj")
        self.assertEqual(m["name"], "bare")
        self.assertEqual(m["ty"], "—")
        self.assertEqual(m["body"], "just text")

    def test_collects_links_without_repeats(self):
        path = write_memory(self.root, "-home-u-proj", "l",
                            body="[[one]] and [[two]] and again [[one]]")
        self.assertEqual(memory.read_memory(path, "-home-u-proj")["ln"],
                         ["one", "two"])


class TestLoading(MemoryCase):
    def test_resolves_the_project_path_from_the_sessions(self):
        simple_tree(self.root)
        memory_tree(self.root)
        _, mems = self.load_items()
        deploy = next(m for m in mems if m["name"] == "deploy-docker")
        self.assertEqual(deploy["p"], "/home/u/proj")

    def test_no_sessions_keeps_the_encoded_name(self):
        # It cannot be reversed: "/" and "." are both encoded as "-".
        memory_tree(self.root)
        _, mems = self.load_items()
        self.assertEqual(
            next(m for m in mems if m["name"] == "deploy-docker")["p"],
            "-home-u-proj")

    def test_ignores_empty_memory_directories(self):
        memory_tree(self.root)
        _, mems = self.load_items()
        self.assertNotIn("-home-u-empty", {m["project_dir"] for m in mems})

    def test_marks_what_is_in_the_index(self):
        memory_tree(self.root)
        _, mems = self.load_items()
        by_name = {m["name"]: m for m in mems}
        self.assertTrue(by_name["deploy-docker"]["ix"])
        self.assertFalse(by_name["stray"]["ix"])
        self.assertTrue(by_name["stray"]["hix"])
        self.assertFalse(by_name["no-index"]["hix"])

    def test_sorts_by_date_descending(self):
        memory_tree(self.root)
        _, mems = self.load_items()
        dates = [m["l"] for m in mems]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_public_records_drops_internal_keys(self):
        memory_tree(self.root)
        _, mems = self.load_items()
        for m in memory.public_records(mems):
            self.assertNotIn("project_dir", m)
        # The original is left untouched.
        self.assertIn("project_dir", mems[0])


class TestFilters(MemoryCase):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        memory_tree(self.root)
        _, self.mems = self.load_items()

    def test_by_type(self):
        r = memory.apply_filters(self.mems, kind="reference")
        self.assertEqual([m["name"] for m in r], ["roles-db"])

    def test_by_project(self):
        r = memory.apply_filters(self.mems, project="/home/u/proj")
        self.assertNotIn("no-index", [m["name"] for m in r])

    def test_query_reaches_the_body(self):
        r = memory.apply_filters(self.mems, query="make up")
        self.assertEqual([m["name"] for m in r], ["deploy-docker"])

    def test_query_also_checks_the_description(self):
        r = memory.apply_filters(self.mems, query="orphan")
        self.assertEqual([m["name"] for m in r], ["stray"])


class TestPick(MemoryCase):
    def setUp(self):
        super().setUp()
        memory_tree(self.root)
        _, self.mems = self.load_items()

    def test_by_index(self):
        self.assertEqual(memory.pick(self.mems, "1"), self.mems[0])

    def test_index_out_of_range(self):
        with self.assertRaises(sessions.SessionError):
            memory.pick(self.mems, "99")

    def test_by_prefix(self):
        self.assertEqual(memory.pick(self.mems, "deploy")["name"], "deploy-docker")

    def test_falls_back_to_substring(self):
        self.assertEqual(memory.pick(self.mems, "docker")["name"], "deploy-docker")

    def test_no_matches(self):
        with self.assertRaises(sessions.SessionError):
            memory.pick(self.mems, "nothing-like-it")

    def test_ambiguous(self):
        write_memory(self.root, "-home-u-proj", "deploy-other")
        _, mems = self.load_items()
        with self.assertRaises(sessions.SessionError) as ctx:
            memory.pick(mems, "deploy")
        self.assertIn("ambiguous", str(ctx.exception))


class TestAudit(MemoryCase):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        memory_tree(self.root)
        self.ss, self.mems = self.load_items()
        self.report = memory.audit(self.mems, self.ss, root=self.root)

    def test_project_without_index(self):
        self.assertEqual([m["name"] for m in self.report["no_index"]],
                         ["no-index"])

    def test_memory_outside_the_index(self):
        self.assertEqual([m["name"] for m in self.report["unlisted"]],
                         ["stray"])

    def test_index_entry_without_file(self):
        self.assertEqual([n for _, n in self.report["ghost_entries"]],
                         ["deleted-long-ago"])

    def test_broken_link(self):
        broken = [link for _, link in self.report["broken_links"]]
        self.assertEqual(broken, ["missing"])  # [[roles-db]] does resolve

    def test_lost_origin_session(self):
        # deploy-docker points to a session that exists; no-index does not.
        self.assertEqual([m["name"] for m in self.report["lost_source"]],
                         ["no-index"])

    def test_consistent_tree_reports_nothing(self):
        is_clean = os.path.join(self._tmp.name, "clean")
        os.makedirs(is_clean)
        write_memory(is_clean, "-p", "lone", body="no links")
        write_index(is_clean, "-p", ["lone"])
        mems = memory.load_memories([], root=is_clean)
        self.assertEqual(memory.audit_total(memory.audit(mems, [], root=is_clean)), 0)


class TestDeletion(MemoryCase):
    def setUp(self):
        super().setUp()
        memory_tree(self.root)
        _, self.mems = self.load_items()

    def by_name(self, name):
        return next(m for m in self.mems if m["name"] == name)

    def test_deletes_the_file_and_unindexes_it(self):
        m = self.by_name("deploy-docker")
        self.assertTrue(memory.delete(m, root=self.root))
        self.assertFalse(os.path.exists(memory.memory_path(m, self.root)))
        self.assertNotIn("deploy-docker",
                         memory.read_index("-home-u-proj", self.root))

    def test_unindexing_leaves_other_lines_alone(self):
        memory.unindex(self.by_name("deploy-docker"), root=self.root)
        self.assertIn("roles-db", memory.read_index("-home-u-proj", self.root))

    def test_delete_one_that_was_not_indexed(self):
        m = self.by_name("stray")
        self.assertFalse(memory.delete(m, root=self.root))
        self.assertFalse(os.path.exists(memory.memory_path(m, self.root)))

    def test_delete_without_memory_md(self):
        m = self.by_name("no-index")
        self.assertFalse(memory.delete(m, root=self.root))
        self.assertFalse(os.path.exists(memory.memory_path(m, self.root)))


if __name__ == "__main__":
    unittest.main()
