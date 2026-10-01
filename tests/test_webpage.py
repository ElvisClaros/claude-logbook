import json
import os
import re
import tempfile
import unittest

from claude_logbook import webpage

PAYLOAD_RE = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>', re.S)

LOG_NAME = {"id": "abc", "p": "/proj", "u": 1, "c": [{"r": "u", "x": "hello"}]}


class TestPayload(unittest.TestCase):
    def test_escapes_the_closing_tag(self):
        raw = webpage.encode_payload({"s": [{"x": "look at this </script> here"}]})
        self.assertNotIn("</", raw)
        self.assertEqual(json.loads(raw)["s"][0]["x"], "look at this </script> here")

    def test_does_not_escape_to_ascii(self):
        self.assertIn("é", webpage.encode_payload({"s": [{"x": "café"}]}))

    def test_separates_sessions_from_memories(self):
        payload = webpage.build_payload([LOG_NAME], [{"name": "something"}])
        self.assertEqual(payload["s"], [LOG_NAME])
        self.assertEqual(payload["m"], [{"name": "something"}])

    def test_no_memories_still_has_the_key(self):
        self.assertEqual(webpage.build_payload([LOG_NAME])["m"], [])


class TestRender(unittest.TestCase):
    def test_replaces_the_marker(self):
        html = webpage.render([LOG_NAME], template="<b>__DATA__</b>")
        self.assertNotIn("__DATA__", html)
        self.assertIn('"id":"abc"', html)

    def test_fails_if_the_template_has_no_marker(self):
        with self.assertRaises(webpage.TemplateError):
            webpage.render([LOG_NAME], template="<b>no marker</b>")

    def test_fails_if_the_marker_is_repeated(self):
        with self.assertRaises(webpage.TemplateError):
            webpage.render([LOG_NAME], template="__DATA__ and __DATA__")

    def test_transcript_with_html_does_not_cut_the_script(self):
        # The case that motivates the escape: a session that talked about this very
        # generator has "</script>" and "__DATA__" inside the text.
        dangerous = dict(LOG_NAME, c=[{"r": "u", "x": "type </script><img> and __DATA__"}])
        html = webpage.render([dangerous])

        blocks = PAYLOAD_RE.findall(html)
        self.assertEqual(len(blocks), 1)
        round_trip = json.loads(blocks[0])
        self.assertEqual(round_trip["s"][0]["c"][0]["x"],
                         "type </script><img> and __DATA__")


class TestTemplate(unittest.TestCase):
    def setUp(self):
        self.html = webpage.template_text()

    def test_packaged_template_has_a_single_marker(self):
        self.assertEqual(self.html.count(webpage.MARKER), 1)

    def test_is_a_complete_document(self):
        # Without doctype and charset, a file:// opens in quirks mode with the
        # system encoding: accents come out broken.
        self.assertTrue(self.html.lstrip().startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', self.html)
        self.assertIn('name="viewport"', self.html)
        self.assertTrue(self.html.rstrip().endswith("</html>"))

    def test_makes_no_network_requests(self):
        for attribute in ("src=\"http", "href=\"http", "@import"):
            self.assertNotIn(attribute, self.html)

    def test_another_template_can_be_passed(self):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as f:
            f.write("custom __DATA__")
            path_str = f.name
        self.addCleanup(os.unlink, path_str)
        self.assertTrue(webpage.template_text(path_str).startswith("custom"))


class TestWrite(unittest.TestCase):
    def test_writes_and_summarizes(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "s.html")
            stats = webpage.write(
                [LOG_NAME, dict(LOG_NAME, id="def", p="/other", u=2)], out)
            self.assertEqual(stats, {"sessions": 2, "projects": 2,
                                     "messages": 3, "blocks": 2,
                                     "memories": 0})
            with open(out, encoding="utf-8") as f:
                self.assertEqual(len(PAYLOAD_RE.findall(f.read())), 1)


if __name__ == "__main__":
    unittest.main()
