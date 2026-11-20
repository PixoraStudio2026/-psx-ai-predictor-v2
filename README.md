# PSX AI Predictor

Educational PSX market-research and paper-trading starter application. It does not connect to a broker, place real orders, or provide personalised investment instructions.

## Stack
- React 19 + Vite frontend
- FastAPI + SQLAlchemy backend
- SQLite for local development (PostgreSQL recommended for deployment)
- Pandas, NumPy and scikit-learn
- ReportLab PDF reports
- Optional APScheduler job runner

## Data truthfulness and licensing
No live PSX feed, licensed historical dataset, company fundamentals, or news provider is bundled. CSV records are marked as imported, not live. Imported data is only suitable for model training if the uploader has the necessary rights and can attest to its provenance and quality. Do not scrape behind logins, bypass subscriptions, or redistribute data without permission. Synthetic demo rows are explicitly marked and excluded from training and predictions.

## Run locally
Backend (Python 3.11+):
```bash
cd backend
python -m venv .venv
# Activate the virtual environment, then:
pip install -r requirements.txt
cp .env.example .env
# Set ADMIN_API_TOKEN to a long random secret in .env before using write endpoints.
uvicorn app.main:app --reload
```
API docs: http://127.0.0.1:8000/docs

Frontend (Node.js 20+):
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```
The default frontend API URL is `http://127.0.0.1:8000`.

## Import licensed CSV data
CSV columns:
`symbol,timestamp,open,high,low,close,volume`

Timestamp policy: naive timestamps are interpreted as Pakistan local time (Asia/Karachi); timestamps with an explicit timezone are converted to Asia/Karachi. The database stores PSX-local naive timestamps for compatibility. Confirm the vendor timestamp convention before importing. Daily date-only values remain on their stated calendar date.

CLI:
```bash
cd backend
python scripts/import_csv.py /path/to/licensed_data.csv --source "Provider name and dataset" --interval 1d --training-eligible
```
For intraday records use `--interval 15m`. Synthetic test data can be marked with `--simulated`; such data is not eligible for model training. Data is excluded from training by default. Only add `--training-eligible` after you have independently confirmed the dataset is real and your licence permits model training. The web upload endpoint is `POST /api/admin/import-csv` and requires an administrator bearer token; its `training_eligible=true` option is an explicit administrator attestation, not an automatic licence check.

## Train and retrain
Manual candidate training:
```bash
cd backend
python scripts/train_model.py --symbol SYMBOL --interval 1d
python scripts/train_model.py --symbol SYMBOL --interval 15m
```
The application separates daily models (horizon code `1`) from intraday models (horizon code `0`). The training target predicts the next available bar for the selected interval. The script rejects synthetic data and candidates that fail sample-size, Brier-score and naive-baseline gates.

Run controlled batch retraining:
```bash
cd backend
python scripts/retrain_all.py
```
Batch retraining:
- Ignores synthetic data and applies basic history/data checks.
- Requires a minimum number of new bars after the last promoted model.
- Uses up to the most recent five years (configurable with `TRAINING_WINDOW_YEARS`) and chronological train/calibration/final-test partitions.
- Purges horizon-overlap rows at chronological train/calibration/test boundaries.
- When an incumbent exists, trains the candidate without the newest block of new observations and compares candidate and incumbent on the same later, previously unseen imported block before promotion. The new-data block must also beat a naive prevalence baseline.
- Keeps the previous promoted model if a candidate fails.
- Resolves matured predictions only after a subsequent real imported bar exists.

Daily schedule (2:30 AM Pakistan time) is enabled in the single-replica Docker Compose configuration. For local runs, it remains opt-in:
```env
ENABLE_SCHEDULER=true
RETRAIN_HOUR=2
RETRAIN_MINUTE=30
```
The Compose scheduler runs inside the single API process. Do not run multiple API replicas with the scheduler enabled; use a dedicated worker/leader lock before scaling. A schedule does not fetch market data: new eligible authorised data must already have arrived. It skips retraining unless sufficient new eligible data exists.

## Security configuration
Set a long random `ADMIN_API_TOKEN` and a unique `AUTH_SECRET` (at least 32 characters) in the backend environment. User registration/login uses signed bearer sessions; administrative import/retraining endpoints require `Authorization: Bearer <token>`. The API also applies:
- Exact-origin CORS allow-list
- Basic per-IP in-memory rate limiting
- Request content-length and CSV upload limits
- Security response headers
- Input validation and OHLCV checks
- No hardcoded API credentials

This is a development-grade security baseline, not a complete production identity system. The in-memory rate limiter is not distributed and resets on restart. Use HTTPS, a secret manager, PostgreSQL, database backups, a real migration system (Alembic is not bundled), centralised logs, a reverse proxy/WAF, stronger distributed abuse controls, and a professional security review before public deployment. Do not expose the admin token in a public browser or shared frontend build.

## Account and workspace model
Guest access is read-only for public research. Optional email/password registration enables private watchlists, paper portfolios and alerts. Administrator-only data imports, news/fundamental imports and model retraining use a separate bearer token. Configure both `AUTH_SECRET` and `ADMIN_API_TOKEN`. See the account limitations in the updated implementation notes below.

## Current application features
- Market overview and imported stock lookup
- Probability-of-positive-return prediction endpoint for next daily bar and next 15-minute bar
- Historical prediction records and matured-outcome scoring
- Model-run metrics and evaluation history
- Basic liquidity/data-quality publication gates
- CSV import with separate synthetic-data and explicit training-eligibility safeguards
- Optional user accounts with private watchlists, paper portfolios and alerts
- Price-level and percentage-change alert threshold evaluation against latest imported records (no push delivery)
- Manual news storage (no external news feed is configured)
- Stock historical comparison
- Rule-based, database-grounded research assistant (not an LLM)
- Hypothetical P/L calculator
- PDF report with imported records and saved predictions
- Docker configuration

## Not yet implemented / production blockers
- No authorised live or delayed PSX data-provider integration; 15-minute updates are not automatic.
- No automated fundamentals, economic-data or news-sentiment providers; only manually imported source-attributed snapshots/articles are available, and predictions use only records timestamped no later than the prediction data.
- No trained expected-return distribution; return estimates are empirical summaries.
- No push alert delivery; alert thresholds are evaluated when queried against the latest imported record.
- No general-purpose LLM chat; the research assistant only summarises stored records.
- No comprehensive universe/delisted-symbol ingestion or corporate-action adjustment pipeline.
- Intraday and daily prediction require separate imported data and separately trained models.
- The current evaluation is a chronological holdout baseline, not a proven institutional walk-forward backtest. Repeated nested walk-forward folds, purging/embargo, point-in-time fundamentals, survivorship-bias controls and independent untouched test windows remain advisable.

## Tests
From the project root (or install `backend/requirements-dev.txt` first):
```bash
pytest -q
```
The root `pytest.ini` configures the backend import path.
The tests cover authentication, user isolation, paper-trade limits, CSV validation/timezone handling, data-quality gates, technical features, purged split boundaries, research API contract, security headers and PDF generation. External provider, scheduler, Docker image and frontend production-build tests require their respective services/toolchains.

## Local Docker deployment
Copy `.env.compose.example` to `.env`, replace both placeholder values with unique random secrets of at least 32 characters, then run `docker compose up --build`. The API is internal-only in Compose; Nginx exposes the UI and proxied API/docs. The web UI is served at `http://localhost:4173` and the API documentation is proxied at `/docs`. SQLite, model artifacts and reports use named Docker volumes. The frontend is same-origin proxied to the API in this compose setup. Docker itself was not available in the implementation environment, so the images were not built here.

## Deployment
GitHub stores source code; it is not itself a backend host. Deploy the backend and frontend separately, configure exact CORS origins, set secrets only in the hosting platform, use persistent PostgreSQL storage, and keep the scheduler on one worker. Never commit `.env`, database files, model artifacts containing private data, or provider credentials.

## Licence
MIT for this code. This does not grant rights to PSX market data, third-party news, company data or logos.

## Additional implementation notes (updated)

### Optional private accounts

User registration and login are available through `/api/auth/register`, `/api/auth/login`, and `/api/auth/me`. User passwords are hashed with PBKDF2-HMAC-SHA256 and bearer sessions are signed with `AUTH_SECRET`. Set `AUTH_SECRET` to a unique random value of at least 32 characters before enabling registration. User watchlists, alerts and paper-trade records are associated with the authenticated user. Guest users can still view public market research but cannot write private records. Existing pre-account records remain administrator/legacy workspace records and are not exposed to signed-in users.

This is a starter account implementation, not a complete enterprise identity service: email verification, password reset, MFA, account recovery, session revocation, and audit workflows still need a production identity provider or further implementation. Do not use a weak or shared `AUTH_SECRET`; store it only in deployment secrets. The frontend keeps bearer sessions in tab-scoped `sessionStorage` (not `localStorage`); this reduces persistence but does not protect against same-origin script compromise. Use HTTPS, a strict CSP, and preferably a mature identity provider with HttpOnly secure cookies for production.

### Fundamentals and analysis

A source-attributed company profile can be imported by an administrator using `POST /api/admin/profiles`; retrieve it with `GET /api/profiles/{symbol}`. A fundamentals snapshot can be imported using `POST /api/admin/fundamentals`; retrieve snapshots with `GET /api/fundamentals/{symbol}`. Stock details include RSI, MACD, moving averages, recent support/resistance ranges, volatility, and a **stock-specific trend proxy**. This is not a PSX-wide regime model. No fundamental values are invented when data has not been imported.

Prediction responses include a historical empirical return estimate, gross/net illustrative return estimates, recent return quantiles, volatility-based risk label, and technical feature values. These are research summaries of the imported series, not guaranteed future return bounds. The configured transaction cost is a simple configurable assumption and does not model every PSX fee, tax, levy, spread or slippage component.

News records remain manually imported. The displayed sentiment is a small keyword heuristic and must not be interpreted as a financial NLP model. Alert conditions are evaluated against the latest imported bar when the alerts endpoint is read; no push, SMS, email or real-time notification worker is included.

### Provider integration boundary

`backend/app/providers/base.py` defines an adapter contract for authorised vendors. `manual_csv.py` provides validated manual CSV ingestion. No PSX, SBP, PBS, licensed news or broker API integration is bundled because no credentials or redistribution licence were supplied. Add a provider only after confirming the vendor contract, allowed refresh frequency, timestamp semantics, corporate-action handling and redistribution permissions.

### Model training data timestamp

Model runs store `trained_through` as the data watermark used for the training/promotion decision. Retraining checks new data against this market-data timestamp rather than the wall-clock training time, so importing older historical data does not permanently block subsequent retraining decisions. For incumbent updates, the newest holdout block is not included in candidate fitting/calibration and is only used for the candidate-versus-incumbent promotion comparison.

### Current remaining blockers

- No verified PSX index/regime data, market-wide cross-asset features, SBP/PBS connector, automatic licensed feed or 15-minute polling integration.
- No full universe master/security master, delisted-stock history, corporate-action adjustment or point-in-time survivorship-bias controls.
- No automated news provider or high-quality NLP sentiment model.
- No actual alert delivery worker or push notifications.
- No email verification, password reset, MFA, revocation, account deletion workflow or independent security audit.
- No comprehensive multi-fold purged/embargoed walk-forward validation or independently maintained final holdout dataset.
- The current expected-return estimate is an empirical historical conditional-return calculation, not a trained return-distribution model. Risk labels are simple volatility thresholds, not a validated risk model.
- Frontend production build must be run in a Node environment after `npm install`; package installation could not be completed in this execution environment.
- No deployment target, domain, HTTPS, production database or secret manager has been configured.


## Important final limitations
- The research assistant is a deterministic, database-grounded helper, not a general-purpose LLM. It never claims to have external or live knowledge.
- Model confidence is a separate evidence-quality label derived from validation sample size, Brier score and calibration error; it is not the probability of a positive return.
- Fundamentals and news used in a prediction are restricted to records whose `as_of` / publication timestamp is no later than the prediction's market-data timestamp, reducing look-ahead leakage.
- CSV timestamps are interpreted in PSX local time as described above. Always confirm the source's timestamp convention.
- Intraday and daily models require separate licensed series; there is no automatic polling/feed in this archive.
