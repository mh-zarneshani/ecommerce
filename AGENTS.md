# Coding-agent instructions
- `spec.md` is the sole product contract. `acceptance.md` defines verification; `qa/golden.json` is test-only. Do not expand scope from workbook extras. `prompts/triage-system.md` is for the in-app planner, not for the coding assistant.
- Inspect repo instructions, current state and relevant symbols before editing. Preserve unrelated changes. If using this pack in an existing repo, integrate with its instructions rather than replacing them.
- Read small slices of relevant tables with a script; never put the workbook, generated rows, dependency trees or full test logs into model context. Keep concise failure excerpts and reproduce a single failure before broad edits.
- Implement data and lifecycle rules once; exercise the same services through UI and tools. Do not relax tests, load goldens into the app, or special-case demo names to pass checks. No dependency or service without a concrete need.
- Run focused checks as each slice lands, then the suite and a smoke run. Only pause on a genuine blocker. Report commands, observed outcomes and gaps; do not paste full files. If handing off, a few lines naming the last green check and next failing ID suffice.
