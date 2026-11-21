# Active API

Single origin: http://127.0.0.1:8765 by default. GET / serves the HTML app; /health returns application identity, not a complete database readiness assessment. Static assets are explicitly allowlisted.

All application routes are POST /api/{action}, JSON objects, at most 8192 bytes, matching Origin and X-Active-Session. start returns a session token after hosted identity checks; local start is a labeled simulation. Hosted identity comes only from the trusted proxy token and mapped identity. Sessions expire after one idle hour.

| Actions | Access / purpose |
|---|---|
| start, role | start session; role switch only in local simulation |
| report | business roles; dataset/account/month/day/hour/overlay filters |
| cases, case | scoped case queue and selected ID/detail |
| manual, manual-save | manager or scoped specialist; product/date/counts/revision/confirm |
| history | allowed account dates and products |
| import, review, demo-start, demo-reset, demo-orderable, demo-error | manager; bundled import and explicit training lifecycle |
| decide, close | server-validated case scope, proposal action and owner closure |
| settings, settings-save, settings-clear, roles, assign | admin; real assignment only hosted |
| ai-context, ai-prepare, ai-confirm, ai-cancel | scoped business users; server-prepared consent and validated answer |
| diag-prepare, diag-confirm, diag-cancel | admin; kind plus ephemeral settings, then bound nonce/settings |

Success is a JSON object, not proof of downstream business success by itself. Failures return error plus request_id, with matching X-Request-ID header. Validation is 400, invalid session 401, denied scope 403, unknown action 404, stale/consumed approval 409, wrong content type 415, budget 429, provider failure 502, database/local storage failure 503, unexpected server failure 500. Provider HTTP code appears in the safe error message, never raw body.

No arbitrary file upload or export endpoint exists yet. See ACCEPTANCE_MATRIX.md rather than assuming those workflows are implemented.


Manual audit update: POST /api/manual returns record plus history (latest 100 revisions for the validated account/product/day). Each available trace contains server-derived actor/role/identity_source/recorded_at; historical absent attribution remains unknown. manual-save ignores caller-supplied attribution. No public endpoint arms or resets a controlled AI ledger. Environment-only external transport additionally requires ECOM_AI_TEST_RUN with an approved matching database row; absent/exhausted/unresolved runs stop before sending.
