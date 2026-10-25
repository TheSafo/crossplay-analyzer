# Crossplay Board Analyzer

Review completed NYT Crossplay games, replay turns, and compare plays with Quackle. You can also parse screenshots locally in the browser or enter a board by hand.

## Run locally

Use Python 3.10 or newer:

```bash
python3 crossplay_server.py 8000
```

Open [http://localhost:8000](http://localhost:8000). On the game review page, paste the `NYT-S` cookie from a signed-in NYTimes browser session. The local server validates it with NYT and keeps it in memory for that browser's session. Use **Forget cookie** to remove it. After restarting the server, connect again.

The recent games list comes from NYT's Crossplay service and only completed games can be reviewed. NYT may change its service endpoints or session requirements.

Each game review starts with the result and labeled scores, your points per turn and highest-scoring play, and an interactive cumulative-score timeline. Analyze move quality to see your best-move count, average equity loss, and largest rated opportunities; select an opportunity to replay that turn. Personal summaries exclude opponent moves and unrated turns. Partial analysis and rated-turn coverage are labeled. Estimated win chances remain available under **Explore estimated win chances**.

Opening a finished game puts its shareable URL in the address bar. Send that URL to a friend, or expand **Share this game** and use **Copy game link**. Anyone with the link can replay that game and view player names, scores, racks, and saved analysis without signing in or connecting an NYT account. Links use a random token and grant access only to that game. Guests can run Quackle in their own browser; their analysis does not change the owner's saved results.

Hosted links persist in Supabase. Apply all migrations in `supabase/migrations/` before deploying this feature. Local links last until the owner's local session expires, its cookie is forgotten or replaced, or the server restarts; recipients must be able to reach the server's address. For synthetic data without real credentials, use `npm run frontend` as described under Tests.

The screenshot parser is at `/screenshot.html` and the manual board page is at `/manual.html`. Screenshot parsing and the bundled Quackle engine run locally in the browser.

Use **Try a custom move** on any analysis page to evaluate a word outside
Quackle’s suggested moves. Enter the word, its start square (for example, `G8`),
and Across or Down. Include existing board letters or use `.` for them; uppercase
letters use regular rack tiles and lowercase letters use blanks. Game reviews
evaluate against the board and rack **before** the selected turn.

The result compares score, rack leave, and static equity with the best legal
move. **Estimate win% (slower)** runs 277 samples per candidate and compares
simulated equity and win chances. Moves far down the static ranking take longer
because the bundled engine must simulate the candidates above them too. You can
cancel a custom evaluation independently of other analysis. Custom results stay
in the current page and do not alter the recorded game or saved move-quality review.

## Datadog

All integrations target the US5 site, `us5.datadoghq.com`, with service
`crossplay-analyzer`. Browser monitoring uses environment `production`; tests
use `ci`.

### Browser RUM and Error Tracking

1. Create a **Browser** RUM application in Datadog. In the shared
   `datadog-rum.js` file, replace both public placeholder values:
   - `REPLACE_WITH_DATADOG_RUM_APPLICATION_ID`: the RUM application ID.
   - `REPLACE_WITH_DATADOG_RUM_CLIENT_TOKEN`: the RUM client token.
2. Redeploy. `index.html`, `screenshot.html`, and `manual.html` load that shared
   file, which loads the US5 Browser RUM v6 SDK asynchronously from Datadog's
   CDN. Until **both** placeholders are filled, it loads no SDK and sends no
   telemetry. Allow `www.datadoghq-browser-agent.com` and Datadog US5 RUM intake
   in any deployment content security policy or network allow list.
3. Verify page views, resources, and browser errors in RUM / Error Tracking.

The application ID and client token are public browser configuration. **Never
put `DD_API_KEY` or `DD_APP_KEY` in frontend files.** Session Replay is disabled
(`sessionReplaySampleRate: 0`), `defaultPrivacyLevel: 'mask'` masks all content
and inputs, and the NYT-S form has `data-dd-privacy="hidden"` as an additional
protection. Do not add cookies, request headers/bodies, or authentication data
to RUM context or error messages. Screenshot processing and Quackle remain
local; configured RUM sends browser diagnostics to Datadog.

RUM injects Datadog and W3C trace context only into same-origin
`/api/crossplay` and `/api/crossplay/...` requests. Other origins, including
NYTimes and Supabase, do not receive these tracing headers. To see linked
backend spans, the deployed API must also have Datadog APM ingestion configured
and extract this incoming trace context; the browser configuration alone does
not create backend traces. Backend APM deployment setup is separate from this
repository's browser and CI instrumentation.

### GitHub Actions: pipelines, Test Optimization, and Code Security

Add these **repository Actions secrets** from the same Datadog organization:

| Secret | Required for |
| --- | --- |
| `DD_API_KEY` | Agentless Python test reporting, pipeline custom spans, SAST, and SCA |
| `DD_APP_KEY` | SAST and SCA, with the Code Security access required by the Datadog actions |

In Datadog, connect this repository through the **GitHub integration**, enable
**CI Visibility / Pipeline Visibility** for GitHub Actions, and enable **Test
Optimization** and **Code Security** for the repository. The GitHub integration
supplies full workflow/job/step events. The API key and `datadog-ci trace`
custom span in `test.yml` do not replace that integration.

The existing Test workflow runs `npm test`, covering the API, sharing, game
review, browser pipeline, grid-detection, score-OCR, and RUM checks. The Python
suites run through pytest, with adapters for the standalone OCR/grid scripts.
When `DD_API_KEY` is present, `PYTEST_ADDOPTS=--ddtrace` sends individual Python
test results directly to Datadog, and `datadog-ci trace` adds a regression step
span to the pipeline. The adapters preserve each script's exit status
and execute inside pytest so coverage can be associated with each test;
they do not change OCR or grid checks. RUM privacy and trace-routing checks
run with `npm run test:rum`.

The Datadog Code Security workflow runs the official SAST and SCA actions on
pushes, manual dispatch, and weekly. Datadog Code Security rejects
`pull_request` events, so branch updates use only `push` to avoid duplicate
scans. The Test workflow continues to run on pull requests. SAST uses the Python
and JavaScript security rules in `static-analysis.datadog.yml`; SCA scans dependency
manifests. The test tracer has an exact version in `requirements-test.txt`
because SCA omits ranged versions. SCA still runs if SAST fails. Without the
repository secrets (including fork pull requests), Python tests run without Datadog and security
scans are explicitly skipped. Neither workflow uses `pull_request_target`,
and both only request read access to repository contents.

For local validation:

```bash
npm run frontend                 # mock API/dev server on port 8000
npm run test:rum                 # no npm dependencies or Datadog credentials
npm test                         # full Python and RUM presubmit suite
```

The Python suites need `requirements-test.txt` and a Playwright Chromium
installation, as described below. Local tests do not upload to Datadog unless
explicitly instrumented and given credentials.

## Deploy to Vercel

Vercel serves the HTML and analyzer assets as static files and runs the game-review API as a Python Function. [`vercel.json`](vercel.json) configures the same-origin API route, function region, duration, and bundle exclusions. The function uses `cryptography` from `requirements.txt` to encrypt remembered NYT cookies. Vercel's Python runtime is [generally available](https://vercel.com/changelog/python-on-vercel-is-now-generally-available).

1. Connect a GitHub repository in Vercel, or install the Vercel CLI and sign in:

   ```bash
   npm install --global vercel
   vercel login
   vercel link
   ```

   You can deploy this local checkout with the CLI without forking Kyle's repository. If you want GitHub to trigger deployments automatically, connect a repository your GitHub account can access; fork it if you don't have access to the original.

2. Keep the project root as the repository root and the framework preset as **Other**. Leave the build command and output directory empty; Vercel serves the root files directly.
3. Deploy a preview with `vercel`, then deploy production with `vercel --prod`. With GitHub connected, pushes can deploy automatically.
4. Configure Supabase and Google sign-in before using the production deployment:

   - Apply the checked-in migration with the Supabase CLI from the repository root:

     ```bash
     supabase link --project-ref xxqskwsnnfnpghatcbds
     supabase db push
     ```

     The linked project ref is the one in `supabase-config.js`. Supabase CLI state is local and ignored by Git.
   - In Supabase **Authentication → Providers → Google**, enable Google and enter a Google OAuth client ID and secret. In Google Cloud, set the authorized redirect URI to the callback URL shown in that Supabase provider page. Keep the Google client secret in Supabase, not in Vercel or this repository.
   - In Supabase **Authentication → URL Configuration**, set the production Site URL to your Vercel app URL and add it to the redirect allow list. Supabase allows wildcard patterns for Vercel preview URLs; only add previews if you plan to use them.
   - In Vercel **Project → Settings → Environment Variables**, add `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, and `NYT_COOKIE_ENCRYPTION_KEY` for Production (and Preview if desired). `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are the project URL and public key in `supabase-config.js`; `SUPABASE_SECRET_KEY` must be a new server-only `sb_secret_...` key from Supabase **Settings → API Keys**. Generate a separate 32-byte encryption key locally with `python3 -c 'import secrets; print(secrets.token_hex(32))'` and save that output directly as `NYT_COOKIE_ENCRYPTION_KEY` in Vercel. Do not commit or paste that encryption key into chat. Changing it makes previously remembered NYT cookies unreadable, so users would need to reconnect.
   - Redeploy after adding the variables.

5. Open the HTTPS deployment URL, choose **Sign in with Google**, then paste the `NYT-S` cookie from a signed-in NYTimes browser session. Imported games and completed analyses are saved to the signed-in Supabase account. The cookie is sent over HTTPS and is encrypted before it is stored when **Remember this NYT cookie encrypted on my account** is checked; uncheck it to keep the cookie only in page memory. **Forget cookie** deletes the saved copy.

The local server keeps its existing in-memory browser session and does not use Supabase persistence. The screenshot parser and manual board page remain local browser tools. Vercel ignores local fixtures, developer notes, and test tooling through `.vercelignore`.

Vercel Hobby is free for personal, non-commercial use. The [Hobby plan](https://vercel.com/docs/plans/hobby) allows Functions up to 60 seconds, which is configured here.

Do not put NYT cookies in deployment variables, browser storage, query strings, logs, HAR files, or committed fixtures. If you add a custom Vercel domain, set `APP_ALLOWED_HOSTS` to its hostname in the Vercel project environment variables.

## Tests

### Develop and test with fake NYT data

Start the real frontend and local API with a synthetic NYT transport:

```bash
npm run frontend
# Open http://127.0.0.1:8000
```

Enter `mock-nyt-cookie-for-local-testing` in the **NYT-S cookie** field and click
**Connect**. No real NYT cookie, Supabase account, or network access is needed.
Two finished games are available to replay and analyze with the bundled Quackle
engine; an active game is hidden. Fixtures include existing letters, an assigned
blank, a swap, passes, and a game fetched through the detail endpoint.

The transport replaces only upstream NYT JSON requests. The frontend, HTTP API,
cookie validation, browser sessions, game summaries, and replay use the normal
application code. All players, identifiers, and abbreviated games in
`tools/fixtures/nyt.json` are invented, not captured account data. This exercises
the local API; Vercel's Google sign-in and Supabase persistence are not emulated.

Other fake cookie values exercise error and empty states:

| Cookie value | Scenario |
| --- | --- |
| `mock-empty-cookie-for-local-testing` | Connected account with no recent games |
| `mock-expired-cookie-for-local-testing` | NYT rejects the cookie (401) |
| `mock-outage-cookie-for-local-testing` | Connect succeeds; loading games fails (502) |

`npm run frontend -- 8001` selects another port; `PORT` and `HOST` are also
supported. The default bind address is loopback. Mock mode requires the explicit
`--mock-nyt` flag and is rejected when `VERCEL` is set. Running
`python3 crossplay_server.py 8000` without the flag still uses the live NYT API.

### Run presubmit checks

Use Node.js 22+ and Python 3.10+. Install the test dependencies and Chromium:

```bash
python3 -m pip install -r requirements-test.txt
python3 -m playwright install chromium
```

Bits Code already provides system Chrome, which the browser tests use if
Playwright's bundled Chromium is unavailable. There are no npm dependencies;
`npm ci --ignore-scripts` verifies the package lock without downloading packages.

Run the same suite used for GitHub pull requests:

```bash
npm test
```

Individual suites are available as `npm run test:api` (standard-library HTTP API
and upstream transport tests), `npm run test:sharing` (local and persisted sharing
authorization checks), `npm run test:review` (Playwright game review and
real Quackle analysis), and `npm run test:ocr` (existing grid, score OCR, screenshot
upload, manual board, and engine regressions). API and review tests start and stop
isolated mock servers on free ports; each browser test uses a fresh context and
blocks external requests. No service credentials or GitHub secrets are needed.

To run review checks against the interactive dev server instead:

```bash
# Keep npm run frontend running in another terminal.
CROSSPLAY_TEST_BASE_URL=http://127.0.0.1:8000 npm run test:review
```

For agent-driven exploration, use the `playwright-cli` skill with that server,
then navigate and connect through the visible form:

```bash
playwright-cli open http://127.0.0.1:8000 --browser=chrome
playwright-cli snapshot
# Click the NYT-S textbox ref from the snapshot, then:
playwright-cli type "mock-nyt-cookie-for-local-testing"
# Click Connect, then a finished game; use snapshot to inspect current refs.
playwright-cli close
```

Keep local `.env` files, HAR captures, and account game data out of commits. Those files are ignored by Git.

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE). If you run a modified version of this project as a network service, you must offer its source to the users of that service.

The bundled Quackle engine (`quackle.js`, `quackle.wasm`, `quackle.data`) is built from [Quackle](https://github.com/quackle/quackle), which is licensed under the GPL. Check the dictionary data bundled with it for its own terms. "NYT Crossplay" is a trademark of its owner, and this project is not affiliated with or endorsed by The New York Times.
