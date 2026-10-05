**Critical:** None.

**Important:** None. Release blocker resolved: only catalog fetches register consumers; health retains authentication/header validation; migration purges synthetic registrations; setup-probe→GC regression test covers the original failure.

**Minor:** None introduced. DOCS.md, package validation, job-kind translations, poster recovery, toolbar widths, navigation highlighting, and System refresh fixes are correct on inspection.

Validation: in-memory migration and catalog 200/304 checks passed; Vue type-check passed; 30 Python tests passed. One test required temporary files unavailable under read-only access. Full regression suite, UI runtime tests, and browser smoke were not run.

RELEASE: YES