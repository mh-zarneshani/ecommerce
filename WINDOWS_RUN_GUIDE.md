# Windows execution

The only official launcher in the project root is **Start-Windows.cmd**. Double-click it to start the unified application on loopback port 8765. Python 3.11 and a local PostgreSQL installation are required; Docker/WSL are not required.

The launcher resolves its own directory, checks Python/dependencies using scripts/windows/Ensure-Windows-Python.cmd, and invokes the internal setup helper only if the local database profile is missing. The existing setup_local.py remains responsible for provisioning. The profile is outside the repository under LOCALAPPDATA/ActiveEcomBootcamp. Never paste database passwords or provider keys into chat or command arguments.

Commands from the project directory:
- `Start-Windows.cmd`: normal startup. Starting again reopens the recognized application rather than starting another server.
- `Start-Windows.cmd --setup`: explicitly rerun local database setup using the existing setup flow; this is an operator action, not a routine diagnostic.
- `Start-Windows.cmd --help`: display backend options without database setup/migration.
- `Start-Windows.cmd --credential-status`: print SET/MISSING only, without database setup or provider requests.

Python dependency checks precede these commands and may install declared requirements if missing. The two files under scripts/windows are internal helpers, not separate application launchers. Old DeepSeek and AI diagnostic CMD shortcuts have been removed; update personal shortcuts to Start-Windows.cmd. Python diagnostic sources remain for regression compatibility, not as an approved Live testing route.

Automated verification: `.venv/Scripts/python.exe qa/run_tests.py -- -q` creates a private temporary PostgreSQL cluster. Windows entry-point tests execute the actual CMD from a different working directory with an empty temporary profile, verifying help and safe credential status do not provision a database. Backend startup/restart is covered by tests/test_web_process.py. Interactive double-click, operational migration and actual hosted login/logout remain separate acceptance checks.
