# Capacity Orbital: checkpoint-aware mission predictions

This additive, offline module couples exact synthetic checkpoint replay to the existing single-job network and approximate battery/thermal planners. It plans ground, onboard and hybrid routes, verifies portable evidence, and compares checkpoint intervals against a caller-pinned baseline. It performs no flight, network access, Tool Guard action, billing or automatic promotion.

## Agent and CLI journey

```python
from capacity.orbital.platform.checkpoint import (
    plan_checkpoint_mission, verify_checkpoint_mission,
    compare_checkpoint_missions,
)
from capacity.orbital.platform.checkpoint.fixtures import demo
from capacity.orbital.platform.checkpoint.contracts import normalized, enc
from capacity.orbital.contracts import digest
s = demo()
r = plan_checkpoint_mission(s, 'hybrid')
assert verify_checkpoint_mission(s, r)['valid']
pin = digest(enc(normalized(s)))  # retain independently before proposing changes
comparison = compare_checkpoint_missions(s, s, 'hybrid', pin)
```

```sh
python3 -m capacity.orbital.platform.checkpoint --request capacity/orbital/examples/checkpoint-mission-plan.json --output /tmp/fresh-checkpoint-mission.json
python3 -m capacity.orbital.platform.checkpoint --request capacity/orbital/examples/checkpoint-mission-verify.json
python3 -m unittest capacity.orbital.test_checkpoint_mission -v
```

The `tools.dispatch` envelope is exactly `{schema,id,tool,input}`, with schema `capacity-orbital/checkpoint-mission-tool-v2`. Tools are `plan` (`scenario,route`), `compare` (`baseline,candidate,route,expected_baseline_sha256`), and `verify` (`scenario,report`). Results carry `status`, request ID, input/source hashes and `execution_performed:false`. A plan's admissibility is distinct from transport success, and verification establishes consistency, not admissibility or authenticity. Missing/invalid inputs refuse; caller-corrected retries are explicit new requests. There is no mutation or persistent request-ID store.

Fresh outputs use the existing no-overwrite publisher. Ordinary publication failures preserve existing files. This is not crash-atomic multi-file storage. No output is published on refusal. Programmer exceptions outside explicitly named validation/numeric boundaries propagate without valid output; they are not relabelled as input errors. The inherited v1 validator raises untyped ValueError, so this narrowly scoped boundary cannot distinguish a future programmer ValueError inside that validator.

## Exact declarations and approximate parent views

The wrapper has schema `capacity-orbital/checkpoint-mission-v2`, fields `id,mission,replay`, one mission job, and replay declarations for `origin,destination`. Each replay object has `policy,power_kw,heat_w,provenance`; power and heat declare productive/checkpoint/restart/down states. Productive declarations must exactly agree with mission compute values. Nonzero background power or heat on compute nodes is unsupported, preventing double counting.

Mission numbers preserve exact decimal declarations in the semantic wrapper digest. A separate bounded finite int/float view goes to unchanged parent planners. Report `input_sha256` and `parent_view_sha256` expose the distinction. Different exact declarations can round to the same float; integer-versus-decimal token categories can affect parent receipts without changing semantic identity. Direct float input means its repr decimal. Exact normalized rational objects are hash representations, not accepted numeric inputs. JSON parsing rejects duplicate keys, nonfinite constants, invalid UTF-8 and surrogates. Report subtrees restore ordinary JSON floats before verification hashing.

Only selected positive-work stage temporal inputs must lie on the declared 1/4096-second grid and satisfy replay's bounded decimal grammar. Resource magnitudes such as 0.35 kW and 33.3 W are allowed without binary exactness. Mission-only tiny values such as 1e-300 are allowed when their parent field allows them; nonzero-to-zero float conversion refuses. Temporal Decimal conversion is exact, never default-context rounding. A direct float repr can be off-grid where an explicitly preserved decimal JSON token is on-grid. Unused route work does not block a route, but every selected node outage, including after-deadline outages, is preflighted before simulated failures can mask it.

Positive ground work starts at the upward grid rounding of the parent binary arrival/commissioning maximum; the report preserves original arrival, its exact rational value and delay. The hybrid demo arrives at parent 8.4 seconds, starts replay at 34407/4096 seconds and finishes at 54887/4096 seconds. This rounding preserves data precedence only; it does not claim universal fault monotonicity. Zero ground work remains unquantized. Zero origin work waits through an outage containing release, including adjacent outages; this is an explicit v2 rule that can differ from v1.

## Resources, failures and improvement boundaries

Every replay interval maps once to a dynamics event, with state, exact declared power/heat and converted float values visible in `replay_event_map`. Transfer IDs are bounded hashes after parent report reproduction; `transfer_event_map` preserves the ordered original identities. There is no extra monolithic compute event. Declared exact replay energy, mapped-float replay energy and signed conversion difference are distinct. Parent proposal energy is approximate and whole-proposal; dynamics may stop at a violating prefix. Electrical power does not infer heat.

Storage-unpreserved outage overlap makes the entire stage conditional. Its full trace stays inspectable, but all its events (including before the outage), costs and energy are excluded from realized totals. No downstream work is scheduled. Consequently realized dynamics makes **no statement** about that conditional stage's battery/thermal adequacy, even if its pre-outage energy would exhaust a battery. A missed job deadline is retained alongside the durability failure. Ordinary deadline-missed partial stages remain modeled. Checkpoint image transfer bytes and physical radiation/fault probabilities are not modeled.

Exact compute USD is declared decimal price times productive/checkpoint/restart seconds; down time is unbilled. Lost work is already productive time. Network USD and combined partial operating USD are labelled approximate/mixed precision. Separate lifecycle sensitivity is linked, not summed into a fabricated mission bill.

Comparison permits only IDs/descriptive provenance/names and checkpoint policy version/interval changes listed by this API; hardware, jobs, prices, authority, node/link/contact identities and fixed durations stay fixed. Adjacent outage spelling and numeric equivalence normalize. A matching caller digest does not establish approval origin. The caller must retain an independently approved baseline outside this calculator. Comparison summaries retain full report receipt/source/input hashes; deltas are candidate minus baseline, with completion delta null unless both have a completion. Scores never promote a candidate or expand authority.

## Bounds and source integrity

Plan/compare: raw and normalized request 1,000,000 bytes, depth32/nodes50,000. Verify: request10,000,000 bytes, scenario1,000,000 bytes, report8,000,000 bytes, depth64/nodes1,000,000. Canonical emitted byte counts include the terminal newline. Report/source hashes use compact sorted JSON with ASCII escaping; pretty-printed transport can exceed these bounds. Normalization can enlarge UTF-8 input. These are serialized size bounds, not Python process-memory bounds.

Mission number tokens are limited to768 characters/coefficient digits, exponent spelling3 digits and magnitude400, and defensive reduced rational numerator/denominator1200 digits. Selected replay values use the stricter existing48-character/24-coefficient/12-place rules. Replay/grid representation failures refuse `UNSUPPORTED_NUMERIC_DOMAIN`; physical range failures are `INVALID_ARGUMENT`; finite work/event/transport budgets are `BUDGET_EXCEEDED`. Full intermediate comparison reports obey their limits with baseline/candidate-specific reasons. Combined events are at most10,000; parent network/shared-clock/active-event bounds remain active.

This package hashes its code and imported local parent modules/initializers. It requires the reviewed v1 parent source hash `dc7420c8d4be3466d1036eadf39206567d37d2b0bc11ddd8d9f3c00040e0593e`. It does not register in or change v1. Hashes establish source consistency, not signatures, execution authenticity or technical acceptance. Version updates require explicit reviewed composition and refreshed evidence. Cross-tool review, CI and designated acceptance remain separate delivery gates.
