# PSX AI Predictor — implementation status

This file maps the supplied 17-section project brief to what is actually present in this archive. It deliberately distinguishes implemented code from integrations that require licensed data, external credentials, infrastructure, or further verification.

| Brief section | Status | What is present / what remains |
|---|---|---|
| 1. Main objective | Partial | Educational research and paper-trading only; no brokerage execution. Live-market coverage requires a licensed provider. |
| 2. Stock coverage | Partial | Analyses imported symbols, applies liquidity/data-quality gates, and returns up to 10 candidates. No official PSX security master, delisted universe, or corporate-action-adjusted universe is bundled. |
| 3. Prediction horizons | Partial | Separate daily and next-15-minute-bar models are supported. No automatic 15-minute feed/polling is configured; imported timestamps and source status are displayed. |
| 4. Prediction methodology | Partial | Technical OHLCV features feed the classifier. Fundamentals/news can be manually imported and displayed with point-in-time filters; they are not yet model features. No verified macroeconomic or PSX-wide index regime feed is integrated. |
| 5. Prediction outputs | Partial | Positive/negative probabilities, gross/net empirical return estimates, quantile upside/downside, heuristic risk label, separate evidence-confidence label, source/time/model version and reasons are returned. Return/risk estimates are empirical/heuristic, not validated return-distribution models. |
| 6. Self-learning | Partial | Supervised training, calibration, chronological purging, untouched test windows, new-data holdout comparison, promotion gates, model versioning, outcome scoring and scheduled retraining are implemented. This is not yet a multi-fold institutional walk-forward framework. |
| 7. Historical/external data | Partial | Validated CSV import and provider adapter contract are included. No PSX/PSX Data Portal, SBP, PBS, licensed news or paid vendor integration is configured. No five-year dataset was supplied. |
| 8. Risk and quality | Partial | Liquidity, missing/invalid OHLCV, zero-volume and extreme single-bar-return gates; synthetic-data exclusion; simulated costs and downside estimates. Corporate-action adjustment and a validated risk model are absent. |
| 9. Nine application features | Partial | Prediction history, manually imported news, threshold alerts, P/L calculator, stock comparison, PDF report, database-grounded research helper, virtual portfolio and private watchlists are present. No push alert delivery or general-purpose LLM chat is bundled. |
| 10. Dashboard/design | Partial | React/Vite responsive layout, tables, charts and navigation are present. JSX transpilation was checked; a full Vite production build could not be run because npm dependency installation timed out. |
| 11. User access | Partial | Guest read-only access, basic registration/login, signed bearer sessions and per-user watchlist/portfolio/alerts. Email verification, password recovery, MFA, revocation and account deletion are not implemented. |
| 12. Cybersecurity | Partial | Strong-secret checks, PBKDF2 password hashes, admin bearer token, user separation, validation, request/upload limits, in-memory API rate limiting, Nginx rate limiting, CORS and security headers. No independent security audit, WAF, centralised audit system, distributed rate limiter or managed identity service is included. |
| 13. Architecture | Implemented baseline | React 19/Vite, FastAPI, SQLAlchemy, SQLite/PostgreSQL driver support, modular model/provider/report code and Docker Compose. Alembic migrations are not bundled. |
| 14. Testing | Partial | Automated Python suite, API integration checks, PDF generation, CSV validation, Python compilation, JSX transpilation and Compose YAML parsing were run. Docker image build, scheduler runtime and Vite production build were not verified. |
| 15. Deployment/budget | Partial | Open-source dependencies and Docker configuration; no paid service is required by the included code. No hosting account, production domain, HTTPS certificate, licensed data plan or GitHub repository was configured. |
| 16. Android/GitHub workflow | Partial | ZIP and README are prepared for repository upload. Actual Android browser rendering and deployment from GitHub were not tested here. |
| 17. Immediate task | Delivered with limitations | The supplied source archive has been modified and repackaged. This archive is not represented as fully production-complete while the external integrations and verification listed above remain outstanding. |

## Data and model integrity notes

- Synthetic/demo rows are excluded from training and prediction publication.
- CSV timestamps without offsets are interpreted as Asia/Karachi local time. Explicitly zoned timestamps are converted to Asia/Karachi.
- Fundamentals/news used in prediction summaries are restricted to records timestamped no later than the relevant market-data bar.
- The current model is a calibrated classification model for the probability of a positive next-bar return. Expected return and risk are separate empirical/heuristic calculations.
- A scheduler does not fetch market data. It only considers retraining when enough new eligible data already exists.
- Never interpret model probabilities as guaranteed outcomes or personalised investment instructions.
