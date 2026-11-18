# Market Headlines

A small web app that:

- shows the latest financial news from major outlets (CNBC, MarketWatch, Wall Street Journal, Yahoo Finance, New York Times, Financial Times) on the front page, merged, de-duplicated and sorted newest first
- given a ticker symbol (for example `AAPL`), shows the current quote, the change on the day, a one-month price chart and related headlines

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
| `MAX_ITEMS_PER_SOURCE` | `12` | Most headlines any one outlet can take on the front page, so busy feeds don't crowd out the rest. |
| `HTTP_TIMEOUT_SECONDS` | `10` | Timeout for each outside request. |

News feeds are listed in `app/config.py`.

## Endpoints

| Path | Description |
| --- | --- |
| `/` | Front page with the latest headlines |
| `/ticker/{symbol}` | Quote and related news for a ticker |
| `/search?symbol=aapl` | Redirects to the ticker page |
| `/api/news` | Headlines as JSON |
| `/api/ticker/{symbol}` | Quote and news as JSON (400 invalid, 404 unknown, 503 provider down) |
| `/healthz` | Health check |

## Tests

All outside HTTP calls are mocked with [respx](https://lundberg.github.io/respx/) using the sample data in `tests/fixtures/`, so the tests never depend on live news.

```bash
pip install -r requirements-dev.txt
pytest                 # unit + API tests
python -m playwright install chromium
pytest -m e2e          # browser tests against a live local server
```

| Folder | What it covers |
| --- | --- |
| `tests/unit` | Feed parsing, HTML cleaning, merging and de-duplication, quote parsing, symbol validation, cache |
| `tests/api` | Every route: JSON shape, caching, error codes, empty states, HTML escaping |
| `tests/e2e` | Playwright: front page, ticker search, not-found and invalid input, mobile layout |

## CI

- **GitHub Actions:** `.github/workflows/tests.yml` runs unit/API tests and then browser tests on every push and pull request, and uploads JUnit results.
- **Jenkins:** `Jenkinsfile` runs the same stages inside the official Playwright Python Docker image and publishes JUnit results.
