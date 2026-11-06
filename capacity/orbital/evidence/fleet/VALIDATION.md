# Synthetic fleet local evidence

Candidate base: `176b7f5a6fb9f380d0d3cad2d2893a1e4805036a`. New fleet module only; parent lifecycle/physics/planner/runtime unchanged. Inputs are authored synthetic fixtures, not measured hazards.

`python3 -m unittest capacity.orbital.test_fleet capacity.orbital.test_diligence -q`: 39 tests passed in 0.271 s (seven new fleet test methods plus existing diligence tests). Checks include half-life arithmetic, fractional commissioning/retirement interval integration, zero-hazard equivalence to existing lifecycle, integer-count expectation conservation, annual projection equality, fixed-input hazard/delay monotonicity, malformed/oversized inputs, projection limits, no mutation, deterministic replay and actual CLI success/refusal/corrected retry/overwrite preservation.

`evaluate.json` and `compare.json` are fresh CLI outputs from the committed synthetic example requests. Each fleet result includes input/source digests. They are expected-capacity sensitivity evidence, not hardware, flight, finance or operational qualification. The CLI refuses invalid input, permits corrected input at a fresh path, and never overwrites an existing receipt.

`scaling.json` records one observed local run each for 1×3, 50×20 and 200×100 cohort-year dimensions. The largest produced 20,000 rows in approximately 0.654 s with 19.3 MB peak Python-traced allocations. This does not establish a runtime/SLO guarantee, total process memory or concurrency behavior. Work/output scale with cohorts×years; cohort-year economics projection remains capped by the existing calculator's 200-row contract.

The new Ubuntu/macOS workflow runs fleet and existing diligence tests without installing dependencies. At that original candidate, hosted execution and independent review were pending; see the later status below. Designated acceptance remains separate. Local test counts are not release acceptance. No production controls, network qualification or new failure calibration is claimed.

Full composed modules plus bundle and fleet: **138 tests passed in 7.362 s**. Existing committed bundle fixture remained valid, confirming this additive module did not alter its source-bound parent graph.

## Near-zero hazard correction

At `79f9685`, hazard 5e-324 over [0.25, 1] with commissioning 0.25 returned 1.0 node-year per node instead of 0.75. Baseline failure is retained in nearzero-baseline.json. The correction uses duration × normalized exprel(hazard × duration), with the continuous value 1 when the product rounds to zero, retaining the exponential age factor and genuine output-underflow refusal. Regression covers 13 hazard levels (zero, subnormal, log-spaced and ordinary), a 380-digit Decimal exponential oracle, partial commissioning and economics projection agreement. Corrected source-bound evaluate/compare receipts are regenerated; earlier scaling timings remain dated to the prior implementation.

Historical corrected validation: 40 fleet+diligence tests passed in 0.284 s; 139 composed tests passed in 4.999 s. These are local checks, not independent acceptance.

## Input binding and projection correction

An optional independently supplied baseline digest now rejects paired baseline drift; unpinned pairs remain explicitly unbound sensitivity calculations. Strictly validated numeric equivalents compare equally. Compare and economics receipts cover their complete inputs, source and outputs, including deltas and supplied economic template. Economics maps each projected row back to cohort/year and records both provenance sources; its availability assumptions explicitly describe derived survival rather than inherited constant-only language. Dispatch refusals preserve validated request identity and available hashes. Projection means beyond rounding tolerance refuse instead of being silently clamped.

42 fleet/diligence tests passed in 0.302 s; 141 composed tests passed in 5.049 s. New regression cases cover pinned paired drift, equivalent numbers, receipt reconstruction, complete template binding, projection mapping/provenance, assumption correctness and refusal identity. Fresh CLI processes regenerated evaluate/compare receipts and added the economics example/receipt. Parent modules remain unchanged.

Documentation now distinguishes stochastic unmet demand, possible delay/shortfall tradeoffs, the 40,000-row comparison bound and high-hazard numerical refusal. The historical scaling measurement is retained; a committed benchmark generator (F9 nit) remains deferred. No physical hazard calibration, investment suitability or automatic baseline promotion is inferred.

## Baseline-binding and regression correction

The baseline label now states only that it matched the supplied digest; the tool does not know whether that digest was independently approved. Callers must check the returned baseline input digest against their own approved record outside this calculator. Explicit null pins refuse; omitted pins remain explicitly unbound. Validated signed zero is normalized for fixed-field equivalence.

43 fleet/diligence tests passed in 0.362 s; 142 composed tests passed in 5.267 s. Added assertions compare every projection mapping value with its active cohort-period row; recompute the complete compare input digest including candidate and supplied pin; verify completed input/source and refused source digests; exercise genuine aged-survival underflow and the narrow mean-survival roundoff clamp. Null-pin refusal and signed-zero equivalence are covered. Evaluate, compare and economics receipts were regenerated by fresh CLI processes after the final source edit. Earlier counts and scaling measurements above are historical; hosted execution and independent re-review were pending at the time of that correction receipt. Parent modules and workflow were unchanged.

## Independent review and reproducibility clarification

At `a7f65de5645cf2e3a2a4ea9e12f037c0589e553f`, the coordinator reported all 10 hosted checks passing. Independent review confirmed the baseline-binding and regression corrections, reproduced 43 focused / 142 composed tests, and caught all 19 tested mutations; no blocking finding remained. This is dated source review, not designated acceptance or a new-head CI claim. Documentation-only follow-up changes no Python, fixture, receipt or workflow bytes.

Committed receipt reproduction was byte-identical under CPython 3.12.6 in the reviewed Mac environment; pin that interpreter/source/input environment when byte identity is required. The inherited lifecycle summation produced a 1.6e-16 relative total difference under Python 3.9.6, altering the economics receipt despite identical source/input digests. Cross-version and cross-platform byte identity are not guaranteed; hosted tests check numeric behavior, not every committed receipt byte. Direct compare(..., None) remains explicitly unbound; dispatch refuses an explicitly null pin. No parent arithmetic or model change is included.
