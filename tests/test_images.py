import base64
import json
import os

from claude_logbook import sessions as S

from .fixtures import assistant, user, write_session
from .test_share import ShareCase

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
SRC = "data:image/png;base64," + PNG


def image(kind="image/png", data=PNG):
    return {"type": "image", "source": {"type": "base64", "media_type": kind, "data": data}}


def pasted(*blocks, **extra):
    ev = user("x", **extra)
    ev["message"]["content"] = list(blocks)
    return ev


class TestImages(ShareCase):
    ID = "eeeeeeee-0000-0000-0000-000000000001"

    def setUp(self):
        super().setUp()
        tool_result = {"type": "tool_result", "tool_use_id": "t1", "content": [
            {"type": "text", "text": "read it"}, image("image/jpeg")]}
        self.path = write_session(self.root, "-home-u-proj", self.ID, [
            pasted({"type": "text", "text": "look at this"}, image()),
            assistant("Reading the other one.", tools=[("Read", {"file_path": "/x/a.jpg"})]),
            pasted(tool_result),
            pasted(image("image/svg+xml", "PHN2Zz4=")),
        ])

    def test_the_record_has_no_pictures(self):
        rec = S.read_session(self.path)
        self.assertEqual([m["r"] for m in rec["c"]], ["u", "i", "a", "t", "v", "i"])
        self.assertFalse(any("src" in m for m in rec["c"]))
        self.assertEqual(rec["u"], 1)
        self.assertEqual(S.count_images(rec), (3, 0))

    def test_with_images_brings_only_raster_ones(self):
        rec = S.read_session(self.path, images=True)
        srcs = [m.get("src") for m in rec["c"] if m["r"] in "iv"]
        self.assertEqual(srcs[0], SRC)
        self.assertTrue(srcs[1].startswith("data:image/jpeg;base64,"))
        self.assertIsNone(srcs[2])  # svg is not shown
        self.assertEqual(S.count_images(rec), (3, 2))

    def test_json_and_html_only_with_the_flag(self):
        _, out, _ = self.run_cli("-s", "eeeeeeee", "--json")
        self.assertNotIn(PNG, out)
        _, out, _ = self.run_cli("-s", "eeeeeeee", "--json", "--images")
        self.assertIn(SRC, json.dumps(json.loads(out)))
        page = os.path.join(self.home, "p.html")
        self.run_cli("-s", "eeeeeeee", "--html", page, "--images")
        with open(page, encoding="utf-8") as f:
            self.assertIn(PNG, f.read())

    def test_images_need_a_session(self):
        code, _, err = self.run_cli("--json", "--images")
        self.assertEqual(code, 2)
        self.assertIn("needs a session", err)

    def test_share_leaves_them_out_unless_asked(self):
        _, _, err = self.run_cli("-s", "eeeeeeee", "--share", "-y")
        self.assertIn("3 images left out", err)
        body = self.fake.requests[-1][2]
        self.assertNotIn(PNG, json.dumps(body))

        _, _, err = self.run_cli("-s", "eeeeeeee", "--share", "-y", "--images")
        self.assertIn("2 images included", err)
        self.assertIn(SRC, json.dumps(self.fake.requests[-1][2]))

    def test_too_large_suggests_without_images(self):
        self.fake.force = (413, "payload larger than 20971520 bytes")
        code, _, err = self.run_cli("-s", "eeeeeeee", "--share", "-y", "--images")
        self.assertEqual(code, 2)
        self.assertIn("try it without --images", err)
