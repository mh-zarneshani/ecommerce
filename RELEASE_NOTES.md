# Stabilization checkpoint — not a production release

Changes: exact-form AI credential testing; separate reachability/authentication/inference diagnostics; random probe identifiers; settings-bound consent; explicit Mock status; safe API error correlation IDs; source baseline and audit branch; private operational backup and disposable restore-rehearsal tools; backend process restart smoke test.

Preserved: existing HTML reference, same server/port/launcher, domain formulas, workbook and synthetic data separation, PostgreSQL tables, revision/conflict rules, evidence and human case decisions. No external AI request, business data transmission or schema migration was performed.

Not finished: master-request upload/preview and export workflows, complete user activity audit, production identity/logout and deployment hardening, model capabilities, live provider proof, production-data contextual AI, visual regression at all three requested widths, broad load evaluation, full release packaging. See ACCEPTANCE_MATRIX.md. Do not label this checkpoint production-ready.

Rollback: initial source snapshot is commit c05ed6b on audit/stabilization. Subsequent fixes are separate commits; revert those commits to restore prior code without replacing data. Original Git history was not supplied, so this repository starts at the observed baseline. Operational backup stays outside Git.


## 2026-11-21 — Windows launcher consolidation
Root CMD count reduced from seven to one: Start-Windows.cmd. Dependency/setup helpers moved to scripts/windows; four legacy alias/diagnostic wrappers removed after reference/history review, while Python sources/tests remain. Update personal shortcuts. Use Start-Windows.cmd --setup for explicit setup. Help and credential-status no longer trigger database provisioning when a profile is absent. Full offline suite: 171 passed. See HANDOFF.md for continuation and production/Live gaps. Revert this cleanup commit to restore the prior wrapper layout; no schema/data changes belong to this release slice.
