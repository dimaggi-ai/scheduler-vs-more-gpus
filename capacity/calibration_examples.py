"""Deterministic contract examples; these are not measurements or model tuning."""
from copy import deepcopy

from capacity.calibration_evidence import compare_pair, CONTEXT_FIELDS

NOW = "2026-09-19T12:00:30Z"


def example_pair():
    context = dict(zip(CONTEXT_FIELDS, ("synthetic-job-0", "synthetic-config-v1", "synthetic-host",
                                       "synthetic-topology", "synthetic-node-0", "host_total_memory", "peak", "synthetic-protocol-v1")))
    prediction = {"context": context, "value": 100, "unit": "byte", "state": "known",
                  "source_id": "synthetic-prediction-0", "evidence_class": "synthetic_model",
                  "measurement_start_utc": None, "observed_at_utc": None, "valid_until_utc": None}
    observation = deepcopy(prediction)
    observation.update(value=110, source_id="synthetic-observation-0", evidence_class="synthetic_contract_fixture",
                       measurement_start_utc="2026-09-19T11:59:00Z", observed_at_utc="2026-09-19T12:00:00Z",
                       valid_until_utc="2026-09-19T12:01:00Z")
    return {"prediction": prediction, "observation": observation,
            "absolute_tolerance": {"value": 10, "unit": "byte", "source_id": "synthetic-predeclared-tolerance"},
            "as_of_utc": NOW}


def fixtures():
    cases = []
    def add(name, expected, mutate=lambda p: None, split="development"):
        args = example_pair()
        mutate(args)
        cases.append({"id": name, "split": split, "evidence_class": "synthetic_contract_fixture",
                      "seed": None, "input": args, "expected_assessment": expected})
    add("equal-to-explicit-tolerance", "within_supplied_tolerance")
    add("underprediction-outside-tolerance", "outside_supplied_tolerance", lambda p: p["observation"].update(value=111))
    add("overprediction-outside-tolerance", "outside_supplied_tolerance", lambda p: p["observation"].update(value=89))
    add("measured-zero-no-relative-ratio", "outside_supplied_tolerance", lambda p: p["observation"].update(value=0))
    add("unknown-observation", "incomplete", lambda p: p["observation"].update(value=None, state="missing"))
    add("stale-at-expiry-equality", "incomplete", lambda p: p.update(as_of_utc="2026-09-19T12:01:00Z"))
    add("not-run", "incomplete", lambda p: p["observation"].update(value=None, state="not_run"))
    add("unknown-tolerance", "incomplete", lambda p: p["absolute_tolerance"].update(value=None))
    add("unknown-target", "incomplete", lambda p: p["observation"]["context"].update(hardware_id=None))
    add("wrong-statistic", "incomparable", lambda p: p["prediction"]["context"].update(statistic="even_shard_rough_estimate"))
    add("wrong-scope", "incomparable", lambda p: p["observation"]["context"].update(scope_id="synthetic-node-1"), "exposed_acceptance")
    add("wrong-unit", "incomparable", lambda p: p["observation"].update(unit="s"), "exposed_acceptance")
    add("future-observation", "invalid", lambda p: p.update(as_of_utc="2026-09-19T11:59:59Z"), "exposed_acceptance")
    add("wrong-protocol", "incomparable", lambda p: p["observation"]["context"].update(protocol_id="different-coverage"), "exposed_acceptance")
    add("declared-drift", "incomplete", lambda p: p["observation"].update(state="stale"), "exposed_acceptance")
    return cases


def run_cases():
    rows = []
    for case in fixtures():
        output = compare_pair(**case["input"])
        if output["assessment"] != case["expected_assessment"]:
            raise AssertionError(case["id"])
        rows.append({**case, "output": output})
    return {"schema_version": "calibration-contract-cases/v0.1", "tuning": [],
            "held_out": [], "seed": None, "generation": "deterministic hand-authored cases; no stochastic physical generator",
            "cases": rows}


if __name__ == "__main__":
    import json
    print(json.dumps(run_cases(), indent=2, sort_keys=True, allow_nan=False))
