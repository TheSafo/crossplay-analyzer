#!/usr/bin/env python3

import base64
import functools
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Error, sync_playwright


ROOT = Path(__file__).resolve().parent

FIXTURES = {
    "test_board.png": {
        "grid": [
            "...............",
            "...............",
            "...............",
            "......VAT....W.",
            ".......MACHINES",
            "..........E...O",
            "..........X...B",
            "......GOONEY..E",
            "........PURE..R",
            "..............I",
            "..............N",
            "..............G",
            "...............",
            "...............",
            "...............",
        ],
        "scores": ("108", "130"),
        "rack": "WLSAPDI",
        "tiles": "31",
        "bag": "55",
        "words": 12,
        "blanks": ["O9"],
    },
    "IMG_3046.png": {
        "grid": [
            "...............",
            "...............",
            "...............",
            ".......G.......",
            ".....GOAT......",
            ".......P..F....",
            ".......E..A....",
            ".......DUCTAL..",
            "..........H....",
            "..........E....",
            "..........R....",
            "........PLEATED",
            "..........D....",
            "...............",
            "...............",
        ],
        "scores": ("43", "93"),
        "rack": "G",
        "tiles": "26",
        "bag": "66",
        "words": 5,
        "blanks": ["K11", "N12"],
    },
    "IMG_3047.png": {
        "grid": [
            "...........M..T",
            "...........A.EH",
            "......Q....N.WE",
            "GRIP.GUTTERY..I",
            "...O..A.E...F.N",
            "...LINY.E..WEDS",
            "...O....M.BIZE.",
            "...SEI.JIHAD.T.",
            "........N.TE.A.",
            "........G.H..I.",
            ".............L.",
            "...........PASS",
            "...........A...",
            ".......CAB.R...",
            "........LOCKER.",
        ],
        "scores": ("235", "285"),
        "rack": "DUOONES",
        "tiles": "73",
        "bag": "13",
        "words": 26,
        "blanks": ["O6", "I8", "N12"],
    },
    "IMG_3048.png": {
        "grid": [
            "...K....POCO...",
            "..TEMPERED.....",
            "...N....TAUGHT.",
            "FEATHERS.......",
            "....I..A.......",
            "....V..B..Z....",
            ".VINE.DE..O....",
            ".....JARGOON...",
            "......I...MOI..",
            "L...CURB.......",
            "O.....YA...QIS.",
            "A......L.WAITER",
            "D...HAULIERS.X.",
            "SIXTEEN......Y.",
            "...AW.SELFED...",
        ],
        "scores": ("407", "412"),
        "rack": "--",
        "tiles": "96",
        "bag": "--",
        "words": 35,
        "blanks": ["I2", "C14", "H15"],
    },
    "IMG_150_139.png": {
        "grid": [
            "..........G....",
            ".......A.NOUN.Y",
            ".......L...TAME",
            "......YEAH...E.",
            ".........AB.YA.",
            "......LOB.OWED.",
            "..PROG..I.T.N.F",
            "....D..JOGS...I",
            "...LASSI.O..RUN",
            ".......V.R..I..",
            "...C...E..HIPS.",
            "...A.BASE.A.E..",
            "...R.O..D.V....",
            "..RENT.LITER...",
            ".....H..T......",
        ],
        "scores": ("150", "139"),
        "rack": "IUAFTIO",
        "tiles": "82",
        "bag": "4",
        "words": 34,
        "blanks": ["J5", "K5", "M5"],
    },
    "IMG_150_156.png": {
        "grid": [
            "..........G....",
            ".......A.NOUN.Y",
            ".......L...TAME",
            "......YEAH...E.",
            ".........AB.YA.",
            "......LOB.OWED.",
            "..PROG..I.TEN.F",
            "....D..JOGS...I",
            "...LASSI.O..RUN",
            ".......V.R.MI..",
            "...C...E..HIPS.",
            "...A.BASE.A.E..",
            "...R.O..D.V....",
            "..RENT.LITER...",
            ".....H..T......",
        ],
        "scores": ("150", "156"),
        "rack": "WEAFTUO",
        "tiles": "84",
        "bag": "2",
        "words": 38,
        "blanks": ["J5", "K5", "M5"],
    },
    "IMG_153_169.png": {
        "grid": [
            "..........G....",
            ".......A.NOUN.Y",
            ".......L...TAME",
            "......YEAH...E.",
            ".CITED...AS.YA.",
            "...O..LOB.OWED.",
            "..PROG..I.TEN.F",
            "....D..JOGS...I",
            "...LASSI.O..RUN",
            ".......V.R.MI..",
            "...C...E..HIPS.",
            "...A.BASE.A.E..",
            "...R.O..D.V....",
            "..RENT.LITER...",
            ".....H..T......",
        ],
        "scores": ("153", "169"),
        "rack": "WEAFIUZ",
        "tiles": "90",
        "bag": "0",
        "words": 40,
        "blanks": ["J5", "K5", "M5"],
    },
}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class BrowserPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietHandler, directory=ROOT)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Error:
            cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def open_page(self):
        page = self.browser.new_page()
        page_errors = []
        console_messages = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_messages.append(message.text))
        page.goto(f"{self.base_url}/screenshot.html", wait_until="domcontentloaded")
        return page, page_errors, console_messages

    def wait_for_analysis(self, page):
        page.locator("#analyzeBtn").click()
        page.wait_for_function(
            "document.getElementById('status').classList.contains('done') || "
            "document.getElementById('status').classList.contains('error')",
            timeout=120_000,
        )
        self.assertEqual(page.locator("#status").get_attribute("class"), "done")

    def rendered_grid(self, page):
        return page.eval_on_selector_all(
            "#boardContainer table.board tr:not(:first-child)",
            """rows => rows.map(row => [...row.querySelectorAll('td')]
              .map(cell => cell.classList.contains('empty') ? '.' : cell.textContent.trim())
              .join(''))""",
        )

    def rendered_blank_positions(self, page):
        return page.eval_on_selector_all(
            "#boardContainer table.board tr:not(:first-child)",
            """rows => rows.flatMap((row, rowIndex) =>
              [...row.querySelectorAll('td')].flatMap((cell, colIndex) =>
                cell.classList.contains('blank-tile')
                  ? [`${String.fromCharCode(65 + colIndex)}${rowIndex + 1}`]
                  : []))""",
        )

    def test_all_fixtures(self):
        for fixture, expected in FIXTURES.items():
            with self.subTest(fixture=fixture):
                page, page_errors, console_messages = self.open_page()
                page.locator("#imageUrlInput").fill(f"{self.base_url}/{fixture}")
                self.wait_for_analysis(page)

                self.assertEqual(self.rendered_grid(page), expected["grid"])
                self.assertEqual(page.locator("#p1Score").text_content(), expected["scores"][0])
                self.assertEqual(page.locator("#p2Score").text_content(), expected["scores"][1])
                self.assertEqual(page.locator("#rackDisplay").text_content(), expected["rack"])
                self.assertEqual(page.locator("#tileCount").text_content(), expected["tiles"])
                self.assertEqual(page.locator("#bagCount").text_content(), expected["bag"])
                self.assertEqual(self.rendered_blank_positions(page), expected["blanks"])
                self.assertEqual(page.locator("#wordsContainer tbody tr").count() - 1, expected["words"])
                self.assertEqual(page_errors, [])

                if fixture == "IMG_3048.png":
                    self.assertTrue(page.locator("#kibitzBtn").evaluate("el => el.classList.contains('hidden')"))

                if fixture in {"IMG_150_139.png", "IMG_150_156.png", "IMG_153_169.png"}:
                    parsed = page.evaluate("lastParsed")
                    self.assertTrue(parsed["tile_values_complete"])
                    internal_blanks = [f"{position[1:]}{position[0]}" for position in expected["blanks"]]
                    self.assertEqual(parsed["blank_positions"], internal_blanks)
                    parsed_grid = [list(row) for row in expected["grid"]]
                    for position in expected["blanks"]:
                        row = int(position[1:]) - 1
                        col = ord(position[0]) - ord("A")
                        parsed_grid[row][col] = parsed_grid[row][col].lower()
                    self.assertEqual(parsed["grid"], ["".join(row) for row in parsed_grid])
                    values = page.evaluate(
                        """async ({fixtureUrl, cells}) => {
                          const response = await fetch(fixtureUrl);
                          const bitmap = await createImageBitmap(await response.blob());
                          const canvas = document.createElement('canvas');
                          canvas.width = bitmap.width;
                          canvas.height = bitmap.height;
                          const context = canvas.getContext('2d');
                          context.drawImage(bitmap, 0, 0);
                          const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
                          const grid = detectBoardGrid(pixels.data, canvas.width, canvas.height);
                          return Object.fromEntries(cells.map(({label, row, col}) => {
                            const letter = readTileLetter(
                              pixels.data, canvas.width,
                              grid.vGrid[col], grid.hGrid[row],
                              grid.vGrid[col + 1], grid.hGrid[row + 1]);
                            const value = readTileValue(
                              pixels.data, canvas.width,
                              grid.vGrid[col], grid.hGrid[row],
                              grid.vGrid[col + 1], grid.hGrid[row + 1], letter);
                            return [label, value];
                          }));
                        }""",
                        {
                            "fixtureUrl": f"{self.base_url}/{fixture}",
                            "cells": ([
                                {"label": "M5", "row": 4, "col": 12},
                                {"label": "L6", "row": 5, "col": 11},
                                {"label": "E8", "row": 7, "col": 4},
                                {"label": "H8", "row": 7, "col": 7},
                            ] if fixture == "IMG_150_156.png" else [
                                {"label": "H8", "row": 7, "col": 7},
                            ]),
                        },
                    )
                    expected_values = (
                        {"M5": 0, "L6": 5, "E8": 2, "H8": 10}
                        if fixture == "IMG_150_156.png" else {"H8": 10}
                    )
                    self.assertEqual(values, expected_values)

                    if fixture == "IMG_150_156.png":
                        self.assertEqual(parsed["bag_count"], 2)
                        self.assertEqual(
                            page.locator("#tilePoolSummary").text_content(),
                            "Bag 2 | Opponent rack 7 hidden | Unseen 9",
                        )
                        unseen = page.eval_on_selector_all(
                            "#unseenTiles .tile-chip",
                            "nodes => nodes.map(node => [node.dataset.tile, Number(node.dataset.count)])",
                        )
                        self.assertEqual(
                            unseen,
                            [["C", 1], ["D", 1], ["E", 1], ["I", 2],
                             ["K", 1], ["Q", 1], ["X", 1], ["Z", 1]],
                        )
                        self.assertFalse(page.locator("#kibitzBtn").evaluate(
                            "el => el.classList.contains('hidden')"
                        ))

                    if fixture == "IMG_153_169.png":
                        self.assertEqual(parsed["final_turns_remaining"], 1)
                        self.assertEqual(parsed["final_turn_labels"], ["Last turn", "Done"])
                        self.assertEqual(page.evaluate("selectedFinalTurns"), 1)
                        self.assertTrue(page.locator("#finalTurnPanel").evaluate(
                            "el => el.classList.contains('hidden')"
                        ))
                        self.assertFalse(page.locator("#kibitzBtn").is_disabled())
                        self.assertIn(
                            "Detected Last turn / Done",
                            page.locator("#engineStatus").text_content(),
                        )
                        self.assertEqual(
                            page.locator("#tilePoolSummary").text_content(),
                            "Bag 0 | Opponent rack 3 hidden | Unseen 3",
                        )

                if fixture == "test_board.png":
                    page.evaluate(
                        "window.__quackleStatuses = []; "
                        "new MutationObserver(() => window.__quackleStatuses.push("
                        "document.getElementById('engineStatus').textContent))"
                        ".observe(document.getElementById('engineStatus'), "
                        "{childList: true, subtree: true})"
                    )
                    page.locator("#kibitzBtn").click()
                    page.wait_for_function(
                        "document.getElementById('engineStatus').textContent.includes('running 277 rounds') || "
                        "document.getElementById('engineStatus').textContent.startsWith('Error:')",
                        timeout=120_000,
                    )
                    running_status = page.locator("#engineStatus").text_content()
                    self.assertIn("running 277 rounds", running_status)
                    self.assertTrue(page.locator("#kibitzBtn").is_disabled())
                    page.evaluate(
                        "window.__quackleHeartbeat = false; "
                        "setTimeout(() => { window.__quackleHeartbeat = true; }, 100)"
                    )
                    page.wait_for_function("window.__quackleHeartbeat", timeout=5_000)
                    page.wait_for_function(
                        "document.getElementById('engineStatus').textContent.startsWith('Found ') || "
                        "document.getElementById('engineStatus').textContent.startsWith('Error:')",
                        timeout=120_000,
                    )
                    engine_status = page.locator("#engineStatus").text_content()
                    self.assertTrue(engine_status.startswith("Found "), engine_status)
                    self.assertTrue(any(
                        "running 277 rounds" in status
                        for status in page.evaluate("window.__quackleStatuses")
                    ))
                    self.assertEqual(page.locator("#movesContainer tbody tr").count() - 1, 15)
                    win_cells = page.locator("#movesContainer tbody tr:not(:first-child) td:nth-child(4)")
                    self.assertEqual(win_cells.count(), 15)
                    for index in range(win_cells.count()):
                        cell = win_cells.nth(index)
                        self.assertRegex(cell.text_content(), r"^(100|[0-9]{1,2})\.\d%$")
                        self.assertEqual(cell.get_attribute("data-samples"), "277")
                    self.assertIn("Simulated 277 rounds per move", engine_status)
                    self.assertIn("4,155 playouts total", engine_status)
                    self.assertFalse(page.locator("#kibitzBtn").is_disabled())
                    self.assertFalse(any("bogowin heuristic" in message for message in console_messages))

                page.close()

    def test_crossplay_premium_layout(self):
        page, page_errors, _ = self.open_page()
        page.evaluate(
            """renderResult({
              grid: Array(15).fill('...............'), rack: 'A',
              player_score: 0, opponent_score: 0,
              player_name: 'You', opponent_name: 'Opponent',
              bag_count: 92,
              tile_values_complete: true
            })"""
        )
        premiums = page.eval_on_selector_all(
            "#boardContainer td[data-premium]",
            "nodes => Object.fromEntries(['3L','2L','2W','3W'].map(type => [type, nodes.filter(node => node.dataset.premium === type).map(node => node.dataset.position)]))",
        )
        self.assertEqual(premiums, {
            "3L": "A1 O1 G2 I2 F5 J5 E6 K6 B7 N7 B9 N9 E10 K10 F11 J11 G14 I14 A15 O15".split(),
            "2L": "H1 E3 K3 D4 L4 C5 M5 H6 A8 F8 J8 O8 H10 C11 M11 D12 L12 E13 K13 H15".split(),
            "2W": "B2 N2 H4 D8 L8 H12 B14 N14".split(),
            "3W": "D1 L1 A4 O4 A12 O12 D15 L15".split(),
        })
        self.assertEqual(page.locator("td[data-position='H8']").get_attribute("data-premium"), None)
        self.assertEqual(page_errors, [])
        page.close()

    def test_crossplay_h_scores_three_points(self):
        page, page_errors, _ = self.open_page()
        result = page.evaluate(
            """async () => {
              if (!await loadQuackleEngine()) throw new Error('Engine did not load');
              return callQuackleWorker('simulateKibitz', {
                gridJson: JSON.stringify(Array(15).fill('...............')),
                rack: 'HAT', playerScore: 0, opponentScore: 0,
                numMoves: 15, iterations: 1, bagCount: 90, finalTurnsRemaining: 0
              });
            }"""
        )
        self.assertTrue(result["simulated"])
        move = next(
            candidate for candidate in result["moves"]
            if candidate["tiles"] == "HAT" and candidate["position"] == "8G"
        )
        self.assertEqual(move["score"], 5)
        self.assertEqual(page_errors, [])
        page.close()

    def test_custom_moves_on_manual_and_screenshot_pages(self):
        for entry in ['manual.html', 'screenshot.html']:
            with self.subTest(entry=entry):
                page, page_errors, _ = self.open_page()
                page.goto(f'{self.base_url}/{entry}', wait_until='domcontentloaded')
                if entry == 'manual.html':
                    page.locator('#rackInput').fill('ACERSTU')
                else:
                    page.evaluate('''() => {
                      lastParsed = { grid: Array(15).fill('...............'), rack: 'ACERSTU',
                        player_score: 0, opponent_score: 0, bag_count: 86 };
                      renderResult(lastParsed);
                    }''')
                page.get_by_role('textbox', name='Custom move word', exact=True).fill('CAT')
                page.get_by_role('textbox', name='Custom move start square', exact=True).fill('G8')
                page.get_by_role('button', name='Evaluate move', exact=True).click()
                page.wait_for_function("document.querySelector('.custom-move-status').textContent === 'Move evaluated.'")
                row = page.locator('.custom-move-result tbody tr').first
                self.assertIn('8G CAT', row.inner_text())
                self.assertEqual(row.locator('td').nth(1).inner_text(), '5')
                self.assertEqual(row.locator('td').nth(2).inner_text(), 'ERSU')
                # Editing the position must discard the prior evaluation.
                if entry == 'manual.html':
                    page.locator('#p1Score').fill('10')
                else:
                    page.evaluate('renderResult(lastParsed)')
                self.assertEqual(page.locator('.custom-move-result tbody tr').count(), 0)
                self.assertEqual(page_errors, [])
                page.close()

    def test_compact_header_and_tile_glyph_regressions(self):
        """Check the exact pixels from the reported compact-screen failure.

        This fixture is the analyzer debug canvas, so it contains overlays on
        tiles that the old detector found. The score, rack, and four missed L
        tiles are unchanged and can be tested directly.
        """
        page, page_errors, _ = self.open_page()
        result = page.evaluate(
            """async fixtureUrl => {
              const response = await fetch(fixtureUrl);
              const bitmap = await createImageBitmap(await response.blob());
              const canvas = document.createElement('canvas');
              canvas.width = bitmap.width;
              canvas.height = bitmap.height;
              const context = canvas.getContext('2d');
              context.drawImage(bitmap, 0, 0);
              const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
              const xs = [19,69,120,172,223,275,325,378,428,480,531,583,633,685,736,788];
              const ys = [383,432,484,534,586,637,689,739,792,842,894,945,997,1047,1099,1150];
              const readCell = (row, col) => ({
                tile: isTileCell(pixels.data, canvas.width, xs[col], ys[row], xs[col + 1], ys[row + 1]),
                letter: readTileLetter(pixels.data, canvas.width, xs[col], ys[row], xs[col + 1], ys[row + 1]),
                value: readTileValue(pixels.data, canvas.width, xs[col], ys[row], xs[col + 1], ys[row + 1])
              });
              const lCells = [[2,7],[5,6],[8,3],[13,7]].map(([row, col]) => readCell(row, col));

              const half = document.createElement('canvas');
              half.width = Math.round(canvas.width / 2);
              half.height = Math.round(canvas.height / 2);
              const halfContext = half.getContext('2d');
              halfContext.drawImage(canvas, 0, 0, half.width, half.height);
              const halfPixels = halfContext.getImageData(0, 0, half.width, half.height);
              return {
                scores: readHeaderScores(pixels.data, canvas.width, canvas.height, ys[0]),
                halfScores: readHeaderScores(
                  halfPixels.data, half.width, half.height, Math.round(ys[0] / 2)),
                lCells,
                compactValues: {
                  J5: readCell(4, 9).value,
                  K5: readCell(4, 10).value,
                  M5: readCell(4, 12).value,
                  H8: readCell(7, 7).value
                },
                rackO: readTileLetter(pixels.data, canvas.width, 686, 1277, 790, 1383)
              };
            }""",
            f"{self.base_url}/compact_header_ocr_debug.png",
        )

        self.assertEqual(result["scores"], {"player": "150", "opponent": "139"})
        self.assertEqual(result["halfScores"], {"player": "150", "opponent": "139"})
        self.assertTrue(all(cell["tile"] and cell["letter"] == "L" for cell in result["lCells"]))
        self.assertEqual(result["compactValues"], {"J5": 0, "K5": 0, "M5": 0, "H8": 10})
        self.assertEqual(result["rackO"], "O")
        self.assertEqual(page_errors, [])
        page.close()

    def test_board_change_clears_simulation_state(self):
        page, page_errors, _ = self.open_page()
        page.locator("#imageUrlInput").fill(f"{self.base_url}/test_board.png")
        self.wait_for_analysis(page)
        page.locator("#kibitzBtn").click()
        page.wait_for_function(
            "document.getElementById('engineStatus').textContent.includes('running 277 rounds') || "
            "document.getElementById('engineStatus').textContent.startsWith('Error:')",
            timeout=120_000,
        )
        self.assertIn("running 277 rounds", page.locator("#engineStatus").text_content())

        page.locator("#imageUrlInput").fill(f"{self.base_url}/IMG_3046.png")
        self.wait_for_analysis(page)
        expected_status = "Board ready. Run Quackle to estimate win percentages."
        self.assertEqual(page.locator("#engineStatus").text_content(), expected_status)
        self.assertTrue(page.locator("#movesContainer").evaluate("el => el.classList.contains('hidden')"))
        self.assertEqual(page.locator("#movesContainer").text_content(), "")
        self.assertFalse(page.locator("#kibitzBtn").is_disabled())
        page.wait_for_timeout(2_500)
        self.assertEqual(page.locator("#engineStatus").text_content(), expected_status)
        self.assertEqual(page.locator("#movesContainer").text_content(), "")
        self.assertEqual(page_errors, [])
        page.close()

    def test_manual_board_simulation(self):
        page, page_errors, console_messages = self.open_page()
        page.goto(f"{self.base_url}/manual.html", wait_until="domcontentloaded")
        page.evaluate("loadSample()")
        page.locator("#kibitzBtn").click()
        page.wait_for_function(
            "document.getElementById('engineStatus').textContent.includes('running 277 rounds') || "
            "document.getElementById('engineStatus').textContent.startsWith('Error:')",
            timeout=120_000,
        )
        self.assertIn("running 277 rounds", page.locator("#engineStatus").text_content())
        self.assertTrue(page.locator("#kibitzBtn").is_disabled())
        page.evaluate(
            "window.__manualHeartbeat = false; "
            "setTimeout(() => { window.__manualHeartbeat = true; }, 100)"
        )
        page.wait_for_function("window.__manualHeartbeat", timeout=5_000)
        page.wait_for_function(
            "document.getElementById('engineStatus').textContent.startsWith('Found ') || "
            "document.getElementById('engineStatus').textContent.startsWith('Error:')",
            timeout=120_000,
        )
        engine_status = page.locator("#engineStatus").text_content()
        self.assertTrue(engine_status.startswith("Found "), engine_status)
        self.assertIn("Simulated 277 rounds per move", engine_status)
        self.assertIn("4,155 playouts total", engine_status)
        win_cells = page.locator("#movesContainer td[data-samples]")
        self.assertEqual(win_cells.count(), 15)
        for index in range(win_cells.count()):
            cell = win_cells.nth(index)
            self.assertRegex(cell.text_content(), r"^(100|[0-9]{1,2})\.\d%$")
            self.assertEqual(cell.get_attribute("data-samples"), "277")
        self.assertFalse(page.locator("#kibitzBtn").is_disabled())
        self.assertFalse(any("bogowin heuristic" in message for message in console_messages))
        self.assertEqual(page_errors, [])
        page.close()

    def test_engine_load_retry(self):
        page, page_errors, _ = self.open_page()
        attempts = {"count": 0}

        def fail_first_worker_request(route):
            attempts["count"] += 1
            if attempts["count"] == 1:
                route.abort()
            else:
                route.continue_()

        page.route("**/quackle-worker.js", fail_first_worker_request)
        page.locator("#imageUrlInput").fill(f"{self.base_url}/test_board.png")
        self.wait_for_analysis(page)
        page.locator("#kibitzBtn").click()
        page.wait_for_function(
            "document.getElementById('engineStatus').textContent.includes('Engine load failed')",
            timeout=10_000,
        )
        self.assertFalse(page.locator("#kibitzBtn").is_disabled())
        self.assertTrue(page.evaluate("quackleWorker === null"))

        page.locator("#kibitzBtn").click()
        page.wait_for_function(
            "document.getElementById('engineStatus').textContent.startsWith('Found ') || "
            "document.getElementById('engineStatus').textContent.startsWith('Error:')",
            timeout=120_000,
        )
        engine_status = page.locator("#engineStatus").text_content()
        self.assertTrue(engine_status.startswith("Found "), engine_status)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(page_errors, [])
        page.close()

    def test_engine_rejects_impossible_tile_distribution(self):
        page, page_errors, _ = self.open_page()
        result = page.evaluate(
            """async () => {
              if (!await loadQuackleEngine()) throw new Error('Engine did not load');
              return callQuackleWorker('simulateKibitz', {
                gridJson: JSON.stringify(Array(15).fill('AAAAAAAAAAAAAAA')),
                rack: 'A', playerScore: 0, opponentScore: 0,
                numMoves: 15, iterations: 1, bagCount: 0, finalTurnsRemaining: 2
              });
            }"""
        )
        self.assertFalse(result["simulated"])
        self.assertEqual(result["iterationsCompleted"], 0)
        self.assertIn("more tiles than the Crossplay distribution", result["error"])
        self.assertEqual(page_errors, [])
        page.close()

    def test_engine_accepts_ocr_assigned_blanks(self):
        page, page_errors, _ = self.open_page()
        uppercase_grid = [
            "..........G....", ".......A.NOUN.Y", ".......L...TAME",
            "......YEAH...E.", ".........AB.YA.", "......LOB.OWED.",
            "..PROG..I.T.N.F", "....D..JOGS...I", "...LASSI.O..RUN",
            ".......V.R..I..", "...C...E..HIPS.", "...A.BASE.A.E..",
            "...R.O..D.V....", "..RENT.LITER...", ".....H..T......",
        ]
        lowercase_grid = uppercase_grid.copy()
        lowercase_grid[4] = ".........ab.yA."
        result = page.evaluate(
            """async ({uppercaseGrid, lowercaseGrid}) => {
              if (!await loadQuackleEngine()) throw new Error('Engine did not load');
              const run = (grid, bagCount = 4) => callQuackleWorker('simulateKibitz', {
                gridJson: JSON.stringify(grid), rack: 'IUAFTIO',
                playerScore: 150, opponentScore: 139,
                numMoves: 15, iterations: 1, bagCount, finalTurnsRemaining: 0
              });
              return {
                uppercase: await run(uppercaseGrid),
                lowercase: await run(lowercaseGrid),
                inconsistentBag: await run(lowercaseGrid, 5)
              };
            }""",
            {"uppercaseGrid": uppercase_grid, "lowercaseGrid": lowercase_grid},
        )
        self.assertIn("more tiles than the Crossplay distribution", result["uppercase"]["error"])
        self.assertTrue(result["lowercase"]["simulated"])
        self.assertEqual(result["lowercase"]["iterationsCompleted"], 1)
        self.assertTrue(all(move["samples"] == 1 for move in result["lowercase"]["moves"]))
        self.assertIn("seven hidden opponent tiles", result["inconsistentBag"]["error"])
        self.assertEqual(page_errors, [])
        page.close()

    def test_bag_empty_requires_explicit_final_turn_state(self):
        page, page_errors, _ = self.open_page()
        page.evaluate(
            """renderResult({
              grid: Array(15).fill('...............'), rack: 'A',
              player_score: 10, opponent_score: 20,
              player_name: 'You', opponent_name: 'Computer',
              bag_count: 0, tile_values_complete: true
            })"""
        )

        self.assertFalse(page.locator("#finalTurnPanel").evaluate("el => el.classList.contains('hidden')"))
        self.assertFalse(page.locator("#kibitzBtn").evaluate("el => el.classList.contains('hidden')"))
        self.assertTrue(page.locator("#kibitzBtn").is_disabled())
        self.assertIn("Choose the Crossplay final-turn state", page.locator("#engineStatus").text_content())

        page.locator("input[name='finalTurnState'][value='2']").check()
        self.assertFalse(page.locator("#kibitzBtn").is_disabled())
        self.assertEqual(page.evaluate("selectedFinalTurns"), 2)

        page.evaluate(
            """renderResult({
              grid: Array(15).fill('...............'), rack: 'A',
              player_score: 10, opponent_score: 20,
              player_name: 'You', opponent_name: 'Computer',
              bag_count: 10, tile_values_complete: true
            })"""
        )
        self.assertTrue(page.locator("#finalTurnPanel").evaluate("el => el.classList.contains('hidden')"))
        self.assertEqual(page.evaluate("selectedFinalTurns"), 0)
        self.assertFalse(page.locator("#kibitzBtn").is_disabled())
        self.assertEqual(page_errors, [])
        page.close()

    def test_near_end_simulation_reaches_crossplay_finish(self):
        page, page_errors, _ = self.open_page()
        grid = [
            "..........G....", ".......A.NOUN.Y", ".......L...TAME",
            "......YEAH...E.", ".........ab.yA.", "......LOB.OWED.",
            "..PROG..I.TEN.F", "....D..JOGS...I", "...LASSI.O..RUN",
            ".......V.R.MI..", "...C...E..HIPS.", "...A.BASE.A.E..",
            "...R.O..D.V....", "..RENT.LITER...", ".....H..T......",
        ]
        result = page.evaluate(
            """async grid => {
              if (!await loadQuackleEngine()) throw new Error('Engine did not load');
              return callQuackleWorker('simulateKibitz', {
                gridJson: JSON.stringify(grid), rack: 'WEAFTUO',
                playerScore: 150, opponentScore: 156,
                numMoves: 15, iterations: 277, bagCount: 2, finalTurnsRemaining: 0
              });
            }""",
            grid,
        )
        self.assertEqual(result["error"], "")
        self.assertTrue(result["simulated"])
        self.assertTrue(result["playToEnd"])
        self.assertEqual(result["simulationMode"], "play-to-end")
        self.assertEqual(result["winModel"], "terminal")
        self.assertEqual(result["plies"], -1)
        self.assertEqual(result["bagCount"], 2)
        self.assertEqual(result["finalTurnsRemaining"], 0)
        self.assertEqual(result["iterationsCompleted"], 277)
        self.assertTrue(all(
            move["samples"] == 277 and move["terminalSamples"] == 277
            for move in result["moves"]
        ))
        self.assertEqual(page_errors, [])
        page.close()

    def test_custom_move_terminal_simulation(self):
        page, page_errors, _ = self.open_page()
        grid = [
            '..........G....', '.......A.NOUN.Y', '.......L...TAME',
            '......YEAH...E.', '.........ab.yA.', '......LOB.OWED.',
            '..PROG..I.TEN.F', '....D..JOGS...I', '...LASSI.O..RUN',
            '.......V.R.MI..', '...C...E..HIPS.', '...A.BASE.A.E..',
            '...R.O..D.V....', '..RENT.LITER...', '.....H..T......',
        ]
        result = page.evaluate('''async grid => {
          if (!await loadQuackleEngine()) throw new Error('Engine did not load');
          return callQuackleWorker('simulateMove', {
            gridJson: JSON.stringify(grid), rack: 'WEAFTUO',
            playerScore: 150, opponentScore: 156, iterations: 1,
            bagCount: 2, finalTurnsRemaining: 0,
            customMove: { word: 'OUTWEAR', square: 'D1', direction: 'down' }
          });
        }''', grid)
        self.assertTrue(result['simulated'])
        self.assertTrue(result['playToEnd'])
        self.assertEqual(result['selected']['score'], 51)
        self.assertEqual(result['selected']['samples'], 1)
        self.assertEqual(result['selected']['terminalSamples'], 1)
        self.assertEqual(result['simulationMode'], 'play-to-end')
        self.assertEqual(page_errors, [])
        page.close()

    def test_observed_last_turn_runs_277_terminal_samples(self):
        page, page_errors, _ = self.open_page()
        page.locator("#imageUrlInput").fill(f"{self.base_url}/IMG_153_169.png")
        self.wait_for_analysis(page)

        self.assertEqual(page.evaluate("selectedFinalTurns"), 1)
        self.assertTrue(page.locator("#finalTurnPanel").evaluate(
            "el => el.classList.contains('hidden')"
        ))
        page.locator("#kibitzBtn").click()
        page.wait_for_function(
            "document.getElementById('engineStatus').textContent.startsWith('Found ') || "
            "document.getElementById('engineStatus').textContent.startsWith('Error:')",
            timeout=120_000,
        )

        engine_status = page.locator("#engineStatus").text_content()
        self.assertIn("Played 277 rounds per move", engine_status)
        self.assertIn("4,155 playouts total", engine_status)
        win_cells = page.locator("#movesContainer tbody tr:not(:first-child) td:nth-child(4)")
        self.assertEqual(win_cells.count(), 15)
        for index in range(win_cells.count()):
            cell = win_cells.nth(index)
            self.assertEqual(cell.get_attribute("data-samples"), "277")
            self.assertRegex(cell.text_content(), r"^(100|[0-9]{1,2})\.\d%$")
        self.assertFalse(page.locator("#kibitzBtn").is_disabled())
        self.assertEqual(page_errors, [])
        page.close()

    def test_simulation_rejects_more_than_277_rounds(self):
        page, page_errors, _ = self.open_page()
        result = page.evaluate(
            """async () => {
              if (!await loadQuackleEngine()) throw new Error('Engine did not load');
              return callQuackleWorker('simulateKibitz', {
                gridJson: JSON.stringify(Array(15).fill('...............')),
                rack: 'A', playerScore: 0, opponentScore: 0,
                numMoves: 15, iterations: 278, bagCount: 92, finalTurnsRemaining: 0
              });
            }"""
        )
        self.assertEqual(
            result["error"],
            "Simulation iterations must be between 1 and 277",
        )
        self.assertEqual(page_errors, [])
        page.close()

    def test_worker_rejects_fractional_game_state(self):
        page, page_errors, _ = self.open_page()
        errors = page.evaluate(
            """async () => {
              if (!await loadQuackleEngine()) throw new Error('Engine did not load');
              const run = async (bagCount, finalTurnsRemaining) => {
                try {
                  await callQuackleWorker('simulateKibitz', {
                    gridJson: JSON.stringify(Array(15).fill('...............')),
                    rack: 'A', playerScore: 0, opponentScore: 0,
                    numMoves: 15, iterations: 1, bagCount, finalTurnsRemaining
                  });
                  return '';
                } catch (error) {
                  return error.message;
                }
              };
              return {
                bag: await run(92.5, 0),
                finalTurns: await run(0, 1.5)
              };
            }"""
        )
        self.assertIn("must be integers", errors["bag"])
        self.assertIn("must be integers", errors["finalTurns"])
        self.assertEqual(page_errors, [])
        page.close()

    def test_empty_bag_simulation_requires_the_observed_phase(self):
        page, page_errors, _ = self.open_page()
        grid = [
            "CD........G....", ".......A.NOUN.Y", ".......L...TAME",
            "......YEAH...E.", ".........ab.yA.", "......LOB.OWED.",
            "..PROG..I.TEN.F", "....D..JOGS...I", "...LASSI.O..RUN",
            ".......V.R.MI..", "...C...E..HIPS.", "...A.BASE.A.E..",
            "...R.O..D.V....", "..RENT.LITER...", ".....H..T......",
        ]
        result = page.evaluate(
            """async grid => {
              if (!await loadQuackleEngine()) throw new Error('Engine did not load');
              const run = finalTurnsRemaining => callQuackleWorker('simulateKibitz', {
                gridJson: JSON.stringify(grid), rack: 'WEAFTUO',
                playerScore: 150, opponentScore: 156,
                numMoves: 15, iterations: 1, bagCount: 0, finalTurnsRemaining
              });
              return {
                unknown: await run(0),
                firstFinal: await run(2),
                lastFinal: await run(1)
              };
            }""",
            grid,
        )
        self.assertIn("Choose whether one or two", result["unknown"]["error"])
        for key, expected_turns in (("firstFinal", 2), ("lastFinal", 1)):
            simulation = result[key]
            self.assertTrue(simulation["simulated"])
            self.assertEqual(simulation["finalTurnsRemaining"], expected_turns)
            self.assertTrue(simulation["playToEnd"])
            self.assertTrue(all(move["terminalSamples"] == 1 for move in simulation["moves"]))
        self.assertEqual(page_errors, [])
        page.close()

    def test_rack_blank_enables_quackle(self):
        page, page_errors, _ = self.open_page()
        page.evaluate(
            """renderResult({
              grid: Array(15).fill('...............'), rack: '?',
              player_score: 0, opponent_score: 0,
              player_name: 'You', opponent_name: 'Opponent',
              bag_count: 92,
              tile_values_complete: true
            })"""
        )
        self.assertFalse(page.locator("#kibitzBtn").evaluate("el => el.classList.contains('hidden')"))
        self.assertEqual(page.evaluate("lastParsed.rack"), "?")
        self.assertEqual(page_errors, [])
        page.close()

    def test_drop_input(self):
        page, page_errors, _ = self.open_page()
        fixture = "test_board.png"
        encoded = base64.b64encode((ROOT / fixture).read_bytes()).decode("ascii")
        page.evaluate(
            """({name, encoded}) => {
              const bytes = Uint8Array.from(atob(encoded), value => value.charCodeAt(0));
              const file = new File([bytes], name, {type: 'image/png'});
              const transfer = new DataTransfer();
              transfer.items.add(file);
              document.getElementById('dropZone').dispatchEvent(new DragEvent('drop', {
                bubbles: true,
                cancelable: true,
                dataTransfer: transfer
              }));
            }""",
            {"name": fixture, "encoded": encoded},
        )
        page.wait_for_function("document.getElementById('status').textContent.includes('Image ready')")
        self.wait_for_analysis(page)
        self.assertEqual(page.locator("#tileCount").text_content(), "31")
        self.assertEqual(page_errors, [])
        page.close()

    def test_photo_library_input(self):
        page, page_errors, _ = self.open_page()
        fixture = "test_board.png"
        page.locator("#imageFileInput").set_input_files(str(ROOT / fixture))
        page.wait_for_function("document.getElementById('status').textContent.includes('Image ready')")
        self.wait_for_analysis(page)
        self.assertEqual(page.locator("#tileCount").text_content(), "31")
        self.assertEqual(page_errors, [])
        page.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
