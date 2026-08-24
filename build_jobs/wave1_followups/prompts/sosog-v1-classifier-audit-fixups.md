You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. This job fixes two issues flagged by a prior
job's own human-review report on `promotion_engine/audit.py` and
`promotion_engine/taxonomy.py` (already merged into this base commit — read
both files in full before starting).

Your current directory is a detached SOSOG Git worktree.

## Task

Fix exactly two issues in `promotion_engine/audit.py`:

1. **Unvalidated override strings.** `categorizer_audit`/`apply_override`
   (or whatever the ported functions are actually named — read the file)
   currently compares an override's action string against another value
   without checking it's a real value at all. A typo in an override
   currently gets silently treated as a new, distinct category instead of
   being rejected. Fix this by validating any override/audit action string
   against the known set of valid values (the six `PromotionAction` values
   from `promotion_engine/classifier.py`, or the four category values from
   `promotion_engine/taxonomy.py` — read both files to determine which one
   this function should actually validate against, since that depends on
   what the function's input is meant to represent) — raise a clear error
   (or return an explicit rejection, matching whatever error-handling
   convention the rest of `promotion_engine/` uses — check
   `promotion_engine/classifier.py` and `promotion_engine/workflow.py` for
   the existing convention) on an unrecognized value, rather than silently
   accepting it.

2. **Inconsistent `source` field.** Candidates that go through the audit
   path currently get a top-level `source` field; candidates that don't go
   through it (i.e., pure automatic classifications with no human override)
   don't have this field at all. Give every candidate a `source` field
   consistently — default it to something like `"automatic"` for
   unaudited candidates, and whatever the audited value already is for
   audited ones. Read how `promotion_engine/classifier.py`'s
   `build_promotion_plan` output is structured (its `candidates` list) to
   find the right place to apply this default, since the fix may need to
   touch how `audit.py` decorates/wraps a candidate rather than the
   candidate's original construction.

Update `promotion_engine/tests/test_audit.py` to cover both fixes: a test
that an unrecognized override value is rejected, and a test that both
audited and unaudited candidates have a `source` field with the expected
values.

## Constraints

- Do not modify `promotion_engine/classifier.py`, `promotion_engine/taxonomy.py`,
  `promotion_engine/workflow.py`, `promotion_engine/reporting.py`, or any
  file outside the two listed below.
- Do not change the function names or public signatures in `audit.py` unless
  strictly necessary for the fix — this may already have callers depending
  on its current shape.

You may change exactly these paths:
- `promotion_engine/audit.py`
- `promotion_engine/tests/test_audit.py`

The host will reject any other changed path, more than 2 changed files, or a
diff above 400000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

Run the full `promotion_engine/tests` suite, not just the new tests, to
confirm nothing else broke. In your final report: list changed files, test
commands run and their results, and confirm explicitly which value set
(the six `PromotionAction` values or the four taxonomy categories) you
validated overrides against and why. Your work is a proposal and cannot
approve itself for merging.
