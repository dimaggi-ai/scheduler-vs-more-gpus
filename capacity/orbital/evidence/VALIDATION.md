# Task105 validation

Builder: Codex generic builder fallback, applying the installed reviewed builder
instructions. Source only under capacity/orbital; base main
1f9ecb7bbd12814c72d6cc70060abf822e04a1e8. Cross-review: Claude, pending. This is not
self-acceptance or a released service.

## Observed on 5 November 2026

- `python3 -m unittest capacity.orbital.test_orbital -v`: 14 tests passed.
- Existing capacity, calculator and simulation suites plus orbital tests:
  `capacity-planning-venv/bin/python -m pytest -q capacity/tests calculator/test_stranded_capacity.py sim/test_sim.py sim/test_validation.py capacity/orbital/test_orbital.py`:
  96 tests and 11 subtests passed in 8.49 seconds.
- Python3.12.6 / macOS27.0.1 ARM64. No package installation.
- Hand oracles cover 100s ground, 30.8s onboard and 28s hybrid completion,
  decimal-GB throughput, energy and partial cost.
- Invalid domains, duplicate/missing schema fields, shared reservations, missed
  contacts, zero contact capacity, memory/power/heat/energy limits, quality,
  deadlines, rollback, deterministic replay and two adapters exercised.
- CLI invalid input -> exit2/no report; corrected input -> JSON+HTML success;
  repeated output paths -> refusal preserving existing bytes. HTML escaping tested.
- Scales and measurements are in scaling.json. One-contact 1,000 jobs: ~0.35s,
  ~4.37MB traced Python memory. 1,000-contact 1,000 jobs: ~3.31s, ~4.34MB.
  These are one-run measurements, not confidence intervals or total RSS.

## Retained failed-check account

The first overflow test expected ValueError for an enormous compute duration,
but planning correctly refused its deadline before cost arithmetic. Replaced
that test with a reachable cost-overflow case; it now refuses nonfinite output.
An initial existing-suite command used an incorrect virtualenv path and failed
before tests; rerun at the existing _Engineering/capacity-planning-venv succeeded.
No product defect or test result was hidden by those command corrections.

## Visual QA and remaining gates

Static HTML review checked explicit units, semantic headers, escaped content,
no external assets/scripts, narrow-width card CSS and partial-cost/refused-work
warnings. Actual browser rendering was **blocked by the browser security policy**
for local file preview; no alternate browser/server was used to circumvent it.
No screenshot or visual-readiness claim. User may open the local HTML manually.

Claude exact-source review, Dmitry/Ronnie acceptance, browser visual verification
and release remain open. Isolated chaos qualification is assigned by task105;
these software refusal tests are supplementary, not host/network-isolation proof.

Hosted CI coverage: existing `.github/workflows/ci.yml` runs `capacity/tests`,
not `capacity/orbital/test_orbital.py`. New orbital tests were run locally only.
A passing existing CI job does not prove this new module passed hosted tests.
Adding the explicit unittest command to CI is a scoped integration follow-up;
this builder did not edit workflows outside its assigned paths.
