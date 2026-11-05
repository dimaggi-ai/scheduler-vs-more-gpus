# Synthetic fleet local evidence

Candidate base: `176b7f5a6fb9f380d0d3cad2d2893a1e4805036a`. New fleet module only; parent lifecycle/physics/planner/runtime unchanged. Inputs are authored synthetic fixtures, not measured hazards.

`python3 -m unittest capacity.orbital.test_fleet capacity.orbital.test_diligence -q`: 39 tests passed in 0.271 s (seven new fleet test methods plus existing diligence tests). Checks include half-life arithmetic, fractional commissioning/retirement interval integration, zero-hazard equivalence to existing lifecycle, integer-count expectation conservation, annual projection equality, fixed-input hazard/delay monotonicity, malformed/oversized inputs, projection limits, no mutation, deterministic replay and actual CLI success/refusal/corrected retry/overwrite preservation.

`evaluate.json` and `compare.json` are fresh CLI outputs from the committed synthetic example requests. Each fleet result includes input/source digests. They are expected-capacity sensitivity evidence, not hardware, flight, finance or operational qualification. The CLI refuses invalid input, permits corrected input at a fresh path, and never overwrites an existing receipt.

`scaling.json` records one observed local run each for 1×3, 50×20 and 200×100 cohort-year dimensions. The largest produced 20,000 rows in approximately 0.654 s with 19.3 MB peak Python-traced allocations. This does not establish a runtime/SLO guarantee, total process memory or concurrency behavior. Work/output scale with cohorts×years; cohort-year economics projection remains capped by the existing calculator's 200-row contract.

The new Ubuntu/macOS workflow runs fleet and existing diligence tests without installing dependencies. Hosted execution, independent Claude review and designated acceptance remain pending. Local test counts are not release acceptance. No production controls, network qualification or new failure calibration is claimed.

Full composed modules plus bundle and fleet: **138 tests passed in 7.362 s**. Existing committed bundle fixture remained valid, confirming this additive module did not alter its source-bound parent graph.
