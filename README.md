# Crossplay Board Analyzer

Review completed NYT Crossplay games, replay turns, and compare plays with Quackle. You can also parse screenshots locally in the browser or enter a board by hand.

## Run locally

Use Python 3.10 or newer:

```bash
python3 crossplay_server.py 8000
```

Open [http://localhost:8000](http://localhost:8000). On the game review page, paste the `NYT-S` cookie from a signed-in NYTimes browser session. The local server validates it with NYT and keeps it in memory for that browser's session. Use **Forget cookie** to remove it. After restarting the server, connect again.

The recent games list comes from NYT's Crossplay service and only completed games can be reviewed. NYT may change its service endpoints or session requirements.

The screenshot parser is at `/screenshot.html` and the manual board page is at `/manual.html`. Screenshot parsing and the bundled Quackle engine run locally in the browser.

## Deploy to Vercel

Vercel serves the HTML and analyzer assets as static files and runs the game-review API as a Python Function. [`vercel.json`](vercel.json) configures the same-origin API route, function region, duration, and bundle exclusions. No build command or third-party runtime Python package is needed. Vercel's Python runtime is [generally available](https://vercel.com/changelog/python-on-vercel-is-now-generally-available).

1. Connect a GitHub repository in Vercel, or install the Vercel CLI and sign in:

   ```bash
   npm install --global vercel
   vercel login
   vercel link
   ```

   You can deploy this local checkout with the CLI without forking Kyle's repository. If you want GitHub to trigger deployments automatically, connect a repository your GitHub account can access; fork it if you don't have access to the original.

2. Keep the project root as the repository root and the framework preset as **Other**. Leave the build command and output directory empty; Vercel serves the root files directly.
3. Deploy a preview with `vercel`, then deploy production with `vercel --prod`. With GitHub connected, pushes can deploy automatically.
4. Open the HTTPS deployment URL. Each person pastes their own NYT-S cookie on the game-review page.

For this stateless Vercel version, the NYT-S value stays in page memory and is sent over HTTPS in a request header to this app's API. It is not placed in a website cookie, local storage, or a query string. Reloading or closing the page clears it, so paste it again next time. The local server keeps its existing in-memory browser session. Vercel ignores local fixtures, developer notes, and test tooling through `.vercelignore`.

Vercel Hobby is free for personal, non-commercial use. The [Hobby plan](https://vercel.com/docs/plans/hobby) allows Functions up to 60 seconds, which is configured here. If you later want the connection to survive page reloads, Supabase can store encrypted server-side sessions; the current app does not need a database.

Do not put NYT cookies in deployment variables, browser storage, query strings, logs, HAR files, or committed fixtures. If you add a custom Vercel domain, set `APP_ALLOWED_HOSTS` to its hostname in the Vercel project environment variables.

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

Keep local `.env` files, HAR captures, and account game data out of commits. Those files are ignored by Git.
