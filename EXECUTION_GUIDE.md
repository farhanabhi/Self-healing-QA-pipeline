# Step-by-Step Local Execution Guide

## Prerequisites
- Docker & Docker Compose v2 (`docker compose version`)
- A free Groq API key from https://console.groq.com — only needed for the
  self-healing demo test; everything else runs without it.

---

## 1. Environment Variables

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```
GROQ_API_KEY=gsk_your_key_here
```

Every other value in `.env.example` already has a sane local default — see
the inline comments in that file for what each one controls (timeouts,
headless mode, self-healing retry budget, Allure output directory).

---

## 2. Bootstrap the Ecosystem

```bash
docker-compose up --build
```

What happens, in order:

1. **`mock-server`** builds and starts on `:8000`. Compose waits for its
   `HEALTHCHECK` (`GET /health`) to pass before starting anything else.
2. **`test-runner`** builds on top of Microsoft's official Playwright image
   (browsers already installed — no flaky `apt-get` step), installs the
   pinned `requirements.txt`, and runs:
   ```
   pytest -n auto --dist=loadgroup --alluredir=/app/allure-results tests/
   ```
   Results are written to `./allure-results` on your host via the mounted
   volume, so they survive after the container exits.
3. **`allure-report`** starts a live report server that watches
   `./allure-results` and re-renders automatically as new results land.

To run just the mock server + tests without the live report viewer:
```bash
docker-compose up --build mock-server test-runner
```

---

## 3. Viewing Logs & Extracting Reports

**Live test execution logs:**
```bash
docker-compose logs -f test-runner
```

**Live, auto-refreshing Allure dashboard (recommended):**
Open **http://localhost:5050/allure-docker-service/latest-report** while
`allure-report` is running.

**One-off static HTML report** (if you'd rather not run the extra
container, or want a report to archive/attach to a PR):
```bash
pip install allure-commandline   # or: brew install allure / scoop install allure
allure generate allure-results --clean -o allure-report
allure open allure-report
```

**Re-running just one marker set** (useful while iterating locally):
```bash
docker-compose run --rm test-runner pytest -m security -v
docker-compose run --rm test-runner pytest -m self_healing -v
```

---

## Alternative: Running Without Docker

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium

# terminal 1
uvicorn mock_server.main:app --reload

# terminal 2
export MOCK_SERVER_URL=http://localhost:8000
pytest -n auto --alluredir=allure-results tests/
allure serve allure-results
```

---

## 4. Tear Down

```bash
docker-compose down -v   # -v also removes the named network + anonymous volumes
```

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `test_self_healing_recovers_from_selector_drift` shows as **SKIPPED** | `GROQ_API_KEY` isn't set in `.env` — this is intentional graceful degradation, not a failure. |
| `mock-server` never becomes healthy | Port `8000` already in use locally — stop whatever's bound to it, or change the `ports:` mapping in `docker-compose.yml`. |
| Playwright browser errors when running **without** Docker | You skipped `playwright install --with-deps chromium` — the Docker path avoids this entirely since the base image ships browsers pre-installed. |
| Allure report shows no history/trend graph | Expected on the very first run — history accumulates across runs when `KEEP_HISTORY=1` (already set) and you reuse the same `allure-results` volume. |
