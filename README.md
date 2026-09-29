# 🔬 Distributed AI-Powered Self-Healing QA & Test Orchestration Pipeline

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![Pytest](https://img.shields.io/badge/Pytest-8.3-0A9EDC?logo=pytest&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.47-2EAD33?logo=playwright&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Mock%20Layer-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Allure](https://img.shields.io/badge/Allure-Reporting-FF5252)
![Groq](https://img.shields.io/badge/Groq-Llama%203-F55036)
![CI](https://img.shields.io/badge/GitHub%20Actions-Parallel%20CI-2088FF?logo=githubactions&logoColor=white)
![Cost](https://img.shields.io/badge/Cost-%240.00-success)

An enterprise-shaped Quality Engineering platform that goes past "write some
Selenium scripts": containerized parallel execution, real service
virtualization, data-driven negative testing, rich Allure analytics, and an
**AI self-healing layer** that repairs broken UI selectors at runtime by
asking a free LLM (Groq's hosted Llama 3) to read the live DOM and propose a
fix — validated before it's ever trusted.

---

## The Quality Engineering Challenge

Modern UI suites break for a boring, expensive reason: the front-end team
renames a button id or restructures a form, and every test that hard-codes
the old selector goes red — even though the feature itself works perfectly.
Triaging those failures burns QA engineering time on noise instead of real
regressions, and it's the single most common source of "flaky" CI in teams
shipping UI changes frequently.

## The Enterprise Solution

This platform treats selector drift as a *first-class, recoverable* failure
mode instead of a hard stop:

1. Every UI interaction runs through a **self-healing wrapper**, not raw
   Playwright calls.
2. On a locator timeout, the wrapper captures the live DOM, asks an LLM for
   a corrected selector *scoped to the original intent*, and — critically —
   **validates that the suggestion actually resolves to one real element**
   before ever using it.
3. The heal is logged as a formal, auditable **"Self-Healed Event"** in
   Allure (original selector → healed selector → LLM's stated reasoning →
   screenshot), so a healed test is visible, not silently hidden.
4. If healing can't produce a *validated* fix, the **original failure is
   re-raised** — the framework never manufactures a false pass.

Everything the suite depends on (a login UI, a payment gateway, an orders
API) is virtualized locally with FastAPI, so the whole thing runs
deterministically, offline-safe, and at zero cost — no paid SaaS, no flaky
third-party dependency in the critical path.

---

## System Architecture & Data Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                         docker-compose up --build                    │
└──────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────────┐   ┌────────────────────────┐   ┌────────────────────┐
│   mock-server      │   │      test-runner        │   │   allure-report    │
│  (FastAPI, :8000)  │   │ (Playwright + Pytest)   │   │  (live HTML UI)     │
│                    │   │                          │   │       :5050         │
│  /login  (UI)      │◄──┤  Page Object Model       │   │                     │
│  /api/security/... │   │   pages/base_page.py     │   │  reads ⇩            │
│  /api/payment       │◄──┤   pages/login_page.py    │   │                     │
│  (flaky, 1st=503)  │   │                          │   │                     │
│  /api/orders        │◄──┤  tests/test_e2e_...py    │   │                     │
│  /api/reset          │   │   - API contracts        │   │                     │
└─────────┬──────────┘   │   - resilience (retry)   │   └──────────▲──────────┘
          │              │   - full E2E journey      │              │
          │              │   - self-healing demo     │   allure-results/
          │              │   - negative/security      ├──────────────┘
          │              └───────────┬──────────────┘
          │                          │ on locator timeout
          │                          ▼
          │              ┌────────────────────────┐
          │              │   utils/healer.py        │
          │              │  1. capture DOM snippet   │
          │              │  2. ask Groq (Llama 3)    │───▶  api.groq.com
          │              │  3. validate new selector │      (free tier)
          │              │  4. retry the action       │
          │              │  5. log "Self-Healed Event"│
          │              └────────────────────────┘
          │
          └── serves the login page in two DOM variants so healing has
              something real to prove itself against:
                /login?variant=stable   → id="login-btn"
                /login?variant=drifted  → id="submit-action-primary"
```

---

## Advanced Features Deep-Dive

### 🩹 AI Self-Healing (`utils/healer.py`)

`BasePage` never calls `page.locator(...).click()` directly — every
interaction goes through `safe_click` / `safe_fill` / `safe_get_text`,
which route through `SelfHealer.run_with_healing()`:

| Step | What happens |
|---|---|
| 1. Attempt | Run the action against the declared selector with a short timeout. |
| 2. Capture | On timeout, grab the current `<body>` HTML (trimmed to ~6 KB to keep the prompt cheap). |
| 3. Ask | Send `{broken selector, intent description, DOM snippet}` to Groq's `llama-3.1-8b-instant`, forced into strict JSON output. |
| 4. Validate | Reject the suggestion unless it resolves to **exactly one** element on the live page — the LLM is never trusted blindly. |
| 5. Retry | Re-run the *original* action (click/fill/read) against the healed locator. |
| 6. Log | Attach a `Self-Healed Event` (original → healed → confidence → reasoning) plus a screenshot to Allure. |
| 7. Fail safe | If every attempt is exhausted, the **original exception** is raised — healing failure never masquerades as a pass. |

This is exercised end-to-end by `tests/test_e2e_workflow.py::test_self_healing_recovers_from_selector_drift`,
which points `LoginPage` at the *drifted* mock UI variant on purpose.

### 🧪 Service Virtualization (`mock_server/main.py`)

* **Deterministic flakiness** — `/api/payment` fails the *first* call for
  any idempotency key (503) and succeeds on retry, so resilience logic is
  tested against a repeatable failure, not real network luck.
* **Hardened auth endpoint** — `/api/security/login` uses strict equality
  against credentials (no string concatenation into any query), so the
  negative test suite can prove that injection-style payloads
  (`' OR '1'='1`, `<script>...`, `admin'--`) are handled as plain wrong
  credentials — a real, defensible security-testing pattern.
* **Mock data generation** — `utils/mock_data.py` uses Faker to seed
  realistic orders and generate randomised invalid-credential fixtures for
  data-driven negative tests (`@pytest.mark.parametrize`).

---

## Local Execution Guide

**1. Configure environment**
```bash
cp .env.example .env
# then edit .env and paste a free key from https://console.groq.com
```

**2. Bootstrap the whole ecosystem**
```bash
docker-compose up --build
```
This builds and starts, in order: the mock server (waits for `/health` to
go green) → the containerized Playwright + Pytest runner (parallel via
`pytest-xdist -n auto`) → a live Allure report viewer.

**3. Watch it run / view results**
```bash
docker-compose logs -f test-runner   # live test execution logs
```
Open **http://localhost:5050/allure-docker-service/latest-report** for the
live, auto-refreshing Allure dashboard, or generate a static report from the
raw results:
```bash
allure generate allure-results --clean -o allure-report
allure open allure-report
```

**4. Tear down**
```bash
docker-compose down -v
```

Full step-by-step instructions (including running without Docker, marker
selection, and CI secrets setup) are in the execution guide provided
alongside this README.

---

## CI/CD

`.github/workflows/advanced_qa_pipeline.yml` runs two suites as genuinely
parallel GitHub Actions jobs (`api-and-security`, `ui-and-self-healing`),
each sharded further internally via `pytest-xdist`, then merges both
result sets into one published Allure HTML report artifact. Set a
`GROQ_API_KEY` repository secret to exercise self-healing in CI — the test
gracefully **skips** (never fails) if it's absent.

---

## Project Structure

```
.
├── mock_server/          # Service virtualization layer (FastAPI)
│   ├── main.py
│   ├── Dockerfile
│   └── static/style.css
├── pages/                 # Page Object Model
│   ├── base_page.py       # self-healing-wrapped generic actions
│   └── login_page.py
├── tests/
│   ├── conftest.py        # fixtures, Allure env metadata, failure screenshots
│   └── test_e2e_workflow.py
├── utils/
│   ├── config.py           # Pydantic settings (single source of truth)
│   ├── healer.py            # AI self-healing engine
│   └── mock_data.py         # Faker-based data generation
├── .github/workflows/advanced_qa_pipeline.yml
├── docker-compose.yml
├── Dockerfile               # test runner (Playwright preinstalled)
└── requirements.txt
```

---

*Built as a portfolio demonstration of enterprise QA architecture:
containerized parallel execution, service virtualization, data-driven and
negative security testing, rich analytics, and a validated AI self-healing
layer.*
