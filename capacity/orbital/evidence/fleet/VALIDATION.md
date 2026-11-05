# Synthetic fleet local evidence

Candidate base: `176b7f5a6fb9f380d0d3cad2d2893a1e4805036a`. New fleet module only; parent lifecycle/physics/planner/runtime unchanged. Inputs are authored synthetic fixtures, not measured hazards.

`python3 -m unittest capacity.orbital.test_fleet capacity.orbital.test_diligence -q`: 39 tests passed in 0.271 s (seven new fleet test methods plus existing diligence tests). Checks include half-life arithmetic, fractional commissioning/retirement interval integration, zero-hazard equivalence to existing lifecycle, integer-count expectation conservation, annual projection equality, fixed-input hazard/delay monotonicity, malformed/oversized inputs, projection limits, no mutation, deterministic replay and actual CLI success/refusal/corrected retry/overwrite preservation.

`evaluate.json` and `compare.json` are fresh CLI outputs from the committed synthetic example requests. Each fleet result includes input/source digests. They are expected-capacity sensitivity evidence, not hardware, flight, finance or operational qualification. The CLI refuses invalid input, permits corrected input at a fresh path, and never overwrites an existing receipt.

`scaling.json` records one observed local run each for 1×3, 50×20 and 200×100 cohort-year dimensions. The largest produced 20,000 rows in approximately 0.654 s with 19.3 MB peak Python-traced allocations. This does not establish a runtime/SLO guarantee, total process memory or concurrency behavior. Work/output scale with cohorts×years; cohort-year economics projection remains capped by the existing calculator's 200-row contract.

The new Ubuntu/macOS workflow runs fleet and existing diligence tests without installing dependencies. Hosted execution, independent Claude review and designated acceptance remain pending. Local test counts are not release acceptance. No production controls, network qualification or new failure calibration is claimed.

Full composed modules plus bundle and fleet: **138 tests passed in 7.362 s**. Existing committed bundle fixture remained valid, confirming this additive module did not alter its source-bound parent graph.

## Near-zero hazard correction

At79f9685, hazard5e-324 over[0.25,1] with commissioning0.25 returned1.0 node-year per node instead of0.75. Baseline failure is retained in nearzero-baseline.json. The correction uses duration × normalized exprel(hazard × duration), with the continuous value1 when the product rounds to zero, retaining the exponential age factor and genuine output-underflow refusal. Regression covers13 hazard levels (zero, subnormal, log-spaced and ordinary), a380-digit Decimal exponential oracle, partial commissioning and economics projection agreement. Corrected source-bound evaluate/compare receipts are regenerated; earlier scaling timings remain dated to the prior implementation.

Corrected validation:40 fleet+diligence tests passed in0.284s;139 composed tests passed in4.999s. These are local checks, not independent acceptance.

## Claude189 F2–F8 correction

An optional independently supplied baseline digest now rejects paired baseline drift; unpinned pairs remain explicitly unbound sensitivity calculations. Strictly validated numeric equivalents compare equally. Compare and economics receipts cover their complete inputs, source and outputs, including deltas and supplied economic template. Economics maps each projected row back to cohort/year and records both provenance sources; its availability assumptions explicitly describe derived survival rather than inherited constant-only language. Dispatch refusals preserve validated request identity and available hashes. Projection means beyond rounding tolerance refuse instead of being silently clamped.

42 fleet/diligence tests passed in 0.302 s; 141 composed tests passed in 5.049 s. New regression cases cover pinned paired drift, equivalent numbers, receipt reconstruction, complete template binding, projection mapping/provenance, assumption correctness and refusal identity. Fresh CLI processes regenerated evaluate/compare receipts and added the economics example/receipt. Parent modules remain unchanged.

Documentation now distinguishes stochastic unmet demand, possible delay/shortfall tradeoffs, the 40,000-row comparison bound and high-hazard numerical refusal. The historical scaling measurement is retained; a committed benchmark generator (F9 nit) remains deferred. No physical hazard calibration, investment suitability or automatic baseline promotion is inferred.
