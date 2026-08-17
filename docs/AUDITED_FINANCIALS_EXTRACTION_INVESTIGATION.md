# Audited Financials / Management Accounts Extraction — Full State Report
*Investigation only — diagnosis, no fixes applied. 21 June 2026.*

**Branches read:** `main` and `paritystaging` in the `Tunnel` repo. Every file cited
below was diff-checked directly (`git diff main paritystaging -- <path>`) and found
**byte-identical on both branches** unless stated otherwise — so every line citation
applies to both `main` and `paritystaging` equally. The working tree (currently
checked out on `fix/rls-disabled-tables-staging`) also matched `main` exactly for
every file read here; the only uncommitted working-tree changes at investigation
time (`router.py`, new `layout_config.py`/`harness.py`/`configs/absa.json`) are an
unrelated ABSA bank-statement parsing experiment, not audited-financials code —
confirmed by reading their contents, not assumed.

---

## 1. Pipeline map

### 1.1 Ingestion entry point — discrepancy from the brief

The brief named `POST /extract/audited-financials`. That path **does not exist
anywhere in the codebase** — confirmed by `grep -rn "extract/audited-financials"`
across the full repo, zero matches. The real entry points are:

- **`POST /v1/ingest/audited-financials`** — [`parity-ingestion/app/main.py:134-183`](../parity-ingestion/app/main.py#L134). PDF only; rejects any other extension with `415` (line 146-150, message explicitly redirects non-PDF to the tabular endpoint). Auto-routes to OCR vs. coordinate extraction based on `is_scanned_pdf()` (line 163).
- **`POST /v1/ingest/audited-financials/tabular`** — [`main.py:186-225`](../parity-ingestion/app/main.py#L186). Accepts `.csv`, `.xlsx`, `.xls` (line 198).
- The actual user-facing upload endpoint, on the **backend** (not parity-ingestion), is **`POST /v1/deals/{deal_id}/upload-financials`** — [`backend/v1/api.py:1788-1878`](../backend/v1/api.py#L1788). Accepts PDF/CSV/XLSX/XLS (line 1824, `_ACCEPTABLE_FINANCIALS_EXTENSIONS`), no explicit size limit found in this handler or in `main.py` — none of the three handlers impose a max upload size.

Call chain: frontend → `upload_audited_financials()` (api.py:1789) → `extract_audited_financials_via_ingestion()` in [`backend/v1/parsing/audited_financials_client.py:60-131`](../backend/v1/parsing/audited_financials_client.py#L60) → HTTP POST to whichever parity-ingestion endpoint matches the file extension (lines 78-83) → on any `AuditedFinancialsExtractionError` **for PDF only**, falls back to an in-process extractor (`audited_financials_inline.py`); CSV/XLSX failures are re-raised with **no fallback** (client.py:100-102, comment: *"No inline fallback for CSV/Excel — re-raise"*).

### 1.2 Extraction logic — the central brittleness question

**`audited_financials_extractor.py`** (PDF, 868 lines) — module docstring states it
was *"Tested on: Buildex Interiors Company Ltd FY2025 (24-page PDF)"* (line 15) and
nothing else. Matching strategy, read directly from the code:

- **Row/column reconstruction is keyed to hardcoded pixel (x0) zone boundaries**,
  one tuple per statement type — `_IS`, `_BS`, `_CF`, `_NT` at
  [lines 38-48](../parity-ingestion/app/extractors/audited_financials_extractor.py#L38).
  E.g. `_IS = dict(label_max=270, note_max=340, cur_min=340, cur_max=440, pri_min=440)`.
  These are literal PDF coordinate positions, derived (per the comment at line 374,
  *"derived from page 22 coordinate inspection"*) from **this one Buildex PDF's
  specific rendering**. `_zone_text()` (line 71) slices characters by `x0` falling
  inside these bounds. A different auditor's PDF — different margins, font, page
  size, or column widths — will shift every glyph's `x0`, causing this slicing to
  capture the wrong substring per row. The keyword matching itself (`_IS_MAP`,
  `_BS_MAP` etc., lines 144-156 / 225-238) is reasonably generic wording, but it
  never gets a chance to run correctly if the zone-slicing already produced garbage
  or empty text — and a wrong zone slice does **not** raise an error, it just
  silently returns a different (possibly numeric-looking) string, so a layout
  mismatch is more likely to produce **wrong or missing values that pass silently**
  than a clean exception.
- **Note 11 / Note 14 detection is keyed to literal note *numbers***, not
  semantic content — [lines 399 and 406](../parity-ingestion/app/extractors/audited_financials_extractor.py#L399):
  `label_raw.strip().startswith("11")` for the cash note, `.startswith("14")` for
  the loan note. This is the single most certain structural finding: Kenyan
  auditors do not standardize note numbering. Any company whose cash note isn't
  literally numbered "11" and loan note isn't literally "14" gets `cash_breakdown:
  None` and `loan_breakdown: None` — silently, with no error — regardless of how
  well everything else extracts.
- **Page-finding** (`_find_page`, lines 104-132) matches by required keyword
  presence (`"COMPREHENSIVE INCOME"`, `"FINANCIAL POSITION"`, `"CASHFLOW"`) plus a
  minimum-numeric-character density check in a fixed x-range — keyword side is
  generic, the density x-range is again tuned to this document's layout.
- **Required-field gate exists for the PDF coordinate path**: `_extract_income_statement`
  and `_extract_balance_sheet` each raise `ValueError` if specific fields are absent
  (lines 209-216, 282-290) — so a sufficiently broken layout *does* fail loudly for
  those two statements. Cash flow has the same gate (lines 352-358). Notes do not —
  they degrade silently to `None` as above.

**OCR fallback exists and is real**, contrary to "no OCR anywhere" being a safe
assumption: `extract_audited_financials_from_ocr()`,
[lines 725-865](../parity-ingestion/app/extractors/audited_financials_extractor.py#L725),
uses `pdf2image` + `pytesseract`, triggered automatically when
`is_scanned_pdf()` returns true
([`pdf_type_detector.py:1-29`](../parity-ingestion/app/extractors/pdf_type_detector.py#L1) —
threshold: fewer than 10 extractable words across the first 2 pages = scanned).
System dependencies (`tesseract-ocr`, `poppler-utils`) are present in
[`parity-ingestion/Dockerfile:3-6`](../parity-ingestion/Dockerfile#L3), Python deps
(`pdf2image==1.17.0`, `pytesseract==0.3.10`) are in `requirements.txt` — both
confirmed identical on `main`/`paritystaging`. **But this OCR path has a live,
reproducible crash bug — see §3, finding F3.** It also only exists in the
parity-ingestion microservice path. The backend's **inline fallback**
(`audited_financials_inline.py:29-39`) imports only `extract_audited_financials`
(coordinate path) — never the OCR function — and its own docstring says so
explicitly (line 108 in `audited_financials_client.py`: *"Only works for PDF
files; no OCR (scanned PDFs fall through to manual entry)"*). Net effect: if
`PARITY_INGESTION_URL` is unset or the service is unreachable, a scanned PDF can
never be OCR'd — it fails cleanly via the `required`-field `ValueError`s above
(confirmed by code path, not independently executed in this exact combination).
Whether the backend's production Cloud Run service actually has
`PARITY_INGESTION_URL` set (i.e. whether this fallback path is ever live in
practice) was **not verified in this session** — out of scope of what I could
confirm without infra/secret access; flagging rather than guessing.

**`tabular_financials_extractor.py`** (CSV/XLSX, 309 lines) — label-matching via
regex (`_LABEL_MAP`, lines 65-93) is genuinely format-agnostic (no hardcoded
positions, since spreadsheets don't have PDF coordinates). It takes the **last
non-null numeric column** per row as "most recent year" (lines 153-159) — fragile
if a sheet's most recent column isn't rightmost. **No required-field gate exists
at all** here (unlike the PDF path) — `_extract_fields_from_df` (lines 137-164)
returns whatever it found, even an empty dict, with no raise. The only thing that
turns a near-empty result into an error is the **confidence == 0** check at the
client layer (`audited_financials_client.py:94-97` and `123-126`) — so a file that
coincidentally matches even one label (e.g. a stray 4-digit number read as
`financial_year`) produces a low-but-nonzero-confidence record that gets saved as
if it were a real partial extraction, never surfacing as a parse failure.

### 1.3 Failure handling — re-verified, both branches

`AuditedFinancialsExtractionError` → `422 {"status": "PARSE_FAILED", ...}` is
confirmed live, **identically on `main` and `paritystaging`**, at
[`backend/v1/api.py:1834-1838`](../backend/v1/api.py#L1834) (v15 cited 1834-1837;
off by one line on the closing brace, otherwise accurate — re-verified directly,
not taken on the prior document's word). Router prefix is `/v1`
(`api.py:33`), confirming the full path is `/v1/deals/{deal_id}/upload-financials`.

### 1.4 Request-parser flow — confirmed live, does persist

`POST /api/request-parser` → full path `/v1/api/request-parser` (router prefix
`/v1`, `api.py:33`), handler at
[`api.py:1932-1953`](../backend/v1/api.py#L1932). Confirmed it **does** write to a
real, queryable table — `parser_requests` (via Supabase insert, line 1948-1950) —
then returns `{"status": "received"}`. This is more than v15 claimed to have
checked ("returns 200" only); re-verified by direct query against both live
projects (see §3, prod has 1 row — a test entry — staging has 1 row, a genuine
"Audited financials parse failed" entry tied to a real `deal_id`).

### 1.5 Consumption — `reconciliation_engine.py`

`_get_audited_financials()` ([lines 55-74](../backend/v1/analysis/reconciliation_engine.py#L55))
raises `ValueError` if no row exists for the deal at all — a hard stop, not silent.

Once a row exists, **every individual field is defaulted with `or 0` if missing**,
e.g. `declared_total_cents = af.get("cash_and_equivalents_cents") or 0` (line 168),
`declared_revenue_cents = af.get("turnover_cents") or 0` (line 311). This does not
error and does not explicitly skip — it produces a result, but the result's
*meaning* differs by check:
- **Revenue / loan checks degrade gracefully**: when the declared figure is `0`
  (because it was actually missing, not actually zero), `gap_pct`/`variance_pct`
  become `None` via an explicit `if declared > 0 else None` guard (lines 323-326,
  432-436), and revenue specifically labels it outright: `"INSUFFICIENT_DATA — no
  declared revenue"` (line 330).
- **Cash position reconciliation does not get the same treatment.** `variance_pct`
  is guarded the same way (line 282-286: `None` if `declared_total_cents <= 0`),
  but the **`status` field is not** — `_variance_status()` (lines 138-145) compares
  `variance_cents` to `declared_total_cents` and, when `declared_total_cents` is 0
  (because the field was missing, not actually zero) and the bank side has any real
  cash, falls through to `"SIGNIFICANT_VARIANCE"`. This is a confirmed, current
  consequence (read directly from the code, not executed against live data this
  session): a partial audited-financials extraction that's missing
  `cash_and_equivalents_cents` produces a cash reconciliation result that *looks
  like* "your bank cash doesn't match your books" rather than "we don't have your
  books' cash figure" — the two are visually indistinguishable in the output shape
  unless someone separately checks whether the declared figure was genuinely zero.

---

## 2. The two items flagged "unconfirmed" in v15 — both resolved

### 2.1 Hardcoded `KES` — ✅ confirmed fixed, but the fix has a live regression

The literal `"currency": "KES"` v15 flagged at `audited_financials_extractor.py`
~512/~756 and `tabular_financials_extractor.py` ~233/~273 **no longer exists**.
Confirmed via `git log -p` on both files: commit `a0568bc`
("3-layer currency detection") replaced every hardcoded literal:

- `audited_financials_extractor.py:515` and `:759` now call
  `detect_currency(raw_text)` / `detect_currency(text)`.
- `tabular_financials_extractor.py:241` and `:289` now use a `currency_hint`
  parameter (default `None`).

`a0568bc` is on both `main` and `paritystaging` (`git branch --contains a0568bc`
lists both). **This part is ✅ Done, not just diagnosed.**

**However**, two new, currently-live problems were found while confirming this:

- **F1 — currency detection regresses on the one file that's supposed to work.**
  Running the existing real test suite (not just reading the code) —
  `pytest tests/test_audited_financials_buildex.py -v` — produces a real failure
  today, on the actual Buildex fixture, on both branches:
  ```
  tests/test_audited_financials_buildex.py::TestMetadata::test_currency FAILED
  AssertionError: assert None == 'KES'
  ```
  Root cause, confirmed by direct inspection: `_extract_metadata()` only feeds
  `pdf.pages[0].extract_text()` (line 476) — the cover page — into
  `detect_currency()`. The real Buildex PDF's page 1 text is
  `"BUILDEX INTERIORS COMPANY LIMITED\nANNUAL REPORT AND FINANCIAL STATEMENTS\nFOR
  THE YEAR ENDED 31 DECEMBER 2025\nDRA FT"` (extracted directly, 115 chars) — no
  currency marker anywhere, so `currency_detector.detect()` correctly returns
  `None` per its own contract (*"Never guesses. Never defaults to KES."*,
  `currency_detector.py:7`). There is no L2/L3 fallback wired into the
  audited-financials extractor at all (L2 country-lookup and L3 explicit-raise
  exist only in `backend/v1/integrations/currency_utils.py`, used solely by the
  Musa flow). **42/43 tests in the suite still pass — only the currency field is
  wrong** — but the file the codebase treats as its one working reference case no
  longer reports its currency correctly. Confirmed by `git show a0568bc --stat`:
  the commit's own test additions were `test_currency_detector.py`,
  `test_currency_utils.py`, `test_musa_integration.py` — `test_audited_financials_buildex.py`
  was never re-run against this change, which is how the regression shipped
  unnoticed.
- **F2 — `tabular_financials_extractor.py`'s `currency_hint` is never populated by
  any caller.** Confirmed by grepping every call site:
  `main.py:216` (`extract_audited_financials_from_csv(str(dest))`) and `:218`
  (`extract_audited_financials_from_excel(str(dest))`) both call the function with
  **no second argument**. No other code anywhere calls these two functions. The
  parameter exists, is documented, and is permanently dead — every CSV/XLSX
  audited-financials upload returns `currency: None`, unconditionally. Not
  hardcoded-KES (that's genuinely fixed), but not detected either — just absent.

### 2.2 `venture_country` API boundary guard — ✅ confirmed clean, but doesn't apply where the brief assumed

`country_to_currency()` (`backend/v1/integrations/currency_utils.py:49-104`) does
raise `ValueError` on unresolvable input, confirmed by reading the function body
and its existing passing test suite (`test_currency_utils.py`, not re-run this
session but matches the code read).

The calling endpoint's handling: **clean, not a 500.**
[`musa_api.py:156-159`](../backend/v1/integrations/musa_api.py#L156):
```python
try:
    deal_currency = country_to_currency(body.venture_country)
except ValueError as exc:
    raise HTTPException(status_code=422, detail=str(exc))
```
This is on `POST /api/musa/sessions` (router prefix `/api/musa`, line 45) —
confirmed identical on both branches.

**Important correction to the brief's framing**: this guard is not in the
audited-financials upload path at all. `grep` across the repo shows
`venture_country`/`country_to_currency` used only in `musa_api.py` and
`musa_file_processor.py` — the Musa **deal/session creation** flow, which runs
*before* any financials file is uploaded. `upload_audited_financials()`
(`api.py:1788`) never references either. So an unhandled exception here cannot
manifest as "a generic 500 on audit upload that looks like a parsing failure" —
those are two unrelated endpoints. There *is* a second, redundant call to
`country_to_currency()` inside the background task
(`musa_file_processor.py:264`, wrapped in `try/except ValueError → raise
RuntimeError`), but it's unreachable in normal operation (the same
`venture_country` was already validated synchronously before the background task
is even scheduled, `musa_api.py:212-221`), and even if it somehow fired, a
`RuntimeError` raised inside a `BackgroundTasks` callback after the HTTP response
has already been returned does not surface to any client — it would only appear
in server logs. **Resolved: not a risk, and not relevant to audited-financials
extraction specifically.**

---

## 3. Real failure-mode testing — partially blocked

**Blocker, reported as instructed rather than worked around:** the brief asks for
5–10 real audited-financials/management-account files from outside
Buildex/FH Consulting LLP. After searching (a) the parity-ingestion and backend
test fixture directories, (b) the user's local Desktop/Downloads/Documents trees
for anything resembling a financial statement, (c) both worktree checkouts under
`.claude/worktrees/`, and (d) the production and staging Supabase projects —
**zero such files exist anywhere accessible to me.** Specifics:

- Every fixture in `parity-ingestion/tests/fixtures/` for audited financials is
  Buildex (`buildex/buildex_financials_2025.pdf` and its companion bank
  statements). No CSV/XLSX audited-financials fixture exists at all.
- Filesystem search for PDFs matching "audit/financial/statement/account" found
  Buildex (multiple copies), bank statements (Equity/KCB/Coop/M-Pesa — wrong
  document type), two crop-yield model validation reports for an agricultural
  insurance scheme (`AIC_CCE_AYII_AUDIT_REPORT.pdf`, `AGRAILS_AIC_AUDIT.pdf` —
  confirmed by extracting page 1 text; this is a satellite-model audit, not a
  company's financial statements), and a personal loan disclosure letter — none
  usable.
- **Production `pds_audited_financials` (9 rows) and staging (7 rows) — every
  single row, on both projects, is Buildex** (`BUILDEX INTERIORS COMPANY LIMITED`
  or `Buildex Interiors Ltd`), re-verified with a direct `SELECT`, not
  `list_tables()` row-count metadata (per the documented lesson that the latter
  can be stale). No other company has ever produced a stored record on either
  environment.
- `parser_requests` (the table the brief's §1.4 concerns) has exactly 1 row on
  each project. Prod's is a literal test entry (*"verification test — ignore"*).
  Staging's is real — `error_message: "Audited financials parse failed"`, tied to
  a real `deal_id` — but carries no filename, bank name, or document URL, so it
  confirms a failure happened without telling me what was uploaded. The original
  file bytes are not recoverable: per the v15 document's own confirmed finding,
  this pipeline parses uploads in-process and never writes them to storage.

I did **not** fabricate a synthetic audited-financials file to fill this gap, per
the explicit instruction not to dress up synthetic data as real test evidence.

**What I did instead, with real files, to get as much genuine signal as possible:**

| Input | Path exercised | Outcome | Category | Evidence |
|---|---|---|---|---|
| `buildex_financials_2025.pdf` (real, the only real audited-financials file available) | `extract_audited_financials()` via real `pytest` run | **42/43 pass, 1 fail** | (a) Currency | Actual pytest output, §2.1 F1, above |
| `scanned_equity_bank_statement.pdf` (real file, but a bank statement, not audited financials — used only as a mechanical vehicle to exercise the OCR code path, since no real scanned audited-financials PDF exists anywhere accessible) | `is_scanned_pdf()` then `extract_audited_financials_from_ocr()`, both run directly | `is_scanned_pdf` → `True` (correct classification). OCR extraction **crashes** | (d) Other — see F3 below | Real traceback, pasted below |
| *(no non-Buildex audited-financials PDF/CSV/XLSX exists to test)* | `extract_audited_financials()` (different auditor layout), `extract_audited_financials_from_csv/_excel()` | **Not run — no real file available** | n/a | Blocked, reported per instructions; structural risk documented in §1.2 from code reading only, explicitly not claimed as a test result |

**F3 — OCR path has a live, reproducible crash bug, found by actually running it:**

```
$ python3 -c "...extract_audited_financials_from_ocr('tests/scanned_equity_bank_statement.pdf')..."
Traceback (most recent call last):
  File ".../audited_financials_extractor.py", line 856, in extract_audited_financials_from_ocr
    result["extraction_confidence"] = _calculate_confidence(result)
  File ".../audited_financials_extractor.py", line 543, in _calculate_confidence
    expected = data["profit_before_tax_cents"] - data["tax_expense_cents"]
TypeError: unsupported operand type(s) for -: 'NoneType' and 'NoneType'
```

Root cause: `_calculate_confidence()` (shared by both the coordinate and OCR
paths) checks field *presence* (`all(f in data for f in [...])`,
[line 541](../parity-ingestion/app/extractors/audited_financials_extractor.py#L541))
but assumes presence implies a non-`None` value. That assumption holds for the
coordinate path, because `_extract_income_statement()` already raises
`ValueError` earlier if those same fields are missing (lines 209-216) — so by the
time `_calculate_confidence` runs on a coordinate-path result, the fields are
guaranteed to be real integers. It does **not** hold for the OCR path: OCR's
result dict literal (lines 754-853) unconditionally sets every key, with
`_ocr_find_amount()` returning `None` on no regex match rather than omitting the
key — and `extract_audited_financials_from_ocr()` deliberately "never raises" per
its own docstring (line 734), so nothing upstream catches this. **Net effect: the
OCR path crashes with an unhandled `TypeError` on any document where OCR's regex
patterns fail to find both "profit before tax" and "tax expense" wording** — which
is a near-certainty for any document that isn't phrased exactly like the patterns
expect. This crash is not caught inside `extract_audited_financials_from_ocr`
(only the OCR-conversion step itself is wrapped in try/except, lines 737-745), so
it propagates to `main.py`'s generic `except Exception → HTTPException(500)`
(lines 176-178) at the parity-ingestion layer. The backend client
(`audited_financials_client.py:48-55`) treats any `>=400` response as
`AuditedFinancialsExtractionError` regardless of status code, so the end user
still only ever sees a clean `422 PARSE_FAILED` — but the *reason* it failed is an
unrelated crash, not a deliberate "we couldn't read this" determination, and the
crash means **no partial OCR result can ever be returned**, even when OCR
successfully read several other fields. This is a genuine, currently-live bug,
confirmed by direct execution, not inferred from reading the code.

---

## 4. Honest summary

Based only on what was actually run or directly read this session: the
Buildex-only symptom is most likely **(b) structural**, with moderate-to-high
confidence, but this conclusion rests on code analysis, not on running a second
real auditor's file through the pipeline — that test could not be performed at
all, for any category, because no such file exists anywhere I could access. The
strongest evidence for (b) is the Note 11/Note 14 literal-number keying
(§1.2) and the hardcoded pixel-coordinate row/column zones tuned to one specific
PDF rendering (§1.2) — both read directly from the extractor and not
auditor-generic by construction. Separately and with high confidence (verified by
actually running the code, not inferring it), there are two more failure modes
that are *not* what the brief hypothesized: (a) a currency-detection regression
that now affects the Buildex reference file itself (F1), and (d) a crash bug that
makes the OCR fallback non-functional for essentially any real-world scanned
document (F3). Whether a different auditor's well-formed text-layer PDF would
clear the structural hurdle in (b) is **not established** either way — it's the
one thing this report cannot answer without a real second file.

---

## 5. What could not be verified, and why

- **Structural brittleness against a real second auditor's layout** — no file
  exists anywhere accessible (local filesystem, repo, prod/staging Supabase) to
  test this directly. §1.2's structural analysis is code-reading only, explicitly
  not a test result.
- **CSV/XLSX extractor behavior on a real management-account spreadsheet** — same
  blocker, no real file available; only the `currency_hint` dead-parameter finding
  (F2) was confirmed, via grep of every call site, not via running the function
  against real data.
- **Whether `PARITY_INGESTION_URL` is actually set on the production backend Cloud
  Run service** (governs whether the inline PDF-only, no-OCR fallback is ever
  live in practice) — not checked this session; would need direct
  `gcloud run services describe` access or equivalent, which I did not use.
- **The one real "Audited financials parse failed" `parser_requests` row on
  staging** — confirms a failure happened, but carries no filename/bank/URL, and
  the original file was never persisted anywhere (confirmed: this pipeline parses
  in-process and never writes uploads to storage), so its specific cause is
  unrecoverable.
- **Whether the cash-flow block inside `_calculate_confidence` (lines 547-557)
  has the same `None`-arithmetic crash risk as the PAT block (F3)** — structurally
  it looks like the same pattern (`all(f in data...)` followed by unguarded
  arithmetic), but execution never reached that block in the one OCR run
  performed (it crashed earlier, at the PAT check). Flagging as a suspected but
  **not independently confirmed** second instance of the same bug class.

---

## 6. Update — 21 June 2026: two confirmed fixes + 5-file real test corpus
*Per the append-only convention above — nothing in §1-5 is edited or deleted.*

**Branch:** `fix/audited-financials-currency-ocr`, branched off `paritystaging`
at `0ef8e6f` (which already includes PR #26, the unrelated Dockerfile
`libgdk-pixbuf2.0-0` fix). Built in an isolated `git worktree`
(`../tunnel-wt-audited-fix`) specifically so this work would not touch the
main checkout's separate, unrelated, uncommitted ABSA layout-harness
experiment (`router.py`, `layout_config.py`, `harness.py`,
`configs/absa.json` — confirmed by reading their contents in the prior
session; still sitting uncommitted in the main `Tunnel` checkout, untouched).
Fix commit: **`61bcd38`** — *"fix: audited-financials currency regression +
OCR confidence crash"* — not yet pushed or merged; sitting locally on the new
branch pending review. Per §0 requirement 1, this is the full state: a local
commit hash, not yet on any remote or branch ancestry beyond itself.

Explicitly **not touched**, per this session's scope: the Note 11/Note 14
literal-note-number matching and the hardcoded pixel-coordinate row/column
zones (`_IS`/`_BS`/`_CF`/`_NT` in `audited_financials_extractor.py`). Both are
read again below, with new real-execution evidence, but the architecture
itself is unchanged — that's the pending strategy call, not this session's.

### 6.1 Fix 1 — currency-detection regression (F1, §2.1)

**Diagnosis before fixing:** scanned the real Buildex fixture page-by-page for
any currency marker. Page 1 (cover) has none. Pages 13 and 24 do — page 13 is
the "Basis of preparation" accounting-policy note (*"The financial statements
are presented in the functional currency, Kenya Shillings (KShs)..."*), page
24 is an explicit numbered note (*"19. CURRENCY — These financial statements
are presented in Kenya Shillings (KShs)"*). Both use **"KShs"**, not "KSh" —
and the existing `_SYMBOLS` regex in `currency_detector.py`
(`r'\bKSh\b|\bKsh\b|\bK\.Sh\b'`) requires a word boundary immediately after
"KSh", which the trailing "s" in "KShs" breaks. So two independent gaps had to
be closed together, not one:

1. **`parity-ingestion/app/extractors/currency_detector.py`** — widened the
   KES symbol pattern to `r'\bKShs?\b|\bKshs?\b|\bK\.Shs?\b'` (purely
   additive — every string the old pattern matched, it still matches).
2. **`parity-ingestion/app/extractors/audited_financials_extractor.py`,
   `_extract_metadata()`** — after `detect_currency(raw_text)` (page 1) comes
   back `None`, falls through to `pdf.pages[1:]`, calling `detect_currency` on
   each subsequent page's text and stopping at the first hit. `company_name`
   and `financial_year` parsing — which do work correctly from page 1 alone —
   were left completely untouched; only the `currency` variable's source
   changed.

**Which fix, and why (`currency_hint` vs. widening the scan):** the
`currency_hint` parameter the original report flagged as dead (F2, §2.1) lives
on `tabular_financials_extractor.py` — the CSV/XLSX extractor. Buildex is a
PDF, going through `extract_audited_financials()` in the *other* file, which
has no `currency_hint` parameter at all and no caller that could supply one
(there is no known currency at the point a PDF is first uploaded — that's
the whole reason detection exists). Wiring up `currency_hint` would not have
touched this regression at all; it was never a candidate fix for *this* bug,
only for the separate, still-unfixed F2 finding on the CSV/XLSX path, which
remains out of scope for this session.

**Why not hardcode a page number instead:** Buildex's note happens to be on
page 13/24 of a 24-page document, but that page number is an artifact of
*this* auditor's template, not a property of audited financial statements in
general — hardcoding it would be exactly the brittle, document-specific
pattern this session was told not to extend. Scanning forward through the
document until a marker is found makes no assumption about which page or
which exact phrasing carries the currency declaration.

**Real test output, before and after** (`pytest tests/test_audited_financials_buildex.py -v`):

```
# Before (matches the original report's F1 finding, re-confirmed at the start of this session):
tests/test_audited_financials_buildex.py::TestMetadata::test_currency FAILED
AssertionError: assert None == 'KES'
...
1 failed, 42 passed in 3.34s

# After:
============================== 43 passed in 3.44s ===============================
```

Also re-ran `tests/test_currency_detector.py` in full — **50/50 passed**,
confirming the widened `_SYMBOLS` regex didn't regress any of the existing
currency-detection cases (KES, UGX, RWF, GHS, ETB, NGN, ZAR, CFA-ambiguity,
inline-amount, and edge-case tests all still pass unchanged).

**Regression tests added**, so this can't silently come back:
- `tests/test_currency_detector.py::TestP3LocalSymbols::test_kshs_plural` and
  `::test_kshs_lowercase_plural` — pin the "KShs"/"Kshs" trailing-s forms
  directly at the unit level.
- `tests/test_audited_financials_buildex.py::TestMetadata::test_currency_not_sourced_from_cover_page_alone`
  — opens the real Buildex fixture, asserts page 1 alone still yields no
  currency marker (documenting *why* the multi-page fallback is needed, not
  just *that* it works) — if a future edit ever changes the cover page to
  carry a marker, this test fails loudly rather than silently making the
  regression guard meaningless.

**Re-run after adding the new tests** (`pytest tests/test_audited_financials_buildex.py tests/test_currency_detector.py -v`):
```
============================== 96 passed in 4.72s ===============================
```

### 6.2 Fix 2 — OCR confidence-calculation crash (F3, §3)

**Exact site:** the crash is not in a regex-match call — `_ocr_find_amount()`
(the regex-match function) already returns `None` cleanly on no match, by
design. The throw site is the **arithmetic that consumes that result**:
`audited_financials_extractor.py`, `_calculate_confidence()`, the PAT
reconciliation check —
```python
if all(f in data for f in pat_fields):
    expected = data["profit_before_tax_cents"] - data["tax_expense_cents"]
```
`all(f in data for f in [...])` checks **key presence**, not whether the
value is `None`. That distinction is invisible for the coordinate path
(`extract_audited_financials`), because `_extract_income_statement()` already
raises `ValueError` earlier if these same fields are missing — so by the time
confidence is calculated there, they're guaranteed to be real integers. OCR's
result dict sets every key unconditionally, with `None` standing in for "no
regex match," and `extract_audited_financials_from_ocr()` is documented to
*"intentionally never raise"* — so nothing upstream catches the mismatch
between what the shared confidence function assumes and what OCR actually
guarantees.

**Fix applied:** wrapped the call site, not the arithmetic inside
`_calculate_confidence()` itself —
```python
try:
    result["extraction_confidence"] = _calculate_confidence(result)
except TypeError as exc:
    logger.error("[OCR] Confidence calculation failed — required fields not "
                 "found in OCR text (%s)", exc)
    return {
        "extraction_method": "tesseract_ocr",
        "extraction_confidence": Decimal("0"),
        "sha256_hash": _sha256({}),
    }
```
in `extract_audited_financials_from_ocr()`. This is the exact same
empty-skeleton shape already returned ten lines earlier for total
`_ocr_pdf_to_text()` failure — no new failure state was invented.
`_calculate_confidence()`'s internals were **not** touched (so the
coordinate path, where this branch can never actually trigger, is provably
unaffected — confirmed by the unchanged, fully-passing Buildex suite above;
exact count corrected to 44/44 in §7 after a new regression test was added
in §6.1, above this point in the file).

**Why this reaches the existing 422 `PARSE_FAILED` path, traced through a real
local run, not just code-reading:** started the real parity-ingestion FastAPI
app locally (`uvicorn app.main:app --port 8099`) and POSTed the real scanned
fixture (`tests/scanned_equity_bank_statement.pdf` — a bank statement, not
audited financials; used only as a mechanical vehicle, as in the original
report, since no real scanned audited-financials PDF exists anywhere
accessible):
```
$ curl -s -w "\nHTTP_STATUS:%{http_code}\n" -X POST http://127.0.0.1:8099/v1/ingest/audited-financials \
    -F "file=@tests/scanned_equity_bank_statement.pdf;type=application/pdf"
{"extraction_method":"tesseract_ocr","extraction_confidence":0,"sha256_hash":"80957c53f68e6a423fa9f34fc6403f1eb012e2cb25616bb9b9dad5bbe8dbbdaa"}
HTTP_STATUS:200
```
**Before the fix this was `HTTP_STATUS:500`** with the raw `TypeError` text in
the body (confirmed in the original investigation session). Then called the
real backend client function (`extract_audited_financials_via_ingestion`)
pointed at this live local instance:
```
$ PARITY_INGESTION_URL=http://127.0.0.1:8099 python3 -c "...extract_audited_financials_via_ingestion(file_bytes, 'scanned_equity_bank_statement.pdf')..."
[AUDITED CLIENT] parity-ingestion failed (Unsupported audited financials format: extraction confidence is zero) — trying inline extraction
AuditedFinancialsExtractionError raised (expected): Inline extraction failed: Income statement page not found
```
This confirms the existing, unmodified `confidence == 0 → AuditedFinancialsExtractionError`
check (`audited_financials_client.py:94-97`) fires exactly as designed — the
log line is the proof. The final exception text differs from a bare
"confidence is zero" message only because this particular test file is a PDF,
which also has the (pre-existing, unmodified) inline-fallback behavior: it
retries with the coordinate-only inline extractor, which then fails too (no
text layer in a scanned bank statement) — both outcomes are pre-existing
`AuditedFinancialsExtractionError`s, and `api.py:1834-1838` (unchanged, not
part of this fix) converts either one to a clean `422 {"status":
"PARSE_FAILED"}`. Did not stand up the full backend app (Supabase-dependent)
to capture that literal final HTTP response in this session — the exception
that triggers it is directly observed above, and the conversion code itself
was already cited and read in the original report without being modified
here.

**Regression tests added** (`tests/test_audited_financials_ocr.py`, new file):
- `test_missing_pat_fields_returns_zero_confidence_not_crash` — monkeypatches
  `_ocr_pdf_to_text` to return text with no financial wording at all (the
  `None - None` case).
- `test_partial_pat_fields_returns_zero_confidence_not_crash` — only
  "profit before tax" present, confirming the fix also covers the
  `int - None` / `None - int` partial case, not just all-missing.
- `test_real_scanned_pdf_smoke_test_does_not_crash` — re-runs the exact real
  file that produced the original crash, skipped automatically if the
  fixture or the `tesseract` binary isn't present.

```
$ pytest tests/test_audited_financials_ocr.py -v
tests/test_audited_financials_ocr.py::test_missing_pat_fields_returns_zero_confidence_not_crash PASSED
tests/test_audited_financials_ocr.py::test_partial_pat_fields_returns_zero_confidence_not_crash PASSED
tests/test_audited_financials_ocr.py::test_real_scanned_pdf_smoke_test_does_not_crash PASSED
3 passed in 8.62s
```

**Found while verifying, not anticipated in the original report:** wrapping
the *call site* rather than patching only the PAT line turned out to matter —
see §6.3, Tres Beau, where a **different** arithmetic operator (`+`, in the
cash-flow reconciliation block, not `-` in the PAT block) crashed on a real
document. The original report had flagged this cash-flow block as a
"suspected, not independently confirmed" second instance of the same bug
class (§3, closing bullet) — it is now **confirmed**, on real data, and
already covered by this fix without any additional code change, because the
fix wraps the function call rather than the specific line that happened to
be the one already observed crashing.

**Suite-wide check:** re-running the entire `parity-ingestion` test suite
hit a pre-existing, unrelated problem — `tests/test_coop.py` fails to import
(`ImportError: cannot import name '_parse_balance_to_signed_cents' from
'app.extractors.coop_extractor'`), confirmed via `git log` to be pre-existing
on `paritystaging` and untouched by this session (Co-op bank-statement
extractor, unrelated to audited financials). Excluding that file, a full run
of the remaining bank-statement extractor suites (`test_absa.py`,
`test_equity.py`, `test_equity_buildex.py`, `test_kcb.py`,
`test_kcb_buildex.py`, `test_mpesa_pdf.py`, `test_stanbic.py`) ran for several
minutes without completing in this session — slow/possibly hung for reasons
unrelated to anything touched here (no failures appeared in the partial
output before it was stopped, only passes and skips). Not chased further:
these files are untouched by either fix, and the directly relevant suites
(`test_audited_financials_buildex.py`, `test_currency_detector.py`,
`test_audited_financials_ocr.py` — 96 + 3 = **99 tests**) all passed in full,
with complete real output pasted above.

### 6.3 Real test corpus — 5 files from `Documents/Parity/Pilot & Demo/Auditfilestraining/`

Real client files, not committed to git (the directory is untracked in the
worktree; `*.pdf` is also repo-gitignored as a second, independent layer),
and read in place from their original location rather than copied into the
repo. Per the handling instruction, only filenames and extracted *field
values* are referenced below — no verbatim document text is quoted, beyond
the bare minimum needed to name a label.

Format check (`is_scanned_pdf()`, the same function the real pipeline uses to
route PDF vs. OCR) — none turned out to need the CSV/XLSX path; all 5 are
PDFs:

| File | Pages | Routed to |
|---|---|---|
| Kenlink Management Account Dec 2025.pdf | 13 | coordinate (`is_scanned_pdf` → False, 10 words on p1) |
| Tawi Fresh 2024 Audited Financial Statements.pdf | 18 | OCR (`is_scanned_pdf` → True, 0 words on p1) |
| Paragon Feeds Ltd Financials 2026 (2).pdf | 17 | coordinate (`is_scanned_pdf` → False, 15 words on p1) |
| Maharaji Audited Accounts.pdf | 21 | OCR (`is_scanned_pdf` → True, 0 words on p1) |
| Tres Beau Ltd Audited Accounts.pdf | 19 | OCR (`is_scanned_pdf` → True, 0 words on p1) |

**Outcome: 0 of 5 extracted any field, fully or partially.** Every one of the
5 failed cleanly (no crashes — confirming Fix 2 holds up on real, not just
synthetic-for-testing, documents) — none silently produced a wrong-but-saved
result.

| File | Outcome | Category | Evidence (exact, from this session's real run) |
|---|---|---|---|
| **Kenlink** | FAIL — `ValueError` at income-statement stage | **(b) Structural** | `_find_page(["COMPREHENSIVE INCOME"])` found nothing; the broader fallback keyword search landed on the wrong page — Note 10's *"Detailed profit and loss account"* breakdown, not the primary P&L statement — because that note's page happened to satisfy the keyword + numeric-density checks. On that wrong page, the hardcoded current-year column zone (`x0` 340–440) sliced the **prior-year** figure for at least one row (label "Raw Milk" → captured 2024's 143,699,400 instead of 2025's 141,783,600 — Kenlink's column order/positions differ from Buildex's). Separately confirmed `_extract_balance_sheet` fails outright (*"Balance sheet page not found"*) while `_extract_cashflow` succeeds (finds `operating_cashflow_cents`) — failure is independent per statement type, not all-or-nothing. |
| **Tawi Fresh** | FAIL — OCR confidence = 0 (clean, was a crash pre-fix) | **(d) Other** — OCR-text-serialization vs. regex-proximity mismatch, adjacent to (c) | OCR genuinely ran and produced substantial real text (34,804 chars across 18 pages). The literal phrase "profit before tax" appears once, "taxation" 7 times, "revenue" 4 times — but `_ocr_find_amount()`'s pattern requires a number within 60 characters **on the same line** (`[^\n]{0,60}?`), and Tesseract serialized this table's labels and figures onto separate lines (label column read first, numeric column read later) — so the proximity window can never bridge label to value for this document's layout, regardless of how many times the right words appear. |
| **Paragon Feeds** | FAIL — `ValueError` at income-statement stage | **(b) Structural** | The real, correctly-titled page (page 8, literally headed *"STATEMENT OF COMPREHENSIVE INCOME"*) **was found by the keyword check and then rejected** by the anti-false-positive numeric-density gate (`num_zone=(350, 440, 15)` — requires ≥15 numeric chars with `x0` in 350–440) — confirmed directly: only 2 numeric tokens on that page fall in that range; Paragon's actual figure column sits at `x0` ≈ 280–350, outside Buildex's hardcoded window. `_find_page` then fell through to its broader fallback keyword set and matched the **Cash Flow Statement** page instead (which also contains "profit", "loss", and "statement" in running text). Separately, `_extract_balance_sheet` and `_extract_cashflow` each got *most* required fields right but failed on 2–3 specific ones (`inventory_cents`/`share_capital_cents`/`retained_earnings_cents`; `financing_cashflow_cents`/`cash_at_start_cents`) — partial, not total, breakdown for those two statements. |
| **Maharaji** | FAIL — OCR confidence = 0 (clean, was a crash pre-fix) | **(d) Other** — same OCR-serialization mismatch as Tawi Fresh | All three of "profit before tax", "profit after tax", and "taxation" appear literally in the OCR text (1, 1, and 5 times) — confirmed via direct `_ocr_find_amount()` calls that all three resolve to `None` regardless. Same root cause: labels and the numeric column are serialized onto different lines by Tesseract for this document's table layout. |
| **Tres Beau** | FAIL — OCR confidence = 0 (clean, was a crash pre-fix) | **(d) Other**, distinct manifestation | This file is the clearest confirmation that the cash-flow block (flagged "suspected, unconfirmed" in the original report) really does carry the same bug class: `profit_before_tax_cents`, `tax_expense_cents`, and `profit_after_tax_cents` were **all successfully parsed as real, roughly self-consistent numbers** (confirmed by calling `_ocr_find_amount()` directly: 1,160,335,400 / 290,093,700 / 870,251,600 cents — PBT − tax ≈ PAT within ~KES 99) — so the PAT block did not crash. But `operating_cashflow_cents`, `investing_cashflow_cents`, and `financing_cashflow_cents` were all `None`, which raises the same `TypeError` inside `_calculate_confidence()`'s **cash-flow** reconciliation block (`+` operator, not `-`). **No unhandled exception reached the caller** — re-confirmed in §7 with an explicit try/except around the call — because this `TypeError` is raised from inside the *same* `_calculate_confidence(result)` call that Fix 2 already wraps (one call site, two internal blocks that can each raise it); the function returned the clean confidence-0 skeleton, exactly as designed. The side effect worth flagging: a genuinely-good income-statement OCR result gets discarded along with the unrelated cash-flow gap, since the except-handler returns the empty skeleton rather than a partial one. This is a direct consequence of doing exactly what was asked (fail cleanly into the existing path) rather than building partial-result handling, which was explicitly not requested. |

### 6.4 Updated honest summary

The original report's conclusion — *"most likely (b) structural, moderate-to-
-high confidence, but this conclusion rests on code analysis, not on running
a second real auditor's file"* — is now **confirmed, not just reinforced, and
sharpened into two distinct mechanisms rather than one.** Both real
text-layer files (Kenlink, Paragon Feeds) failed for exactly the structural
reason predicted: hardcoded page-matching and column-position logic tuned to
Buildex's specific PDF layout does not generalize, confirmed with exact
coordinates and exact wrong-page identifications, not inferred. That part of
the original prediction was right.

What real testing added that code-reading alone could not have found: **all
three scanned files failed for a reason that has nothing to do with
currency, and nothing to do with the crash bug fixed in §6.2 (which held —
zero crashes across all 5 real files).** OCR mechanically works — it produces
substantial, often-correct-looking text — but its field-finding regexes
assume a label and its value sit within 60 characters of each other on the
**same line**, and Tesseract does not serialize multi-column financial
tables that way; it tends to read label-blocks and number-blocks as separate
runs. This means OCR's 0% real-document success rate in this corpus (3 of 3
scanned files) is **not** explained by "no text layer" (category c, as the
original brief's framing anticipated) — there *is* a text layer, OCR reads
it, and the words are frequently present. It is closer to (d) Other, but it's
specific and mechanical enough to name precisely: a regex-proximity
assumption that doesn't match how this OCR engine's default page
segmentation serializes tables.

**The bottom-line answer to "why only Buildex," updated with this session's
evidence:** of the two original hypotheses, (b) Structural explains both
real-world native-PDF failures with exact, traced mechanisms, and a related
but distinct OCR-serialization gap (not quite (c), not generic "(d) Other"
either — specific enough to be its own finding) explains all three scanned
failures. (a) Currency was real (F1, now fixed) but never the reason any
file failed to extract data — it only ever affected the `currency` field's
correctness on files that otherwise succeeded. Across this real,
non-cherry-picked 5-file corpus, after fixing both confirmed bugs: **0 of 5
files extracted any field, partial or full.** That is a materially worse
result than "moderate-to-high confidence" — it is now directly confirmed that
fixing the two known bugs alone does not move the Buildex-only symptom at
all; the structural and OCR-serialization gaps are the actual, dominant, now
directly-evidenced cause.

### 6.5 What could not be verified, and why (this session)

- **The literal final HTTP response/body** for the `/v1/deals/{deal_id}/upload-financials`
  backend endpoint was not captured — that requires a running backend with a
  live Supabase connection (for deal lookup), which was not stood up this
  session. The exception that feeds it (`AuditedFinancialsExtractionError`)
  was directly observed instead; the conversion code itself was already read
  and cited, unmodified, in the original report.
- **Whether other real-world scanned documents would hit the same OCR
  line-serialization problem, or whether it's specific to how these 3 files'
  tables happen to be laid out** — 3 of 3 real scanned files in this corpus
  hit it identically, which is suggestive but not proof of universality.
- **Whether Kenlink's or Paragon Feeds' *wrong* (not just missing) field
  values would have looked plausible enough to pass validation undetected**
  had they not also been missing enough *required* fields to trigger the
  `ValueError` gate — partially answered (the Kenlink wrong-year-column value
  was directly observed), but not exhaustively checked across every field on
  both documents.
- **Whether the bank-statement extractor regression suite
  (`test_absa.py`/`test_equity.py`/`test_kcb.py`/etc.) is actually fully
  green** — the run did not complete in this session for reasons unrelated to
  either fix; not chased further since neither fix touches that code.

---

## 7. Correction — 21 June 2026, same day: two claims in §6 re-verified on request

*Per the append-only convention — §6 is not edited to hide what was wrong;
this section states plainly what was checked and what the actual answer is.*

### 7.1 The "96/99" framing in this session's chat summary was wrong — there are no 3 failing tests

§6.1/§6.2 reported real, correctly-passing test output throughout. The error
was specifically in the **chat summary sent after this session's work**,
which said "43/43 → 96/99 tests pass" — phrasing that reads as "3 of 99 are
failing." That is not true and was never supported by anything actually run;
it was an arithmetic slip (96 was the combined total of two files *before*
the third test file's 3 tests were added, not "96 passing out of 99").

**Re-verified directly, fresh, on request:**

Post-fix, this branch (`fix/audited-financials-currency-ocr`, commit
`61bcd38`), all three relevant files together:
```
$ pytest tests/test_audited_financials_buildex.py tests/test_currency_detector.py tests/test_audited_financials_ocr.py -v
...
============================= 99 passed in 10.58s ==============================
```
Per-file breakdown (run individually, to attribute the count precisely):
`test_audited_financials_buildex.py` → **44 passed**; `test_currency_detector.py`
→ **52 passed**; `test_audited_financials_ocr.py` → **3 passed**. 44+52+3 = 99.
**Zero failures, zero errors, confirmed by `grep -c FAILED` on the captured
output returning 0.**

**Pre-fix comparison, run fresh in a temporary detached-HEAD worktree at
`paritystaging`'s actual current tip (`0ef8e6f`)** — the two files that exist
there at all are the originals, without this session's 4 new tests (the
3rd file, `test_audited_financials_ocr.py`, doesn't exist on `paritystaging`):
```
$ git worktree add -d /tmp/paritystaging-clean-check 0ef8e6f
$ pytest tests/test_audited_financials_buildex.py tests/test_currency_detector.py -v
...
FAILED tests/test_audited_financials_buildex.py::TestMetadata::test_currency
AssertionError: assert None == 'KES'
========================= 1 failed, 92 passed in 4.54s =========================
```
**This is the only failure that ever existed, anywhere, in any run this
session** — the exact F1 regression from §2.1/§6.1, now fixed. There were
never 3 unrelated failing tests, pre- or post-fix. Worktree removed after the
check (`git worktree remove /tmp/paritystaging-clean-check --force`).

### 7.2 Tres Beau's cash-flow `TypeError` — did not crash; degraded cleanly into the path Fix 2 already protects

Re-ran with an explicit `try/except Exception` around the call, specifically
to remove any ambiguity about whether something escaped the function:
```
$ python3 -c "
from app.extractors.audited_financials_extractor import extract_audited_financials_from_ocr
try:
    result = extract_audited_financials_from_ocr('.../Tres Beau Ltd Audited Accounts.pdf')
    print('NO EXCEPTION RAISED — function returned normally')
    print(result)
except Exception as exc:
    print('EXCEPTION ESCAPED THE FUNCTION:', type(exc).__name__, exc)
"
[OCR] Confidence calculation failed — required fields not found in OCR text (unsupported operand type(s) for +: 'NoneType' and 'NoneType')
NO EXCEPTION RAISED — function returned normally
{'extraction_method': 'tesseract_ocr', 'extraction_confidence': '0', 'sha256_hash': '80957c53...'}
```
**No unhandled exception. It degraded cleanly into the zero-confidence path
Fix 2 already protects.** The `[OCR] Confidence calculation failed...` line
is not evidence of a crash — it is the literal `logger.error(...)` call
written *inside* Fix 2's `except TypeError:` block
(`audited_financials_extractor.py:869-878`); its presence is direct proof the
exception was caught, not that it escaped.

**There is no second, unprotected call site.** Confirmed by `grep -n
"_calculate_confidence(result)\|except TypeError"` against the current file:
`_calculate_confidence(result)` is called in exactly two places —
once inside `extract_audited_financials()` (coordinate path, line 653,
unwrapped, but provably safe because `_extract_income_statement()` already
raises before this point if any of the relevant fields would be `None` — see
§6.2's already-cited reasoning) — and once inside
`extract_audited_financials_from_ocr()` (line 868), which **is** the call Fix
2 wraps. The PAT block (`-`, the original confirmed bug) and the cash-flow
block (`+`, Tres Beau's case) are two different statements *inside the same
function*, `_calculate_confidence()`, reached through that single wrapped
call — not two separate call sites. Fix 2's decision to wrap the call rather
than patch the one line already covers both, which is exactly what Tres
Beau's result demonstrates. **No code change was needed or made as a result
of this re-check; no new regression test was added, because the existing
`test_partial_pat_fields_returns_zero_confidence_not_crash` and the real
Tres Beau result above already exercise this exact "TypeError inside
`_calculate_confidence`, caught at the call site" mechanism — adding a
cash-flow-specific variant would test the identical code path a second
time, not a new one.**

**Known, accepted, currently-safe gap — not a bug, left unwrapped
intentionally:** the coordinate path's call to `_calculate_confidence(result)`
at line 653 has no equivalent `try/except` and never will need one *as the
code stands today*, because `_extract_income_statement()`'s `required` check
(lines 209-216, raising `ValueError` on any of `turnover_cents` through
`profit_after_tax_cents` being absent) and `_extract_cashflow()`'s `required`
check (lines 352-358, raising on any of `operating_cashflow_cents` /
`investing_cashflow_cents` / `financing_cashflow_cents` / `cash_at_start_cents`
/ `cash_at_end_cents` being absent) both run and would already have raised
*before* line 653 is ever reached (confirmed by the call order in
`extract_audited_financials()`, lines 637-653: income and cashflow extraction
happen first, `_calculate_confidence` last) — so if either gate's shape ever
changes (e.g. a field is dropped from a `required` list, or the gate is
loosened to tolerate partial data), line 653 stops being provably safe and
this reasoning needs to be re-checked, not assumed.

---

## 8. Architecture decision — 21 June 2026: Claude-based extraction

*Per the append-only convention — §1-7 are not edited. This section records
a decision, not a fix; the build and validation it leads to are recorded as
§9 below, once performed.*

**Decision: build the next audited-financials extraction path on the Claude
API (native PDF/vision input), not on Tesseract OCR + regex, and not on
Google Document AI.**

This is a forward decision, made from the evidence already gathered in §1-7
of this same investigation — not a new round of vendor comparison shopping.
Rationale, each point tied to a specific finding above rather than a general
claim about LLMs being better at documents:

- **The OCR path's failure mode is structural to OCR-then-regex as an
  architecture, not a tuning problem.** §6.4 found, on real documents (Tawi
  Fresh, Maharaji), that Tesseract OCR mechanically succeeds — it reads
  substantial, often-correct-looking text, and the target words ("profit
  before tax", "taxation", "revenue") are frequently present — but
  `_ocr_find_amount()`'s regex requires a label and its value to sit within
  60 characters on the **same line**, and Tesseract's default page
  segmentation serializes a multi-column financial table as a label block
  followed by a separate number block, not as paired same-line text. No
  amount of regex tuning fixes this, because the information OCR discards
  (which number belongs to which row, post-serialization) is exactly the
  information the regex needs and Tesseract's plain-text output no longer
  carries. Claude's native PDF/vision input reads the page's visual layout
  directly — it sees the table as a table, not as two disconnected runs of
  text — so this specific, observed failure mode does not apply to it by
  construction, not by assumption.
- **Document AI's stronger table-handling tier needs training examples the
  team does not have.** Google Document AI's generic Document OCR processor
  would inherit a version of the same proximity problem (it still returns
  text plus layout hints, not guaranteed row/column reconstruction for an
  arbitrary unseen template); the tier that actually solves arbitrary table
  layouts well is the Custom Document Extractor / Layout Parser, which
  benefits from or requires labeled training examples per document
  template. §3/§6.3 establish the real corpus available to this team today:
  **6 real audited-financials files total** (Buildex plus the 5-file
  corpus — Kenlink, Tawi Fresh, Paragon Feeds, Maharaji, Tres Beau), each a
  different auditor/template. That is not enough examples to train a
  per-template custom extractor, and every new client brings a new
  template, so the training-data requirement does not shrink over time the
  way it would for a single standardized form. Claude's approach is
  zero-shot — it does not need template-specific examples to read a table
  it has never seen before.
- **No new vendor or GCP onboarding required.** The codebase already has a
  working Anthropic API relationship and pattern to follow —
  `backend/v1/parity_review/chat.py` already calls `anthropic.Anthropic()`
  with `ANTHROPIC_API_KEY` (read from `backend/.env`) and
  `model = "claude-sonnet-4-6"` for the Parity Review chat feature. Adopting
  Document AI would mean a first GCP project/service-account/IAM setup for
  this specific feature; adopting Claude extraction reuses infrastructure
  that already exists and is already trusted for other financial-context
  work in this product.
- **Cost is comparable between the two paths at current volume and is not
  the deciding factor.** At the volume implied by §3's real numbers (9 rows
  in prod, 7 in staging, all-time, all Buildex), per-document API/processing
  cost for either Claude or Document AI is small relative to the cost of a
  wrong reconciliation result reaching an investment decision. This
  decision is being made on the structural-failure-mode and training-data
  grounds above; cost is noted here only so it is not later mis-cited as
  the reason, since it was never the deciding factor and the other two
  reasons would hold even if Document AI were cheaper.

**Scope for this round is extraction only**, per the brief: build and
validate a Claude-based extraction function in isolation, do not wire it
into `/v1/ingest/audited-financials`, do not write its output anywhere
`reconciliation_engine.py` reads from, and do not touch the existing
Tesseract/regex/coordinate extractor code. That code stays live and
untouched until a human-confirm-before-lock gate exists to safely receive
the new path's output — a separate, later piece of work. The build and the
6-file validation against this decision are recorded in §9 below.

---

## 9. Build + 6-file validation — 21 June 2026

*Per the append-only convention — §1-8 are not edited.*

### 9.1 What was built

New, isolated module:
[`backend/v1/parsing/audited_financials_claude_extractor.py`](../backend/v1/parsing/audited_financials_claude_extractor.py)
in the Tunnel repo (sibling to, but not editing, `audited_financials_client.py`
and `audited_financials_inline.py` in the same directory). Single public
function, `extract_audited_financials_claude(file_bytes, file_name)`:

- Builds a single Claude Messages API call: PDFs go in as a native
  `type: "document"` base64 content block (one call handles text-layer
  *and* scanned PDFs identically — there is no separate OCR code path);
  images go in as a native `type: "image"` block; CSV/XLSX are rendered to
  plain text (XLSX via `openpyxl`, already a backend dependency) and sent
  as a `type: "text"` block, since the Messages API has no native
  spreadsheet content type.
- Model: `claude-sonnet-4-6`, per the brief — not changed to Haiku.
- One prompt (`_SCHEMA_INSTRUCTIONS`) asks for a single JSON object whose
  fields are a superset of the existing pdfplumber-coordinate extractor's
  output shape (`audited_financials_extractor.py`), plus `reference` and
  `type` on each `loan_breakdown` entry as the brief specified. Every
  monetary field is cents; the prompt explicitly says use `null` for
  anything not stated, never substitute zero, never carry forward a
  prior-year figure into a current-year field.
- No fallback model, no retry-with-different-model, no confidence score.
  `ClaudeExtractionError` is raised once, on: missing API key, unsupported
  extension, a Claude API error, or a response that still isn't valid JSON
  after stripping a markdown fence / leading prose (added after Paragon
  Feeds returned `"Here is the extracted JSON:\n\n\`\`\`json\n{...`,
  cut off mid-array at the 8192-token output cap — see §9.4). This is a
  parsing-robustness fix to the new module itself, not a fallback/retry
  mechanism; it does not call the model a second time.
- Not wired into `/v1/ingest/audited-financials`, not used by
  `reconciliation_engine.py`, does not touch
  `audited_financials_extractor.py`. The old Tesseract/regex/coordinate
  extractor is untouched and still the only thing live in production.

One-off validation runner (not production code):
`backend/scripts/validate_claude_audited_extraction.py`, output JSON +
summary in `backend/scripts/validate_claude_audited_extraction_output/`.

### 9.2 Real cost, all 6 files

Real `response.usage` from the actual API calls, Sonnet 4.6 pricing
($3.00 / 1M input, $15.00 / 1M output — no caching, no batching, single
cold call per file):

| File | Input tokens | Output tokens | Real cost |
|---|---:|---:|---:|
| Buildex (`buildex_financials_2025.pdf`, 24pp, text-layer) | 48,930 | 997 | $0.1617 |
| Kenlink (13pp, text-layer) | 25,019 | 776 | $0.0867 |
| Tawi Fresh (18pp, **scanned**) | 29,646 | 735 | $0.1000 |
| Paragon Feeds (17pp, text-layer) | 35,629 | 807 | $0.1190 |
| Maharaji (21pp, **scanned**) | 34,403 | 763 | $0.1147 |
| Tres Beau (19pp, **scanned**) | 31,219 | 656 | $0.1035 |
| **Total, 6 files** | 204,846 | 4,734 | **$0.6856** |

Average **$0.114/document**. No per-page or per-pixel surcharge was
visible in token usage between the text-layer and scanned files — native
vision does not appear to cost materially more for a scanned page than a
text-layer one at this page-count range.

**Operational finding, not an extraction-quality issue:** running the 6
files back-to-back hit the org's live rate limit —
`rate_limit_error: "This request would exceed your organization's rate
limit of 30,000 input tokens per minute"` — on Kenlink and Maharaji (both
attempts on the first pass). Re-run individually with ~75s pacing between
calls succeeded with no code changes. This is a tier/quota fact about the
org's current Anthropic account, not a defect in the extraction approach
itself; it matters for the next phase (any real batch-ingestion volume
will need either request pacing, the Batches API at 50% cost, or a tier
increase) — flagging it rather than building retry/backoff logic into the
extractor itself, which is out of scope for this round.

**Whether a "no text layer" failure category still exists:** no. All 3
scanned files (Tawi Fresh, Maharaji, Tres Beau — the same 3 that produced
**zero extracted fields, confidence 0** on the old Tesseract OCR path per
§6.3/§6.4) were read successfully via native vision with no special-casing
in the code at all — the PDF document content block is identical whether
the source PDF has a text layer or not. The only two real failure modes
hit in this session were (a) a transient JSON-formatting issue (one file,
fixed in the parser, not the model call) and (b) the org rate limit above
— neither is "Claude couldn't read the document."

### 9.3 Buildex vs. the trusted baseline

Per the brief, Buildex was additionally run through the existing
pdfplumber-coordinate extractor on the `fix/audited-financials-currency-ocr`
branch (commit `61bcd38`, both confirmed fixes from §6 applied) to get a
**100%-confidence, independently-trusted** baseline, then every field was
also checked against a direct read of the real 24-page PDF (not just
against the old extractor, since the brief is explicit the old extractor
is not ground truth on its own).

**Of ~50 fields, every income-statement, cash-flow, and most
balance-sheet figures matched the trusted baseline exactly** (turnover,
cost of sales, all four IS expense lines, PBT, tax, PAT, PPE, investments,
inventory, all 5 cash-flow lines, long-term loans, retained earnings,
share capital, trade payables, tax payable). Confirmed by direct PDF read
where the two methods diverged:

- **`auditor_name`**: old extractor always returns `null` by design (no
  attempt to find it). Claude returned `"FH Consulting LLP"` — confirmed
  correct by reading page 3 (`Auditor: FH Consulting LLP`) and page 6 (the
  signed audit opinion). A genuine field the old extractor cannot produce
  at all.
- **`cash_breakdown`**: old extractor merges `Equity` (KES 1,555,872) and
  `Equity Bank Account 2` (KES 310) into one `"Equity": 1,556,182` bucket
  (its code sums same-named keys) and silently drops the zero-balance
  `Tende pay` line (filters `amount > 0`). Claude's breakdown
  (`Absa, Equity, Equity Bank Account 2, KCB, Tende pay: 0, Zemo`)
  matches Note 11 line-for-line, confirmed against the real page —
  **more faithful to the source document's actual structure**, not less.
- **`other_income_cents`** (KES 22,109) and **`depreciation_expense_cents`**
  (KES 5,119,428): both `0` in the old extractor (its income-statement-only
  keyword search never finds either — depreciation is disclosed inside
  Note 7, *Administrative Costs*, not as its own P&L line; other income is
  inside Note 4, *Income*, folded into the combined `Turnover` figure on
  the P&L face). Claude found both, confirmed correct against Notes 4 and
  7. **But** this exposes a real schema ambiguity, not a Claude error:
  Note 4 shows `Turnover` (KES 372,062,277) = `Sales` (372,040,168) +
  `Other Income` (22,109) — i.e. `other_income_cents` is **already
  included inside** `turnover_cents`, not additive to it. Likewise Note 7
  shows `Administrative Costs` (KES 9,475,188) includes `Depreciation
  Expense` (5,119,428) as one of five line items — `depreciation_expense_cents`
  is **nested inside**, not a sibling of, `administrative_costs_cents`.
  Both numbers are individually correct; summing them as if they were
  independent categories would double-count. See §9.5 for why this
  recurs on every other file too.
- **`trade_receivables_cents`/`other_receivables_cents`**: old extractor's
  generic `"receivable"` keyword match grabs the combined Note 12 total
  (KES 5,636,548) into one field. Claude split it into `trade_receivables_cents`
  (Debtors Control Account, 3,989,164) + `other_receivables_cents`
  (Withholding Tax + VAT Claimable, 1,647,385) — confirmed against Note 12,
  correctly distinguishing real trade debtors from tax receivables that the
  old extractor mislabels as trade receivables.
- **`total_liabilities_cents`** (Claude only — old extractor has no such
  field): Claude reported KES 18,606,871, which equals **current
  liabilities only** (Trade & Other Payables + Tax Payable) — it omits
  Bank Loans (KES 20,327,175), which Claude itself correctly extracted
  into `long_term_loans_cents` in the very same response. Real total
  liabilities = 38,934,046. This is wrong, and recurs — see §9.5.

### 9.4 The other 5 files, against a direct read of each real PDF

Same method for all 5: read the actual PDF (via the Read tool's native
vision — including the 3 scanned files, where `pdfplumber.extract_text()`
returns nothing) page by page, and check every field Claude returned
against what the document actually states, not against the old
extractor's output (which, per §3/§6.3, produced **zero usable fields on
all 5 of these files**).

| File | Fields confirmed correct | Fields confirmed wrong/missing | Real cost |
|---|---|---|---:|
| **Kenlink** (management account, old extractor: `ValueError`, wrong-year column) | Turnover (KES 207,907,110) and cost of sales (169,950,672) **exactly right from Note 10** — the precise figures the old extractor's documented coordinate bug got wrong on this exact file (§6.3). Cash breakdown, receivables split, payables split, all P&L lines, all cash-flow lines: correct. ~40 of ~45 populated fields verified exactly correct. | `total_liabilities_cents` = current liabilities only (5,855,240), omits Long Term Loans (3,842,461); real total is 9,697,701. `intangible_assets_cents` left `null` despite Note 2 disclosing a separate Goodwill component (KES 2,000,000) bundled into `property_plant_equipment_cents` instead. | $0.0867 |
| **Tawi Fresh** (scanned; old OCR: confidence 0, zero fields) | Turnover, other income, all 4 expense categories, PBT/tax/PAT, PPE, intangible assets, cash, all 5 cash-flow lines, share capital, retained earnings, equity: all exactly correct against Notes 2-12. | **Material**: Note 12's `Deposits` (KES 4,353,151) and `VAT Recoverable` (84,889,027) — together KES 89.2M, ~74% of total receivables — captured in **no field at all** (not `trade_receivables`, `other_receivables`, or `prepayments`). **Misclassification**: `loan_breakdown` contains `"Standard Chartered Bank Kenya": 851,495`, but that figure is from Note 14, *Due to related parties* — not a loan note; this company discloses no actual loan facility anywhere (confirmed: `long_term_loans_cents`/`short_term_loans_cents` both correctly `null`). `other_payables_cents` (80,543,055) undershoots Note 13's real components (80,981,051) by ~KES 438,000, cause not identified. `total_liabilities_cents` left `null` despite being directly computable (current liabilities, 87,129,908 — no non-current liabilities this year). | $0.1000 |
| **Paragon Feeds** (old extractor: rejected the correct page by the anti-false-positive numeric gate, then partial fields on the wrong page) | Revenue, direct costs, PBT, tax, PAT, all balance-sheet lines including correctly-split receivables/payables, full cash-flow statement, 2/2 loan facilities (K.I.E. Loan + I&M Loan, both amounts and literal "Hire Purchase Loan" type correct): all confirmed exactly correct. | **Severe nesting**: `operating_costs_cents` (19,678,160) is the **entire** `Expenses` total on the P&L face (Production + Administration + Marketing + Finance combined) — not a sub-category — while `administrative_costs_cents` (11,248,592) and `finance_costs_cents` (1,303,392) are *also* populated with their own correct values, both already included inside that same 19,678,160. `staff_costs_cents` (4,436,752) = Admin's `Salaries` (4,389,876) + Production's `Wages` (46,876) combined across two different source categories. `equity_cents` (112,410,291) = the document's own `Total Equity` label, which itself includes the Hire Purchase Loan Account (13,377,526) — real equity (share capital + retained earnings + directors account) is 99,032,765. `total_liabilities_cents` (13,437,771) doesn't match current-liabilities-only (8,059,998), the true total (21,437,524), or any other combination of the file's own reported fields — an unexplained third failure mode for this field. `total_assets_cents`/`total_equity_and_liabilities_cents` (112,410,291) is this auditor's net-of-current-liabilities subtotal, not gross total assets (120,470,289). No field exists for the document's separately-disclosed `Biological Assets` (5,599,697). | $0.1190 |
| **Maharaji** (scanned; old OCR: confidence 0, zero fields) | Income, cost of sales, operating profit, operating expenses, finance cost, PBT, tax, PAT — every P&L figure exactly correct and fully reconciling. PPE, investments, inventory, receivables, cash, all balance-sheet totals, full cash-flow statement: all correct. `long_term_loans_cents` (52,370,917) correctly captures the combined Shareholders+Bank loan figure, split 2 ways in `loan_breakdown` summing back to the same total (internally consistent; the 2-way split itself — Shareholders Funds 49,670,842 / Bank Loans 2,700,075 — was **not independently re-verified** against Note 15, which was not read in this session). | `total_liabilities_cents` (16,194,027) = current liabilities only (Taxation + Accounts payables), omitting the Shareholders & Bank loans figure (52,370,917) that Claude itself extracted correctly elsewhere — same bug as Buildex/Kenlink. `equity_cents` (84,398,045) = the document's own `CAPITAL AND RESERVES` subtotal, which **includes** the Shareholders & Bank loans figure — same equity-contamination pattern as Paragon Feeds. Notes 13-20 were not read in this session; nulls on `cash_breakdown`/`other_*` fields are plausible but not independently confirmed against those pages. | $0.1147 |
| **Tres Beau** (scanned; old OCR: confirmed crash pre-fix, confidence 0 post-fix, zero fields) | Turnover, direct costs, PBT, tax, PAT, PPE, inventory, receivables split (Trade receivables + Rent deposit), cash, payables split, share capital, retained earnings, equity, full cash-flow statement, correctly-`null` loan fields (this company genuinely has none): all confirmed exactly correct. **`total_liabilities_cents` is correct here** (6,362,280) — the one file of six where it is — precisely because this company has zero long-term debt, which is the cleanest possible confirmation of the root cause below. | **Exact duplicate**: `operating_costs_cents` and `other_expenses_cents` hold the **literal identical value**, 555,930,600 (`Other operating expenses`/Establishment expenses) — the same figure placed in two schema fields at once. `depreciation_expense_cents` (572,424) and `staff_costs_cents` (5,054,500, `Employment Expenses`) are each nested inside `administrative_costs_cents`/`operating_costs_cents`, not siblings of them (confirmed via the Schedule of Direct Costs and Operating Expenditure: `Total administrative expenses` 10,022,311 = `Employment Expenses` 5,054,500 + `Other Administrative Expenses` 4,967,811). Naively summing turnover − cost_of_sales − administrative_costs − operating_costs − other_expenses − staff_costs − depreciation as independent fields gives a result far below the real PBT (11,603,354) because three of those fields double- or triple-count the same KES 5,054,500 / 572,424 / 555,930,600. Minor: `other_income_cents`/`finance_costs_cents`/`cash_at_start_cents` rendered as `0` for a real, explicitly-disclosed `"-"` (correct here, since these are genuinely nil this year — but inconsistent with `null` being used for the same dash elsewhere in this same file's own loan fields, and in every other file). | $0.1035 |

### 9.5 Two systematic, repeatable findings (not one-offs)

**Finding 1 — `total_liabilities_cents` cannot be trusted.** Checked in
all 6 files: wrong in 4 (Buildex, Kenlink, Maharaji — all three equal
*current liabilities only*, silently omitting long-term loans the model
itself correctly extracted elsewhere in the same response; Paragon Feeds
— a fourth, unexplained value matching neither current-liabilities-only
nor the true total), absent in 1 (Tawi Fresh, despite being directly
computable from fields already in the same response), and correct in
exactly 1 (Tres Beau) — and that one is correct *only* because that
company happens to have zero long-term debt, which is the cleanest
possible proof the field is really computing "current liabilities," not
"total liabilities," across the board. **Recommendation for the next
phase: do not read `total_liabilities_cents` from this extraction at all
— recompute it in code as the sum of whatever current-liability and
loan/borrowing fields the same response already populated correctly.**

**Finding 2 — expense-category and equity/totals fields reflect whatever
subtotal grouping the *source document* itself uses, including when that
grouping nests one category inside another or blurs equity with debt.**
This is not a Claude bug in the sense of misreading a number — every
individual figure cited above was independently confirmed against the
real document — it is a **schema-design mismatch**: the existing field
list (inherited from the old extractor, designed around Buildex's one
specific layout) implicitly assumes `operating_costs_cents`,
`administrative_costs_cents`, `staff_costs_cents`, `finance_costs_cents`,
and `depreciation_expense_cents` are mutually-exclusive siblings that sum
to total expenses, and that `equity_cents`/`total_assets_cents` are
strict accounting totals. Real documents frequently don't draw those
lines that way (depreciation nested inside admin costs in 5 of 6 files;
a "Total Equity" or "Capital and Reserves" label that includes a loan
balance in 2 of 6; a "net assets"-style bottom line standing in for
gross total assets in 3 of 6). Claude follows whichever the *document*
actually presents, faithfully — sometimes that's a clean, independent
category and the fields are safely additive (Maharaji, Kenlink mostly);
sometimes it isn't, and naively summing the fields downstream would
silently double-, triple-, or even quadruple-count the same money. This
is the one finding that would need a schema or prompt redesign before any
of this output is trusted for arithmetic — not in scope for this round,
but the single most important thing to fix before the next one.

### 9.6 Honest summary

This round's central question — does Claude's native-vision extraction
actually outperform the old Tesseract/regex/coordinate path on real
evidence — has a clear, evidenced **yes** on the dimension that mattered
most: it produced correct headline figures (turnover, cost of sales, PBT,
tax, PAT, cash position, and in 4 of 6 files a genuinely correct loan
facility breakdown with reference/type detail) on **all 6 files**,
including the one file where the old extractor's documented coordinate
bug produced a wrong number (Kenlink) and the three files where the old
OCR path produced literally nothing (Tawi Fresh, Maharaji, Tres Beau,
confidence 0 across the board, per §6.3). On Buildex specifically — the
one file with a 100%-confidence trusted baseline to check against —
every figure the old extractor got right, Claude also got right, plus
several fields (auditor name, a more granular cash breakdown, a correct
trade/other receivables split) the old extractor cannot produce at all by
design. The brief's central architectural hypothesis — that native
PDF/vision input sidesteps OCR's proximity-matching failure mode
entirely — is confirmed directly: zero "couldn't read the document"
failures across 3 scanned files that previously produced zero usable
fields each.

That is not the same as "ready to trust blindly." The systematic findings
in §9.5 are real, recur across multiple files, and are exactly the kind
of error that would corrupt a reconciliation calculation if this output
were wired in as-is: `total_liabilities_cents` is wrong far more often
than it's right, and several expense/equity totals reflect the source
document's own subtotal grouping rather than a strict, schema-consistent
accounting category, in ways that create real double-counting risk if
summed downstream. There is also one materially-sized, confirmed
omission (Tawi Fresh's KES 89.2M of unmapped VAT-recoverable/deposits)
and one confirmed misclassification (a related-party balance placed in
`loan_breakdown`). None of this was averaged away above — every number
in §9.3/§9.4 is cited against the real document, and every wrong or
missing figure is named exactly, per the standing instruction for this
investigation.

---

## 10. Fix — 21 June 2026, same day: `total_liabilities_cents` recomputed in code

*Per the append-only convention — §1-9 are not edited. Scope of this round
was this one fix only — see §10.4 for what was explicitly not touched.*

### 10.1 The fix

[`backend/v1/parsing/audited_financials_claude_extractor.py`](../backend/v1/parsing/audited_financials_claude_extractor.py):

- **Line 93 (old):** `"total_liabilities_cents": integer or null,` removed
  from `_SCHEMA_INSTRUCTIONS` — the model is no longer asked to produce
  this field at all.
- **Lines 137-169 (new, at time of writing — see note below on line
  drift):** a module-level comment explaining why, the
  `_LIABILITY_COMPONENT_FIELDS` tuple (`trade_payables_cents`,
  `tax_payable_cents`, `short_term_loans_cents`, `long_term_loans_cents`,
  `other_payables_cents`, `other_noncurrent_liabilities_cents` — the six
  granular liability fields the model does extract reliably, per §9.3/§9.4),
  and `_compute_total_liabilities_cents(data)`, which sums whichever of
  those six are non-`None` and returns `None` only if *all six* are
  `None` (i.e. it never fabricates a `0` where nothing was found).
- **`data["total_liabilities_cents"] = _compute_total_liabilities_cents(data)`**
  — called once, after the model's JSON response is parsed, before the
  function returns (line 301 at time of writing). This is the only call
  site; nothing else in the module changed. (Line numbers in this section
  shifted by +6 after §11's model-pinning comment was added above them in
  the same file — citing by function/variable name rather than re-chasing
  line numbers on every subsequent edit.)

The function deliberately does not try to detect or absorb liability
components that have no corresponding schema field (a bank overdraft shown
as its own balance-sheet line, a "due to related parties" balance, deferred
income under current liabilities) — see §10.3, both real files where this
exact gap shows up.

### 10.2 Re-validated against the real documents — all 6 files

Same standard as §9: real document, not the model's own prior output. The
6 real total-liabilities figures below were derived directly from the page
reads already on record in §9.3/§9.4 (current liabilities + long-term
loans, line by line, from the real balance sheets) — re-stated here for
the direct comparison. All 6 files were re-run through the fixed
extractor (fresh API calls, not cached from §9 — token counts and cost
differ slightly run-to-run, as expected from an unconstrained, non-zero-
temperature model call).

| File | Real total liabilities (ground truth) | Recomputed `total_liabilities_cents` | Match? | Real cost |
|---|---:|---:|:---:|---:|
| Buildex | KES 38,934,046 (Trade & Other Payables 15,724,351 + Tax Payable 2,882,520 + Bank Loans 20,327,175) | KES 38,934,046 | ✅ exact | $0.1615 |
| Kenlink | KES 9,697,701 (Overdraft 1,287,991 + Accounts payable 2,480,519 + Short Term Loan 2,086,730 + Long Term Loans 3,842,461) | KES 8,409,710 | ❌ short by 1,287,991 | $0.0852 |
| Tawi Fresh | KES 87,129,908 (Trade & Other Payables 89,940,166 + Related parties 851,495 + Deferred Income −3,668,698 + Current tax 6,945) | KES 89,106,117 | ❌ off by 1,976,209 (net) | $0.0997 |
| Paragon Feeds | KES 21,437,524 (Trade and other payables 986,553 + Taxation 7,073,445 + Hire Purchase Loan 13,377,526) | KES 21,437,524 | ✅ exact | $0.1184 |
| Maharaji | KES 68,564,944 (Taxation 5,989,379 + Accounts payables 10,204,648 + Shareholders & Bank loans 52,370,917) | KES 68,564,944 | ✅ exact | $0.1144 |
| Tres Beau | KES 6,362,280 (Tax Payable 2,900,839 + Trade and other payables 3,461,441 + Loan 0) | KES 6,362,280 | ✅ exact | $0.1032 |

**4 of 6 now exact**, fixing Buildex, Paragon Feeds, and Maharaji outright
(all three previously wrong by exactly the omitted long-term-loan amount —
the bug this fix targeted) and leaving Tres Beau correct as it already was.
Field-level citation for the 4 exact matches (from the fresh run's own
JSON output, not carried over from §9):

- Buildex: `trade_payables_cents` 1,572,435,100 + `tax_payable_cents`
  288,252,000 + `long_term_loans_cents` 2,032,717,500 = 3,893,404,600 cents.
- Paragon Feeds: `trade_payables_cents` 88,655,300 + `tax_payable_cents`
  707,344,500 + `other_payables_cents` 10,000,000 + `long_term_loans_cents`
  1,337,752,600 = 2,143,752,400 cents.
- Maharaji: `trade_payables_cents` 1,020,464,800 + `tax_payable_cents`
  598,937,900 + `long_term_loans_cents` 5,237,091,700 = 6,856,494,400 cents.
- Tres Beau: `trade_payables_cents` 283,544,100 + `tax_payable_cents`
  290,083,900 + `other_payables_cents` 62,600,000 = 636,228,000 cents.

### 10.3 The 2 of 6 that are *still* wrong, and exactly why — this is the
"flag rather than guess" case the brief anticipated

Both remaining gaps are real balance-sheet liability lines that have **no
corresponding field anywhere in the schema** — not a re-emergence of the
omitted-long-term-loan bug this fix targeted, and not something the fix
could have closed without adding a new field, which is schema redesign,
out of scope for this round.

- **Kenlink — short by exactly KES 1,287,991, the Overdraft.** Kenlink's
  balance sheet (§9.4 read, page 7) discloses the bank overdraft **twice**:
  once netted inside Note 4 (`Cash and Bank Balances`, where it already
  shows up correctly as the `"Overdraft": -128799100` cents component of
  `cash_breakdown`), and **again as its own line under Current
  Liabilities** (`Overdraft: 1,287,991`, separate from `Cash and Bank
  balances: 601,095` under Current Assets). The schema has no
  `overdraft_cents`-style liability field, so the model — correctly, given
  the schema it was given — only ever places the figure in
  `cash_breakdown`. The recomputed total (8,409,710 = `trade_payables_cents`
  2,476,020 + `short_term_loans_cents` 2,086,730 + `long_term_loans_cents`
  3,842,461 + `other_payables_cents` 4,499) is real and internally
  consistent; it is short of the true 9,697,701 by precisely the
  double-disclosed overdraft amount.
- **Tawi Fresh — off by KES 1,976,209 (net), from two independent,
  partially-offsetting causes.** (1) `other_payables_cents` this run
  (80,140,056) undershoots Note 13's own four-component sum (Other
  liabilities 21,914,940 + Prov-performance bonds 7,025,880 + Accrued
  expenses 31,841,634 + Employee ESOP 20,198,597 = 80,981,051) by ~840,995
  — the same kind of small, unexplained shortfall on this field already
  flagged in §9.4 on a *prior* run (there it was ~438,000; the two figures
  differ because each is a fresh, independent API call — see §10.1's note
  on run-to-run variance — but the field undershoots its own note total
  both times). (2) Two real current-liability lines on the face of the
  balance sheet, `Related parties: 851,495` and `Deferred Income:
  (3,668,698)`, have no schema field at all — same category of gap as
  Kenlink's overdraft. These two causes partially cancel (the
  under-mapped `other_payables_cents` pulls the total down; the
  unmapped `Related parties`/`Deferred Income` pull it, net, in the
  other direction by a different amount), landing the final number close
  to but not at the real total, for reasons that are coincidental, not
  causally connected.

Both are reported here exactly as found, not smoothed over: the fix in
§10.1 closes the bug it was built for (3 of 3 real long-term-loan omissions
now exact), and is not capable of closing a gap that exists because the
schema itself has no field for the missing line — which is precisely why
this section flags rather than guesses, per the brief.

### 10.4 Explicitly deferred, not touched in this round

Per the brief's scope instruction, none of the following were modified —
they are confirm-gate design questions a human should resolve (which
category a "Shareholders Loan" or a "Related parties" balance belongs in,
whether to add new schema fields for overdrafts/deferred income/VAT
recoverable, how to disambiguate nested vs. sibling expense categories),
not extraction bugs with a code fix:

- **§9.5 Finding 2 — expense-category and equity nesting** (depreciation
  inside administrative costs, `operating_costs_cents` sometimes holding a
  full combined total rather than one category, `equity_cents` sometimes
  including a loan balance the source document's own subtotal groups with
  equity). Untouched.
- **Tawi Fresh's KES 89.2M unmapped receivables** (`Deposits` +
  `VAT Recoverable`, §9.4). Untouched — and structurally the same kind of
  gap as the two liability gaps in §10.3 above (a real disclosed line with
  no schema field), now confirmed to recur on both sides of the balance
  sheet, not just receivables.
- **The Tawi Fresh loan misclassification** (a `Due to related parties`
  balance placed in `loan_breakdown`, §9.4). Untouched.

---

## 11. Addendum — 22 June 2026: model pinning confirmed, reconciliation
engine's expense field investigated

*Per the append-only convention — §1-10 are not edited.*

### 11.1 Model pinning — already satisfied, now documented

Checked [`audited_financials_claude_extractor.py`](../backend/v1/parsing/audited_financials_claude_extractor.py)
line by line for any per-file or per-format model selection: there is none.
`MODEL = "claude-sonnet-4-6"` (line 40, after this addendum's edit) is a
single module-level constant; the only call site that uses it is the one
`client.messages.create(model=MODEL, ...)` in
`extract_audited_financials_claude()` (lines 264-265). `_build_content_block()`
branches on file extension (PDF → `document` block, image → `image` block,
CSV/XLSX → `text` block, lines 206-229) but never touches `MODEL` — content
*shape* varies by format, the model does not. All 6 files in §9 and both
re-runs in §10 used the identical model for this reason; there was nothing
to fix. Added a comment at lines 34-39 making the invariant explicit
(`"do not branch on file type/extension to pick a different model"`) so a
future change doesn't introduce per-format switching without anyone
noticing — no other code change.

### 11.2 Does `reconciliation_engine.py`'s Expenses row have the same bug?

**Short answer: it sums granular fields, the same way `total_liabilities_cents`
did — but the specific bug (nested/double-counted categories) does not
currently reach it, because of which extractor's output it reads. It would
become a real risk the moment the Claude extractor is wired into production,
which it isn't yet.**

The Expenses row of the 4-point reconciliation check (Cash Position,
Revenue, **Expense**, Loan Activity —
[`reconciliation_engine.py:149-456`](../backend/v1/analysis/reconciliation_engine.py))
is `calculate_expense_reconciliation()`,
[lines 353-396](../backend/v1/analysis/reconciliation_engine.py#L353-L396).
It does **not** read a single document-stated "total expenses" figure —
there is no such column in `pds_audited_financials` (confirmed against the
table definition in §migrations) — it sums five fields:

```python
cost_fields = [
    "cost_of_sales_cents", "operating_costs_cents", "administrative_costs_cents",
    "staff_costs_cents", "finance_costs_cents",
]
declared_expenses_cents = sum(int(af.get(f) or 0) for f in cost_fields)
```

(`af` comes from `_get_audited_financials()`,
[lines 55-74](../backend/v1/analysis/reconciliation_engine.py#L55-L74),
which selects `*` from `pds_audited_financials` — i.e. whatever the
*production ingestion path* most recently wrote there.)

`depreciation_expense_cents` and `other_income_cents` are deliberately
excluded from the sum, and the function's own `explanation` field says why:
*"Gap explained by: non-cash expenses (depreciation, amortisation), accrued
payables, inventory build, and opening accruals"* — the design expects
declared (accrual) expenses to exceed bank (cash) outflows by roughly the
depreciation amount. That exclusion is intentional and correct, not part of
this finding.

**Why the nesting bug from §9.5 doesn't reach this table today:**
`pds_audited_financials` is currently populated exclusively by the
*existing* pdfplumber-coordinate extractor — per §8/§9.1, the new Claude
extractor this investigation built is explicitly **not** wired into
`/v1/ingest/audited-financials`, and writes to no table at all. So the
question becomes: is the *old* extractor's version of these five fields
vulnerable to the same nesting/double-counting failure mode? Checked
[`audited_financials_extractor.py`'s `_extract_income_statement()`](../parity-ingestion/app/extractors/audited_financials_extractor.py#L171-L218):
its `_IS_MAP` (line 144) is walked **once per row of the income-statement
page only** (never notes pages), and the loop
(`if field not in data and _match_label(...)`, lines 193-194) lets each
field be set by **at most one matching row**, first match wins. Structurally,
this cannot produce a value that absorbs multiple categories' worth of
figures into one field the way the Claude extractor did on Paragon Feeds
(§9.4) — it either finds one clean row per category, or it doesn't find the
field at all and raises `ValueError` on the `required` check (line 209),
aborting the whole extraction (the brittleness already documented in §3/§6,
a different failure mode from this one). So: **no, the specific bug does
not currently manifest in `calculate_expense_reconciliation()`**, because
the data source it reads is structurally incapable of producing it.

**This is a landmine for later, not a bug now.** The moment the Claude
extractor's output is wired into the same `pds_audited_financials` table —
explicitly future work, called out as out of scope in both this
investigation's brief and §9.1 — this exact `cost_fields` sum would inherit
§9.5 Finding 2 directly: on a Paragon-Feeds-shaped document,
`operating_costs_cents` held the *entire* combined expense total
(production + administration + marketing + finance, §9.4), so summing all
five `cost_fields` against data shaped like that would multiply-count the
same money and hand `calculate_expense_reconciliation()` a
`declared_expenses_cents` several times too large — which would surface
downstream as a fabricated `SIGNIFICANT_VARIANCE` against bank outflows, a
false alarm a human analyst would have to chase. The fix for that, when the
wiring work happens, belongs in the extraction/schema layer (the same
confirm-gate design work already deferred in §9.5/§10.4) — not as a patch
to `reconciliation_engine.py`'s summing logic, which is doing exactly what
it should with non-overlapping inputs. No code change made here; this
paragraph is the flag for whoever does that wiring work next.
