# Crossplay Board Analyzer

Review completed NYT Crossplay games, replay turns, and compare plays with Quackle. You can also parse screenshots locally or enter a board by hand.

## Run locally

Use Python 3.10 or newer:

```bash
python3 crossplay_server.py 8000
```

Open [http://localhost:8000](http://localhost:8000). The game review page asks for the value of the `NYT-S` cookie from a signed-in NYTimes browser session. The cookie is sent to the local server, validated with NYT, and saved in a `.env` file with owner-only permissions. Use **Forget cookie** to remove it.

The server binds to `127.0.0.1`; the app does not send the cookie to another host. The recent games list comes from NYT's Crossplay service and only completed games can be reviewed. NYT may change its service endpoints or session requirements.

The screenshot parser is at `/screenshot.html` and the manual board page is at `/manual.html`. Screenshot parsing and the bundled Quackle engine run locally in the browser.

## Tests

Install the test dependencies and Chromium:

```bash
python3 -m pip install -r requirements-test.txt
python3 -m playwright install chromium
```

Then run the root-level Python tests:

```bash
python3 test_grid_detection.py
python3 test_score_ocr.py
python3 test_browser_pipeline.py
```

Keep `.env`, HAR captures, and account game data out of commits. Those local files are ignored by Git.
