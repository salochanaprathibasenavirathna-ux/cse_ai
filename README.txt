SETUP (Windows)
1. Install Python 3.10+ and Ollama (ollama.com)
2. Optional pre-download: ollama pull qwen2.5:1.5b
3. In this folder:
     python -m venv venv
     venv\Scripts\activate
     pip install -r requirements.txt
4. Double-click run.bat (desktop window opens), or run: streamlit run app.py
   run.bat starts the background AI agent automatically; the app starts Ollama when installed.
   The selected model is downloaded automatically if missing; this first download needs internet.
   To add a Windows desktop icon, double-click install_desktop_shortcut.bat once.

GITHUB WINDOWS RELEASE
The .github/workflows/windows-release.yml workflow builds a branded Windows EXE and ZIP
when a v* tag is pushed (or can be started from GitHub Actions). The ZIP includes an
"Install Desktop Shortcut.bat" file that creates a desktop shortcut using the app icon.
Ollama is installed separately; the EXE does not bundle Ollama or its AI model.
Release builds keep the database and uploaded PDFs in %LOCALAPPDATA%\CSE AI Alpha Terminal.

Database: data\stock.db  (on your PC). Uploaded PDFs: data\uploads\
Change the AI model, optional official CSE announcement RSS/Atom URL, and PC notification
preferences in Settings. News/announcement polling and price alerts run in the background
while the app or installed agent service is active.

BACKGROUND AI AGENT (works when the app window is closed)
  run.bat starts it hidden, and it keeps running when the app window closes.
  Optional: double-click install_autostart.bat once to also start the agent when you log in to Windows.
  Sends Windows PC pop-up notifications only. Telegram and WhatsApp notifications are disabled.
  Stop it with stop_agent.bat.

WHAT'S NEW (smooth + live + AI auto-start)
  * Tabs slide/fade in when you switch (direction follows the sidebar order).
  * One background thread keeps live CSE data in memory - tabs open instantly, every tab shows the same numbers,
    and if cse.lk fails the last good numbers stay (with a "delayed" warning) instead of 0.00.
  * When the app opens, ALL AI systems start together: live data, Ollama, the AI model (auto-download + loaded into
    memory), the AI agent, news. See the "AI System" panel at the bottom of the sidebar.
  * Numbers now come with pie charts (dashboard, explorer, portfolio, reports, dividends, compare).
  * Peer Compare -> "Live market compare": pick two companies, each pie is split between the two.
  After updating, run:  pip install -r requirements.txt   (streamlit must be 1.50 or newer)

FINANCIAL PRECISION AND DATA LIMITS
  * New portfolio, dividend, alert, report, and ratio calculations use Decimal; exact inputs are
    persisted as SQLite TEXT. Legacy database REAL values are retained for compatibility, but
    their original precision cannot be recovered during migration.
  * Ratios requiring unavailable report data (e.g. current assets/liabilities, share count, DPS)
    are shown as unavailable. Review and correct AI-extracted values against the PDF before saving.
  * Decimal avoids binary-float arithmetic errors; it cannot guarantee that PDFs, remote market
    feeds, OCR/model extraction, or financial source data are error-free. AI output is a draft,
    not audited data or investment advice.
