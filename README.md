# Market Headlines

A small web app that:

- shows the latest financial news from major outlets (Wall Street Journal, New York Times, CNBC, Financial Times) on the front page, merged, de-duplicated and sorted newest first
- has a left sidebar to pick one news source (WSJ, NYT, CNBC, FT) or all of them; on phones it becomes a row of pills
- has a top ticker bar with live prices for AAPL, META, NVDA, AMAT, AVGO, LLY, GOOGL and MSFT. Visitors can add tickers with **+** and remove them with **×**; their list is saved in their browser
- given a ticker symbol (for example `AAPL`), shows the current quote, the change on the day, a one-month price chart and related headlines
- has a **Portfolio** tab with live prices for every ticker. A **1D / 1M / 3M / 6M / 1Y / 2Y / 5Y** picker (default 1D, today's change) sets each card's price change badge and what the research compares with (saved in the browser). Clicking a ticker opens a side panel with that company's top 3 headlines
- runs a **market research agent** for every company in the Portfolio, following the financial-report-analysis method: it reads the latest 10-K/10-Q figures from SEC EDGAR, compares them with the same period a year earlier (or a quarter, two quarters, two or five years earlier, from the picker; companies report quarterly, so 1M uses the prior quarter), and shows **risks and red flags first**, then the headline, a key metrics table (revenue, margins, net income, EPS, cash flow, free cash flow, cash, debt, buybacks, dividends), what drove the results, guidance and sources. With `ANTHROPIC_API_KEY` set, Claude writes the drivers, guidance and extra risks from the figures and recent headlines; without it the analysis is rule-based. Each company gets its own tab with a risk-level dot, so you read one analysis at a time: risks first, four key number tiles, and a "Show" section with all fundamentals, drivers, guidance and sources. It is factual analysis only, not financial advice
- has a light/dark mode toggle in the header on every page. It follows the system setting until the visitor picks one, then remembers that choice in their browser

Built with FastAPI, Jinja templates, httpx and feedparser.

## Put it online

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sureshadi/MyApplication)

Click the button, sign in to Render (GitHub sign-in works), and click **Deploy Blueprint**. Render reads `render.yaml`, builds the app and gives you a public URL like `https://market-headlines.onrender.com`. It redeploys automatically on every push to `main`.

On the free plan the site sleeps after about 15 minutes without visitors, so the first visit after that takes up to a minute to load.

A `Dockerfile` is also included for Docker-based hosts (Fly.io, Railway, Google Cloud Run).

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

### Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `FINNHUB_API_KEY` | unset | If set, quotes come from [Finnhub](https://finnhub.io) (free key). Otherwise Yahoo Finance's public chart endpoint is used. |
| `CACHE_TTL_SECONDS` | `300` | How long news and quotes are cached in memory. |
| `WATCHLIST` | `AAPL,META,NVDA,AMAT,AVGO,LLY,GOOGL,MSFT` | Default tickers in the top bar. |
| `MAX_ITEMS_PER_SOURCE` | `12` | Most headlines any one outlet can take on the front page, so busy feeds don't crowd out the rest. |
| `HTTP_TIMEOUT_SECONDS` | `10` | Timeout for each outside request. |
| `SEC_USER_AGENT` | generic | SEC EDGAR asks automated clients to identify themselves, e.g. `Your Name you@example.com`. Set this in production. |
| `ANTHROPIC_API_KEY` | unset | Optional. Turns on Claude-written drivers, guidance and risks in the market research (model `claude-opus-5-5`). |
| `PORTFOLIO_USER` | unset | Username for the Portfolio sign-in (not case sensitive). |
| `PORTFOLIO_PASSWORD` | unset | Password for the Portfolio sign-in. Until both are set, Portfolio stays locked. Never commit it. |
| `SESSION_SECRET` | derived | Optional key that signs the sign-in cookie. By default it is derived from the credentials, so changing the password signs everyone out. |
| `SESSION_DAYS` | `30` | How long a sign-in lasts. |
| `RESEARCH_MODEL` | `claude-opus-5-5` | Claude model for the market research. |
| `RESEARCH_TTL_SECONDS` | `21600` | How long each company's analysis is cached (6 hours). |
| `PERFORMANCE_TTL_SECONDS` | `3600` | How long each ticker's 1M to 5Y price changes are cached (1 hour). |

News feeds are listed in `app/config.py`.

## Portfolio sign-in

`/portfolio` and the APIs only it uses (`/api/performance`, `/api/research/{symbol}`, `/api/ticker/{symbol}/news`) need a signed-in session. Unsigned visitors are sent to `/login` (pages) or get `401` (APIs). The news tabs, ticker pages and the top ticker bar stay public. After 5 wrong passwords from one address, sign-in waits 15 minutes.

## Endpoints

| Path | Description |
| --- | --- |
| `/` | Front page with the latest headlines (`/?source=wsj` shows one source) |
| `/ticker/{symbol}` | Quote and related news for a ticker |
| `/search?symbol=aapl` | Redirects to the ticker page |
| `/api/news` | Headlines as JSON (`?source=cnbc` filters; unknown source is 404) |
| `/api/sources` | Sidebar sources with headline counts |
| `/api/quotes?symbols=AAPL,MSFT` | Quotes for the ticker bar (defaults to `WATCHLIST`). Unknown symbols come back with `"error": "not_found"` |
| `/api/ticker/{symbol}` | Quote and news as JSON (400 invalid, 404 unknown, 503 provider down) |
| `/api/ticker/{symbol}/news?limit=3` | Top headlines for one company (the Portfolio side panel) |
| `/api/performance?symbols=AAPL,MSFT` | Current price and its change over 1D, 1M, 3M, 6M, 1Y, 2Y and 5Y for each symbol (Yahoo Finance daily history) |
| `/api/research/{symbol}?period=1D` | Market research (`period` is 1D, 1M, 3M, 6M, 1Y, 2Y or 5Y; 1D compares the figures with a year earlier): risks, key metrics, drivers, guidance, sources (404 when the company has no SEC filings, 503 when EDGAR is down) |
| `/healthz` | Health check |

## Tests

All outside HTTP calls are mocked with [respx](https://lundberg.github.io/respx/) using the sample data in `tests/fixtures/`, so the tests never depend on live news.

```bash
pip install -r requirements-dev.txt
pytest                 # unit + API tests
python -m playwright install chromium
pytest -m e2e          # browser tests against a live local server
pytest -m e2e tests/e2e/test_login.py --headed   # watch the sign-in tests in a browser

# the sign-in tests against the live site (other browser tests are skipped: they need mocked data)
BASE_URL=https://market-headlines.onrender.com PORTFOLIO_USER=... PORTFOLIO_PASSWORD=... pytest -m e2e -rs
```

| Folder | What it covers |
| --- | --- |
| `tests/unit` | Feed parsing, HTML cleaning, merging and de-duplication, quote parsing, symbol validation, cache, research figures, changes against each period (including trailing twelve months for annual lines), price changes over 1M to 5Y, red flags and the Claude fallback |
| `tests/api` | Every route: JSON shape, caching, error codes, empty states, HTML escaping |
| `tests/e2e` | Playwright: front page, ticker search, ticker bar (prices, add, remove, saved after reload, errors), not-found and invalid input, mobile layout, dark mode (system default, toggle, saved after reload), ticker news side panel, market research tabs (one tab per company with a risk dot, arrow keys, risks first, key number tiles, "Show" for all fundamentals, add/remove, phone layout), period picker (badges, research comparisons, saved choice, arrow keys, phone fit), Portfolio sign-in (`test_login.py`, with a `LoginPage` page object in `tests/e2e/pages/`: correct sign-in, wrong username or password, empty fields, redirects, sign out, lockout after 5 wrong tries, staying signed in, phone and dark mode) |

## CI

**Live site tests** (`.github/workflows/live-site-tests.yml`): run by hand from Actions → Live site tests → Run workflow. It runs the sign-in tests against a deployed URL (default https://market-headlines.onrender.com) using the `PORTFOLIO_USER` and `PORTFOLIO_PASSWORD` repository secrets. The lockout test is skipped there so it can't lock you out, and each test ends with a correct sign-in, which clears any wrong attempts.

- **GitHub Actions:** `.github/workflows/tests.yml` runs unit/API tests and then browser tests on every push and pull request, and uploads JUnit results.
- **Jenkins:** `Jenkinsfile` runs the same stages inside the official Playwright Python Docker image and publishes JUnit results.
