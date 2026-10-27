# Code review instructions

Read AGENTS.md and docs/ARCHITECTURE.md. Review concrete correctness, regressions, security and data integrity; avoid style-only comments. Cite the affected path and explain a reproducible failure or violated invariant.

- There is one database and one rating implementation. Do not replace full history with recent samples or infer identities from names.
- Rating changes must follow haido/README.md. Flag per-account scoring exceptions, baseline deletion/recalibration, or inconsistent weekly/per-match totals.
- Preserve the existing build/data/privacy gates, shared locks, candidate promotion and full SHA256 artifact verification.
- A build, Release upload or directory sync is not a successful website deployment. Production remains on the original WorkBuddy application.
- Visitor records, real device IDs, local configurations, credentials and recovery bundles must not enter source or battle-data Releases. Development analytics is opt-in.
- Pull requests run with read-only tokens. Never execute untrusted PR code with privileged pull_request_target access or expose secrets to forks.
- Keep documentation normative: no development diaries, trial scores, personal judgments or copied execution logs.
- AI feedback is advisory. Do not suggest bypassing failed checks, auto-merging production changes, or silently changing scoring weights.
