# Repository Guidelines

Contributor guide for Crossplay Board Analyzer. It can review finished NYT Crossplay games through a local API proxy or a Vercel Function, parse screenshots entirely offline, accept manual board input, and analyze positions with the bundled Quackle engine. The game review uses the NYT Crossplay service; no OpenAI API is used.

## Project Structure & Module Organization

- `index.html` — game review UI, same-origin API connection, turn replay, and on-demand Quackle analysis.
- `screenshot.html` — offline screenshot parsing: grid detection, tile detection, OCR, word finding, and Quackle analysis.
- `manual.html` — manual board-input page.
- `crossplay_server.py` — localhost static server and JSON proxy for NYT Crossplay requests. Local browser sessions are held in memory. In Vercel, Supabase Auth identifies users; the page can hold the NYT-S value in memory, or the function can decrypt a remembered per-user cookie from Supabase before making NYT requests.
- `api/crossplay.py` — Vercel Python Function entry point for the review API.
- `supabase-auth.js` and `supabase-config.js` — browser PKCE login and public Supabase project config.
- `supabase/migrations/` — schema for per-user imported games, completed analyses, and encrypted NYT cookie storage.
- `requirements.txt` — Python runtime dependencies for Vercel Functions.
- `vercel.json` — Vercel route, region, function duration, and bundle configuration.
- `.vercelignore` — keeps local fixtures, private data, and development files out of deployments.
- `quackle.js`, `quackle.wasm`, `quackle.data` — bundled Quackle engine and dictionary.
- `quackle-worker.js` — runs Quackle move generation and simulation off the page thread.
- `test_board.png` and `IMG_*.png` — screenshot fixtures.
- `test_grid_detection.py`, `test_score_ocr.py`, and `test_browser_pipeline.py` — offline CV/OCR and browser regression tests.
- `tools/har_summary.py` — summarizes HAR endpoint paths and can write redacted response captures. Keep raw captures, redacted game data, and credentials out of version control.

## Build, Test, and Development Commands

Start the local proxy server to use the review page:

```bash
python3 crossplay_server.py 8000
# Open http://localhost:8000
```

The server uses Python's standard library. Vercel serves static files directly and invokes the Python entry point in `api/crossplay.py`; deployment behavior is configured in `vercel.json`. The screenshot tests additionally need Python 3.10+, NumPy, Pillow, SciPy, Playwright, and Chromium:

```bash
python3 -m pip install -r requirements-test.txt
python3 -m playwright install chromium
python3 test_grid_detection.py
python3 test_score_ocr.py
python3 test_browser_pipeline.py
```

The review page talks to the same-origin API. On Vercel, the NYT-S value is sent in an HTTPS request header and kept only in page memory unless the user opts to remember it; remembered values are encrypted by the function before they are stored in Supabase. Do not put NYT cookies in browser storage, deployment variables, query strings, logs, HAR files, or committed fixtures. Supabase secret keys and the cookie encryption key belong only in Vercel environment variables.

## Coding Style & Naming Conventions

- JavaScript: 2-space indent and `camelCase`.
- Python: 4-space indent and `snake_case`.
- No linter or formatter is configured; match the surrounding style.
- Keep browser pages self-contained and avoid adding external runtime dependencies.
- Keep the screenshot analyzer offline and deterministic. API work belongs in the local server and game review page.

## Testing Guidelines

- Python tests live at the repository root and use the example screenshots.
- The browser pipeline test opens `screenshot.html` and checks parsing and Quackle output.
- New CV/OCR work should update or add a root-level test so regressions remain reproducible offline.
- API behavior should be exercised against sanitized fixtures or a stubbed client; do not commit account data or credentials.

## Commit & Pull Request Guidelines

- Use an imperative, descriptive subject (for example, `Fix grid detection: ...` or `Add game review: ...`) followed by a body explaining the change and validation.
- Keep changes focused and describe user-visible behavior, implementation, and validation in PRs.
- Screenshots or sanitized output are useful for UI and parsing changes.

## Architecture Overview

The screenshot path is **premium-label grid detection → tile detection → template-match letter and score OCR → word finding → Quackle kibitz → win estimates**. The game review path is **NYT-S supplied by the browser or decrypted from per-user encrypted storage → same-origin local API or Vercel Function → imported finished games and reviews in Supabase → turn-by-turn board reconstruction → on-demand Quackle analysis saved per game**. Vercel requests require a verified Supabase Auth user. Locally, the server binds to loopback and keeps the NYT session in memory.
