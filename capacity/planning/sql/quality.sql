-- Relational completeness is distinct from per-record schema validity.
SELECT
  (SELECT count(*) FROM plans WHERE plan_id=?) AS expected_hours,
  (SELECT count(*) FROM actuals WHERE actual_id=?) AS observed_hours,
  (SELECT count(*) FROM actuals a WHERE a.actual_id=? AND NOT EXISTS
      (SELECT 1 FROM plans p WHERE p.plan_id=a.plan_id AND p.hour=a.hour)) AS orphan_hours;
