# PAR-86 — Cold-Start Rehydration False States: Investigation & Fix

## Summary

A deal page reload could show an analyst three different false states — an
active "first-time setup" button, a persistent "No analysis run yet", or a
"0 transactions / all stages QUEUED" table — on a deal that had already
completed analysis. All three were traced to one root design flaw: the
page's `analysisState` used the same value (`'idle'`) to mean both "haven't
checked the backend yet" and "checked, and confirmed no analysis exists".
Fixed by introducing a genuinely distinct `'checking'` state, a module-level
shared-promise cache to close a real double-fetch race, and per-surface UI
fixes so nothing renders an actionable or negative claim while the real
answer is still in flight.

Shipped as three PRs: [#99](../../pull/99) (the initial, narrower fix),
[#101](../../pull/101) (the full root-cause fix), and
[#102](../../pull/102) (a follow-up gap found during validation).

## Timeline

### 1. Original symptom (this morning)

Opening or reloading a deal whose analysis had already completed
intermittently showed the Analytics/Documents/Parity Review tabs as if the
deal had never been analysed — an "Initialise analysis pipeline" CTA active
on a deal with 12,851 processed transactions, a "No analysis run yet" empty
state, or a transient "0 transactions" table.

### 2. First fix (PR #99) — and why it didn't fully catch it

The existing rehydration effect (from an earlier PR #62) called
`getLatestAnalysis()` → `exportSnapshot()` → `listDealTransactions()` in
sequence on mount. PR #99 correctly identified that its `catch` block
conflated a **thrown error** (network blip, cold start, transient 4xx/5xx)
with **genuinely no analysis exists**, both silently falling back to the
same "idle" render. The fix distinguished those two outcomes and added a
retryable error state for the thrown case.

**This did not fully fix the bug**, because none of the three false states
actually involved a thrown error — the backend call always returned `200`.
The real mechanism was something else entirely (see below), and validating
PR #99 in an **already-logged-in, warm browser session** never exercised
the actual failure path. See "Lesson" below — this is the important part
to retain, not just that this specific bug is now fixed.

### 3. Real reproduction and root cause (PR #101)

Live incognito testing — genuine cold session, log in from scratch, click
straight into an already-analyzed deal as the very first action — reliably
reproduced the false states PR #99 missed. Root-caused using **actual
Cloud Run production request logs** for the `parity-backend` service (not
just code reading): every logged `/analysis/latest` call for the affected
deals returned `200`, but a consistent, timing-dependent pattern showed up
— **two near-simultaneous calls to the same endpoint for the same deal**,
per page load. The frontend has only one call site for that endpoint, so
this was a genuine double-invocation of the page's mount-time effects —
most likely tied to how Next.js renders a `useSearchParams()`-consuming
component wrapped in `<Suspense>` (required for that hook) on a cold,
uncached navigation. A warm, already-loaded session's client-side
transitions never exercise this path, which is exactly why it was missed
before.

Three distinct bugs were found and fixed:

1. **Documents tab CTA never checked analysis state at all.**
   `components/deal-tabs/DocumentsTab.tsx`'s "Initialise analysis
   pipeline" button's enabled/label logic depended only on document-queue
   readiness — completely independent of the rehydration effect. Fixed by
   disabling it during `'checking'` and relabeling it "Add documents &
   re-run analysis" once analysis is already done.

2. **`'idle'` meant two different things.** The state used as the true
   initial value (before any backend check) was the same value used to
   mean "conclusively confirmed no analysis". Any code path that left the
   check unresolved rendered identically to a definitive negative. Fixed
   by adding a genuinely distinct `'checking'` state (see
   `components/deal-tabs/types.ts`); `'idle'` now only means conclusively
   confirmed.

3. **Render-order flash ("0 transactions / all QUEUED").** `run` (derived
   from `exportData`) could become truthy one render tick before
   `analysisState` flipped to `'done'` and before `rawTransactions` was
   populated, because the sequential `await`s in the old effect set state
   across multiple ticks. Fixed as a side effect of moving the fetch
   sequence into a single resolved result object and applying all the
   resulting `set*` calls back-to-back with no intervening `await` (React
   batches these into one render).

**Mechanism fix**: rehydration work moved from a component-local `useRef`
guard to a **module-scoped promise cache keyed by `dealId`**
(`app/v1/deal/page.tsx`, `rehydrationPromises` / `getOrFetchRehydration`).
A component-local ref cannot protect against a genuine double-mount (a
fresh mount gets a fresh ref); the module-level cache means every mount —
however many there are — shares the one real fetch chain instead of
racing separate ones, and each mount applies the shared result to its own
local state once resolved.

**Bonus, same effort (PAR-91)**: the app now lands on the Analysis tab by
default once a deal's existing analysis is confirmed, instead of Documents
— unless the user has already navigated somewhere themselves, tracked via
`userSelectedTabRef`.

### 4. Follow-up gap found during validation (PR #102)

Structured validation of PR #101 (see "Validation" below) surfaced one
more real gap: `components/deal-tabs/DealSidebar.tsx` renders its own,
separate tab list (the left rail) with its own `onClick` calling
`setActiveTab` directly — never marking `userSelectedTabRef`, unlike the
horizontal tab row and the various `onGoTo*` callbacks in `page.tsx`,
which were all correctly wrapped in PR #101. Reproduced live: click
"Review Queue" in the left sidebar while a deal's background check is
still resolving — once it resolves, the auto-land-on-Analysis effect
fired and overrode the user's manual navigation anyway, since it never
saw evidence of a deliberate choice. Fixed by wrapping the `setActiveTab`
passed into `<DealSidebar>` at its single call site, rather than touching
`DealSidebar.tsx` itself.

## Validation

- Cross-deal cache isolation: two tabs, two different deals, loaded
  concurrently — each resolved with its own correct, distinct data, no
  contamination (expected: each browser tab is a separate JS module
  instance, so the cache literally cannot be shared across tabs).
- Client-side deal-to-deal navigation (same tab, no full reload, via the
  `/deals` list → `router.push`): confirmed the target deal's state
  resets and resolves fresh, not reusing the previous deal's cached
  state — verified across two independent deal pairs.
- Manual-navigation-respected check: clicked into Review Queue and,
  separately, Parity Review via the **left sidebar** specifically (the
  surface PR #102 fixed) on deals still mid-resolution — confirmed the
  page stays exactly where the user navigated once the background check
  completes, for both.
- Genuine cold incognito session (fresh login, first action = click into
  an already-analyzed deal), repeated across both real test deals
  multiple times: no instance of any of the three original false states
  observed. Confirmed on both `parity-sme-staging.vercel.app` and
  `demo.paritytunnel.com` (identical bundle hash, same backend).

## Lesson: how this class of bug needs to be tested

**The earlier "confirmed working" check on PR #99 was run in an
already-logged-in, warm browser session — not a genuine cold start.**
That is the specific reason it missed all three bugs fixed in PR #101:
warm client-side transitions within an already-loaded app never exercise
the double-mount path that only shows up on a cold, uncached navigation
into a `useSearchParams()` + `<Suspense>` page.

For any future bug in this class (client-side state that's supposed to
reflect backend truth on page load), validation must specifically include:
a **genuine fresh browser context** (incognito/private window or a fully
new session — not just "reload the tab"), **login from scratch**, and
the suspect action as the **very first thing done in that session** — not
after any other navigation has already happened in the same tab/session.
A warm-session check, however thorough, is not sufficient evidence that
this class of bug is fixed.

## Known follow-up (not yet actioned)

Deals whose snapshot was exported/cached **before** the PAR-89-adjacent
join-key fix (PR #98, from earlier the same night) will still show the
pre-fix "100% unclassified" bug until they're re-exported — `export()`
short-circuits to the cached snapshot when nothing has changed, and that
particular fix did not bump `CONFIG_VERSION`. Confirmed live: the demo
account's other seeded deals (e.g. "USA", `856c4bd5-...`) still show
`Unclassified: 12,851 transactions` (100%) despite the fix being live,
because their snapshots predate it. Only the two deals explicitly
re-tested tonight (`e21404a2-...`, `2a619980-...`) have fresh,
post-fix snapshots. Needs a decision: bulk re-export the other demo
deals, or scope the demo to the two already-verified ones.

## Addendum — Export Snapshot button: premature "complete" status (PR #104)

Separate bug, same session, different code path (Snapshot tab export flow,
not the cold-start rehydration mount effects above — no overlap, safe to
land independently).

**Symptom (reported by user):** clicking "Save & Export PDF" on the
Snapshot tab immediately showed a "complete" state and updated "Last
exported" timestamp, but the PDF file itself landed later. Because the UI
already claimed completion, impatient users clicked again — 2-3 times —
and files arrived in a batch roughly matching the click count.

**Root cause:** `handleReExport` (`app/v1/deal/page.tsx`) calls two
independent backend endpoints in sequence:
1. `POST /deals/{id}/export` — writes/returns the snapshot. Cheap on
   repeat calls: `export()` (`backend/v1/api.py`) short-circuits to the
   cached snapshot when no docs/overrides changed since the last export.
2. `GET /deals/{id}/report` — renders HTML and runs weasyprint to
   generate the PDF from scratch, **every call, with no caching**.

The old code set `analysisState` to `'done'` and stamped
`lastExportedAt` right after step 1 resolved — before step 2 (the actual
PDF) had even started. That both re-enabled the button and displayed
"Last exported" ahead of the real deliverable. Because the button
re-enabled early, each impatient re-click ran the full flow again,
including a genuinely separate, redundant, non-cached weasyprint PDF
render for step 2 — real wasted backend work, not just a display glitch.

**Fix:** keep `analysisState` at `'exporting'` ("Generating PDF…", button
disabled) for the entire flow, and only stamp `lastExportedAt` / flip to
`'done'` after the PDF blob is actually in hand. Added an explicit
in-flight guard (`if (analysisState === 'exporting') return;`) so a click
during an active job for the deal is a no-op rather than starting a
second job.

**Validation status:** `tsc --noEmit` is clean on the touched file. Live
click-through validation on the two real deals
(`2a619980-0f74-4d9f-bb3b-648ab1eb9c95`,
`e21404a2-6bef-4484-a1cb-3fedea4bb2d6`) against the PR's preview
deployment was **attempted but blocked** — both the per-PR preview URL and
the `parity-sme-staging.vercel.app` alias returned a per-action browser
approval wall that could not be cleared in this session. This is
**unvalidated in a live browser** and needs manual confirmation before
being considered closed, per the "Lesson" section above: code-level
tracing and a clean type-check are not a substitute for exercising the
actual click path.

PR: [#104](../../pull/104).
