-- Migration 039: backfill pds_audited_financials.total_expenses_cents where it
-- was populated with a post-Gross-Profit "total operating expenses" subtotal
-- instead of true total expenses (PAR-217).
--
-- Root cause (see PAR-217, PAR-207's comment thread for the full trace): the
-- audited-financials extraction prompt (backend/v1/parsing/
-- audited_financials_claude_extractor.py, fixed in this same PR) instructed the
-- model to treat "Total expenses" and "Total operating expenses" as
-- interchangeable. On any income statement with a Gross Profit line, they are
-- not -- "Total operating expenses" excludes Cost of Sales.
--
-- Detection rule used here is mechanical and provable, not a per-deal guess:
-- Cost of Sales is always a subset of true total expenses, so a stored
-- total_expenses_cents value that is LESS than cost_of_sales_cents alone
-- cannot possibly be a true, all-inclusive total -- it is provably wrong,
-- regardless of which specific document produced it. This does not attempt to
-- catch every possible instance of the underlying ambiguity (a total that
-- happens to still exceed cost_of_sales_cents in magnitude cannot be
-- mechanically distinguished from a genuinely correct one without reading the
-- source document), only the subset that is unambiguously provable from the
-- stored data alone.
--
-- The fix is to null the bad value, not attempt to compute a "corrected" one:
-- reconciliation_engine.py's calculate_expense_reconciliation() already has a
-- safe, already-verified-correct fallback (sums cost_of_sales_cents +
-- operating_costs_cents + administrative_costs_cents + staff_costs_cents +
-- finance_costs_cents) that runs automatically whenever total_expenses_cents
-- is null. Nulling the bad value is sufficient to route every affected deal
-- back onto that already-correct path -- no re-extraction or manual
-- recomputation needed.
--
-- Confirmed via this exact query against both live environments before writing
-- this migration: 0 rows affected on prod (ifcdbhbuucmjgtjkluna -- no deal
-- there currently has total_expenses_cents populated at all), 12 rows affected
-- on staging (kstuensfekanfberjubz) -- all sharing one of two duplicated
-- source documents across multiple test/demo deals, not 12 independent real
-- customer statements.
update pds_audited_financials
set total_expenses_cents = null
where total_expenses_cents is not null
  and cost_of_sales_cents is not null
  and total_expenses_cents < cost_of_sales_cents;
