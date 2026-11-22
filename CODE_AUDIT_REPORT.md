# CSE AI Alpha Terminal — Source Audit

**Audit date:** 2026-11-19  
**Scope:** App-owned Python, configuration, launch/setup scripts, README, and existing tests.  
**Excluded:** `venv/`, SQLite database, uploaded PDFs, and generated `__pycache__/` files.

## Summary

The slow first open had three avoidable waits in the UI path. The desktop launcher waited for Ollama before opening the app URL; the app waited up to five seconds for the first CSE overview; and live overview/trade readers defaulted to waiting for their first fetch. These waits are removed from the UI path. Live data, Ollama, model loading, and news continue in background tasks.

The Windows desktop flow is `Desktop shortcut → run.bat → launcher.py → pywebview`. A desktop shortcut is installed and was verified. The app UI layout and styling were preserved; notification delivery remains Windows-PC-only as previously requested.

## Launch path and changes

| File | Review result |
|---|---|
| `launcher.py` | Removed the up-to-eight-second Ollama wait before `window.load_url()`. Streamlit readiness is still checked; its timeout remains 40 seconds for a failed startup. |
| `app.py` | Initial overview now reads the latest snapshot without waiting for CSE. Removed a duplicate synchronous `db.init_db()` call; `bootstrap.start_all()` still initializes the database once before its worker threads. |
| `core/live.py` | `overview()` and `trades()` now default to no wait. Price, trade, and breadth readers also use the nonblocking snapshot. Bootstrap’s explicit waits remain in background worker code. |
| `core/price_fetcher.py` | Dashboard movers read the nonblocking live snapshot. Freshness-limited price requests do not fall back to an un-timestamped quote. |
| `core/bootstrap.py` | Ollama startup/model download, live data, agent, news, and company preload run in background threads. A first model download can still use time and bandwidth, but no longer delays the window loading. |
| `run.bat` | Creates/uses the local venv, installs dependencies on first setup, starts the background service, then launches the desktop wrapper. First-time setup can take longer while packages download. |
| `install_desktop_shortcut.bat` | Creates the Windows Desktop shortcut targeting `run.bat`. |

## File-by-file review

| File(s) | Audit notes |
|---|---|
| `app.py` | Reviewed navigation, market dashboard, company explorer, agent, copilot, news, portfolio, report analyzer/chat, comparison, dividends, alerts, journal, and settings. Uploads use generated names; article HTML is escaped and links are HTTPS-only; report chat resets after a new analysis. Remaining display issues are listed below. |
| `config.py`, `.streamlit/config.toml`, `requirements.txt` | Paths are rooted at the app folder; dependencies include Streamlit, Ollama, PDF, chart, and desktop-window packages. |
| `core/agent.py` | Notifications use Windows desktop only. Daily messages are marked sent only after notification dispatch succeeds. Portfolio quote fallbacks are identified as estimates in agent context. |
| `core/ai_analyzer.py`, `core/comparison.py`, `core/financial.py` | Financial input parsing rejects non-finite values; ratios use Decimal; missing report totals do not count as zero in the health score. |
| `core/alerts.py` | Alerts require a recent quote and remain active if PC notification dispatch fails. |
| `core/database.py` | Table names are allow-listed and user values are parameterized. Migrations retain exact decimal text. Obsolete Telegram/WhatsApp credential keys are removed at database initialization. |
| `core/companies.py` | Directory and company-info requests have timeouts; HTTP status is checked before parsing. Stale company-info cache can still be returned after a request error. |
| `core/news_fetcher.py` | Feed requests have timeouts and stale-cache fallback. UI rendering escapes feed content. |
| `core/pdf_reader.py` | Selects text-based statement pages; scanned/image-only PDFs have no OCR support and return no extractable text. |
| `core/charts.py` | Charts are presentation-only and convert financial values to floats. Dividend chart aggregation still uses legacy SQLite `REAL` values rather than exact text values. |
| `core/desktop_notify.py` | Uses `winotify`, with a PowerShell fallback. The fallback confirms process start, not guaranteed Windows toast delivery. |
| `agent_service.py`, `install_autostart.bat`, `stop_agent.bat` | Background service and login startup are scoped to this app; dependency installation errors are surfaced; stop script matches the app service path. |
| `README.txt` | Setup describes the desktop shortcut and PC-only notifications. |
| `tests/test_financial_comparison.py`, `tests/test_market_state.py` | Existing tests cover Decimal arithmetic, DB migration, ratios, and market status. They do not cover desktop launch timing, external CSE/Ollama calls, or toast delivery. |

## Remaining findings

1. **Fractional shares display rounded to whole shares** — `app.py:701`. The input and calculations allow fractional shares, but the table formats them with zero decimal places. A 0.5-share holding appears as 0.
2. **Health-score help text is inaccurate** — `app.py:782`. It says one usable statement total is enough, while `health_score()` needs the assets, liabilities, revenue, net profit, and equity values to calculate a score.
3. **Dividend charts use legacy float data** — `core/charts.py` dividend aggregation uses `amount` (`REAL`) even though exact values are stored in `amount_exact`; chart totals can differ slightly from exact totals.
4. **Desktop toast fallback is best-effort** — `core/desktop_notify.py`. A successful PowerShell process start is treated as dispatch success; Windows may still suppress the toast.
5. **First-run setup remains slower** — `run.bat` creates the venv and downloads packages when the dependency marker is absent. Ollama may also download the selected model in the background.

## Verification

- Existing financial tests: **5 passed**.
- Existing market-state tests: **2 passed**.
- Python syntax compilation for modified modules: **passed**.
- The desktop shortcut exists. CSE/Ollama API timing and actual toast delivery were not runtime-benchmarked in this audit.

## Desktop startup re-check (2026-11-19)

The desktop launch path was rechecked after reports of a slow or unclear opening screen. `launcher.py` previously always used port 8501 and opened whichever server answered there. If an earlier Streamlit process still owned that port, the shortcut could show the wrong/stale app. Startup failure also gave little guidance.

The launcher now:

- Uses port 8501 when it is free; if it is already occupied, chooses a free local port for this launch, avoiding an accidental connection to an older app.
- Binds Streamlit to `127.0.0.1` and opens that same address in the desktop window.
- Writes Streamlit startup output to `data/desktop_app.log` so startup errors are inspectable.
- Checks whether Streamlit exits while the window waits for readiness, and shows a readable error with the log location. The readiness timeout is 45 seconds.
- Stops this launch's Streamlit process tree when the desktop window closes on Windows.
- Keeps the existing app layout and theme; the splash message now says the desktop workspace is opening while background market/AI services initialize.

### Re-check verification

- Python syntax parsed for all **21 app-owned `.py` files** across the root, `core/`, and `tests/`: passed.
- Port-conflict check with a temporary listener on 8501: launcher selected a different port, as expected.
- `pytest` could not run in this environment: neither the app virtual environment nor system Python has the `pytest` module installed. No dependency was installed as part of this review.
- Actual pywebview display, Windows process shutdown, external CSE/Ollama startup, and Windows toast delivery were not exercised here. The existing 7-test pass recorded above is from the earlier audit run.

## Reported Streamlit runtime error (2026-11-19)

The user's redacted Streamlit error was recoverable from `data/desktop_app.log`. The traceback pointed to `app.py:327` in `render_system_panel()`: the function assigned a string to the local name `html`, shadowing the imported `html` module, then attempted `html.escape(...)`. This caused the sidebar AI System fragment to raise `AttributeError: 'str' object has no attribute 'escape'` on each refresh.

The import now exposes `escape` as `html_escape`, and all HTML escaping call sites use that function. The sidebar markup variable remains local and no longer conflicts with the escape helper.

Verification after the fix:

- Isolated `render_system_panel()` execution with HTML-special characters in its label/detail: passed; output correctly escaped `&` and `< >`.
- Python syntax parsed for all 21 app-owned `.py` files: passed.
- The full pytest suite remains unavailable in this environment because `pytest` is not installed in either available Python environment.

## AI Copilot response delay review (2026-11-19)

The selected model is `qwen2.5:1.5b` (Q4_K_M, about 1 GB). Ollama reported it running with `size_vram: 0`, so inference is CPU-side on this machine. A recent Ollama server-log sample showed about 7 generated tokens/second; an answer around 80 tokens therefore needs roughly 11 seconds of generation alone. In Sinhala mode, when the answer fails the Sinhala quality check, the app makes a second full model call for English. Before this fix, it rebuilt the live context for that second call too.

The Copilot context also included synchronous optional network work: a first news fetch could wait around 9 seconds, and up to two company-info lookups could each wait up to 8 seconds. These delays stack ahead of inference. During this review a simple, 32-token local Ollama request did not respond within 90 seconds, although the `/api/tags` and `/api/ps` endpoints answered. This indicates the local inference runtime was also stalled at that time; source changes alone cannot guarantee a fast response while Ollama is unresponsive.

Changes made:

- Reuse one live-data context if Sinhala output needs an English fallback; skip the second inference when the first model request fails.
- Limit AI-agent requests to 120 generated tokens and use a 45-second HTTP timeout so a stalled local model does not leave the user waiting indefinitely.
- Keep the AI agent's context size aligned with the startup warm-up setting to avoid changing model context between agent calls.
- Make the AI agent's first news fetch background-only and reduce its company-info request timeout to 2 seconds per lookup. Other app callers keep their existing news behavior and company-info timeout.

Verification: syntax checks for `core/agent.py`, `core/news_fetcher.py`, and `core/companies.py` passed. Isolated tests confirmed the Sinhala fallback reuses the existing snapshot and a failed first model request does not trigger a second one. The local live-model check timed out, so post-change end-to-end answer timing could not be measured.

## Final source check (2026-11-21)

Rechecked app-owned Python modules, database and financial calculations, market/news fetch paths, notification agent, PDF analyzer, charts, settings, and Windows launch scripts.

Changes from this check:

- Portfolio share counts preserve fractional values in the table instead of rounding to whole shares.
- The unavailable health-score message lists all five required statement totals.
- Dividend charts aggregate `amount_exact` when available, with legacy `amount` as fallback.
- AI report extraction treats non-finite Decimal values as unavailable instead of allowing NaN/Infinity into score calculations.
- Upcoming dividend dates use Sri Lanka time consistently.

Verification: all **7 existing unit tests passed**; all **21 app-owned Python files parsed**; an isolated smoke check passed for exact-value dividend charts and rejection of a non-finite extracted value. This was a source and local-runtime check; live CSE/Ollama services, actual Windows desktop rendering, and toast delivery were not exercised.
