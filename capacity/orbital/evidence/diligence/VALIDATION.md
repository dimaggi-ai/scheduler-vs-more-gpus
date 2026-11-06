# Task109 delivery validation

Codex delegated builder, applying installed dimaggi-builder instructions via a generic role fallback. Base1aa7364a5b9bc6f818527284f6bb774b4fd831e5; disjoint branch codex/109-orbital-diligence. Original standard math and authored synthetic fixtures only; no confidential strategy/model copy, vendor telemetry, financial recommendations or authority changes.

Commands:

```sh
python3 -m unittest capacity.orbital.test_orbital capacity.orbital.test_dynamics capacity.orbital.test_diligence -v
python3 -m capacity.orbital.diligence.benchmark
python3 -m capacity.orbital.diligence --request capacity/orbital/examples/diligence-lifecycle.json
python3 -m capacity.orbital.diligence --request capacity/orbital/examples/diligence-thermal.json
python3 -m capacity.orbital.diligence --request capacity/orbital/examples/diligence-unknown.json
python3 -m capacity.orbital.diligence --request capacity/orbital/examples/diligence-zero-output.json
```

64tests pass (32inherited planner/dynamics,32diligence). Numerical oracles: present cost1173.5537190082644; output1/1.1+1/1.1²; unitcost676.190476; battery1hour; decimal link8seconds; ideal thermal459.300327939W. Tests cover lower-utilization monotonicity, commissioning/retirement/replacement gaps, zero output, netcredit review, marginal/prepaid distinction, signed residual credit, invalid/mixedcurrency/financing input refusal, derived overflow/underflow, ambiguous panel area unknown, excessive absorbed flux inconsistent, unsupported radiation/transient unknown, immutable/deterministic API results, corrected retries, source unavailability, report escaping and output preservation.

All four example JSON results reproduce exactly with source/input/outcome hashes. HTML derives from the same response and is escaped/self-contained; actual browser visual QA remains pending with the coordinator. Do not count static HTML tests as visual verification.

Scaling observations retain Python/platform, elapsed seconds, traced Python peak allocations and byte sizes. Largest measured case is1000cashflows/200cohorts/100years, the declared list/horizon caps, within1MBrequest. Tracemalloc is not total process RSS; one observation is not a production SLO. The new read-only test workflow runs the inherited and diligence suites, without installs/secrets/deploy.

Pre-commit review defects and failure-triggering inputs are retained in history/early-review.md and regression tests. No claim that initial tests caught them. Claude exact-source review, Dmitry technical acceptance, Ronnie independent reproduction, browser QA and tested multi-module composition remain open. No merge, release, physical qualification, investment recommendation or automatic promotion.
