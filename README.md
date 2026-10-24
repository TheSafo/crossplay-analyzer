# Crossplay Board Analyzer

Review completed NYT Crossplay games, replay turns, and compare plays with Quackle. You can also parse screenshots locally in the browser or enter a board by hand.

## Run locally

Use Python 3.10 or newer:

```bash
npm run frontend
```

Open [http://localhost:8000](http://localhost:8000). On the game review page, paste the `NYT-S` cookie from a signed-in NYTimes browser session. The local server validates it with NYT and keeps it in memory for that browser's session. Use **Forget cookie** to remove it. After restarting the server, connect again.

The recent games list comes from NYT's Crossplay service and only completed games can be reviewed. NYT may change its service endpoints or session requirements.

Opening a finished game puts its shareable URL in the address bar. Send that URL to a friend, or use **Copy game link**. Anyone with the link can replay that game and view player names, scores, racks, and saved analysis without signing in or connecting an NYT account. Links use a random token and grant access only to that game. Guests can run Quackle in their own browser; their analysis does not change the owner's saved results.

Hosted links persist in Supabase. Apply all migrations in `supabase/migrations/` before deploying this feature. Local links last until the owner's local session expires, its cookie is forgotten or replaced, or the server restarts; recipients must be able to reach the server's address. Without npm, run `python3 crossplay_server.py 8000` directly.

The screenshot parser is at `/screenshot.html` and the manual board page is at `/manual.html`. Screenshot parsing and the bundled Quackle engine run locally in the browser.

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
python3 -m unittest test_game_sharing.py
```

Keep local `.env` files, HAR captures, and account game data out of commits. Those files are ignored by Git.

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE). If you run a modified version of this project as a network service, you must offer its source to the users of that service.

The bundled Quackle engine (`quackle.js`, `quackle.wasm`, `quackle.data`) is built from [Quackle](https://github.com/quackle/quackle), which is licensed under the GPL. Check the dictionary data bundled with it for its own terms. "NYT Crossplay" is a trademark of its owner, and this project is not affiliated with or endorsed by The New York Times.
