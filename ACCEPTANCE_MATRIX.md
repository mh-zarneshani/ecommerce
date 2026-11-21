# Acceptance matrix — stabilization checkpoint

PASS is scoped to the evidence stated, not a declaration of production readiness. Live and browser tests are separate from automated mock/integration tests.

| ID | Status | Evidence / gap |
|---|---|---|
| AC-01 | PARTIAL | Single active web entry retained; legacy implementation still preserved pending full dependency audit. |
| AC-02 | PASS | README and Start-Windows.cmd route to one web backend; no new launcher added. |
| AC-03 | PARTIAL | Root reduced from seven CMDs to one official launcher; two internal helpers relocated and four wrappers removed after caller review. Legacy Python retained pending broader dependency review. |
| AC-04 | PASS | Operational DB untouched; custom backup restored into disposable cluster; five tables queried. |
| AC-05 | PASS | Original deterministic acceptance suite green on supplied dataset; broader production data not certified. |
| AC-06 | PARTIAL | Supported XLSX upload, preview/confirmation and manual entry pass integration. Binary XLS and arbitrary column mapping remain unsupported. |
| AC-07 | PARTIAL | Revision/concurrency/history and server-derived actor/time for new web manual writes verified; historical rows are not retroactively attributed. |
| AC-08 | PASS | Persisted case/evidence API and lifecycle exercised by existing unified web tests. |
| AC-09 | PASS | Approval/referral/owner closure and replay regression tests pass. |
| AC-10 | PARTIAL | Server-side role/account tests pass; real hosted identity/login E2E not run. |
| AC-11 | PASS | Existing same-origin HTML/CSS/JS frontend remains main application. |
| AC-12 | NOT RUN | Fresh approved-reference visual comparison not performed. |
| AC-13 | PARTIAL | Operational views use backend data; all expanded requested reporting pages not implemented. |
| AC-14 | PASS | MockTransport regression proves newly typed wrong key is used rather than previous saved key; 401 fails. |
| AC-15 | NOT RUN | No authorized real provider inference; live credentials not used. |
| AC-16 | PASS | Injected transport diagnostics/context responses labeled mock; never reported as live. |
| AC-17 | PARTIAL | Synthetic report/case assistant works in integration; workbook remains offline. |
| AC-18 | PASS | Free questions and follow-up supported in scoped assistant tests; live remains not run. |
| AC-19 | PARTIAL | Four-field schema and evidence IDs validated; semantic truth of live model unverified. |
| AC-20 | PASS | Explicit preview, single-use nonce, expiry and context/settings recheck covered. |
| AC-21 | PARTIAL | Keys excluded from public settings and protected by DPAPI; lost original history cannot be scanned. |
| AC-22 | PASS | 25 diagnostic regression cases plus transport suites cover HTTP/network/malformed response handling. |
| AC-23 | PARTIAL | Actual CMD help/credential-status from another directory and backend-process smoke pass on Windows. Interactive setup/double-click rollout remains NOT RUN. |
| AC-24 | PASS | Original domain tests retained; latest verified totals recorded in HANDOFF.md and TEST_REPORT.md. |
| AC-25 | PARTIAL | New diagnostics, HTTP error and backend-process tests; full browser E2E workflow remains. |
| AC-26 | NOT RUN | Fresh 1280/768/390 screenshots and keyboard checks not executed. |
| AC-27 | PARTIAL | Current-run documentation provided; production installation/release packaging not completed. |
| AC-28 | PARTIAL | New baseline branch and incremental commits; preexisting Git history absent. |
| AC-29 | PARTIAL | Redundant CMD shortcuts removed with documented replacements and Git recovery; Python business features/tests retained. Exhaustive browser regression pending. |
| AC-30 | PASS | All thirty criteria explicitly reported with bounded evidence and remaining gaps. |


Persistence checkpoint update (2026-11-21): AC-07 now has verified server-derived actor/time provenance for new primary-web manual revisions plus scoped history and concurrent-edit regression; historical unrecorded attribution is not fabricated. Versioned migrations and controlled AI attempt reservation are implemented/tested, but operational migration and Live provider acceptance remain NOT RUN. See reports/ecom-persistence-controls.md; the rest of the earlier matrix is not upgraded by these changes.
