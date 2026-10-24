#!/usr/bin/env python3
"""Exercise the real HTTP API and NYT parsing with synthetic upstream data."""

import gzip
import http.client
import io
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from crossplay_server import CrossplayClient, CrossplayError, Handler, SESSION_COOKIE
from tools.mock_nyt import EMPTY_COOKIE, EXPIRED_COOKIE, MOCK_COOKIE, OUTAGE_COOKIE
from tools.test_support import mock_server

ROOT = Path(__file__).resolve().parent


class CrossplayAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.stack.enter_context(patch.dict(os.environ, {'VERCEL': ''}))
        # HTTP tests use http.client. Any accidental upstream request must fail.
        cls.stack.enter_context(patch('crossplay_server.urllib.request.urlopen',
                                    side_effect=AssertionError('Unexpected upstream network request')))
        cls.base_url = cls.stack.enter_context(mock_server())

    def setUp(self):
        self.cookie = ''
        with Handler.sessions_lock:
            Handler.sessions.clear()

    def request(self, method, route, body=None, headers=None, raw=False):
        parsed = urlsplit(self.base_url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        self.addCleanup(connection.close)
        request_headers = {'Origin': self.base_url, 'Cookie': self.cookie}
        if body is not None and not raw:
            body = json.dumps(body)
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        path = route if route.startswith('/') else '/api/crossplay/' + route
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        response_headers = dict(response.getheaders())
        payload = response.read()
        if response_headers.get('Content-Type') == 'application/json':
            payload = json.loads(payload)
        return response.status, payload, response_headers

    def connect(self, cookie=MOCK_COOKIE):
        status, payload, headers = self.request('PUT', 'token', {'nyt_s': cookie})
        self.assertEqual(status, 200, payload)
        self.cookie = headers['Set-Cookie'].split(';', 1)[0]
        return payload, headers

    def test_health_and_disconnected_state(self):
        self.assertEqual(self.request('GET', '/health')[:2], (200, {'ok': True, 'mock_nyt': True}))
        self.assertEqual(self.request('GET', 'status')[:2], (200, {'configured': False}))
        for endpoint in ('me', 'games', 'games/mockgame01/review'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.request('GET', endpoint)[0], 409)

    def test_connect_identity_and_cookie_privacy(self):
        payload, headers = self.connect()
        self.assertEqual(payload, {'configured': True, 'user_id': 1001, 'username': 'Demo Player'})
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        self.assertNotIn(MOCK_COOKIE, json.dumps([payload, headers]))
        self.assertEqual(self.request('GET', 'status')[:2], (200, {'configured': True}))
        self.assertEqual(self.request('GET', 'me')[1]['username'], 'Demo Player')

    def test_recent_games_filter_and_summaries(self):
        self.connect()
        status, payload, _ = self.request('GET', 'games')
        self.assertEqual(status, 200)
        self.assertEqual([game['id'] for game in payload['games']],
                         ['mockgame01', 'mockgame02', 'mockactive01'])
        self.assertEqual(payload['games'][0]['opponent'], 'Demo Cedar')
        self.assertEqual(payload['games'][0]['my_score'], 10)
        self.assertNotIn('game_data', json.dumps(payload))

    def test_review_reconstructs_positions_racks_scores_and_blanks(self):
        self.connect()
        status, review, _ = self.request('GET', 'games/mockgame01/review')
        self.assertEqual(status, 200, review)
        turns = review['turns']
        self.assertEqual(len(turns), 6)
        self.assertEqual([turn['mine'] for turn in turns], [True, False] * 3)
        self.assertEqual(turns[0]['grid'], ['.' * 15] * 15)
        self.assertEqual(turns[0]['grid_after'][7], '......CAT......')
        self.assertEqual(turns[0]['rack'], 'ACERSTU')
        self.assertEqual(turns[0]['bag_count'], 86)
        self.assertEqual(turns[1]['mover_score'], 0)
        self.assertEqual(turns[1]['other_score'], 5)
        self.assertEqual(turns[2]['rack'], '?EINRSU')
        self.assertEqual(turns[2]['grid_after'][7], '.....sCAT......')
        self.assertEqual(turns[3]['swapped_tiles'], 'UV')
        self.assertEqual(turns[3]['grid'], turns[3]['grid_after'])
        self.assertEqual(turns[4]['mover_score'], 10)
        self.assertEqual(turns[4]['other_score'], 4)
        for before, after in zip(turns, turns[1:]):
            self.assertEqual(before['grid_after'], after['grid'])

    def test_detail_fallback_and_opponent_opens(self):
        self.connect()
        status, review, _ = self.request('GET', 'games/mockgame02/review')
        self.assertEqual(status, 200, review)
        self.assertEqual(review['opponent'], 'Demo River')
        self.assertFalse(review['turns'][0]['mine'])
        self.assertTrue(review['turns'][1]['mine'])

    def test_active_foreign_missing_and_invalid_games(self):
        self.connect()
        for game_id, expected in (('mockactive01', 403), ('mockforeign01', 403),
                                  ('missing001', 404), ('bad!', 400)):
            with self.subTest(game_id=game_id):
                status, payload, _ = self.request('GET', f'games/{game_id}/review')
                self.assertEqual(status, expected, payload)
                self.assertIn('error', payload)
                self.assertNotIn('turns', payload)

    def test_empty_account(self):
        self.connect(EMPTY_COOKIE)
        self.assertEqual(self.request('GET', 'games')[:2], (200, {'games': []}))

    def test_rejected_cookie_does_not_create_session(self):
        status, payload, headers = self.request('PUT', 'token', {'nyt_s': EXPIRED_COOKIE})
        self.assertEqual(status, 401, payload)
        self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(self.request('GET', 'status')[1], {'configured': False})

    def test_upstream_failure(self):
        self.connect(OUTAGE_COOKIE)
        status, payload, _ = self.request('GET', 'games')
        self.assertEqual(status, 502)
        self.assertEqual(payload, {'error': 'NYT returned HTTP 503'})

    def test_forget_removes_server_session(self):
        self.connect()
        old_cookie = self.cookie
        status, payload, headers = self.request('DELETE', 'token')
        self.assertEqual((status, payload), (200, {'configured': False}))
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertEqual(self.request('GET', 'games', headers={'Cookie': old_cookie})[0], 409)

    def test_sessions_are_isolated_rotated_and_expire(self):
        self.connect()
        old_cookie = self.cookie
        self.assertEqual(self.request('GET', 'status', headers={'Cookie': ''})[1], {'configured': False})
        self.connect()
        self.assertNotEqual(self.cookie, old_cookie)
        self.assertEqual(self.request('GET', 'status', headers={'Cookie': old_cookie})[1], {'configured': False})
        session_id = self.cookie.removeprefix(SESSION_COOKIE + '=')
        with Handler.sessions_lock:
            Handler.sessions[session_id]['expires_at'] = time.time() - 1
        self.assertEqual(self.request('GET', 'games')[0], 409)

    def test_origin_and_host_guards(self):
        for method in ('GET', 'PUT', 'POST', 'DELETE'):
            for headers in ({'Origin': 'https://untrusted.invalid'}, {'Host': 'untrusted.invalid'}):
                with self.subTest(method=method, headers=headers):
                    self.assertEqual(self.request(method, 'token', {'nyt_s': MOCK_COOKIE}, headers)[0], 403)
        self.assertEqual(self.request('PUT', 'token', {'nyt_s': MOCK_COOKIE}, {'Origin': ''})[0], 403)

    def test_invalid_bodies_and_cookie_values(self):
        for body, content_type, expected in (
                ('{', 'application/json', 400), ('[]', 'application/json', 400),
                ('{}', 'text/plain', 415), ('', 'application/json', 400),
                ('x' * 16385, 'application/json', 400)):
            with self.subTest(body=body[:15], content_type=content_type):
                self.assertEqual(self.request('PUT', 'token', body,
                                             {'Content-Type': content_type}, raw=True)[0], expected)
        for value in ('short', 'a' * 20 + '; other=value'):
            self.assertEqual(self.request('PUT', 'token', {'nyt_s': value})[0], 400)

    def test_unknown_routes_and_methods(self):
        self.connect()
        self.assertEqual(self.request('GET', 'unknown')[0], 404)
        self.assertEqual(self.request('POST', 'games')[0], 405)
        self.assertEqual(self.request('GET', 'token')[0], 405)

    def test_private_files_are_not_served(self):
        for path in ('/.git/config', '/%252egit/config', '/crossplay_server.py',
                     '/tools/fixtures/nyt.json', '/tools/mock_nyt.py', '/package.json'):
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.request('GET', '/')[0], 200)

    def test_mock_mode_is_rejected_on_vercel(self):
        result = subprocess.run([sys.executable, str(ROOT / 'crossplay_server.py'), '--mock-nyt'],
                                env={**os.environ, 'VERCEL': '1'}, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn('only available for local development', result.stderr)


class NYTTransportTest(unittest.TestCase):
    def test_gzip_response_and_request_headers(self):
        response = io.BytesIO(gzip.compress(b'{"player":{"user_id":1001}}'))
        response.headers = {'Content-Encoding': 'gzip'}
        with patch('crossplay_server.urllib.request.urlopen', return_value=response) as urlopen:
            self.assertEqual(CrossplayClient(MOCK_COOKIE).me(), {'user_id': 1001, 'username': None})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://www.nytimes.com/svc/games/player')
        self.assertEqual(request.get_header('Cookie'), 'NYT-S=' + MOCK_COOKIE)
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 15)

    def test_http_and_connection_errors(self):
        for code, expected in ((401, 401), (403, 401), (404, 404), (429, 502), (503, 502)):
            with self.subTest(code=code):
                error = urllib.error.HTTPError('https://example.invalid', code, 'unavailable', {}, None)
                with patch('crossplay_server.urllib.request.urlopen', side_effect=error):
                    with self.assertRaises(CrossplayError) as caught:
                        CrossplayClient(MOCK_COOKIE).get('/svc/games/player')
                self.assertEqual(caught.exception.status, expected)
        with patch('crossplay_server.urllib.request.urlopen', side_effect=urllib.error.URLError('offline')):
            with self.assertRaisesRegex(CrossplayError, 'Could not reach NYT'):
                CrossplayClient(MOCK_COOKIE).me()


if __name__ == '__main__':
    unittest.main(verbosity=2)
