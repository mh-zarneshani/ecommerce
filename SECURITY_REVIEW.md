# Security review — 2026-11-20

This is a scoped code/test review, not penetration-test certification or production approval.

## Fixed and verified
- AI diagnostics previously ignored unsaved form credentials. Candidate settings now validate provider/base/model and use the exact submitted key without storing it. Existing key is used only when the field is deliberately blank for the same provider/base.
- Network probe omits Authorization and cannot claim authentication. Authentication/inference probes require a per-request challenge in a real provider response; discovery alone is not proof.
- Pending diagnostics are single-use, expire after ten minutes, and bind settings. Hosted users cannot supply replacement keys. All diagnostic routes require admin.
- Mock responses remain explicitly labeled; no real provider was contacted.
- API failures include an opaque request ID. Unexpected exception diagnostics record only type, method/status and request ID; no exception text, credentials, raw provider payload or business context is logged.

## Existing protections retained
Provider URL allowlist and no redirects; protected Windows DPAPI storage; atomic settings replacement; scoped server-side role checks; session/header and Origin checks; parameterized PostgreSQL queries; transactional revision/conflict handling; case owner closure; explicit single-use external-send consent; persisted AI daily budget. These protections are not a substitute for actual hosted TLS/proxy deployment tests.

## Remaining risks / gates
P1: production authentication/logout workflow and rate/load controls require end-to-end verification. Local role selection is a training simulation.
P1: operational workbook AI remains offline; safe production-data policy and payload review are not yet implemented.
P1: arbitrary Excel upload and associated limits/type validation are not implemented.
P1: manual revision trace lacks authenticated actor/time; versioned migration ledger absent.
P2: old planner and assistant transports duplicate provider behavior; preserve until equivalent regression coverage permits consolidation.
P2: stdlib HTTP server is not approved for public exposure; use the documented trusted TLS proxy for controlled pilots, not an unverified production deployment.
P2: no full secret-history scan possible before the newly created baseline because original Git history was absent.
No destructive database command was executed against the operational database. Backup is outside Git under the protected local profile. See DATABASE_OPERATIONS.md.
