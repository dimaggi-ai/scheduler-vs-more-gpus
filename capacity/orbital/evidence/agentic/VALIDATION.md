# Task107 validation receipt

Implementer: Codex delegated builder (generic fallback; applied installed dimaggi-builder instructions). Base4d80c164c336ba2e1bb1cb00c8208a5ad0061384, branch codex/107-orbital-agentic-loop. Local Python3.12.6, stdlib only, no package installation or external model calls.

Commands run from repository root:

```sh
python3 -m unittest capacity.orbital.test_orbital capacity.orbital.test_agentic -v
python3 -m capacity.orbital.agentic.benchmark
python3 -m capacity.orbital.agentic --request capacity/orbital/examples/agentic-evaluate.json
python3 -m capacity.orbital.agentic --request capacity/orbital/examples/agentic-regression.json
```

50 tests pass:21existing planner tests and29agentic boundary/evaluation tests. Both example outcomes reproduce deterministically, including current source/input/outcome hashes. The training winner is onboard; the standard heldout recommends independent review, while the deliberately adverse heldout returns regression/retain_baseline. Neither promotes or changes active_policy=ground.

Tests cover agent-only plan/compare, hand arithmetic, immutable requests and results, duplicate/conflicting IDs, corrected retry, unknown schemas/tools, supplied callbacks/authority refusal, invalid and leaked splits, heldout nonselection, cost not winning by dropping jobs, source changes/unavailability, all-refused outcomes, byte/count/cache budgets, JSON-lines stopping and safe output preservation. Source manifest includes imported v1 files and agentic code/schema. Formal JSON Schema is a wire-shape artifact; runtime validation additionally enforces semantic domains and budgets.

`scaling.json` retains measured full-dispatch evaluations at2,100and1000totaljobs. Single observations with tracemalloc; peak is traced Python allocation, not total RSS. Byte caps apply jointly with list caps; no production or horizontal-scaling claim.

Failed evidence: first agentic suite run had25passes/1failure in test_budgets. Test reused a session after an intentionally refused request, which correctly consumed one idempotency record, then incorrectly expected32additional records. The test now uses a fresh session for the32-record boundary. Product behavior was correct; do not present this as a fixed product defect. A subsequent self-review unified the cache-exhaustion refusal message so an uncached budget refusal and identical retry produce identical envelopes; covered by regression.

Remaining gates: other-tool exact-source review, designated technical acceptance by dimaggi-cto, independent reproduction by mutebironald and tested composition with future dynamics/network modules. No hardware execution, native Tool Guard authorization, sandbox qualification, acceptance, merge or release is claimed. Heldout confidentiality/reuse acrosssessions is not enforced; independent sealed evaluation is still required for promotion decisions.
