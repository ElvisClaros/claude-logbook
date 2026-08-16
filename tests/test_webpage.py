import json
import os
import re
import tempfile
import unittest

from claude_sesiones import webpage

PAYLOAD_RE = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>', re.S)

REGISTRO = {"id": "abc", "p": "/proj", "u": 1, "c": [{"r": "u", "x": "hola"}]}


class TestPayload(unittest.TestCase):
    def test_escapa_el_cierre_de_etiqueta(self):
        raw = webpage.encode_payload([{"x": "mirá este </script> de acá"}])
        self.assertNotIn("</", raw)
        self.assertEqual(json.loads(raw)[0]["x"], "mirá este </script> de acá")

    def test_no_escapa_a_ascii(self):
        self.assertIn("ñ", webpage.encode_payload([{"x": "año"}]))


class TestRender(unittest.TestCase):
    def test_reemplaza_el_marcador(self):
        html = webpage.render([REGISTRO], template="<b>__DATA__</b>")
        self.assertNotIn("__DATA__", html)
        self.assertIn('"id":"abc"', html)

    def test_falla_si_el_template_no_tiene_marcador(self):
        with self.assertRaises(webpage.TemplateError):
            webpage.render([REGISTRO], template="<b>sin marcador</b>")

    def test_falla_si_el_marcador_esta_repetido(self):
        with self.assertRaises(webpage.TemplateError):
            webpage.render([REGISTRO], template="__DATA__ y __DATA__")

    def test_una_transcripcion_con_html_no_corta_el_script(self):
        # El caso que motiva el escape: una sesión donde se habló de este mismo
        # generador tiene "</script>" y "__DATA__" adentro del texto.
        peligrosa = dict(REGISTRO, c=[{"r": "u", "x": "poné </script><img> y __DATA__"}])
        html = webpage.render([peligrosa])

        bloques = PAYLOAD_RE.findall(html)
        self.assertEqual(len(bloques), 1)
        vuelta = json.loads(bloques[0])
        self.assertEqual(vuelta[0]["c"][0]["x"], "poné </script><img> y __DATA__")


class TestTemplate(unittest.TestCase):
    def setUp(self):
        self.html = webpage.template_text()

    def test_el_template_del_paquete_tiene_un_solo_marcador(self):
        self.assertEqual(self.html.count(webpage.MARKER), 1)

    def test_es_un_documento_completo(self):
        # Sin doctype ni charset, un file:// se abre en quirks mode y con la
        # codificación del sistema: los acentos salen rotos.
        self.assertTrue(self.html.lstrip().startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', self.html)
        self.assertIn('name="viewport"', self.html)
        self.assertTrue(self.html.rstrip().endswith("</html>"))

    def test_no_pide_nada_por_red(self):
        for atributo in ("src=\"http", "href=\"http", "@import"):
            self.assertNotIn(atributo, self.html)

    def test_se_puede_pasar_otro_template(self):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as f:
            f.write("propio __DATA__")
            ruta = f.name
        self.addCleanup(os.unlink, ruta)
        self.assertTrue(webpage.template_text(ruta).startswith("propio"))


class TestWrite(unittest.TestCase):
    def test_escribe_y_resume(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "s.html")
            stats = webpage.write(
                [REGISTRO, dict(REGISTRO, id="def", p="/otro", u=2)], out)
            self.assertEqual(stats, {"sesiones": 2, "proyectos": 2,
                                     "mensajes": 3, "bloques": 2})
            with open(out, encoding="utf-8") as f:
                self.assertEqual(len(PAYLOAD_RE.findall(f.read())), 1)


if __name__ == "__main__":
    unittest.main()
