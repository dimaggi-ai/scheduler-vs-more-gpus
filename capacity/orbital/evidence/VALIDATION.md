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

Hosted CI coverage: the initial task105 delivery at15fe4b4 did not add the new
orbital path to existing hosted tests. After the coordinator explicitly extended
the owned scope, `.github/workflows/ci.yml` gained one named step, "Orbital planner
contracts", running `python3 -m unittest capacity.orbital.test_orbital -v` in the
existing test job. Triggers, permissions, dependencies and all other steps are
unchanged. The exact command passes locally. Hosted execution of this new step
must be checked on the new PR head; earlier green runs do not prove its execution.

## Claude167 corrections (source successor to9538f76)

- Ordinary CLI publication failures now clean staged files and only this run's
  published inodes. Preflight rejects missing parents; no-overwrite hard-link
  publication refuses racing destinations. Regression injects a foreign file
  at the second publish and verifies the first output is removed and foreign
  file retained. Process crash / power loss / cleanup-permission failure remain
  outside multi-file atomicity guarantees.
- Receipt-v2 binds input SHA, supplied source SHA, model version, outcome fields
  and committed events. CLI supplies the actual source fingerprint. Pure API
  without a fingerprint is explicitly marked unbound. No signature or billing
  guarantee is implied. Outcome/event/source mutation tests change the ID.
- `--jobs` with `--scenario` now refuses. Summary cards show assumed quality
  beside unit cost; one power figure across nodes is explicitly an assumption.
- Validation now runs once per comparison with minimum-goodput overflow checks;
  contact scans bisect expired windows; transaction copies hold only changed
  cursors. Scaling measured through the10,000 schema cap (two synthetic shapes),
  not inferred: ~4.88s one contact / ~5.01s10,000contacts, ~43.4MB Python peak.
  Adversarial contact scans can still approach jobs×contacts.
- New unit suite:21tests; combined capacity/calculator/simulator + orbital suite:
  103tests and11subtests pass in9.16s. Original pre-review reports and initial scaling results
  retained. Source/report hashes regenerated; no claim that receipts stayed equal.
- Visual rendering gate remains blocked; static escaped HTML reviewed only.
