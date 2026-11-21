# Database operations

PostgreSQL remains the source of truth. Operational inspection observed PostgreSQL 18.6 (server_version 180006), with records, conflicts, cases, triage_state and model_budget. No operational import, reset or schema migration was performed during this change.

Schema remains in store.SCHEMA. records stores versioned normalized JSONB and raw trace; conflicts retains equal-revision discrepancies; cases/triage_state persist scoped lifecycle state; model_budget enforces daily limits. Dataset locks and transactions serialize business updates; manual updates require an expected revision and explicit correction.

A versioned migration ledger is still required before future structural work. Do not drop/recreate operational tables to introduce it.

Backup: `.venv/Scripts/python.exe qa/backup_database.py`. Uses the existing configured workshop database and installed PostgreSQL binaries. Credentials pass in child environment, never CLI arguments or output. Dumps reside in the private profile backups directory, outside Git. The script refuses a different database name and verifies the custom archive listing.

Observed backup: workshop-20261120T101556Z.dump, 111234 bytes, under `%LOCALAPPDATA%/ActiveEcomBootcamp/backups`.

Restore rehearsal: `.venv/Scripts/python.exe qa/verify_backup.py PATH_TO_DUMP`. Creates a separate private temporary cluster, restores with no owner/privilege changes, reads five table counts, then stops and removes only that scratch cluster. Never targets the installed operational cluster. The result of this rehearsal is recorded in TEST_REPORT.md.

Production recovery is a separate operator action: stop writers, preserve the current database and profile, restore the approved dump into an isolated destination first, verify source counts and application workflows, and switch the protected connection profile only after approval. No automatic destructive in-place restore is provided.


## Versioned persistence update (2026-11-21)
The schema source is now migrations/001_existing_schema.sql; store.SCHEMA remains a compatibility alias. store.initialize applies checksum-verified transactional migrations through db_migrations.upgrade. Migration 002 adds ai_test_runs/ai_test_attempts; it does not alter sales/case rows. Operational migration has NOT been run by the agent; the next app startup applies it. Confirm the fresh backup/recovery plan before starting the new release.

Rollback: revert application commits while retaining additive tables and all history. db_migrations.downgrade(db,1) is an internal maintenance function that refuses to drop populated ledger tables. Never force-drop a ledger or fabricate old migration checksums to get past a failure. See reports/ecom-persistence-controls.md for tests and the fresh backup rehearsal.
