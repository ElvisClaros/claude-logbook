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
    def test_conversacion_basica(self):
        path = write_session(self.root, "-p", "11111111-1111-1111-1111-111111111111", [
            user("¿por qué falla?", at=ts(0)),
            assistant("Miro.", tools=[("Bash", {"command": "make test"})], at=ts(5)),
        ])
        rec = S.read_session(path)

        self.assertEqual(rec["u"], 1)
        self.assertEqual(rec["a"], 1)
        self.assertEqual(rec["d"], 5)
        self.assertEqual(rec["p"], "/home/u/proj")
        self.assertEqual(rec["b"], "main")
        self.assertFalse(rec["e"])
        self.assertFalse(rec["ai"])
        self.assertEqual(rec["t"], "¿por qué falla?")
        self.assertEqual([m["r"] for m in rec["c"]], ["u", "a", "t"])
        self.assertEqual(rec["c"][2]["x"], "Bash: make test")

    def test_el_titulo_de_claude_le_gana_al_primer_mensaje(self):
        path = write_session(self.root, "-p", "22222222-0000-0000-0000-000000000000", [
            user("arreglá esto", at=ts(0)),
            ai_title("Primer intento"),
            ai_title("Título final"),
        ])
        rec = S.read_session(path)
        self.assertEqual(rec["t"], "Título final")
        self.assertTrue(rec["ai"])

    def test_ignora_el_ruido_del_harness(self):
        path = write_session(self.root, "-p", "33333333-0000-0000-0000-000000000000", [
            user("<command-name>/clear</command-name>", at=ts(0)),
            user("<system-reminder>ojo</system-reminder>", at=ts(1)),
            user("texto real <system-reminder>ojo</system-reminder>", at=ts(2)),
            user("meta", at=ts(2), isMeta=True),
            user("de un subagente", at=ts(3), isSidechain=True),
            assistant("respuesta de subagente", at=ts(4), isSidechain=True),
        ])
        rec = S.read_session(path)
        self.assertEqual(rec["u"], 1)
        self.assertEqual(rec["a"], 0)
        self.assertEqual(rec["c"][0]["x"], "texto real")

    def test_tolera_una_linea_cortada_a_la_mitad(self):
        path = write_session(self.root, "-p", "44444444-0000-0000-0000-000000000000", [
            user("primero", at=ts(0)),
        ])
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"type": "user", "message": {"content": [{"type": "te')
        rec = S.read_session(path)
        self.assertEqual(rec["u"], 1)

    def test_sesion_sin_mensajes(self):
        path = write_session(self.root, "-p", "55555555-0000-0000-0000-000000000000", [
            {"type": "system", "timestamp": ts(0), "cwd": "/home/u/proj"},
        ])
        rec = S.read_session(path)
        self.assertTrue(rec["e"])
        self.assertIsNone(rec["t"])
        self.assertEqual(rec["c"], [])

    def test_un_solo_mensaje_enorme_es_claude_p(self):
        largo = "x" * (S.NONINTERACTIVE_CHARS + 1)
        path = write_session(self.root, "-p", "66666666-0000-0000-0000-000000000000", [
            user(largo, at=ts(0)),
        ])
        self.assertTrue(S.read_session(path)["n"])

    def test_una_charla_corta_no_es_claude_p(self):
        path = write_session(self.root, "-p", "77777777-0000-0000-0000-000000000000", [
            user("hola", at=ts(0)),
        ])
        self.assertFalse(S.read_session(path)["n"])


class TestToolSummary(unittest.TestCase):
    def test_usa_el_parametro_representativo(self):
        self.assertEqual(
            S.tool_summary({"name": "Read", "input": {"file_path": "/a/b.py", "limit": 5}}),
            "Read: /a/b.py")

    def test_cae_al_primer_string_si_la_tool_es_desconocida(self):
        self.assertEqual(
            S.tool_summary({"name": "Rara", "input": {"n": 1, "q": "algo"}}),
            "Rara: algo")

    def test_recorta_los_argumentos_largos(self):
        out = S.tool_summary({"name": "Bash", "input": {"command": "a" * 500}})
        self.assertTrue(out.endswith("…"))
        self.assertEqual(len(out), len("Bash: ") + S.TOOL_ARG_MAX + 1)

    def test_sin_argumentos_usables(self):
        self.assertEqual(S.tool_summary({"name": "X", "input": {"n": 1}}), "X")
        self.assertEqual(S.tool_summary({"name": "X", "input": "no es dict"}), "X")


class TestLoad(TempRoot):
    def test_ordena_por_ultima_actividad(self):
        simple_tree(self.root)
        got = [s["id"][:8] for s in self.load()]
        self.assertEqual(got, ["aaaaaaaa", "bbbbbbbb", "cccccccc"])

    def test_deduce_la_ruta_de_otra_sesion_del_proyecto(self):
        write_session(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001",
                      [user("con cwd", at=ts(0))])
        write_session(self.root, "-home-u-proj", "dddddddd-0000-0000-0000-000000000004",
                      [{"type": "system", "timestamp": ts(30)}])
        huerfana = next(s for s in self.load() if s["id"].startswith("dddddddd"))
        self.assertEqual(huerfana["p"], "/home/u/proj")
        self.assertTrue(huerfana["i"])

    def test_sin_ninguna_ruta_conocida_queda_el_nombre_del_directorio(self):
        write_session(self.root, "-sin-cwd", "eeeeeeee-0000-0000-0000-000000000005",
                      [{"type": "system", "timestamp": ts(0)}])
        s = self.load()[0]
        self.assertEqual(s["p"], "-sin-cwd")
        self.assertTrue(s["i"])

    def test_ignora_los_jsonl_de_subagentes(self):
        simple_tree(self.root)
        sub = os.path.join(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001", "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-1.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(user("soy un subagente")) + "\n")
        self.assertEqual(len(self.load()), 3)


class TestCache(TempRoot):
    def test_reusa_lo_que_no_cambio(self):
        simple_tree(self.root)
        self.load()

        # Ensuciamos el caché a mano: si la segunda corrida devuelve el título
        # falso es porque no volvió a leer el archivo.
        with open(self.cache, encoding="utf-8") as f:
            blob = json.load(f)
        for entry in blob["entries"].values():
            entry["rec"]["t"] = "vino del caché"
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump(blob, f)

        self.assertEqual(self.load()[0]["t"], "vino del caché")

    def test_reparsea_si_el_archivo_cambio(self):
        path = write_session(self.root, "-p", "99999999-0000-0000-0000-000000000009",
                             [user("original", at=ts(0))])
        self.load()
        write_session(self.root, "-p", "99999999-0000-0000-0000-000000000009",
                      [user("cambiado", at=ts(0)), user("y otro", at=ts(1))])
        self.assertEqual(self.load()[0]["u"], 2)
        self.assertTrue(os.path.exists(path))

    def test_un_cache_de_otra_version_se_descarta(self):
        simple_tree(self.root)
        self.load()
        with open(self.cache, encoding="utf-8") as f:
            blob = json.load(f)
        blob["v"] = S.CACHE_VERSION - 1
        for entry in blob["entries"].values():
            entry["rec"]["t"] = "no debería verse"
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump(blob, f)

        self.assertEqual(self.load()[0]["t"], "Arreglar el build")

    def test_un_cache_roto_no_rompe_nada(self):
        simple_tree(self.root)
        with open(self.cache, "w", encoding="utf-8") as f:
            f.write("{esto no es json")
        self.assertEqual(len(self.load()), 3)

    def test_no_cache_no_escribe_nada(self):
        simple_tree(self.root)
        self.load(use_cache=False)
        self.assertFalse(os.path.exists(self.cache))

    def test_el_cache_guarda_la_ruta_sin_deducir(self):
        write_session(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-000000000001",
                      [user("con cwd", at=ts(0))])
        write_session(self.root, "-home-u-proj", "dddddddd-0000-0000-0000-000000000004",
                      [{"type": "system", "timestamp": ts(30)}])
        self.load()
        with open(self.cache, encoding="utf-8") as f:
            blob = json.load(f)
        recs = {os.path.basename(k): v["rec"] for k, v in blob["entries"].items()}
        self.assertIsNone(recs["dddddddd-0000-0000-0000-000000000004.jsonl"]["p"])

    def test_drop_from_cache_saca_las_borradas(self):
        simple_tree(self.root)
        self.load()
        with open(self.cache, encoding="utf-8") as f:
            paths = list(json.load(f)["entries"])
        S.drop_from_cache(paths[:1], cache_path=self.cache)
        with open(self.cache, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["entries"]), len(paths) - 1)


class TestFiltros(TempRoot):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        self.sessions = self.load()

    def test_por_proyecto(self):
        out = S.apply_filters(self.sessions, project="/home/u/otro")
        self.assertEqual(len(out), 1)

    def test_por_contenido_de_la_conversacion(self):
        out = S.apply_filters(self.sessions, grep="build")
        self.assertEqual([s["id"][:8] for s in out], ["aaaaaaaa"])

    def test_por_titulo_ruta_rama_o_uuid(self):
        self.assertEqual(len(S.apply_filters(self.sessions, query="arreglar")), 1)
        self.assertEqual(len(S.apply_filters(self.sessions, query="main")), 2)
        self.assertEqual(len(S.apply_filters(self.sessions, query="cccccccc")), 1)

    def test_ocultar_vacias(self):
        out = S.apply_filters(self.sessions, hide_empty=True)
        self.assertTrue(all(not s["e"] for s in out))
        self.assertEqual(len(out), 2)


class TestPick(TempRoot):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        self.sessions = self.load()

    def test_por_indice(self):
        self.assertEqual(S.pick(self.sessions, "1")["id"][:8], "aaaaaaaa")

    def test_por_prefijo_de_uuid(self):
        self.assertEqual(S.pick(self.sessions, "cccc")["id"][:8], "cccccccc")

    def test_indice_fuera_de_rango(self):
        with self.assertRaises(S.SessionError):
            S.pick(self.sessions, "99")

    def test_prefijo_inexistente(self):
        with self.assertRaises(S.SessionError):
            S.pick(self.sessions, "zzzz")

    def test_prefijo_ambiguo(self):
        write_session(self.root, "-home-u-proj", "aaaaaaaa-0000-0000-0000-0000000000ff",
                      [user("otra más", at=ts(50))])
        with self.assertRaises(S.SessionError):
            S.pick(self.load(), "aaaa")


class TestPublicRecords(TempRoot):
    def test_saca_las_claves_internas_sin_tocar_el_original(self):
        simple_tree(self.root)
        sessions = self.load()
        pub = S.public_records(sessions)
        for r in pub:
            self.assertNotIn("project_dir", r)
            self.assertNotIn("mtime", r)
        self.assertIn("project_dir", sessions[0])


class TestParseTs(unittest.TestCase):
    def test_acepta_z_y_offset(self):
        self.assertIsNotNone(S.parse_ts("2025-08-14T10:00:00.000Z"))
        self.assertIsNotNone(S.parse_ts("2025-08-14T10:00:00+02:00"))

    def test_devuelve_none_si_no_se_puede_leer(self):
        self.assertIsNone(S.parse_ts(None))
        self.assertIsNone(S.parse_ts(""))
        self.assertIsNone(S.parse_ts("ayer a la tarde"))


class TestRoots(unittest.TestCase):
    def test_claude_config_dir_manda(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/x/cfg"}):
            self.assertEqual(S.default_root(), os.path.join("/x/cfg", "projects"))

    def test_sin_variable_cae_al_home(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(S.default_root().endswith(os.path.join(".claude", "projects")))


if __name__ == "__main__":
    unittest.main()
