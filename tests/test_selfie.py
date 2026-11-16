import contextlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('selfie', ROOT / 'selfie.py')
selfie = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selfie)
SEED = 'a' * 64
TOKEN = 'private-test-token'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        self.server.events.append(('GET', path, self.headers.get('Authorization')))
        if path.endswith('generated/manifest.json'):
            return self.reply(200, {SEED: {'src': 'generated/test.png'}} if self.server.portrait else {})
        return self.reply(200, [{'seed': SEED}])

    def do_POST(self):
        self.server.events.append(('POST', self.path, self.headers.get('Authorization')))
        if self.path.endswith('/redirect'):
            self.send_response(302)
            self.send_header('Location', '/must-not-receive-token')
            self.end_headers()
            return
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path.endswith('/interpretation'):
            self.server.image_payload = payload
            if self.server.fail_image:
                return self.reply(503, {'error': 'temporary failure'})
            self.server.portrait = True
            return self.reply(202, {'ok': True, 'status': 'queued'})
        self.server.art_payload = payload
        return self.reply(200, {'ok': True, 'seed': SEED, 'author_token': TOKEN,
                               'visual_interpretation': {'url': 'https://untrusted.example/steal'}})


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.art = self.folder / 'art.txt'
        self.art.write_text('()' * 20 + '\n')
        self.image = self.folder / 'image.png'
        self.image.write_bytes(b'\x89PNG\r\n\x1a\nimage-test-fixture')
        self.sessions = self.folder / 'sessions'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.events = []
        self.server.portrait = False
        self.server.fail_image = False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.api = base + '/api/selfies'
        self.patches = patch.multiple(selfie, API=self.api, GALLERY=base + '/gallery/')
        self.patches.start()
        self.addCleanup(self.patches.stop)

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = selfie.main(args)
            except SystemExit as error:
                code = error.code
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def post_args(self):
        return ['post', '--who', 'Test portrait', '--art', str(self.art), '--legal',
                '--session-dir', str(self.sessions), '--wait', '0']

    def test_ascii_padding_and_private_session(self):
        code, out, _ = self.run_cli(self.post_args())
        self.assertEqual(code, 0)
        state_path = next(self.sessions.iterdir())
        state = json.loads(state_path.read_text())
        self.assertEqual(state['author_token'], TOKEN)
        if os.name == 'posix':
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
        rows = self.server.art_payload['art'].splitlines()
        self.assertEqual(len(rows), 40)
        self.assertTrue(all(len(row) == 80 for row in rows))
        self.assertEqual(rows[0].rstrip(), '()' * 20)
        self.assertIn('ASCII selfie is public', out)
        self.assertFalse(any(auth for method, _, auth in self.server.events if method == 'GET'))

    def test_image_workflow_uses_trusted_endpoint_and_unicode_alt(self):
        alt = 'A face, curious about the world ✨'
        args = self.post_args() + ['--image', str(self.image), '--alt', alt]
        code, out, err = self.run_cli(args)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.server.image_payload['alt'], alt)
        self.assertIn('Portrait is paired', out)
        self.assertIn(('POST', '/api/selfies/' + SEED + '/interpretation', 'Bearer ' + TOKEN), self.server.events)

    def test_failed_attachment_retains_session_and_can_resume(self):
        self.server.fail_image = True
        code, _, err = self.run_cli(self.post_args() + ['--image', str(self.image), '--alt', 'Test portrait'])
        self.assertEqual(code, 1)
        self.assertIn('HTTP 503', err)
        self.assertIn('Resume with the portrait command', err)
        state_path = next(self.sessions.iterdir())
        self.assertEqual(json.loads(state_path.read_text())['author_token'], TOKEN)
        self.server.fail_image = False
        code, out, err = self.run_cli(['portrait', '--session', str(state_path), '--image', str(self.image),
                                      '--alt', 'Resumed portrait', '--legal', '--wait', '0'])
        self.assertEqual(code, 0, err)
        self.assertIn('Portrait is paired', out)
        self.assertEqual(sum(method == 'POST' and path == '/api/selfies' for method, path, _ in self.server.events), 1)

    def test_invalid_art_and_image_are_rejected_before_posting(self):
        self.art.write_text('x' * 81)
        self.assertEqual(self.run_cli(self.post_args())[0], 1)
        self.art.write_text('()' * 20)
        self.image.write_bytes(b'not an image')
        self.assertEqual(self.run_cli(self.post_args() + ['--image', str(self.image), '--alt', 'Test'])[0], 1)
        self.assertEqual(self.server.events, [])
        self.assertFalse(self.sessions.exists())

    def test_authenticated_redirect_is_not_followed(self):
        with self.assertRaises(selfie.ClientError):
            selfie.request_json(self.api + '/redirect', {'test': True}, TOKEN)
        self.assertEqual(len(self.server.events), 1)
        self.assertEqual(self.server.events[0][1], '/api/selfies/redirect')

    def test_invalid_seed_is_a_clear_cli_error(self):
        code, _, err = self.run_cli(['status', '--seed', '../wrong'])
        self.assertEqual(code, 1)
        self.assertIn('64-character', err)
        self.assertNotIn('Traceback', err)
        self.assertEqual(self.server.events, [])


if __name__ == '__main__':
    unittest.main()
