-- Parameter 1: actual artifact; parameter 2: immutable plan.
-- Loss buckets telescope to productive capacity. Demand error is reported
-- separately, because it is not independent of reservation/idle losses.
WITH joined AS (
    SELECT p.hour, a.hour IS NULL AS missing,
      p.nominal_gpu_h pn, a.nominal_gpu_h an,
      p.envelope_gpu_h pe, a.envelope_gpu_h ae,
      p.inf_alloc_gpu_h pi, a.inf_alloc_gpu_h ai,
      p.train_alloc_gpu_h pt, a.train_alloc_gpu_h ata,
      p.inf_productive_gpu_h pip, a.inf_productive_gpu_h aip,
      p.train_productive_gpu_h ptp, a.train_productive_gpu_h atp,
      p.inf_demand_gpu_h pd, a.inf_demand_gpu_h ad,
      p.rate_usd_per_allocated_gpu_h pr, a.rate_usd_per_allocated_gpu_h ar,
      a.work_lost_gpu_h lost, p.work_lost_gpu_h plost
    FROM plans p LEFT JOIN actuals a ON a.plan_id=p.plan_id AND a.hour=p.hour AND a.actual_id=?
    WHERE p.plan_id=?
)
SELECT hour, missing,
  pd AS forecast_demand_gpu_h, ad AS actual_demand_gpu_h,
  ad-pd AS demand_error_gpu_h,
  CASE WHEN missing THEN NULL ELSE greatest(ad-aip, 0) END AS unmet_inference_gpu_h,
  pip+ptp AS planned_productive_gpu_h, aip+atp AS actual_productive_gpu_h,
  aip+atp-pip-ptp AS productive_delta_gpu_h,
  an-pn AS nominal_effect_gpu_h,
  -((an-ae)-(pn-pe)) AS availability_effect_gpu_h,
  -((ae-ai-ata)-(pe-pi-pt)) AS idle_effect_gpu_h,
  -((ai-aip)-(pi-pip)) AS reservation_effect_gpu_h,
  -((ata-atp)-(pt-ptp)) AS training_loss_effect_gpu_h,
  lost AS work_reversed_gpu_h,
  (pi+pt)*pr AS planned_cost_usd, (ai+ata)*ar AS actual_cost_usd,
  (ai+ata)*ar-(pi+pt)*pr AS cost_delta_usd,
  ((ai+ata)-(pi+pt))*pr AS allocation_cost_effect_usd,
  (ai+ata)*(ar-pr) AS rate_cost_effect_usd,
  greatest(abs(an-pn),abs(ae-pe),abs(ai-pi),abs(ata-pt),abs(aip-pip),abs(atp-ptp),abs(ad-pd),abs(ar-pr),abs(lost-plost)) AS max_absolute_change
FROM joined ORDER BY hour;
