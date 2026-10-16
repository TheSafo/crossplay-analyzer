#!/usr/bin/env python3
"""Serve the analyzer and load your finished Crossplay games.

Usage:
    python3 crossplay_server.py [port]      # then open http://localhost:8000

The server serves the static app and a JSON API that fetches the current
browser user's games from NYT Crossplay. Locally, the NYT-S cookie is kept in
server memory for that browser's session. On Vercel, the page keeps it only in
memory and sends it to the same-origin API with each request.

    GET    /api/crossplay/status               is a cookie configured? (no NYT call)
    GET    /api/crossplay/me                   your NYT games user id and name
    PUT    /api/crossplay/token                save a cookie: {"nyt_s": "..."}
    DELETE /api/crossplay/token                forget the saved cookie
    GET    /api/crossplay/games                your recent games (summary rows)
    GET    /api/crossplay/games/<id>/review    a finished game, turn by turn

Reviews are only served for completed games, so the tool can't be used to
look at a game while it is still being played. By default the server binds to
127.0.0.1 for local use. The Vercel function accepts same-origin requests for
the deployment URL and configured custom domains. The local server never
serves dotfiles, Python source, or capture files.
"""

import gzip
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookies import CookieError, SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
NYT_BASE = 'https://www.nytimes.com'
DEFAULT_UA = 'Crossplay/7955 CFNetwork Darwin'
COLS = 'ABCDEFGHIJKLMNO'
GAME_ID_RE = re.compile(r'^[a-z0-9]{6,32}$')
# RFC 6265 cookie-octet characters; NYT-S values can include '^'.
COOKIE_RE = re.compile(r'^[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]{20,4096}$')
ACROSS_RE = re.compile(r'^(\d{1,2})([A-O])$')
DOWN_RE = re.compile(r'^([A-O])(\d{1,2})$')
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
SESSION_COOKIE = 'crossplay_session'
SESSION_TTL_SECONDS = 14 * 24 * 60 * 60
MAX_SESSIONS = 256
LIST_CACHE_SECONDS = 15
TOTAL_TILES = 100
CENTER = (7, 7)


class CrossplayError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


# ── Move notation and game replay ────────────────────────────────────────

def parse_play(action):
    """Parse 'BR(E)AST D10 27' into (row, col, dr, dc, [(letter, existing)]).

    Returns None for moves that place no tiles (swaps and passes). Letters in
    parentheses are already on the board; lowercase letters are blanks.
    '8F' (row first) is across and 'F8' (column first) is down.
    """
    parts = action.split()
    if len(parts) != 3:
        return None
    word, pos = parts[0], parts[1]
    across = ACROSS_RE.match(pos)
    down = DOWN_RE.match(pos)
    if across:
        row, col, dr, dc = int(across.group(1)) - 1, COLS.index(across.group(2)), 0, 1
    elif down:
        row, col, dr, dc = int(down.group(2)) - 1, COLS.index(down.group(1)), 1, 0
    else:
        return None
    tiles, existing = [], False
    for ch in word:
        if ch == '(':
            existing = True
        elif ch == ')':
            existing = False
        elif ch.isalpha():
            tiles.append((ch, existing))
        else:
            raise ValueError(f'Unexpected character {ch!r} in play {action!r}')
    if not 0 <= row < 15 or not 0 <= col < 15:
        raise ValueError(f'Play {action!r} starts off the board')
    return row, col, dr, dc, tiles


def apply_play(board, placement):
    """Place a parsed play on board in place; False if it does not fit."""
    row, col, dr, dc, tiles = placement
    for i, (letter, existing) in enumerate(tiles):
        r, c = row + dr * i, col + dc * i
        if not (0 <= r < 15 and 0 <= c < 15):
            return False
        if existing:
            if board[r][c].upper() != letter.upper():
                return False
        elif board[r][c] != '.':
            return False
        else:
            board[r][c] = letter
    return True


def normalize_rack(tray):
    return ''.join('?' if ch in '?*_ ' or ch.islower() else ch for ch in (tray or '')).upper()


def play_score(action):
    last = action.split()[-1] if action.split() else ''
    return int(last) if last.lstrip('-').isdigit() else 0


def turn_order(game):
    """Interleave both players' plays in the order they happened.

    The API stores plays per player, so try each player as the opener and
    keep the order in which every play fits the board as it stood and the
    first placement covers the center square.
    """
    players = game['game_data']['players']
    for first in (0, 1):
        a, b = players[first], players[1 - first]
        pa, pb = a.get('plays', []), b.get('plays', [])
        if len(pa) - len(pb) not in (0, 1):
            continue
        order = []
        for i in range(len(pa)):
            order.append((a, pa[i]))
            if i < len(pb):
                order.append((b, pb[i]))
        board = [['.'] * 15 for _ in range(15)]
        placed_any, valid = False, True
        for _, play in order:
            placement = parse_play(play['action'])
            if not placement:
                continue
            if not placed_any:
                row, col, dr, dc, tiles = placement
                cells = {(row + dr * i, col + dc * i) for i in range(len(tiles))}
                if CENTER not in cells:
                    valid = False
                    break
            if not apply_play(board, placement):
                valid = False
                break
            placed_any = True
        if valid:
            return order
    raise ValueError('Could not determine the order of plays')


def game_timeline(game, me):
    """Every turn of a game with the exact position the mover faced.

    Each turn carries the board before the move, the mover's rack, both
    scores, the bag count and (with an empty bag) how many final turns
    remained, so it can be handed straight to the Quackle worker.
    """
    order = turn_order(game)
    final_trays = {p['id']: p.get('tray') or '' for p in game['game_data']['players']}

    def rack_at(player_id, index):
        """The rack player_id held at turn index (before any later play)."""
        for j in range(index, len(order)):
            if order[j][0]['id'] == player_id:
                return order[j][1].get('tray') or ''
        return final_trays[player_id]

    board = [['.'] * 15 for _ in range(15)]
    scores = {p['id']: 0 for p in game['game_data']['players']}
    turns = []
    for index, (player, play) in enumerate(order):
        pid = player['id']
        other = next(o for o in scores if o != pid)
        rack = normalize_rack(play.get('tray'))
        on_board = sum(ch != '.' for row in board for ch in row)
        bag = TOTAL_TILES - on_board - len(rack) - len(rack_at(other, index))
        if bag < 0:
            raise ValueError('Tile counts do not add up')
        turns.append({
            'index': index,
            'mine': pid == me,
            'action': play['action'],
            'swapped_tiles': play.get('swapped_tiles'),
            'score': play_score(play['action']),
            'rack': rack,
            'grid': [''.join(row) for row in board],
            'mover_score': scores[pid],
            'other_score': scores[other],
            'bag_count': bag,
            'final_turns_remaining': min(len(order) - index, 2) if bag == 0 else 0,
        })
        placement = parse_play(play['action'])
        if placement and not apply_play(board, placement):
            raise ValueError(f'Play {play["action"]!r} does not fit the board')
        turns[-1]['grid_after'] = [''.join(row) for row in board]
        scores[pid] += turns[-1]['score']
    return turns


def split_players(game, me):
    players = {p['id']: p for p in game.get('players', [])}
    if me not in players:
        raise CrossplayError('You are not a player in this game', 403)
    opponent_id = next(pid for pid in players if pid != me)
    return players[me], players[opponent_id]


def summarize_game(game, me):
    mine, theirs = split_players(game, me)
    return {
        'id': game['id'],
        'status': game.get('game_status'),
        'opponent': theirs.get('username') or 'Opponent',
        'my_score': mine.get('score'),
        'opponent_score': theirs.get('score'),
        'turn_count': game.get('turn_count'),
        'timestamp': game.get('timestamp'),
    }


def game_review(game, me):
    """A completed game's summary plus every turn, for the review page."""
    if game.get('game_status') != 'completed':
        raise CrossplayError('Only finished games can be reviewed', 403)
    mine, theirs = split_players(game, me)
    review = summarize_game(game, me)
    review.update({
        'my_name': mine.get('username') or 'You',
        'turns': game_timeline(game, me),
    })
    return review


# ── NYT client ────────────────────────────────────────────────────────────


class CrossplayClient:
    def __init__(self, nyt_s, user_agent=DEFAULT_UA):
        self.nyt_s = nyt_s
        self.user_agent = user_agent
        self._lock = threading.Lock()
        self._me = None
        self._games = (0.0, None)

    def get(self, path):
        request = urllib.request.Request(NYT_BASE + path, headers={
            'Cookie': f'NYT-S={self.nyt_s}',
            'User-Agent': self.user_agent,
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
        })
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
                if response.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise CrossplayError('NYT rejected the NYT-S cookie; paste a fresh one', 401)
            if e.code == 404:
                raise CrossplayError('Game not found', 404)
            raise CrossplayError(f'NYT returned HTTP {e.code}')
        except urllib.error.URLError as e:
            raise CrossplayError(f'Could not reach NYT: {e.reason}')

    def me(self):
        with self._lock:
            if self._me is None:
                player = self.get('/svc/games/player').get('player') or {}
                if not player.get('user_id'):
                    raise CrossplayError('NYT did not recognize this cookie; is it from a logged-in session?', 401)
                self._me = {'user_id': player['user_id'], 'username': player.get('username')}
            return self._me

    def recent_games(self):
        with self._lock:
            fetched_at, games = self._games
            if games is None or time.time() - fetched_at > LIST_CACHE_SECONDS:
                data = self.get('/svc/games/mp/subscribe/fallback')
                games = [g for msg in data.get('msgs', [])
                         for g in msg.get('recent-games', {}).get('games', [])
                         if g.get('game') == 'crossplay']
                self._games = (time.time(), games)
            return games

    def game(self, game_id):
        # The recent-games response includes the full play history for games
        # it returns. Use that payload when possible; some NYT clients deliver
        # game state through the subscription response rather than a separate
        # GET request.
        for game in self.recent_games():
            game_data = game.get('game_data') or {}
            players = game_data.get('players') or []
            has_play_history = len(players) == 2 and all(
                isinstance(player.get('plays'), list) for player in players
            )
            if str(game.get('id', '')).lower() == game_id and has_play_history:
                return game
        return self.get(f'/svc/games/mp/game/{game_id}')


# ── HTTP server ───────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    client_factory = CrossplayClient
    sessions = {}
    sessions_lock = threading.Lock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def log_message(self, format, *args):
        # Keep request lines but never echo bodies or headers.
        sys.stderr.write('%s - %s\n' % (self.address_string(), format % args))

    def send_json(self, status, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_route(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if os.environ.get('VERCEL') and path == '/api/crossplay':
            return parse_qs(parsed.query).get('route', [''])[0].strip('/')
        if not path.startswith('/api/crossplay/'):
            return None
        return path[len('/api/crossplay/'):].strip('/')

    @staticmethod
    def authority_host(authority):
        try:
            return (urlsplit('//' + authority).hostname or '').lower().rstrip('.')
        except ValueError:
            return ''

    def allowed_host(self, host_header):
        host = self.authority_host(host_header)
        configured_hosts = os.environ.get('APP_ALLOWED_HOSTS', '').split(',')
        vercel_hosts = [
            os.environ.get('VERCEL_URL', ''),
            os.environ.get('VERCEL_PROJECT_PRODUCTION_URL', ''),
        ]
        allowed_hosts = {
            self.authority_host(value.strip())
            for value in [*vercel_hosts, *configured_hosts]
            if value.strip()
        }
        return host in LOCAL_HOSTS or bool(host and host in allowed_hosts)

    def same_origin_request(self, method):
        """Accept only this app's host and reject cross-site API mutations."""
        host = (self.headers.get('Host') or '').strip().lower()
        if not self.allowed_host(host):
            return False
        origin = self.headers.get('Origin')
        if origin:
            try:
                parsed_origin = urlsplit(origin)
            except ValueError:
                return False
            if parsed_origin.scheme not in ('http', 'https') or parsed_origin.netloc.lower() != host:
                return False
        elif method in ('PUT', 'DELETE'):
            return False
        return True

    @classmethod
    def purge_sessions(cls, now):
        expired = [
            session_id for session_id, session in cls.sessions.items()
            if now > session['expires_at']
        ]
        for session_id in expired:
            del cls.sessions[session_id]

    def session_id_from_cookie(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie') or '')
        except CookieError:
            return None
        morsel = cookies.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def current_session(self):
        if os.environ.get('VERCEL'):
            value = (self.headers.get('X-NYT-S') or '').strip()
            if not COOKIE_RE.fullmatch(value):
                return None, None
            return None, self.client_factory(value, os.environ.get('CROSSPLAY_UA', DEFAULT_UA))
        session_id = self.session_id_from_cookie()
        if not session_id:
            return None, None
        now = time.time()
        with Handler.sessions_lock:
            Handler.purge_sessions(now)
            session = Handler.sessions.get(session_id)
            if not session:
                return None, None
            return session_id, session['client']

    def save_session(self, client, previous_session_id=None):
        now = time.time()
        with Handler.sessions_lock:
            Handler.purge_sessions(now)
            if previous_session_id in Handler.sessions:
                del Handler.sessions[previous_session_id]
            if len(Handler.sessions) >= MAX_SESSIONS:
                raise CrossplayError('The app is at its active session limit; try again later', 503)
            session_id = secrets.token_urlsafe(32)
            Handler.sessions[session_id] = {
                'client': client,
                'expires_at': now + SESSION_TTL_SECONDS,
            }
            return session_id

    @staticmethod
    def session_cookie(session_id, max_age):
        cookie = f'{SESSION_COOKIE}={session_id}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax'
        if os.environ.get('CROSSPLAY_SECURE_COOKIE', '').lower() in ('1', 'true', 'yes'):
            cookie += '; Secure'
        return cookie

    def do_GET(self):
        if self.path.split('?', 1)[0] == '/health':
            return self.send_json(200, {'ok': True})
        route = self.api_route()
        if route is not None:
            return self.handle_api('GET', route)
        # Decode before checking so a request such as /%2eenv cannot bypass
        # the dotfile and private-directory guard below.
        request_path = self.path.split('?', 1)[0]
        while True:
            decoded_path = unquote(request_path)
            if decoded_path == request_path:
                break
            request_path = decoded_path
        segments = [s for s in request_path.split('/') if s]
        private_files = {
            'AGENTS.md', 'Dockerfile', 'README.md', 'requirements-test.txt',
            'package.json', 'package-lock.json', '.dockerignore', '.gitignore',
        }
        if (any(s.startswith('.') for s in segments)
                or (segments and segments[0] in ('captures', 'tools'))
                or (segments and (segments[0] in private_files or segments[0].endswith('.py')))):
            return self.send_error(404)
        return super().do_GET()

    def do_PUT(self):
        return self.handle_api('PUT', self.api_route())

    def do_DELETE(self):
        return self.handle_api('DELETE', self.api_route())

    def read_json_body(self):
        if 'application/json' not in (self.headers.get('Content-Type') or ''):
            raise CrossplayError('Expected a JSON body', 415)
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise CrossplayError('Bad request body', 400)
        if not 0 < length <= 16384:
            raise CrossplayError('Bad request body', 400)
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            raise CrossplayError('Bad request body', 400)
        if not isinstance(body, dict):
            raise CrossplayError('Expected a JSON object', 400)
        return body

    def handle_api(self, method, route):
        if route is None:
            return self.send_error(405)
        if not self.same_origin_request(method):
            return self.send_json(403, {'error': 'The API only accepts same-origin requests'})
        try:
            if route == 'status' and method == 'GET':
                _, client = self.current_session()
                return self.send_json(200, {'configured': client is not None})
            if route == 'token':
                return self.handle_token(method)
            if method != 'GET':
                return self.send_json(405, {'error': 'Method not allowed'})
            _, client = self.current_session()
            if client is None:
                return self.send_json(409, {'error': 'Paste your NYT-S cookie first'})
            me = client.me()
            if route == 'me':
                return self.send_json(200, me)
            if route == 'games':
                games = client.recent_games()
                return self.send_json(200, {'games': [summarize_game(g, me['user_id']) for g in games]})
            match = re.match(r'^games/([^/]+)/review$', route)
            if match:
                game_id = match.group(1).lower()
                if not GAME_ID_RE.match(game_id):
                    return self.send_json(400, {'error': 'Invalid game ID'})
                return self.send_json(200, game_review(client.game(game_id), me['user_id']))
            return self.send_json(404, {'error': 'Unknown endpoint'})
        except CrossplayError as e:
            return self.send_json(e.status, {'error': str(e)})
        except (KeyError, ValueError, StopIteration, TypeError) as e:
            return self.send_json(502, {'error': f'Unexpected game data: {e}'})

    def handle_token(self, method):
        if method == 'DELETE':
            if os.environ.get('VERCEL'):
                return self.send_json(200, {'configured': False})
            session_id = self.session_id_from_cookie()
            if session_id:
                with Handler.sessions_lock:
                    Handler.sessions.pop(session_id, None)
            return self.send_json(200, {'configured': False}, {
                'Set-Cookie': self.session_cookie('', 0),
            })
        if method != 'PUT':
            return self.send_json(405, {'error': 'Method not allowed'})
        value = str(self.read_json_body().get('nyt_s') or '').strip()
        value = re.sub(r'^NYT-S=', '', value).strip().strip('"')
        if not COOKIE_RE.match(value):
            return self.send_json(400, {
                'error': 'Paste only the NYT-S cookie value, not the full Cookie header'
            })
        client = self.client_factory(value, os.environ.get('CROSSPLAY_UA', DEFAULT_UA))
        me = client.me()  # validates the cookie before saving it
        if os.environ.get('VERCEL'):
            return self.send_json(200, {'configured': True, **me})
        previous_session_id, _ = self.current_session()
        session_id = self.save_session(client, previous_session_id)
        return self.send_json(200, {'configured': True, **me}, {
            'Set-Cookie': self.session_cookie(session_id, SESSION_TTL_SECONDS),
        })


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get('PORT', '8000'))
    host = os.environ.get('HOST', '127.0.0.1')
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'Serving on {host}:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
