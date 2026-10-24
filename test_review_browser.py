#!/usr/bin/env python3
"""Playwright checks through the real frontend, local API and NYT fixtures.

Starts an isolated server by default. Set CROSSPLAY_TEST_BASE_URL to exercise
an already-running `npm run frontend` server instead. External requests fail.
"""

import json
import os
import unittest
from contextlib import ExitStack
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

    def test_analyze_turn_with_bundled_quackle(self):
        self.open_game()
        self.page.get_by_role('combobox', name='Select game turn').select_option('0')
        self.page.get_by_role('button', name='Analyze this turn', exact=True).click()
        expect(self.page.locator('#engineStatus')).to_contain_text('Finished 277 simulations per move', timeout=120_000)
        expect(self.page.locator('.moves-table tbody tr').first).to_be_visible()
        self.assertGreater(self.page.locator('.moves-table tbody tr').count(), 0)
        expect(self.page.get_by_role('button', name='Analyze this turn', exact=True)).to_be_enabled()


if __name__ == '__main__':
    unittest.main(verbosity=2)
