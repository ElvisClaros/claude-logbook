import io
import json
import os
import re
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout

from claude_sesiones import cli

from .fixtures import simple_tree, ts, user, write_session

PAYLOAD_RE = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>', re.S)


class CliCase(unittest.TestCase):
    """Cada test corre contra un ~/.claude y un caché de mentira."""

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
    def test_lista_las_sesiones(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Arreglar el build", out)
        self.assertIn("3 sesiones · 2 proyectos", out)

    def test_filtra_por_texto(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("arreglar")
        self.assertEqual(code, 0)
        self.assertIn("1 de 3 sesiones", out)

    def test_limita_la_cantidad(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-n", "1")
        self.assertIn("1 de 3 sesiones", out)

    def test_un_filtro_sin_resultados_sale_con_1(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("no-existe-esto")
        self.assertEqual(code, 1)
        self.assertIn("Ninguna sesión coincide", err)

    def test_sin_directorio_de_claude_sale_con_2(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/no/existe"}):
            code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("no existe", err)

    def test_sin_ninguna_sesion_sale_con_1(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("No hay ninguna sesión", err)


class TestExportar(CliCase):
    def test_json(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(len(data), 3)
        self.assertNotIn("project_dir", data[0])

    def test_html(self):
        simple_tree(self.root)
        out_path = os.path.join(self.home, "s.html")
        code, _, err = self.run_cli("--html", out_path)
        self.assertEqual(code, 0)
        self.assertIn("3 sesiones", err)
        with open(out_path, encoding="utf-8") as f:
            html = f.read()
        self.assertEqual(len(json.loads(PAYLOAD_RE.findall(html)[0])), 3)

    def test_html_no_toca_stdout(self):
        # El resumen va a stderr para que `--html /dev/stdout` siga sirviendo.
        simple_tree(self.root)
        _, out, _ = self.run_cli("--html", os.path.join(self.home, "s.html"))
        self.assertEqual(out, "")


class TestLectura(CliCase):
    def test_show_por_indice(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("-s", "1", "--no-pager")
        self.assertEqual(code, 0)
        self.assertIn("¿por qué falla el build?", out)

    def test_show_por_prefijo_de_uuid(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-s", "cccccccc", "--no-pager")
        self.assertIn("hola", out)

    def test_show_respeta_el_filtro_previo(self):
        simple_tree(self.root)
        _, out, _ = self.run_cli("-p", "/home/u/otro", "-s", "1", "--no-pager")
        self.assertIn("hola", out)

    def test_una_referencia_que_no_existe_sale_con_2(self):
        simple_tree(self.root)
        code, _, err = self.run_cli("-s", "99")
        self.assertEqual(code, 2)
        self.assertIn("fuera de rango", err)

    def test_resume_imprime_el_comando(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("-r", "1")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(),
                         "cd /home/u/proj && claude --resume "
                         "aaaaaaaa-0000-0000-0000-000000000001")


class TestBorrado(CliCase):
    def paths(self):
        return sorted(os.listdir(os.path.join(self.root, "-home-u-proj")))

    def test_dry_run_no_toca_nada(self):
        simple_tree(self.root)
        antes = self.paths()
        code, out, _ = self.run_cli("--delete-empty", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("no se tocó nada", out)
        self.assertEqual(self.paths(), antes)

    def test_borra_las_vacias(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 sesión borrada", out)
        self.assertEqual(self.paths(),
                         ["aaaaaaaa-0000-0000-0000-000000000001.jsonl"])

    def test_borra_una_puntual_por_prefijo(self):
        simple_tree(self.root)
        code, _, _ = self.run_cli("-D", "aaaaaaaa", "-y")
        self.assertEqual(code, 0)
        self.assertEqual(self.paths(),
                         ["bbbbbbbb-0000-0000-0000-000000000002.jsonl"])

    def test_no_repite_si_la_pediste_dos_veces(self):
        simple_tree(self.root)
        code, out, _ = self.run_cli("-D", "aaaaaaaa", "1", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 sesión borrada", out)

    def test_la_borrada_no_vuelve_desde_el_cache(self):
        simple_tree(self.root)
        self.run_cli()                       # llena el caché
        self.run_cli("--delete-empty", "-y")
        _, out, _ = self.run_cli()
        self.assertIn("2 sesiones", out)
        self.assertNotIn("bbbbbbbb", out)

    def test_el_filtro_acota_lo_que_se_borra(self):
        write_session(self.root, "-home-u-otro", "ffffffff-0000-0000-0000-000000000006",
                      [{"type": "system", "timestamp": ts(0)}])
        simple_tree(self.root)
        code, out, _ = self.run_cli("-p", "/home/u/proj", "--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("1 sesión borrada", out)
        self.assertTrue(os.path.exists(os.path.join(
            self.root, "-home-u-otro", "ffffffff-0000-0000-0000-000000000006.jsonl")))

    def test_sin_nada_para_borrar_avisa(self):
        write_session(self.root, "-p", "aaaaaaaa-0000-0000-0000-000000000001",
                      [user("hola", at=ts(0))])
        code, _, err = self.run_cli("--delete-empty", "-y")
        self.assertEqual(code, 0)
        self.assertIn("No hay sesiones que borrar", err)


class TestParser(unittest.TestCase):
    def test_html_sin_valor_usa_el_nombre_por_defecto(self):
        args = cli.build_parser().parse_args(["--html"])
        self.assertEqual(args.html, cli.DEFAULT_HTML)

    def test_html_con_valor(self):
        self.assertEqual(cli.build_parser().parse_args(["--html", "x.html"]).html,
                         "x.html")

    def test_la_query_junta_las_palabras(self):
        args = cli.build_parser().parse_args(["dos", "palabras"])
        self.assertEqual(args.query, ["dos", "palabras"])


if __name__ == "__main__":
    unittest.main()
