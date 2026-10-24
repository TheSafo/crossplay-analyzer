"""Synthetic NYT transport for local development; never calls the network.

Keep the real client's identity lookup, subscription parsing, caching, game
lookup and replay intact. Only replace its upstream JSON transport.
"""

import json
from pathlib import Path

from crossplay_server import CrossplayClient, CrossplayError, Handler

MOCK_COOKIE = 'mock-nyt-cookie-for-local-testing'
EMPTY_COOKIE = 'mock-empty-cookie-for-local-testing'
OUTAGE_COOKIE = 'mock-outage-cookie-for-local-testing'
EXPIRED_COOKIE = 'mock-expired-cookie-for-local-testing'
FIXTURE = Path(__file__).with_name('fixtures') / 'nyt.json'


class MockCrossplayClient(CrossplayClient):
    def get(self, path):
        if self.nyt_s not in (MOCK_COOKIE, EMPTY_COOKIE, OUTAGE_COOKIE):
            raise CrossplayError('NYT rejected the NYT-S cookie; paste a fresh one', 401)
        data = json.loads(FIXTURE.read_text())
        if path == '/svc/games/player':
            return data['player']
        if path == '/svc/games/mp/subscribe/fallback':
            if self.nyt_s == OUTAGE_COOKIE:
                raise CrossplayError('NYT returned HTTP 503')
            if self.nyt_s == EMPTY_COOKIE:
                return {'msgs': []}
            return data['subscription']
        prefix = '/svc/games/mp/game/'
        if path.startswith(prefix):
            game = data['details'].get(path[len(prefix):])
            if game:
                return game
            raise CrossplayError('Game not found', 404)
        raise AssertionError(f'Unmocked NYT endpoint: {path}')


class MockHandler(Handler):
    client_factory = MockCrossplayClient

    def do_GET(self):
        if self.path.split('?', 1)[0] == '/health':
            return self.send_json(200, {'ok': True, 'mock_nyt': True})
        return super().do_GET()
