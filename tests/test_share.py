import json
import os
import stat
import threading
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from claude_logbook import share

from .fixtures import simple_tree
from .test_cli import CliCase


class FakeServer:
    """Just enough of the share API: remembers shares and checks secrets."""

    def __init__(self):
        self.shares = {}
        self.requests = []
        self.force = None  # (code, body) to answer the next write with
        self.n = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, body=None):
                raw = b"" if body is None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def handle_write(self):
                body = self.body() if self.command != "DELETE" else {}
                fake.requests.append((self.command, self.path, body,
                                      self.headers.get("Authorization")))
                if fake.force:
                    code, msg = fake.force
                    fake.force = None
                    return self.reply(code, {"error": msg})
                exp = "2030-01-01T00:00:00Z"
                if self.command == "POST":
                    fake.n += 1
                    sid = f"id{fake.n:08d}"
                    fake.shares[sid] = ("s3cret", body["payload"])
                    return self.reply(201, {"id": sid, "url": f"{fake.url}/share/{sid}",
                                            "secret": "s3cret", "expires": exp})
                sid = self.path.rsplit("/", 1)[1]
                if sid not in fake.shares:
                    return self.reply(404, {"error": "share not found"})
                if self.headers.get("Authorization") != "Bearer " + fake.shares[sid][0]:
                    return self.reply(403, {"error": "wrong secret"})
                if self.command == "PUT":
                    fake.shares[sid] = ("s3cret", body["payload"])
                    return self.reply(200, {"id": sid, "url": f"{fake.url}/share/{sid}",
                                            "expires": exp})
                del fake.shares[sid]
                return self.reply(204)

            do_POST = do_PUT = do_DELETE = handle_write

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ShareCase(CliCase):
    def setUp(self):
        super().setUp()
        simple_tree(self.root)
        self.fake = FakeServer()
        self.addCleanup(self.fake.close)
        env = unittest.mock.patch.dict(os.environ, {
            "XDG_STATE_HOME": os.path.join(self.home, "state"),
            share.SERVER_ENV: self.fake.url,
        })
        env.start()
        self.addCleanup(env.stop)

    def share(self, *extra):
        return self.run_cli("-s", "aaaaaaaa", "--share", "-y", *extra)


class TestShare(ShareCase):
    def test_creates_then_updates_the_same_link(self):
        code, out, err = self.share()
        self.assertEqual(code, 0, err)
        url = out.strip()
        self.assertEqual(url, f"{self.fake.url}/share/id00000001")
        method, path, body, _ = self.fake.requests[0]
        self.assertEqual((method, path, body["expire"]), ("POST", "/api/shares", "30d"))
        self.assertEqual([s["id"] for s in body["payload"]["s"]],
                         ["aaaaaaaa-0000-0000-0000-000000000001"])
        self.assertEqual(body["payload"]["m"], [])
        self.assertNotIn("project_dir", body["payload"]["s"][0])

        code, out, err = self.share("--expire", "7d")
        self.assertEqual(out.strip(), url)
        self.assertIn("Updated", err)
        method, path, body, auth = self.fake.requests[1]
        self.assertEqual((method, path, auth), ("PUT", "/api/shares/id00000001", "Bearer s3cret"))
        self.assertEqual(len(share.load_registry()), 1)

    def test_registry_is_private(self):
        self.share()
        path = share.registry_path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)
        self.assertEqual(share.load_registry()[0]["secret"], "s3cret")

    def test_expired_on_the_server_creates_a_new_one(self):
        self.share()
        self.fake.shares.clear()
        _, out, _ = self.share()
        self.assertEqual(out.strip(), f"{self.fake.url}/share/id00000002")
        self.assertEqual([e["id"] for e in share.load_registry()], ["id00000002"])

    def test_needs_a_session(self):
        code, _, err = self.run_cli("--share", "-y")
        self.assertEqual(code, 2)
        self.assertIn("needs a session", err)

    def test_empty_session_is_refused(self):
        code, _, err = self.run_cli("-s", "bbbbbbbb",
                                    "--share", "-y")
        self.assertEqual(code, 2)
        self.assertIn("no messages", err)
        self.assertEqual(self.fake.requests, [])

    def test_dry_run_uploads_nothing(self):
        code, _, err = self.share("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("nothing was uploaded", err)
        self.assertEqual(self.fake.requests, [])
        self.assertFalse(os.path.exists(share.registry_path()))

    def test_without_terminal_or_yes_it_does_not_upload(self):
        with unittest.mock.patch("claude_logbook.cli.confirm", return_value=False):
            code, _, err = self.run_cli("-s", "aaaaaaaa", "--share")
        self.assertEqual(code, 1)
        self.assertIn("Nothing was uploaded", err)
        self.assertEqual(self.fake.requests, [])

    def test_server_errors(self):
        for code, words in ((429, "limiting requests"), (413, "too large"),
                            (500, "answered 500")):
            self.fake.force = (code, "nope")
            rc, _, err = self.share()
            self.assertEqual(rc, 2)
            self.assertIn(words, err)
        self.assertEqual(share.load_registry(), [])

    def test_unreachable_server(self):
        rc, _, err = self.share("--server", "http://127.0.0.1:9")
        self.assertEqual(rc, 2)
        self.assertIn("cannot reach", err)


class TestSharesAndUnshare(ShareCase):
    def test_list_and_unshare_by_session_prefix(self):
        _, out, _ = self.run_cli("--shares")
        self.assertEqual(out, "")
        self.share()
        _, out, _ = self.run_cli("--shares")
        self.assertIn("Fix the build", out)
        self.assertIn("/share/id00000001", out)

        code, out, _ = self.run_cli("--unshare", "aaaaaaaa")
        self.assertEqual(code, 0)
        self.assertIn("Deleted", out)
        self.assertEqual(self.fake.requests[-1][0], "DELETE")
        self.assertEqual(self.fake.shares, {})
        self.assertEqual(share.load_registry(), [])

    def test_unshare_by_url_when_already_gone(self):
        self.share()
        self.fake.shares.clear()
        code, out, _ = self.run_cli("--unshare", f"{self.fake.url}/share/id00000001.txt")
        self.assertEqual(code, 0)
        self.assertIn("already gone", out)
        self.assertEqual(share.load_registry(), [])

    def test_unknown_ref(self):
        code, _, err = self.run_cli("--unshare", "zzzz")
        self.assertEqual(code, 2)
        self.assertIn("no share of yours", err)


class TestScanSecrets(ShareCase):
    def test_finds_and_locates(self):
        payload = {"s": [{"t": "token=abcdefgh12345", "c": [
            {"r": "u", "x": "my key is sk-ant-api03-" + "x" * 30},
            {"r": "a", "x": "nothing here"},
            {"r": "t", "x": "-----BEGIN OPENSSH PRIVATE KEY-----"},
            {"r": "u", "x": "AKIAABCDEFGHIJKLMNOP and ghp_" + "a" * 36},
        ]}]}
        found = dict(share.scan_secrets(payload))
        self.assertEqual(found["Anthropic API key"], [1])
        self.assertEqual(found["private key"], [3])
        self.assertEqual(found["AWS access key"], [4])
        self.assertEqual(found["GitHub token"], [4])
        self.assertEqual(found["password or token assignment"], [0])
        self.assertNotIn("OpenAI-style API key", found)

    def test_clean_text(self):
        self.assertEqual(share.scan_secrets({"s": [{"t": "x", "c": [
            {"r": "u", "x": "set the password in the env"}]}]}), [])

    def test_warning_is_shown_without_the_value(self):
        from .fixtures import user, write_session
        key = "sk-ant-api03-" + "q" * 30
        write_session(self.root, "-home-u-sec", "dddddddd-0000-0000-0000-000000000009",
                      [user(f"use {key}")])
        _, _, err = self.run_cli("-s", "dddddddd", "--share", "--dry-run")
        warning = next(l for l in err.splitlines() if "warning" in l)
        self.assertIn("possible Anthropic API key in the title, block 1", warning)
        self.assertNotIn(key, warning)
