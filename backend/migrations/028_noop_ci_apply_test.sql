-- Migration 028: deliberate no-op, exists only to test the new
-- apply-backend-migrations CI workflow (PAR-142) end-to-end before any real
-- schema change is trusted to it. Touches nothing.
select 1;
