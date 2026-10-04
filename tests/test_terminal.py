import io
import unittest
from datetime import datetime, timedelta, timezone

from claude_logbook import terminal as T

NOW = datetime(2025, 8, 14, 12, 0, tzinfo=timezone.utc)


def ago(days):
    """An ISO timestamp `days` days away from NOW."""
    return (NOW - timedelta(days=days)).isoformat()


class TestStyle(unittest.TestCase):
    def test_off_emits_nothing(self):
        st = T.Style(False)
        self.assertEqual(st.amber, "")
        self.assertEqual(st.reset, "")

    def test_on_emits_ansi(self):
        st = T.Style(True)
        self.assertTrue(st.amber.startswith("\x1b["))

    def test_unknown_color_is_attribute_error(self):
        with self.assertRaises(AttributeError):
            T.Style(True).fuchsia

    def test_from_stream_without_tty_turns_color_off(self):
        self.assertFalse(T.Style.from_stream(io.StringIO()).on)


class TestFormatting(unittest.TestCase):
    def test_fmt_dur(self):
        self.assertEqual(T.fmt_dur(None), "—")
        self.assertEqual(T.fmt_dur(0), "<1m")
        self.assertEqual(T.fmt_dur(45), "45m")
        self.assertEqual(T.fmt_dur(60), "1h")
        self.assertEqual(T.fmt_dur(125), "2h05")

    def test_fmt_rel(self):
        self.assertEqual(T.fmt_rel(ago(0.2), NOW), "today")
        self.assertEqual(T.fmt_rel(ago(1.5), NOW), "yesterday")
        self.assertEqual(T.fmt_rel(ago(3), NOW), "3d ago")
        self.assertEqual(T.fmt_rel(ago(10), NOW), "1w ago")
        self.assertEqual(T.fmt_rel(ago(70), NOW), "2mo ago")

    def test_fmt_size(self):
        self.assertEqual(T.fmt_size(12.5), "12.5 KB")
        self.assertEqual(T.fmt_size(2048), "2.0 MB")

    def test_clip(self):
        self.assertEqual(T.clip("hello", 10), "hello")
        self.assertEqual(T.clip("hello world", 6), "hello…")
        self.assertEqual(T.clip("line\nbreak", 20), "line break")

    def test_visible_len_ignores_ansi_codes(self):
        self.assertEqual(T.visible_len("\x1b[1mhello\x1b[0m"), 5)

    def test_plural(self):
        self.assertEqual(T.plural(1, "session", "sessions"), "1 session")
        self.assertEqual(T.plural(2, "session", "sessions"), "2 sessions")

    def test_stripe_without_color_is_a_bar(self):
        self.assertEqual(T.stripe(ago(1), NOW, T.Style(False)), "|")

    def test_stripe_changes_color_with_age(self):
        st = T.Style(True)
        use_colors = {T.stripe(ago(d), NOW, st) for d in (1, 4, 10, 60)}
        self.assertEqual(len(use_colors), 4)


class TestMarkdown(unittest.TestCase):
    def test_strip_md(self):
        self.assertEqual(T.strip_md("## Title"), "Title")
        self.assertEqual(T.strip_md("this is **bold**"), "this is bold")

    def test_render_block_respects_fences(self):
        st = T.Style(False)
        out = T.render_block("text\n```py\nx = 1\n```\nend", st, 40, "")
        self.assertIn("  text", out)
        self.assertIn("  x = 1", out)
        self.assertNotIn("```py", "".join(out))

    def test_render_block_does_not_split_long_words(self):
        out = T.render_block("a" * 60, T.Style(False), 20, "")
        self.assertEqual(out, ["  " + "a" * 60])


class TestOutput(unittest.TestCase):
    def session_item(self, **kw):
        s = {
            "id": "abcdef01-2345-6789-abcd-ef0123456789",
            "p": "/home/u/proj", "b": "main", "t": "Fix the build",
            "ai": True, "n": False, "e": False, "i": False,
            "f": ago(1), "l": ago(1), "d": 12, "u": 2, "a": 3, "k": 10.0,
            "v": "1.0.0", "c": [{"r": "u", "x": "hello"}, {"r": "a", "x": "bye"},
                                {"r": "t", "x": "Bash: ls"}],
        }
        s.update(kw)
        return s

    def test_print_table_without_color_has_no_ansi(self):
        buf = io.StringIO()
        T.print_table([self.session_item()], T.Style(False), NOW, buf, width=120)
        out = buf.getvalue()
        self.assertNotIn("\x1b", out)
        self.assertEqual(len(out.strip().split("\n")), 2)  # header + 1 row
        self.assertIn("Fix the build", out)
        self.assertIn("abcdef01", out)

    def test_narrow_print_table_hides_columns(self):
        buf = io.StringIO()
        T.print_table([self.session_item()], T.Style(False), NOW, buf, width=60)
        self.assertNotIn("/home/u/proj", buf.getvalue())

    def test_print_chat_includes_the_resume_command(self):
        buf = io.StringIO()
        T.print_chat(self.session_item(), T.Style(False), buf)
        out = buf.getvalue()
        self.assertIn("cd /home/u/proj && claude --resume abcdef01", out)
        self.assertIn("hello", out)
        self.assertIn("Bash: ls", out)

    def test_no_tools_removes_the_tools(self):
        buf = io.StringIO()
        T.print_chat(self.session_item(), T.Style(False), buf, show_tools=False)
        self.assertNotIn("Bash: ls", buf.getvalue())

    def test_compaction_is_a_mark_without_the_summary(self):
        buf = io.StringIO()
        c = [{"r": "c", "x": "SUMMARY TEXT"}, {"r": "u", "x": "hello"}]
        T.print_chat(self.session_item(c=c), T.Style(False), buf)
        out = buf.getvalue()
        self.assertIn("context compacted here", out)
        self.assertNotIn("SUMMARY TEXT", out)

    def test_branch_hides_what_it_inherited(self):
        buf = io.StringIO()
        c = [{"r": "u", "x": "OLD QUESTION"}, {"r": "a", "x": "OLD ANSWER"},
             {"r": "d", "x": "/home/u/proj/sub"}, {"r": "u", "x": "new one"}]
        T.print_chat(self.session_item(c=c, h=2, o="12345678-aa", ot="The original"),
                     T.Style(False), buf)
        out = buf.getvalue()
        self.assertIn("2 messages inherited from The original", out)
        self.assertNotIn("OLD", out)
        self.assertIn("→ /home/u/proj/sub", out)
        self.assertIn("new one", out)

    def test_empty_session_says_so(self):
        buf = io.StringIO()
        T.print_chat(self.session_item(c=[], t=None), T.Style(False), buf)
        self.assertIn("has no messages", buf.getvalue())

    def test_resume_cmd(self):
        self.assertEqual(
            T.resume_cmd({"p": "/a b", "id": "xyz"}),
            "cd /a b && claude --resume xyz")


class TestMemories(unittest.TestCase):
    def memory_item(self, **kw):
        m = {
            "name": "deploy-docker", "file": "deploy-docker.md",
            "p": "/home/u/proj", "desc": "How it is deployed", "ty": "project",
            "src": "abcdef01-2345-6789-abcd-ef0123456789",
            "body": "Deployed with `make up`.", "ln": ["roles-db"],
            "k": 1.2, "l": ago(1), "ix": True, "hix": True,
        }
        m.update(kw)
        return m

    def test_table_without_color_has_no_ansi(self):
        buf = io.StringIO()
        T.print_memories([self.memory_item()], T.Style(False), NOW, buf, width=120)
        out = buf.getvalue()
        self.assertNotIn("\x1b", out)
        self.assertEqual(len(out.strip().split("\n")), 2)
        self.assertIn("deploy-docker", out)
        self.assertIn("project", out)
        self.assertIn("How it is deployed", out)

    def test_narrow_table_hides_columns(self):
        buf = io.StringIO()
        T.print_memories([self.memory_item()], T.Style(False), NOW, buf, width=70)
        out = buf.getvalue()
        self.assertIn("deploy-docker", out)
        self.assertNotIn("How it is deployed", out)

    def test_marks_the_ones_missing_from_the_index(self):
        buf = io.StringIO()
        T.print_memories([self.memory_item(ix=False)], T.Style(False), NOW, buf,
                         width=120)
        self.assertIn("*", buf.getvalue())

    def test_reading_brings_body_links_and_origin(self):
        buf = io.StringIO()
        T.print_memory(self.memory_item(), T.Style(False), buf, path="/x/y.md")
        out = buf.getvalue()
        self.assertIn("Deployed with", out)
        self.assertIn("roles-db", out)
        self.assertIn("abcdef01", out)
        self.assertIn("/x/y.md", out)

    def test_reading_warns_if_not_indexed(self):
        buf = io.StringIO()
        T.print_memory(self.memory_item(ix=False), T.Style(False), buf)
        self.assertIn("not listed in MEMORY.md", buf.getvalue())

    def test_reading_warns_if_the_project_has_no_index(self):
        buf = io.StringIO()
        T.print_memory(self.memory_item(ix=False, hix=False), T.Style(False), buf)
        self.assertIn("has no MEMORY.md", buf.getvalue())

    def test_empty_audit_prints_nothing(self):
        buf = io.StringIO()
        total = T.print_audit({}, T.Style(False), buf)
        self.assertEqual(total, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_audit_counts_every_block(self):
        buf = io.StringIO()
        m = self.memory_item()
        total = T.print_audit({
            "no_index": [m],
            "unlisted": [m],
            "ghost_entries": [("-p", "ghost")],
            "broken_links": [(m, "broken")],
            "lost_source": [m],
        }, T.Style(False), buf)
        out = buf.getvalue()
        self.assertEqual(total, 5)
        self.assertIn("ghost", out)
        self.assertIn("[[broken]]", out)


if __name__ == "__main__":
    unittest.main()
