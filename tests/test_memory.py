import os
import tempfile
import unittest

from claude_sesiones import memory, sessions

from .fixtures import (
    memory_tree, simple_tree, write_index, write_memory,
)


class MemoryCase(unittest.TestCase):
    """Cada test corre contra un ~/.claude/projects de mentira."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "projects")
        os.makedirs(self.root)

    def cargar(self):
        """Sesiones + memorias del árbol, como las ve la CLI."""
        ss = sessions.load_sessions(root=self.root, use_cache=False)
        return ss, memory.load_memories(ss, root=self.root)


class TestParseo(MemoryCase):
    def test_lee_frontmatter_y_cuerpo(self):
        path = write_memory(self.root, "-home-u-proj", "una",
                            body="el cuerpo", desc="qué es", kind="feedback",
                            origin="abc123")
        m = memory.read_memory(path, "-home-u-proj")
        self.assertEqual(m["name"], "una")
        self.assertEqual(m["desc"], "qué es")
        self.assertEqual(m["ty"], "feedback")
        self.assertEqual(m["src"], "abc123")
        self.assertEqual(m["body"], "el cuerpo")

    def test_descripcion_entrecomillada_pierde_los_escapes(self):
        # Claude escribe la descripción como string YAML cuando trae comillas.
        path = write_memory(self.root, "-home-u-proj", "q",
                            desc=r'"la máquina \"legion\" y algo"')
        self.assertEqual(memory.read_memory(path, "-home-u-proj")["desc"],
                         'la máquina "legion" y algo')

    def test_sin_frontmatter_cae_al_nombre_del_archivo(self):
        path = write_memory(self.root, "-home-u-proj", "pelada",
                            body="solo texto", frontmatter=False)
        m = memory.read_memory(path, "-home-u-proj")
        self.assertEqual(m["name"], "pelada")
        self.assertEqual(m["ty"], "—")
        self.assertEqual(m["body"], "solo texto")

    def test_junta_los_enlaces_sin_repetir(self):
        path = write_memory(self.root, "-home-u-proj", "l",
                            body="[[uno]] y [[dos]] y otra vez [[uno]]")
        self.assertEqual(memory.read_memory(path, "-home-u-proj")["ln"],
                         ["dos", "uno"])


class TestCarga(MemoryCase):
    def test_resuelve_la_ruta_del_proyecto_desde_las_sesiones(self):
        simple_tree(self.root)
        memory_tree(self.root)
        _, mems = self.cargar()
        deploy = next(m for m in mems if m["name"] == "deploy-docker")
        self.assertEqual(deploy["p"], "/home/u/proj")

    def test_sin_sesiones_deja_el_nombre_codificado(self):
        # No se puede invertir: "/" y "." se codifican los dos como "-".
        memory_tree(self.root)
        _, mems = self.cargar()
        self.assertEqual(
            next(m for m in mems if m["name"] == "deploy-docker")["p"],
            "-home-u-proj")

    def test_ignora_los_directorios_memory_vacios(self):
        memory_tree(self.root)
        _, mems = self.cargar()
        self.assertNotIn("-home-u-vacio", {m["project_dir"] for m in mems})

    def test_marca_lo_que_esta_en_el_indice(self):
        memory_tree(self.root)
        _, mems = self.cargar()
        por_nombre = {m["name"]: m for m in mems}
        self.assertTrue(por_nombre["deploy-docker"]["ix"])
        self.assertFalse(por_nombre["suelta"]["ix"])
        self.assertTrue(por_nombre["suelta"]["hix"])
        self.assertFalse(por_nombre["sin-indice"]["hix"])

    def test_ordena_por_fecha_descendente(self):
        memory_tree(self.root)
        _, mems = self.cargar()
        fechas = [m["l"] for m in mems]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

    def test_public_records_saca_las_claves_internas(self):
        memory_tree(self.root)
        _, mems = self.cargar()
        for m in memory.public_records(mems):
            self.assertNotIn("project_dir", m)
        # El original no se toca.
        self.assertIn("project_dir", mems[0])


class TestFiltros(MemoryCase):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        memory_tree(self.root)
        _, self.mems = self.cargar()

    def test_por_tipo(self):
        r = memory.apply_filters(self.mems, kind="reference")
        self.assertEqual([m["name"] for m in r], ["roles-db"])

    def test_por_proyecto(self):
        r = memory.apply_filters(self.mems, project="/home/u/proj")
        self.assertNotIn("sin-indice", [m["name"] for m in r])

    def test_la_query_entra_al_cuerpo(self):
        r = memory.apply_filters(self.mems, query="make up")
        self.assertEqual([m["name"] for m in r], ["deploy-docker"])

    def test_la_query_tambien_mira_la_descripcion(self):
        r = memory.apply_filters(self.mems, query="huérfana")
        self.assertEqual([m["name"] for m in r], ["suelta"])


class TestPick(MemoryCase):
    def setUp(self):
        super().setUp()
        memory_tree(self.root)
        _, self.mems = self.cargar()

    def test_por_indice(self):
        self.assertEqual(memory.pick(self.mems, "1"), self.mems[0])

    def test_indice_fuera_de_rango(self):
        with self.assertRaises(sessions.SessionError):
            memory.pick(self.mems, "99")

    def test_por_prefijo(self):
        self.assertEqual(memory.pick(self.mems, "deploy")["name"], "deploy-docker")

    def test_cae_a_subcadena(self):
        self.assertEqual(memory.pick(self.mems, "docker")["name"], "deploy-docker")

    def test_sin_coincidencias(self):
        with self.assertRaises(sessions.SessionError):
            memory.pick(self.mems, "nada-que-ver")

    def test_ambiguo(self):
        write_memory(self.root, "-home-u-proj", "deploy-otro")
        _, mems = self.cargar()
        with self.assertRaises(sessions.SessionError) as ctx:
            memory.pick(mems, "deploy")
        self.assertIn("ambiguo", str(ctx.exception))


class TestAuditoria(MemoryCase):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        memory_tree(self.root)
        self.ss, self.mems = self.cargar()
        self.report = memory.audit(self.mems, self.ss, root=self.root)

    def test_proyecto_sin_indice(self):
        self.assertEqual([m["name"] for m in self.report["sin_indice"]],
                         ["sin-indice"])

    def test_memoria_fuera_del_indice(self):
        self.assertEqual([m["name"] for m in self.report["sin_listar"]],
                         ["suelta"])

    def test_entrada_del_indice_sin_archivo(self):
        self.assertEqual([n for _, n in self.report["indice_fantasma"]],
                         ["borrada-hace-rato"])

    def test_enlace_roto(self):
        rotos = [link for _, link in self.report["enlaces_rotos"]]
        self.assertEqual(rotos, ["no-existe"])  # [[roles-db]] sí resuelve

    def test_sesion_de_origen_perdida(self):
        # deploy-docker apunta a una sesión que existe; sin-indice no.
        self.assertEqual([m["name"] for m in self.report["origen_perdido"]],
                         ["sin-indice"])

    def test_arbol_consistente_no_reporta_nada(self):
        limpio = os.path.join(self._tmp.name, "limpio")
        os.makedirs(limpio)
        write_memory(limpio, "-p", "sola", body="sin enlaces")
        write_index(limpio, "-p", ["sola"])
        mems = memory.load_memories([], root=limpio)
        self.assertEqual(memory.audit_total(memory.audit(mems, [], root=limpio)), 0)


class TestBorrado(MemoryCase):
    def setUp(self):
        super().setUp()
        memory_tree(self.root)
        _, self.mems = self.cargar()

    def por_nombre(self, name):
        return next(m for m in self.mems if m["name"] == name)

    def test_borra_el_archivo_y_lo_desindexa(self):
        m = self.por_nombre("deploy-docker")
        self.assertTrue(memory.delete(m, root=self.root))
        self.assertFalse(os.path.exists(memory.memory_path(m, self.root)))
        self.assertNotIn("deploy-docker",
                         memory.read_index("-home-u-proj", self.root))

    def test_desindexar_no_toca_las_otras_lineas(self):
        memory.unindex(self.por_nombre("deploy-docker"), root=self.root)
        self.assertIn("roles-db", memory.read_index("-home-u-proj", self.root))

    def test_borrar_una_que_no_estaba_indexada(self):
        m = self.por_nombre("suelta")
        self.assertFalse(memory.delete(m, root=self.root))
        self.assertFalse(os.path.exists(memory.memory_path(m, self.root)))

    def test_borrar_sin_memory_md(self):
        m = self.por_nombre("sin-indice")
        self.assertFalse(memory.delete(m, root=self.root))
        self.assertFalse(os.path.exists(memory.memory_path(m, self.root)))


if __name__ == "__main__":
    unittest.main()
