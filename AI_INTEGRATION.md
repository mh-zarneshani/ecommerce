# AI integration and diagnostics

The active path is frontend/assistant.js → web_app.Application.ai → web_ai → httpx. Settings and allowed endpoints are centralized in web_config.py. Providers are AvalAI, GapGPT and DeepSeek plus an operator-configured compatible endpoint. Model names are configurable; a complete capability catalog is not yet implemented.

Settings form diagnostics use ephemeral form values. A nonempty typed key replaces the saved key for this test only. A blank field retains an existing key only for the same provider and base URL. Saving is a separate operation. Keys are never returned by public settings or previews.

Three explicit probes:
1. Network: GET /models without credentials. Any HTTP response demonstrates network reachability only, including HTTP 401. It does not prove authentication.
2. Authentication: a minimal protected chat completion with a random test identifier. Failure may also mean insufficient credit or inaccessible model; it never claims a credential is valid merely from a public model list.
3. Model inference: the selected model must return the exact random test identifier via the completion response.

Auth/inference can incur a charge and require explicit UI confirmation. The server binds the approved candidate settings to a single-use ten-minute nonce and rechecks them on confirmation. Unsaved tested settings are not persisted. Transport injection is labeled mock, never live.

Current business assistant: backend scope/cutoff/account/evidence context, four validated textual response fields plus evidence IDs, single-use preview consent, stale context recheck, bounded conversation history and persisted daily budget. Workbook remains offline under the existing privacy contract. Synthetic class-demo is the only permitted online business context. No live test was run or key-use permission requested in this change.

Tests: tests/test_ai_diagnostics.py, tests/test_unified_web.py and existing transport suites. HTTP 400/401/402/403/404/422/429/5xx, malformed/empty/fixed responses, timeout/connect errors, wrong key with prior key, unauthorized candidate destination, changed approval and single-use behavior are covered with MockTransport. Live AvalAI/GapGPT availability: NOT RUN.


## Controlled temporary-token test mode
Set ECOM_AI_ENV_ONLY=1 explicitly in the server process and use a separate ECOM_SETTINGS_DIR for test settings. Only AVALAI_API_KEY and GAPGPT_API_KEY are read in this mode. Configure provider/base/model explicitly through the existing settings screen; key entry is disabled. No saved/generic key fallback occurs. Changing provider selects that provider's environment variable, including when testing unsaved candidate settings. This does not itself authorize inference: the normal UI preview/confirmation and budget gates remain. Do not set tokens in command history, source files, reports, browser forms or chat. No live test has yet been performed; see reports/live-avalai.md and reports/live-gapgpt.md.


## Persistent controlled-run guard (2026-11-21)
Environment-only real HTTP requests now additionally require ECOM_AI_TEST_RUN pointing to an explicitly approved exact provider/base/model row. The internal live_test_ledger service stores attempts before sending, reserves a conservative cost estimate, caps each run/provider at six, and serializes all providers through a PostgreSQL advisory lock. Unknown or crashed attempts block continuation; no automatic reset/refund/retry. MockTransport bypasses paid accounting and remains mock. No operational run is armed and GapGPT remains blocked pending compatibility/pricing evidence. See reports/ecom-persistence-controls.md; invoice guarantees and a reviewed operator campaign interface are still outstanding.
