# Observed test report — 2026-11-20

Environment: Windows, Python 3.11.0, installed PostgreSQL 18.6. Baseline and final integration suites use qa/run_tests.py with a private temporary cluster, not the operational database. No external provider request was sent.

| Check | Command / evidence | Result |
|---|---|---|
| Original baseline | .venv/Scripts/python.exe qa/run_tests.py -- -q; reports/audit-baseline.log | 83 passed, 85.41s |
| Regression reproduction | pytest tests/test_ai_diagnostics.py -q before fix; reports/ai-reproduction.log | FAIL as expected: wrong authorization key used instead of supplied key |
| Focused diagnostics | pytest tests/test_ai_diagnostics.py -q | 25 passed, 0.43s |
| Full suite after AI | qa/run_tests.py -- -q; reports/audit-after-ai.log | 108 passed, 77.35s |
| Safe unexpected error | pytest tests/test_unified_web.py::test_unexpected_error_has_safe_correlation_id -q | 1 passed |
| Final regression | qa/run_tests.py -- -q; reports/audit-final-tests.log | 110 passed, 78.34s |
| Actual web process | tests/test_web_process.py in final run | starts twice, HTTP health/page/session/report pass, persisted net=2416 after restart |
| Backup | qa/backup_database.py | 111234-byte custom archive; listing verified |
| Restore rehearsal | qa/verify_backup.py private dump | PASS: records=2393, conflicts=0, cases=2, triage_state=2, model_budget=1; private cluster stopped and removed |
| Syntax/patch hygiene | compileall on changed Python/backup tools; git diff --check | PASS |
| Real AvalAI / GapGPT inference | requires explicit authorization to use a valid key | NOT RUN |
| Interactive Start-Windows.cmd and hosted login/logout | manual end-to-end | NOT RUN |
| Current reference parity 1280/768/390 | browser screenshots and interactions | NOT RUN |
| Production concurrency/load | representative dataset and workload | NOT RUN |

Suite durations are observations, not performance improvement claims. Existing warm-query performance assertion ran in the suite; detailed new production-size timings were not captured. Old screenshots/reports are retained but not counted as new evidence. Full logs stay local and are not pasted into the report.

Root cause of AI defect: frontend sent only diagnostic kind while backend selected stored connection; newly entered key was ignored. Fix validates ephemeral candidates, binds them to consent, sends the selected key, and requires a nonce challenge for inference/auth checks. No retries on authentication or validation failures. Unknown/unsupported model is reported via provider failure, not replaced by another model.

Remaining high-priority work: import preview/upload, user activity audit, migrations, identity/logout/rate limits, production context policy, visual/browser regression and authorized live validation. See AUDIT_REPORT.md and ACCEPTANCE_MATRIX.md. This checkpoint is not final acceptance.


## Persistence controls — 2026-11-21
Pristine baseline f7497ba: 139 passed. Final suite after migrations, controlled-run reservations and manual attribution: **155 passed in 100.06s**. Focused: 21 passed. Includes real abrupt child-process exit, concurrent manual corrections, transactional upgrade/rollback and server identity spoof prevention. Operational migration and provider Live calls remain NOT RUN. Full evidence: reports/ecom-persistence-controls.md.


## Launcher cleanup and handoff — 2026-11-21
Baseline from previous phase: 169 passed in 134.69s. New focused checks: 3 passed in 16.02s. Final full suite: **171 passed in 136.94s** using `.venv/Scripts/python.exe qa/run_tests.py -- -q`; private PostgreSQL stopped cleanly. Actual Windows CMD help/credential-status ran from an unrelated working directory and empty temporary LOCALAPPDATA without database provisioning. Existing backend process startup/restart smoke also passed. `git diff --check`: PASS.
Logs: reports/launcher-cleanup-focused.log and reports/launcher-cleanup-final.log (local, ignored). No operational migration, destructive database action or provider request occurred. Visual browser parity and interactive double-click/setup are still NOT RUN. Current tasks and limitations are in HANDOFF.md; earlier test counts and absent-feature notes are historical where superseded.
