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

    def test_un_color_que_no_existe_es_attribute_error(self):
        with self.assertRaises(AttributeError):
            T.Style(True).fucsia

    def test_from_stream_sin_tty_apaga_el_color(self):
        self.assertFalse(T.Style.from_stream(io.StringIO()).on)


class TestFormatting(unittest.TestCase):
    def test_fmt_dur(self):
        self.assertEqual(T.fmt_dur(None), "—")
        self.assertEqual(T.fmt_dur(0), "<1m")
        self.assertEqual(T.fmt_dur(45), "45m")
        self.assertEqual(T.fmt_dur(60), "1h")
        self.assertEqual(T.fmt_dur(125), "2h05")

    def test_fmt_rel(self):
        self.assertEqual(T.fmt_rel(ago(0.2), NOW), "hoy")
        self.assertEqual(T.fmt_rel(ago(1.5), NOW), "ayer")
        self.assertEqual(T.fmt_rel(ago(3), NOW), "hace 3d")
        self.assertEqual(T.fmt_rel(ago(10), NOW), "hace 1sem")
        self.assertEqual(T.fmt_rel(ago(70), NOW), "hace 2mes")

    def test_fmt_size(self):
        self.assertEqual(T.fmt_size(12.5), "12.5 KB")
        self.assertEqual(T.fmt_size(2048), "2.0 MB")

    def test_clip(self):
        self.assertEqual(T.clip("hola", 10), "hola")
        self.assertEqual(T.clip("hola mundo", 6), "hola …")
        self.assertEqual(T.clip("con\nsalto", 20), "con salto")

    def test_visible_len_ignores_ansi_codes(self):
        self.assertEqual(T.visible_len("\x1b[1mhola\x1b[0m"), 4)

    def test_plural(self):
        self.assertEqual(T.plural(1, "sesión", "sesiones"), "1 sesión")
        self.assertEqual(T.plural(2, "sesión", "sesiones"), "2 sesiones")

    def test_stripe_without_color_is_a_bar(self):
        self.assertEqual(T.stripe(ago(1), NOW, T.Style(False)), "|")

    def test_stripe_changes_color_with_age(self):
        st = T.Style(True)
        use_colors = {T.stripe(ago(d), NOW, st) for d in (1, 4, 10, 60)}
        self.assertEqual(len(use_colors), 4)


class TestMarkdown(unittest.TestCase):
    def test_strip_md(self):
        self.assertEqual(T.strip_md("## Título"), "Título")
        self.assertEqual(T.strip_md("esto es **fuerte**"), "esto es fuerte")

    def test_render_block_respects_fences(self):
        st = T.Style(False)
        out = T.render_block("texto\n```py\nx = 1\n```\nfin", st, 40, "")
        self.assertIn("  texto", out)
        self.assertIn("  x = 1", out)
        self.assertNotIn("```py", "".join(out))

    def test_render_block_does_not_split_long_words(self):
        out = T.render_block("a" * 60, T.Style(False), 20, "")
        self.assertEqual(out, ["  " + "a" * 60])


class TestOutput(unittest.TestCase):
    def session_item(self, **kw):
        s = {
            "id": "abcdef01-2345-6789-abcd-ef0123456789",
            "p": "/home/u/proj", "b": "main", "t": "Arreglar el build",
            "ai": True, "n": False, "e": False, "i": False,
            "f": ago(1), "l": ago(1), "d": 12, "u": 2, "a": 3, "k": 10.0,
            "v": "1.0.0", "c": [{"r": "u", "x": "hola"}, {"r": "a", "x": "chau"},
                                {"r": "t", "x": "Bash: ls"}],
        }
        s.update(kw)
        return s

    def test_print_table_sin_color_no_tiene_ansi(self):
        buf = io.StringIO()
        T.print_table([self.session_item()], T.Style(False), NOW, buf, width=120)
        out = buf.getvalue()
        self.assertNotIn("\x1b", out)
        self.assertEqual(len(out.strip().split("\n")), 2)  # header + 1 row
        self.assertIn("Arreglar el build", out)
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
        self.assertIn("hola", out)
        self.assertIn("Bash: ls", out)

    def test_no_tools_removes_the_tools(self):
        buf = io.StringIO()
        T.print_chat(self.session_item(), T.Style(False), buf, show_tools=False)
        self.assertNotIn("Bash: ls", buf.getvalue())

    def test_empty_session_says_so(self):
        buf = io.StringIO()
        T.print_chat(self.session_item(c=[], t=None), T.Style(False), buf)
        self.assertIn("no tiene mensajes", buf.getvalue())

    def test_resume_cmd(self):
        self.assertEqual(
            T.resume_cmd({"p": "/a b", "id": "xyz"}),
            "cd /a b && claude --resume xyz")


class TestMemories(unittest.TestCase):
    def memory_item(self, **kw):
        m = {
            "name": "deploy-docker", "file": "deploy-docker.md",
            "p": "/home/u/proj", "desc": "Cómo se despliega", "ty": "project",
            "src": "abcdef01-2345-6789-abcd-ef0123456789",
            "body": "Se despliega con `make up`.", "ln": ["roles-db"],
            "k": 1.2, "l": ago(1), "ix": True, "hix": True,
        }
        m.update(kw)
        return m

    def test_tabla_sin_color_no_tiene_ansi(self):
        buf = io.StringIO()
        T.print_memories([self.memory_item()], T.Style(False), NOW, buf, width=120)
        out = buf.getvalue()
        self.assertNotIn("\x1b", out)
        self.assertEqual(len(out.strip().split("\n")), 2)
        self.assertIn("deploy-docker", out)
        self.assertIn("project", out)
        self.assertIn("Cómo se despliega", out)

    def test_narrow_table_hides_columns(self):
        buf = io.StringIO()
        T.print_memories([self.memory_item()], T.Style(False), NOW, buf, width=70)
        out = buf.getvalue()
        self.assertIn("deploy-docker", out)
        self.assertNotIn("Cómo se despliega", out)

    def test_marks_the_ones_missing_from_the_index(self):
        buf = io.StringIO()
        T.print_memories([self.memory_item(ix=False)], T.Style(False), NOW, buf,
                         width=120)
        self.assertIn("*", buf.getvalue())

    def test_reading_brings_body_links_and_origin(self):
        buf = io.StringIO()
        T.print_memory(self.memory_item(), T.Style(False), buf, path="/x/y.md")
        out = buf.getvalue()
        self.assertIn("Se despliega con", out)
        self.assertIn("roles-db", out)
        self.assertIn("abcdef01", out)
        self.assertIn("/x/y.md", out)

    def test_reading_warns_if_not_indexed(self):
        buf = io.StringIO()
        T.print_memory(self.memory_item(ix=False), T.Style(False), buf)
        self.assertIn("no figura en MEMORY.md", buf.getvalue())

    def test_reading_warns_if_the_project_has_no_index(self):
        buf = io.StringIO()
        T.print_memory(self.memory_item(ix=False, hix=False), T.Style(False), buf)
        self.assertIn("no tiene MEMORY.md", buf.getvalue())

    def test_empty_audit_prints_nothing(self):
        buf = io.StringIO()
        total = T.print_audit({}, T.Style(False), buf)
        self.assertEqual(total, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_audit_counts_every_block(self):
        buf = io.StringIO()
        m = self.memory_item()
        total = T.print_audit({
            "sin_indice": [m],
            "sin_listar": [m],
            "indice_fantasma": [("-p", "fantasma")],
            "enlaces_rotos": [(m, "roto")],
            "origen_perdido": [m],
        }, T.Style(False), buf)
        out = buf.getvalue()
        self.assertEqual(total, 5)
        self.assertIn("fantasma", out)
        self.assertIn("[[roto]]", out)


if __name__ == "__main__":
    unittest.main()
