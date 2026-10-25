#!/usr/bin/env python3
"""Playwright checks through the real frontend, local API and NYT fixtures.

Starts an isolated server by default. Set CROSSPLAY_TEST_BASE_URL to exercise
an already-running `npm run frontend` server instead. External requests fail.
"""

import json
import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect, sync_playwright

from tools.mock_nyt import EMPTY_COOKIE, EXPIRED_COOKIE, MOCK_COOKIE, OUTAGE_COOKIE
from tools.test_support import mock_server


class ReviewBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.stack.enter_context(patch.dict(os.environ, {'VERCEL': ''}))
        cls.stack.enter_context(patch('crossplay_server.urllib.request.urlopen',
                                     side_effect=AssertionError('Unexpected upstream network request')))
        cls.base_url = os.environ.get('CROSSPLAY_TEST_BASE_URL', '').rstrip('/')
        if not cls.base_url:
            cls.base_url = cls.stack.enter_context(mock_server())
        parsed = urlsplit(cls.base_url)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('CROSSPLAY_TEST_BASE_URL must be a loopback HTTP mock server')
        cls.playwright = cls.stack.enter_context(sync_playwright())
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Error:
            # Bits Code provides system Chrome; CI installs Playwright Chromium.
            cls.browser = cls.playwright.chromium.launch(channel='chrome', headless=True)
        cls.stack.callback(cls.browser.close)
        request = cls.playwright.request.new_context()
        try:
            health = request.get(cls.base_url + '/health')
            if not health.ok or health.json().get('mock_nyt') is not True:
                raise ValueError('Browser tests require a server started with --mock-nyt')
        finally:
            request.dispose()

    def setUp(self):
        self.context = self.browser.new_context(service_workers='block')
        self.addCleanup(self.context.close)
        self.external_requests = []
        self.page_errors = []
        self.context.route('**/*', self.route_request)
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: self.page_errors.append(str(error)))
        self.page.goto(self.base_url, wait_until='domcontentloaded')
        expect(self.page.locator('#connectionState')).to_contain_text('Not connected')

    def route_request(self, route):
        if urlsplit(route.request.url).netloc != urlsplit(self.base_url).netloc:
            self.external_requests.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    def tearDown(self):
        self.assertEqual(self.external_requests, [], 'The review page must work offline')
        self.assertEqual(self.page_errors, [])

    def connect(self, cookie=MOCK_COOKIE):
        self.page.get_by_role('textbox', name='NYT-S cookie').fill(cookie)
        self.page.get_by_role('button', name='Connect', exact=True).click()

    def open_game(self):
        self.connect()
        self.page.get_by_role('button', name='Review game against Demo Cedar').click()
        expect(self.page.get_by_role('heading', name='vs Demo Cedar', exact=True)).to_be_visible()

    def test_connect_replay_refresh_reload_and_forget(self):
        self.open_game()
        expect(self.page.locator('#connectionState')).to_have_text('NYT connected as Demo Player')
        expect(self.page.locator('#cookieInput')).to_have_value('')
        expect(self.page.locator('#gameCount')).to_have_text('2 finished · 1 in progress hidden')
        expect(self.page.locator('.game-card')).to_have_count(2)
        expect(self.page.get_by_role('button', name='Review game against Demo Active')).to_have_count(0)
        expect(self.page.locator('.turn-row')).to_have_count(6)
        turns = self.page.get_by_role('combobox', name='Select game turn')
        expect(turns).to_have_value('5')
        turns.select_option('0')
        expect(self.page.locator('.turn-action')).to_have_text('Turn 1 · Demo Player · +5')
        expect(self.page.locator('.board .tile')).to_have_count(3)
        expect(self.page.get_by_role('button', name='← Previous')).to_be_disabled()
        self.page.get_by_role('button', name='Show before move').click()
        expect(self.page.locator('.board .tile')).to_have_count(0)
        self.page.get_by_role('button', name='Show after move').click()
        self.page.get_by_role('button', name='Next →').click()
        expect(turns).to_have_value('1')
        expect(self.page.locator('.board .tile')).to_have_count(5)
        turns.select_option('2')
        expect(self.page.locator('.board .blank-tile')).to_have_count(1)
        expect(self.page.locator('.board .blank-tile')).to_have_text('S')
        self.page.get_by_role('button', name='Refresh', exact=True).click()
        expect(self.page.locator('.game-card')).to_have_count(2)
        self.page.reload()
        expect(self.page.get_by_role('heading', name='Demo Player vs Demo Cedar', exact=True)).to_be_visible()
        expect(self.page.locator('#sharedBanner')).to_be_visible()
        self.page.get_by_role('link', name='View your games', exact=True).click()
        expect(self.page.locator('#connectionState')).to_have_text('NYT connected as Demo Player')
        expect(self.page.locator('.game-card')).to_have_count(2)
        cookies = self.context.cookies()
        session = next(cookie for cookie in cookies if cookie['name'] == 'crossplay_session')
        self.assertTrue(session['httpOnly'])
        storage = self.page.evaluate('JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})')
        self.assertNotIn(MOCK_COOKIE, storage)
        self.assertNotIn(MOCK_COOKIE, json.dumps(cookies))
        self.page.get_by_role('button', name='Forget cookie').click()
        expect(self.page.locator('#connectionState')).to_contain_text('Cookie forgotten')
        expect(self.page.locator('.game-card')).to_have_count(0)
        self.page.reload()
        expect(self.page.locator('#connectionState')).to_contain_text('Not connected')

    def test_guest_can_replay_shared_game_until_owner_forgets_cookie(self):
        self.open_game()
        self.page.locator('.share-details summary').click()
        share_url = self.page.get_by_role('textbox', name='Shareable game link').input_value()
        guest_context = self.browser.new_context(service_workers='block')
        self.addCleanup(guest_context.close)
        guest_context.route('**/*', self.route_request)
        guest = guest_context.new_page()
        guest.on('pageerror', lambda error: self.page_errors.append(str(error)))
        shared_requests = []
        guest.on('request', lambda request: shared_requests.append(request)
                 if '/api/crossplay/shared/' in request.url else None)
        guest.goto(share_url)
        expect(guest.get_by_role('heading', name='Demo Player vs Demo Cedar', exact=True)).to_be_visible()
        expect(guest.locator('.account')).to_be_hidden()
        expect(guest.locator('.turn-row')).to_have_count(6)
        guest.get_by_role('combobox', name='Select game turn').select_option('0')
        expect(guest.locator('.board .tile')).to_have_count(3)
        self.assertEqual(len(shared_requests), 1)
        for header in ('authorization', 'x-nyt-s', 'cookie'):
            self.assertNotIn(header, shared_requests[0].all_headers())
        self.page.get_by_role('button', name='Forget cookie', exact=True).click()
        expect(self.page.locator('#connectionState')).to_contain_text('Cookie forgotten')
        guest.reload()
        expect(guest.locator('#reviewPanel')).to_contain_text('Shared game not found')

    def test_review_detail_fallback(self):
        self.connect()
        self.page.get_by_role('button', name='Review game against Demo River').click()
        expect(self.page.get_by_role('heading', name='vs Demo River', exact=True)).to_be_visible()
        self.page.get_by_role('combobox', name='Select game turn').select_option('0')
        expect(self.page.locator('.turn-action')).to_have_text('Turn 1 · Demo River · +5')

    def test_empty_account(self):
        self.connect(EMPTY_COOKIE)
        expect(self.page.locator('#connectionState')).to_contain_text('NYT connected as Demo Player')
        expect(self.page.locator('#gameCount')).to_have_text('0 finished')
        expect(self.page.locator('#gameList')).to_contain_text('No recent Crossplay games')

    def test_rejected_cookie(self):
        self.connect(EXPIRED_COOKIE)
        expect(self.page.locator('#connectionState')).to_contain_text('NYT rejected')
        expect(self.page.get_by_role('button', name='Refresh', exact=True)).to_be_disabled()
        expect(self.page.get_by_role('button', name='Forget cookie')).to_be_hidden()

    def test_upstream_failure(self):
        self.connect(OUTAGE_COOKIE)
        expect(self.page.locator('#gameList')).to_contain_text('NYT returned HTTP 503')
        expect(self.page.locator('#gameCount')).to_have_text('Could not load games')

    def use_saved_analysis(self, analysis=None, **review_changes):
        """Exercise the saved-analysis API contract with explicitly synthetic data."""
        if analysis is None:
            analysis = json.loads((Path(__file__).parent / 'tools/fixtures/review-analysis.json').read_text())

        def review_route(route):
            response = route.fetch()
            review = response.json()
            review.update(review_changes)
            review['stored_analysis'] = analysis
            route.fulfill(response=response, json=review)

        self.page.route('**/api/crossplay/games/mockgame01/review', review_route)

    def stat(self, label):
        return self.page.locator('.dashboard-stat').filter(
            has=self.page.get_by_text(label, exact=True))

    def test_personal_summary_and_score_replay_without_analysis(self):
        self.open_game()
        expect(self.page.locator('.review-heading')).to_contain_text('Won by 6 points')
        expect(self.page.locator('.score-person').first).to_have_text('You')
        expect(self.stat('Points per turn')).to_contain_text('3.3')
        expect(self.stat('Highest-scoring play')).to_contain_text('5 pts')
        expect(self.stat('Highest-scoring play')).to_contain_text('CAT')
        expect(self.stat('Best moves').locator('.dashboard-stat-value')).to_have_text('—')
        expect(self.stat('Avg. equity lost').locator('.dashboard-stat-value')).to_have_text('—')
        expect(self.page.locator('.quality-empty')).to_be_visible()
        expect(self.page.locator('.score-point')).to_have_count(6)
        self.page.locator('.score-point').first.focus()
        self.page.keyboard.press('Enter')
        expect(self.page.get_by_role('combobox', name='Select game turn')).to_have_value('0')
        expect(self.page.locator('.score-point').first).to_be_focused()
        expect(self.page.locator('.board .tile')).to_have_count(3)
        expect(self.page.locator('#cookieForm')).to_be_hidden()
        self.page.get_by_role('button', name='Manage connection', exact=True).click()
        expect(self.page.locator('#cookieForm')).to_be_visible()
        expect(self.page.get_by_role('button', name='Manage connection')).to_have_attribute('aria-expanded', 'true')

    def test_saved_quality_excludes_opponent_and_unrated_moves(self):
        self.use_saved_analysis()
        self.open_game()
        expect(self.stat('Best moves').locator('.dashboard-stat-value')).to_have_text('1 / 2')
        expect(self.stat('Avg. equity lost').locator('.dashboard-stat-value')).to_have_text('3.0')
        expect(self.stat('Avg. equity lost')).to_contain_text('2 of your 3 turns rated')
        expect(self.page.locator('.quality-summary')).to_contain_text('1 Best')
        expect(self.page.locator('.quality-summary')).not_to_contain_text('Blunder')
        expect(self.page.locator('.quality-summary')).to_contain_text('1 unrated')
        expect(self.page.locator('.quality-point')).to_have_count(3)
        expect(self.page.locator('.insight')).to_have_count(1)
        expect(self.page.locator('.insight')).to_contain_text('Turn 3 · SCAT')
        expect(self.page.locator('.insight')).to_contain_text('5.6 equity')
        self.page.locator('.insight').click()
        expect(self.page.get_by_role('combobox', name='Select game turn')).to_have_value('2')
        expect(self.page.locator('.turn-meta')).to_contain_text('Mistake')
        expect(self.page.locator('.board .last-play')).to_have_count(1)
        self.page.locator('.quality-point').first.focus()
        self.page.keyboard.press('Space')
        expect(self.page.get_by_role('combobox', name='Select game turn')).to_have_value('0')
        expect(self.page.locator('.quality-point').first).to_be_focused()
        self.page.get_by_role('button', name='Review game against Demo River').click()
        expect(self.stat('Avg. equity lost').locator('.dashboard-stat-value')).to_have_text('—')
        expect(self.page.locator('.insight')).to_have_count(0)
        expect(self.page.locator('.review-heading')).to_contain_text('Lost by 6 points')

    def test_luck_panel_without_analysis_and_legacy_saved_analysis(self):
        self.use_saved_analysis()
        self.open_game()
        panel = self.page.locator('.luck-panel')
        cards = panel.locator('.luck-stat')
        expect(cards.nth(0)).to_contain_text('3 of your 3 racks estimated')
        expect(cards.nth(1)).to_contain_text('2 of your 3 turns rated')
        expect(cards.nth(2).locator('strong')).to_have_text('—')
        expect(panel).to_contain_text('Re-analyze moves')
        panel.locator('.luck-breakdown summary').click()
        expect(panel.locator('tbody tr')).to_have_count(3)
        panel.get_by_role('button', name='Replay turn 3 from luck breakdown').click()
        expect(self.page.get_by_role('combobox', name='Select game turn')).to_have_value('2')
        self.page.get_by_role('button', name='Review game against Demo River').click()
        expect(self.page.locator('.luck-panel')).to_contain_text('Use Analyze move quality above')
        expect(self.page.locator('.luck-stat').nth(1).locator('strong')).to_have_text('—')

    def test_saved_word_opportunities_weight_only_eligible_personal_turns(self):
        analysis = {'version': 'quackle-equity-v1', 'move_quality': {
            'state': 'stopped', 'points': [
                {'turnIndex': 0, 'category': 'mistake', 'loss': 10, 'playedEquity': 20,
                 'opportunity': {'version': 1, 'accessibleEquity': 26, 'bestWord': 'QAT',
                                 'bestWordZipf': 2, 'knownCandidates': 2, 'candidateCount': 3}},
                {'turnIndex': 1, 'category': 'best', 'loss': 0, 'playedEquity': 30,
                 'opportunity': {'version': 1, 'accessibleEquity': 30, 'bestWord': 'CAT',
                                 'bestWordZipf': 5, 'knownCandidates': 1, 'candidateCount': 1}},
                {'turnIndex': 2, 'category': 'unrated', 'loss': None}]}}
        self.use_saved_analysis(analysis)
        self.open_game()
        panel = self.page.locator('.luck-panel')
        expect(panel.locator('.luck-stat').nth(1).locator('strong')).to_have_text('50 / 100')
        expect(panel.locator('.luck-stat').nth(2).locator('strong')).to_have_text('63 / 100')
        expect(panel).to_contain_text('1 of your 3 turns weighted · partial analysis')
        expect(panel).to_contain_text('Word frequency available for 2 of 3 candidate entries')
        panel.locator('.luck-breakdown summary').click()
        expect(panel.locator('tbody tr').first).to_contain_text('QAT · Less common')
        expect(panel.locator('tbody tr').first).to_contain_text('6.0 eq')
        expect(panel.locator('tbody tr').nth(1)).to_contain_text('Unrated')

    def test_incomplete_and_unrated_analysis_never_implies_perfect_play(self):
        analysis = {'version': 'quackle-equity-v1', 'move_quality': {
            'state': 'stopped', 'points': [
                {'turnIndex': 0, 'category': 'unrated', 'loss': None, 'reason': 'Outside candidates'},
                {'turnIndex': 1, 'category': 'best', 'loss': 0.0}]}}
        self.use_saved_analysis(analysis)
        self.open_game()
        expect(self.stat('Avg. equity lost').locator('.dashboard-stat-value')).to_have_text('—')
        expect(self.page.locator('.insights-panel')).to_contain_text('No rated turns yet')
        expect(self.page.locator('.insights-panel')).to_contain_text('Analysis is incomplete')
        expect(self.page.locator('.insights-panel')).not_to_contain_text('Every rated move')

    def test_draw_missing_scores_and_final_adjustments(self):
        self.use_saved_analysis(my_score=14, opponent_score=14)
        self.open_game()
        expect(self.page.locator('.review-heading')).to_contain_text('Draw')
        expect(self.page.locator('.score-point')).to_have_count(7)
        expect(self.page.locator('.score-point').last).to_have_attribute('aria-label', 'Final score: 14 to 14. Replay turn 6')
        self.page.unroute('**/api/crossplay/games/mockgame01/review')
        self.use_saved_analysis(my_score=None, opponent_score=None)
        self.page.get_by_role('button', name='Review game against Demo Cedar').click()
        expect(self.page.locator('.review-heading')).to_contain_text('Final scores unavailable')
        expect(self.page.locator('.review-heading')).not_to_contain_text('Draw')
        expect(self.page.locator('.score-value').first).to_have_text('—')

    def test_mobile_layout_and_board_fit(self):
        self.use_saved_analysis()
        self.open_game()
        self.page.locator('.luck-breakdown summary').click()
        for width in (320, 390, 768, 1024, 1440):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                self.assertTrue(self.page.evaluate(
                    'document.documentElement.scrollWidth <= window.innerWidth'),
                    'The page must not scroll horizontally')
                board = self.page.locator('.board-scroll')
                self.assertTrue(board.evaluate('(el) => el.scrollWidth <= el.clientWidth'),
                                'The complete board must fit the viewport')
                expect(self.page.get_by_role('button', name='Re-analyze moves')).to_be_visible()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('.insight').click()
        expect(self.page.get_by_role('combobox', name='Select game turn')).to_have_value('2')

    def test_move_quality_refreshes_summary_with_real_engine(self):
        self.open_game()
        self.page.get_by_role('button', name='Analyze move quality', exact=True).click()
        expect(self.page.locator('.quality-panel .trend-status')).to_contain_text(
            'Your review is ready', timeout=120_000)
        expect(self.page.locator('.quality-point')).to_have_count(3)
        expect(self.page.locator('.quality-summary')).to_contain_text('unrated')
        expect(self.page.locator('.insights-panel')).to_contain_text('of your 3 turns rated')
        expect(self.page.get_by_role('button', name='Re-analyze moves', exact=True)).to_be_enabled()
        # The selected turn is the opponent's final pass; its badge updates too.
        expect(self.page.locator('.turn-meta .quality-chip')).to_have_text('Unrated')
        points = self.page.evaluate('moveQualityResults.points')
        word_points = [point for point in points if point['turnIndex'] in (0, 1, 2)]
        self.assertTrue(all(point['opportunity']['version'] == 1 for point in word_points))
        self.assertTrue(all(point['reason'].startswith('Passes and tile exchanges')
                            for point in points if point['turnIndex'] in (3, 4, 5)))
        expect(self.page.locator('.luck-panel')).to_contain_text('3 of your 3 racks estimated')

    def test_analyze_turn_with_bundled_quackle(self):
        self.open_game()
        self.page.get_by_role('combobox', name='Select game turn').select_option('0')
        self.page.get_by_role('button', name='Analyze this turn', exact=True).click()
        expect(self.page.locator('#engineStatus')).to_contain_text('Finished 277 simulations per move', timeout=120_000)
        expect(self.page.locator('.moves-table tbody tr').first).to_be_visible()
        self.assertGreater(self.page.locator('.moves-table tbody tr').count(), 0)
        expect(self.page.get_by_role('button', name='Analyze this turn', exact=True)).to_be_enabled()

    def test_frequency_failure_preserves_move_quality_and_can_be_retried(self):
        self.page.route('**/wordfreq-en-25000-log.json',
                        lambda route: route.fulfill(status=503, body='Unavailable'))
        self.open_game()
        self.page.get_by_role('button', name='Analyze move quality', exact=True).click()
        expect(self.page.locator('.quality-panel .trend-status')).to_contain_text(
            'Your review is ready', timeout=120_000)
        expect(self.page.locator('.luck-panel')).to_contain_text('Word commonness could not load')
        self.assertTrue(self.page.evaluate('moveQualityResults.points.length > 0'))
        self.assertFalse(self.page.evaluate('moveQualityResults.points.some(point => point.opportunity)'))
        self.page.unroute('**/wordfreq-en-25000-log.json')
        self.page.get_by_role('button', name='Re-analyze moves', exact=True).click()
        expect(self.page.locator('.quality-panel .trend-status')).to_contain_text(
            'Your review is ready', timeout=120_000)
        expect(self.page.locator('.luck-panel')).not_to_contain_text('Word commonness could not load')
        self.assertTrue(self.page.evaluate('moveQualityResults.points.some(point => point.opportunity)'))

    def test_real_engine_produces_weighted_performance_for_a_rated_move(self):
        # A synthetic opening with a short rack and a top static candidate.
        grid = ['.' * 15 for _ in range(15)]
        after = grid.copy()
        after[7] = '.......ACT.....'
        self.use_saved_analysis({}, turns=[{
            'index': 0, 'mine': True, 'action': 'ACT 8H 6', 'score': 6,
            'rack': 'CAT', 'grid': grid, 'grid_after': after,
            'bag_count': 90, 'final_turns_remaining': 0,
            'mover_score': 0, 'other_score': 0,
        }], my_score=6, opponent_score=0, turn_count=1)
        self.open_game()
        self.page.get_by_role('button', name='Analyze move quality', exact=True).click()
        expect(self.page.locator('.quality-panel .trend-status')).to_contain_text(
            'Your review is ready', timeout=120_000)
        expect(self.page.locator('.luck-panel')).to_contain_text('1 of your 1 turns weighted')
        expect(self.page.locator('.luck-stat').nth(1).locator('strong')).to_have_text('100 / 100')
        expect(self.page.locator('.luck-stat').nth(2).locator('strong')).to_have_text('100 / 100')
        self.page.locator('.luck-breakdown summary').click()
        expect(self.page.locator('.luck-table')).to_contain_text('ACT · Common')
        first_points = self.page.evaluate('moveQualityResults.points')
        self.assertEqual(self.page.evaluate('moveQualityResults.evaluation'), 'static-equity-v1')
        self.page.get_by_role('button', name='Re-analyze moves', exact=True).click()
        expect(self.page.locator('.quality-panel .trend-status')).to_contain_text(
            'Your review is ready', timeout=120_000)
        self.assertEqual(self.page.evaluate('moveQualityResults.points'), first_points,
                         'Move quality must not inherit luck from random simulations')


if __name__ == '__main__':
    unittest.main(verbosity=2)
