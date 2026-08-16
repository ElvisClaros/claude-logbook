import io
import unittest
from datetime import datetime, timedelta, timezone

from claude_sesiones import terminal as T

NOW = datetime(2025, 8, 14, 12, 0, tzinfo=timezone.utc)


def ago(days):
    """Un ISO que queda a `days` días de NOW."""
    return (NOW - timedelta(days=days)).isoformat()


class TestStyle(unittest.TestCase):
    def test_apagado_no_emite_nada(self):
        st = T.Style(False)
        self.assertEqual(st.amber, "")
        self.assertEqual(st.reset, "")

    def test_prendido_emite_ansi(self):
        st = T.Style(True)
        self.assertTrue(st.amber.startswith("\x1b["))

    def test_un_color_que_no_existe_es_attribute_error(self):
        with self.assertRaises(AttributeError):
            T.Style(True).fucsia

    def test_from_stream_sin_tty_apaga_el_color(self):
        self.assertFalse(T.Style.from_stream(io.StringIO()).on)


class TestFormato(unittest.TestCase):
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

    def test_visible_len_ignora_los_codigos_ansi(self):
        self.assertEqual(T.visible_len("\x1b[1mhola\x1b[0m"), 4)

    def test_plural(self):
        self.assertEqual(T.plural(1, "sesión", "sesiones"), "1 sesión")
        self.assertEqual(T.plural(2, "sesión", "sesiones"), "2 sesiones")

    def test_stripe_sin_color_es_una_barra(self):
        self.assertEqual(T.stripe(ago(1), NOW, T.Style(False)), "|")

    def test_stripe_cambia_de_color_con_la_edad(self):
        st = T.Style(True)
        colores = {T.stripe(ago(d), NOW, st) for d in (1, 4, 10, 60)}
        self.assertEqual(len(colores), 4)


class TestMarkdown(unittest.TestCase):
    def test_strip_md(self):
        self.assertEqual(T.strip_md("## Título"), "Título")
        self.assertEqual(T.strip_md("esto es **fuerte**"), "esto es fuerte")

    def test_render_block_respeta_las_cercas(self):
        st = T.Style(False)
        out = T.render_block("texto\n```py\nx = 1\n```\nfin", st, 40, "")
        self.assertIn("  texto", out)
        self.assertIn("  x = 1", out)
        self.assertNotIn("```py", "".join(out))

    def test_render_block_no_parte_palabras_largas(self):
        out = T.render_block("a" * 60, T.Style(False), 20, "")
        self.assertEqual(out, ["  " + "a" * 60])


class TestSalida(unittest.TestCase):
    def sesion(self, **kw):
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
        T.print_table([self.sesion()], T.Style(False), NOW, buf, width=120)
        out = buf.getvalue()
        self.assertNotIn("\x1b", out)
        self.assertEqual(len(out.strip().split("\n")), 2)  # encabezado + 1 fila
        self.assertIn("Arreglar el build", out)
        self.assertIn("abcdef01", out)

    def test_print_table_angosta_esconde_columnas(self):
        buf = io.StringIO()
        T.print_table([self.sesion()], T.Style(False), NOW, buf, width=60)
        self.assertNotIn("/home/u/proj", buf.getvalue())

    def test_print_chat_incluye_el_comando_para_reanudar(self):
        buf = io.StringIO()
        T.print_chat(self.sesion(), T.Style(False), buf)
        out = buf.getvalue()
        self.assertIn("cd /home/u/proj && claude --resume abcdef01", out)
        self.assertIn("hola", out)
        self.assertIn("Bash: ls", out)

    def test_no_tools_saca_las_herramientas(self):
        buf = io.StringIO()
        T.print_chat(self.sesion(), T.Style(False), buf, show_tools=False)
        self.assertNotIn("Bash: ls", buf.getvalue())

    def test_una_sesion_vacia_lo_dice(self):
        buf = io.StringIO()
        T.print_chat(self.sesion(c=[], t=None), T.Style(False), buf)
        self.assertIn("no tiene mensajes", buf.getvalue())

    def test_resume_cmd(self):
        self.assertEqual(
            T.resume_cmd({"p": "/a b", "id": "xyz"}),
            "cd /a b && claude --resume xyz")


if __name__ == "__main__":
    unittest.main()
