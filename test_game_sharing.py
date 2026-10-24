"""Exercise sharing with synthetic games and an in-memory persistence stub."""

import copy
import http.client
import json
import os
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from crossplay_server import CrossplayError, Handler, SHARE_TOKEN_RE, game_review


GAME = {
    'id': 'game0001', 'game_status': 'completed', 'turn_count': 2,
    'timestamp': 1792800000,
    'players': [
        {'id': 'alice', 'username': 'Alice', 'score': 10},
        {'id': 'bob', 'username': 'Bob', 'score': 2},
    ],
    'game_data': {'players': [
        {'id': 'alice', 'tray': 'ERS?UVW', 'plays': [{'action': 'CAT 8G 10', 'tray': 'CATERS?'}]},
        {'id': 'bob', 'tray': 'TILEDSO', 'plays': [{'action': '(A)T H8 2', 'tray': 'ATTILED'}]},
    ]},
}
OWNER = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'


class FakeClient:
    def me(self):
        return {'user_id': 'alice', 'username': 'Alice'}

    def game(self, game_id):
        game = copy.deepcopy(GAME)
        game['id'] = game_id
        if game_id == 'ongoing1':
            game['game_status'] = 'active'
        if game_id == 'foreign1':
            game['players'][0]['id'] = 'charlie'
        return game


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class PersistentHandler(QuietHandler):
    rows = {}
    calls = []

    def current_session(self):
        user = self.current_supabase_user(required=False)
        return (user['id'] if user else None), None

    def current_supabase_user(self, required=True):
        if self.headers.get('Authorization') == 'Bearer owner':
            return {'id': OWNER, 'email': 'private@example.invalid'}
        if self.headers.get('Authorization') == 'Bearer other':
            return {'id': OTHER, 'email': 'other@example.invalid'}
        if required:
            raise CrossplayError('Sign in first', 401)
        return None

    def supabase_data_request(self, method, table, params=None, payload=None, prefer=None):
        self.calls.append((method, table, copy.deepcopy(params)))
        if table == 'game_analyses':
            return [{'analysis_version': 'quackle-equity-v1', 'win_trend': {'state': 'done', 'points': []},
                     'move_quality': None}]
        if table != 'crossplay_games':
            raise AssertionError('Sharing must not access credentials')
        rows = list(self.rows.values())
        for field in ('user_id', 'nyt_game_id', 'share_token'):
            value = params.get(field)
            if value == 'is.null':
                rows = [row for row in rows if row.get(field) is None]
            elif value:
                rows = [row for row in rows if row.get(field) == value[3:]]
        if method == 'PATCH':
            for row in rows:
                row.update(payload)
        elif method != 'GET':
            raise AssertionError('Unexpected persistence mutation')
        fields = params['select'].split(',')
        return [{field: copy.deepcopy(row.get(field)) for field in fields} for row in rows]


class SharingTests(unittest.TestCase):
    handler = QuietHandler
    vercel = ''

    def setUp(self):
        self.environment = patch.dict(os.environ, {'VERCEL': self.vercel})
        self.environment.start()
        Handler.sessions.clear()
        Handler.sessions['owner-session'] = {'client': FakeClient(), 'expires_at': time.time() + 600}
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        Handler.sessions.clear()
        self.environment.stop()

    def request(self, route, owner=False, method='GET', origin=None, other=False):
        connection = http.client.HTTPConnection(*self.server.server_address)
        headers = {}
        if owner:
            headers = {'Cookie': 'crossplay_session=owner-session', 'Authorization': 'Bearer owner'}
        if other:
            headers['Authorization'] = 'Bearer other'
        if origin:
            headers['Origin'] = origin
        connection.request(method, '/api/crossplay/' + route, headers=headers)
        response = connection.getresponse()
        body = json.loads(response.read())
        status = response.status
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        connection.close()
        return status, body

    def open_game(self, game_id='game0001'):
        status, review = self.request('games/' + game_id + '/review', owner=True)
        self.assertEqual(status, 200, review)
        self.assertTrue(SHARE_TOKEN_RE.fullmatch(review['share_token']))
        return review

    def test_guest_can_replay_one_game_without_credentials(self):
        review = self.open_game()
        status, shared = self.request('shared/' + review['share_token'])
        self.assertEqual(status, 200)
        self.assertEqual(shared['turns'], review['turns'])
        self.assertEqual(shared['my_name'], 'Alice')
        self.assertEqual(shared['opponent'], 'Bob')
        self.assertNotIn('user_id', shared)
        self.assertNotIn('email', shared)
        self.assertNotIn('nyt_s', shared)

    def test_reopening_keeps_link_stable(self):
        self.assertEqual(self.open_game()['share_token'], self.open_game()['share_token'])

    def test_different_games_have_different_links(self):
        first, second = self.open_game(), self.open_game('game0002')
        self.assertNotEqual(first['share_token'], second['share_token'])
        self.assertEqual(self.request('shared/' + first['share_token'])[1]['id'], first['id'])

    def test_invalid_unknown_and_bare_game_ids_are_not_public(self):
        for token in ('bad-token', 'game0001', 'x' * 43, ''):
            self.assertEqual(self.request('shared/' + token)[0], 404)
        self.assertIn(self.request('games/game0001/review')[0], (401, 409))
        self.assertIn(self.request('games')[0], (401, 409))

    def test_public_endpoint_is_read_only_and_rejects_cross_origin(self):
        token = self.open_game()['share_token']
        origin = 'http://127.0.0.1:' + str(self.server.server_port)
        for method in ('POST', 'PUT', 'DELETE'):
            self.assertEqual(self.request('shared/' + token, method=method, origin=origin)[0], 405)
        self.assertEqual(self.request('shared/' + token, origin='https://untrusted.invalid')[0], 403)

    def test_local_shares_expire_with_the_session(self):
        token = self.open_game()['share_token']
        Handler.sessions['owner-session']['expires_at'] = 0
        self.assertEqual(self.request('shared/' + token)[0], 404)

    def test_ongoing_and_other_players_games_cannot_be_shared(self):
        for game_id in ('ongoing1', 'foreign1'):
            self.assertEqual(self.request('games/' + game_id + '/review', owner=True)[0], 403)
        self.assertFalse(Handler.sessions['owner-session'].get('shared_reviews'))


class PersistentSharingTests(SharingTests):
    handler = PersistentHandler
    vercel = '1'

    def setUp(self):
        PersistentHandler.rows = {}
        PersistentHandler.calls = []
        for game_id in ('game0001', 'game0002', 'ongoing1', 'foreign1'):
            review = game_review(FakeClient().game('game0001'), 'alice')
            review['id'] = game_id
            if game_id == 'ongoing1':
                review['status'] = 'active'
            PersistentHandler.rows[game_id] = {
                'user_id': OTHER if game_id == 'foreign1' else OWNER,
                'nyt_game_id': game_id, 'review': review, 'share_token': None,
            }
        super().setUp()

    def test_local_shares_expire_with_the_session(self):
        token = self.open_game()['share_token']
        Handler.sessions.clear()
        self.assertEqual(self.request('shared/' + token)[0], 200)

    def test_ongoing_and_other_players_games_cannot_be_shared(self):
        self.assertEqual(self.request('games/ongoing1/review', owner=True)[0], 403)
        self.assertEqual(self.request('games/foreign1/review', owner=True)[0], 409)
        self.assertIsNone(PersistentHandler.rows['ongoing1']['share_token'])
        self.assertIsNone(PersistentHandler.rows['foreign1']['share_token'])

    def test_guest_analysis_is_loaded_from_shared_games_owner(self):
        token = self.open_game()['share_token']
        status, review = self.request('shared/' + token, other=True)
        self.assertEqual(status, 200)
        self.assertEqual(review['stored_analysis']['win_trend']['state'], 'done')
        analysis_query = PersistentHandler.calls[-1][2]
        self.assertEqual(analysis_query['user_id'], 'eq.' + OWNER)
        self.assertEqual(analysis_query['nyt_game_id'], 'eq.game0001')

    def test_share_link_never_grants_analysis_write_access(self):
        self.open_game()
        origin = 'http://127.0.0.1:' + str(self.server.server_port)
        self.assertEqual(self.request('games/game0001/analysis', method='PUT', origin=origin)[0], 401)

    def test_concurrent_token_creation_reuses_the_winner(self):
        token = self.open_game()['share_token']
        # Simulate a stale reader that did not see the token set by another request.
        with patch.object(PersistentHandler, 'saved_game_review', return_value=game_review(GAME, 'alice')):
            self.assertEqual(self.open_game()['share_token'], token)

    def test_public_reader_rejects_unfinished_stored_review(self):
        token = self.open_game()['share_token']
        PersistentHandler.rows['game0001']['review']['status'] = 'active'
        self.assertEqual(self.request('shared/' + token)[0], 404)


if __name__ == '__main__':
    unittest.main()
