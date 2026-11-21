> Update 2026-11-21: root CMD cleanup is complete; Start-Windows.cmd is the only root launcher, with two internal helpers in scripts/windows. Old diagnostic wrappers were removed after dependency review; Python implementations/tests remain. See HANDOFF.md for current handoff, verification and remaining gates.

# Engineering audit — 2026-11-20

Status: audit in progress; not a production release. Evidence below is from the working directory, not historical report claims.

## Baseline and sources
- Working directory: ecom-project under ecom-postgres-starter-v2. No .git directory or ancestor repository exists; historical commits and provenance cannot be recovered from this copy. A new baseline can preserve subsequent changes but cannot recreate lost history.
- Product contract read: spec.md; verification: acceptance.md. The new master request extends the classroom scope to production workflows. Existing synthetic/workbook segregation remains mandatory while extensions are implemented.
- Available: sales-agent-desk-ai-contextual.html, frontend/SOURCE.md, original XLSX, class-demo.json, prior reports/screenshots. Sibling ecom-project-clean.rar and ecom-project.rar exist; contents have NOT been audited or substituted.
- Not found in parent-tree filename search: sales-agent-desk-ai-designs.html, ecom-ui-rebuild-brief.md.
- Current dependencies: Python runtime to be measured; psycopg 3.3.9, openpyxl 3.1.5, Streamlit 1.67.0 (legacy), pytest 9.2.0, httpx 0.28.1.
- Existing official route: Start-Windows.cmd → Ensure-Windows-Python.cmd → optional Setup-Windows.cmd → web_app.py, loopback 8765. Other scripts include diagnostics and legacy entry points; preserve until callers are checked.
- Baseline command: .venv/Scripts/python.exe qa/run_tests.py -- -q. Uses installed PostgreSQL binaries, a fresh private temporary cluster, dedicated test database and cleanup. Full output retained locally in reports/audit-baseline.log; 83 passed in 85.41 seconds on Windows / Python 3.11.0.
- No operational schema change, reset, import or external AI call performed. Operational backup created; see DATABASE_OPERATIONS.md and TEST_REPORT.md for restore verification. Mandatory before structural database work.

## Actual architecture and data flow
| Boundary | Implementation / input → output | Controls and verification |
|---|---|---|
| Acquisition | readers.WorkbookReader: bundled XLSX → typed domain.Input / Rejected | dictionary ranges, product/date mapping, raw row provenance; acceptance tests |
| Domain | domain.py: Sale/Plan/Offer/Policy/Witness, clock, ratios | numeric ranges, units, known scope; acceptance tests |
| Persistence | store.py: normalized records → PostgreSQL records/conflicts | parameterized SQL, transactions, revision keys, dataset advisory locks |
| Manual input | web_app → store.save_manual | allowed dates/products/accounts, expected revision, explicit correction, source overlap guard |
| Reports | store.metrics → web_app.report → frontend/app.js | source/cutoff/account filters; full-month target and pace remain separate |
| Cases | triage.py + planner.py → cases/triage_state JSONB | scoped evidence, draft/approval/referral separation, owner closure, replay guards |
| AI | frontend/assistant.js → web_app.ai → web_ai → httpx provider | server-built context, nonce TTL/single use, snapshot recheck, budget; workbook stays offline |
| Settings | web_config.Settings | Windows DPAPI, atomic writes, provider URL allowlist; no key in public settings |
| Identity | web_app sessions + reverse-proxy identity in hosted mode | role checks, origin/header checks, one-hour idle expiry; local roles explicitly simulated |
| UI | frontend/index.html + style.css/app.css + app.js/assistant.js | same-origin static assets/API, local Vazirmatn; reference-derived DOM/CSS per SOURCE.md |
| Legacy | app.py, slice_assistant.py, launch.py | Streamlit/older transport paths retained for regression, not main launcher |

Python inventory: access.py, app.py, domain.py, launch.py, planner.py, probe_avalai.py, readers.py, setup_local.py, slice_assistant.py, store.py, triage.py, web_ai.py, web_app.py, web_config.py; tests and qa/run_tests.py. Schema: records, conflicts, triage_state, cases, model_budget. Versioned migration ledger is absent.

## Findings
| ID | Severity | Evidence / consequence | Status |
|---|---|---|---|
| AI-01 | P1 | frontend diag-prepare sends only kind; backend reads saved connection. Newly typed wrong key is ignored and old valid key can be tested. | Fixed; exact-key regression test passed |
| AI-02 | P1 | GET /models with a list is reported as connection success; a publicly readable list cannot establish authentication or inference. | Fixed in diagnostic layer; live verification NOT RUN |
| AI-03 | P2 | Inference probe uses fixed greeting; no per-test identifier. | Fixed in diagnostic layer; live verification NOT RUN |
| DATA-01 | P1 | No versioned migration ledger, no observed operational backup/restore. | Open; no schema edits allowed yet |
| DATA-02 | P1 | Manual raw revisions preserved but trace only marks hypothetical mode; actor/time audit missing. | Open |
| IMPORT-01 | P1 | UI imports bundled workbook; arbitrary XLS/XLSX upload, mapping and preview workflow absent. | Open |
| AUTH-01 | P1 | Local identity is simulated; hosted identity depends on configured trusted proxy. Real deployment login/logout not exercised. | Open |
| OPS-01 | P1 | stdlib ThreadingHTTPServer, no production workload evidence; do not call production-ready. | Open |
| OPS-02 | P2 | Handler suppresses access logs; no general correlation-ID diagnostic pipeline. | Open |
| UI-01 | P2 | Prior screenshots at 390/1366/1920 do not prove current 1280/768/390 parity. | NOT RUN |
| GIT-01 | P1 | No source history in supplied directory. | Historical recovery blocked |
| CASE-01 | P2 | Domain supports stockout and discount; other master-request types lack validated lifecycle contracts. | Open |
| AI-04 | P1 | Contextual online assistant restricted to synthetic class-demo; actual workbook AI is offline by existing contract. | Partial; no business data sent |

No P0 exploit has been established by this audit; that is not a full security clearance. Existing checks and historical reports are not substituted for observed runs.

## Preserve and regression coverage
Preserve domain arithmetic, original workbook, dataset/source separation, revision/conflict ingestion, manual correction locks, lifecycle and owner closure, persistent referrals, evidence clocks and offline planner. tests/test_acceptance.py covers original contract; tests/test_unified_web.py covers HTTP workflows and permissions; transport, hosted UI, launch, legacy UI and assistant tests remain intact. Do not remove alternate scripts or duplicate transport implementations before dependency/regression evaluation.

## Staged plan and gates
1. Baseline: record suite results, preserve source snapshot/branch, recover historical Git if available; operational backup and restore before schema changes.
2. Critical AI: reproduce unsaved-key bug, bind diagnostics to exact submitted settings, separate network/auth/inference, forbid mock live claims; targeted tests then full suite.
3. Backend/security: actors/audit, versioned migrations, session/logout and request limits; integration tests against isolated PostgreSQL and restore drill.
4. UI: keep approved reference; compare identical contexts at 1280/768/390, keyboard and error-state checks.
5. Workflows: validated upload/preview, exports, history and case extensions only with domain rules; regression matrix.
6. Contextual AI: approved business payload policy, provider capabilities, evidence validation; live test only with explicit key-use permission.
7. Hardening: safe diagnostics, concurrency/load measurements, security regression.
8. Release: launcher E2E, acceptance matrix, documentation and reversible commits. No release while critical tests are missing/failing.


## Observed checkpoint results
Baseline 83 passed; final 110 passed including added web backend process restart smoke. Operational database reachable on Windows/Python 3.11.0/PostgreSQL 18.6. Backup 111234 bytes restored successfully in an isolated disposable cluster (2393 records; two cases); no operational schema/data write. AI-01/02/03 repaired with mock regression evidence, not live certification. Error correlation IDs added without logging exception payloads. Full matrix: ACCEPTANCE_MATRIX.md; commands/results: TEST_REPORT.md. Production release remains incomplete.
