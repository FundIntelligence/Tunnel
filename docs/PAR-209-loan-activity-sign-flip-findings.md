# PAR-209 — Loan Activity Reconciliation Sign-Flip Investigation

**Branch:** `claude/par-209-loan-activity-sign-flip` (from `paritystaging`)
**Starting point:** PAR-207's confirmed bug — Loan Activity row on the Buildex deal
(`deal_id=4f4f4cba-d688-4b9c-a887-71a0dd6b83d5`, FY2025) shows bank-observed
KES −3.50M (net repayment) vs. declared KES +2.56M (net borrowing),
variance −236.7%. PAR-102 (self-transfer/account_id) already ruled out as the
cause — not re-derived here.

## TL;DR

**Not a classifier bug.** An exhaustive keyword sweep found no missed
disbursement-side transactions. **It's a structural scope mismatch**,
confirmed two independent ways, compounded on Buildex specifically by a known
data-coverage gap. No `classifier.py` change made. One small, additive
`reconciliation_engine.py` change made: surface the deal's existing
account-coverage advisory on the loan_activity row so a data-coverage gap
doesn't read as an unexplained formula bug.

---

## Candidate 1 — Classifier under-tagging: ruled out

Pulled every transaction tagged `loan` / `loan_inflow` / `loan_disbursement` /
`loan_repayment` for the Buildex deal's FY2025 window (25 transactions: 1
disbursement, 24 repayments — matches PAR-207's figures exactly). Then swept
**every positive-amount FY2025 transaction** (the side that would carry a
missed disbursement) against every keyword in `_LOAN_KEYWORDS` and
`_LOAN_REPAYMENT_PATTERNS` (`loan`, `facility`, `disburs*`, `tendepay`,
`jiinue`, `fuliza`, `overdraft`, `od`, and the rest of the named-lender list).

Result: zero missed disbursement-side transactions. The only credit-side hits
were ordinary customer payments (`revenue_operational`) and one
`needs_review` wood-purchase payment — a false-positive match on "wood"
containing the substring "od ", not a real loan. The classifier is tagging
correctly: the 24 repayment transactions (Tendepay, Jiinue — both real Kenyan
asset-finance/digital lenders) are legitimately `loan_repayment`.

**Conclusion: the keyword rules are not under-tagging. No classifier change
warranted or made.**

## Candidate 2 — Scope mismatch: confirmed, two ways

### 2a. The loan portfolio is dominated by asset finance, which is structurally invisible to bank-side classification

`pds_audited_financials.loan_breakdown` for this deal:

| Facility | Balance (KES) |
|---|---|
| AssetFinance-074FLBC242960001 | 4,504,258 |
| AssetFinance-074FLBC241980001 | 4,217,598 |
| AssetFinance-074FLBC251700001 | 5,315,011 |
| Normalloan-074RF01253440002 | 2,700,000 |
| JiinueLoan-0100011413058 | 3,590,308 |
| **Total** | **20,327,175** |

3 of 5 facilities (KES 14.04M of KES 20.33M, ~69% of the loan balance) are
asset-finance type. Asset finance is disbursed by the lender **directly to
the equipment/vendor**, not credited to the borrower's own bank account — by
construction there is no bank-observable credit for any classifier rule to
ever tag, regardless of keyword coverage. Repayments (the installments) do
hit the bank and are correctly tagged (this is exactly what the Tendepay/
Jiinue repayment transactions are).

This is a genuine definitional gap between "audited financing cashflow"
(whole-company, can include drawdowns that never touch the company's own
bank account) and "bank-visible loan roles" (only sees cash that actually
hit an ingested statement) — not a bug a keyword fix can close. Per PAR-150,
`loan_breakdown.name` is free text from the extractor, not a controlled
vocabulary; encoding "asset finance is excluded from bank-side comparability"
as classifier logic would itself be a taxonomy decision requiring Parity
Science sign-off, not something to add unilaterally here. **Flagging this
back to PAR-209 as a scoping question, not fixing it in code.**

### 2b. Buildex specifically also has a known, already-tracked account-coverage gap

`pds_account_coverage` for this deal declares 4 bank accounts: KCB
(MATERIAL, submitted), Absa (MATERIAL, **not submitted**), Zemo (MINOR, not
submitted), Equity (CRITICAL, submitted). Only 2 of 4 were ever ingested.
`pds_audited_financials.account_coverage_advisory` for this deal is already
persisted as **MATERIAL** (`account_coverage_pct = 87.47`) — the system
already knows about and computes this gap, and already uses it to gate the
snapshot's `HIGH_CONFIDENCE` tier (`snapshot_generator._compute_tier`). But
`calculate_loan_activity_reconciliation()` never referenced it, so on this
one row a known data gap was indistinguishable from a formula defect.

Any loan activity (disbursement or repayment) that happened to route through
the un-submitted Absa account is invisible to the bank-side sum, on top of
the asset-finance gap above.

### Corroborating evidence this is systemic, not a one-off

`test_par189_stage4_loan_variance_fmt_fix.py` (already in the test suite)
recorded loan_activity `variance_pct` computed directly via
`reconciliation_engine.py`'s real formula against **9 real prod deals**:
all 9 fall in **−143% to −237%** — every deal with loan activity shows the
same large, sign-disagreeing pattern. A per-deal classifier miss would be
expected to vary in sign and magnitude; a near-uniform pattern across 9
independent deals is much more consistent with a structural/definitional gap
that recurs on every deal (asset-finance-type drawdowns are common SME debt
structures in this portfolio) than with a keyword bug.

---

## The fix made (`backend/v1/analysis/reconciliation_engine.py`)

`calculate_loan_activity_reconciliation()` now looks up the deal's existing
`calculate_account_coverage()` result whenever it returns `VARIANCE`, and
attaches an `account_coverage_note` field when coverage is `MATERIAL` or
`CRITICAL`:

```
"MATERIAL bank account coverage gap (87.47% of declared accounts submitted,
2 missing) — this variance may reflect loan activity in an unsubmitted
account rather than a classification error."
```

- Purely additive — no existing field, variance math, or status thresholds
  changed. `account_coverage_note` is `None` whenever coverage is fine
  (`NEGLIGIBLE`/`MINOR`) or the row isn't a `VARIANCE` in the first place
  (an `EXACT_MATCH`/`ACCEPTABLE` result doesn't need a caveat).
- Degrades safely: if `calculate_account_coverage()` raises (e.g. no
  `cash_breakdown` declared at all) the note is just omitted, never an
  exception.
- Does not touch `classifier.py` — no new keywords, no new roles, nothing
  requiring Parity Science sign-off.
- Presentation/template wiring (surfacing this note on the actual snapshot
  row) is out of scope for this backend-only session per the ticket; the
  field is available on the raw reconciliation JSON for the next session
  (or PAR-207's remaining waterfall-breakdown work) to consume.

## Before / after — Buildex + 3 additional real deals

Since the fix is additive, `status`/`variance_pct` are **unchanged**; only
`account_coverage_note` is new.

| Deal | Bank net (KES) | Declared net (KES) | Variance | Status | Coverage advisory | Note attached? |
|---|---|---|---|---|---|---|
| Buildex Ltd (`4f4f4cba…`) | −3,495,696 | +2,557,092 | −236.7% | VARIANCE | MATERIAL (87.47%) | Yes |
| Fortmore Enterprises Ltd (`bb00c96d…`) | −1,107,012 | +2,557,092 | −243.3% | VARIANCE | not computed (no `cash_breakdown`) | No (coverage unavailable, degrades safely) |
| Deal 1 Ltd (`a407e9b8…`) | −2,003,534 | +2,557,092 | −178.4% | VARIANCE | CRITICAL (14.26%) | Yes |
| Buildex LTD 2 (`b33410d9…`) | −1,508,162 | +2,557,092 | −159.0% | VARIANCE | CRITICAL (73.21%) | Yes |

All four are effectively the same underlying template dataset (identical
`financing_cashflow_cents` across deals is itself a signal these are cloned
sandbox/demo deals sharing one audited-financials fixture, not independently
distinct audits) — consistent with the −143%..−237% range PAR-189 already
found across 9 real deals. No deal in the dataset reconciles cleanly on this
row today, so there was nothing to regress: the fix doesn't change any
deal's status or variance, only adds context to the ones already flagged.

## Test coverage added

`backend/tests_v1/test_par209_loan_activity_coverage_caveat.py` — 4 new
tests: note attached on MATERIAL/CRITICAL coverage + VARIANCE, note absent
when coverage is full, note never attached on EXACT_MATCH even with a
coverage gap present, and graceful degradation when the coverage lookup
itself fails. Full reconciliation/loan-related suite (221 tests) and the
full `tests_v1/` suite (475 passed, 9 skipped — 21 pre-existing failures are
all `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` missing in this sandbox, not
this branch; reproduced identically on `paritystaging` before this change)
pass.

## Deterministic Rules Audit

Watched path touched: `backend/v1/analysis/reconciliation_engine.py` (core
reconciliation logic). `classifier.py` was **not** touched.

- `math.floor()` / `round()` in confidence/coverage calcs: unchanged.
- `min()` conservative-estimate / `base_confidence` logic: unchanged, not in
  this file's scope.
- `canonical_hash` / `sort_rows`: not touched.
- `financial_state_hash` → `enriched_hash` separation: not touched.
- Migrations: none added or touched.
- Override penalty cap (70% / 7000bp): not touched.
- 60% overlap threshold for reconciliation: not touched — this change is
  additive metadata on the loan_activity result, not a change to any
  variance/threshold/status computation.

**DETERMINISTIC RULES: PASS** — one watched path touched, invariant-by-
invariant check above confirms nothing listed was altered; only a new
optional field was added to an existing function's return value.

## Recommendation / scoping question back to PAR-209

The asset-finance definitional gap (§2a) is not fixable by any code change
in this session's scope — the cash literally never touches an ingested bank
account, so there is no transaction for any rule to classify. Options for a
future ticket, for Parity Science / product to decide, not decided here:
- Accept that Loan Activity reconciliation can only ever validate the
  "normal loan" (cash-to-borrower) portion of `financing_cashflow_cents`,
  and make that scope explicit in the UI/label rather than implying full
  comparability.
- Extract a "cash financing" vs. "non-cash/asset-finance financing" split
  from the audited cashflow statement notes (adjacent to PAR-183's
  extraction-fidelity work) so the declared figure being compared can be
  scoped to only the cash-to-borrower portion.

Both are ontology/extraction-scope decisions, not classifier bugs — flagging
back to PAR-209 rather than forcing a fix here.
