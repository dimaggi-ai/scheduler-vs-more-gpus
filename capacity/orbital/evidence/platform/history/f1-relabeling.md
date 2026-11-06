# PR13 F1 — relabelled held-out workload leakage

Reviewed baseline: `28d748d7c4c295461abf5c24ee78c0400efc67d4`. Claude's independent source review found that changing node names let a copied training mission enter held-out policy evaluation and feedback. Previous sorting of jobs/contacts did not normalize node dictionary keys and references. This was a split-isolation defect, not actual control execution or production learning.

Correction: a label-free incidence graph represents node roles and physical attributes, node-local terminals, shared links and directed contacts. Bounded color refinement derives canonical identities. IDs, spelling and dictionary/list insertion order never break an unresolved tie. Physical data, quality, prices, jurisdiction and aliasing remain in the fingerprint. Ambiguous referenced identities return `SEMANTIC_TOPOLOGY_AMBIGUOUS`; 64-round and 500,000-work limits return `BUDGET_EXCEEDED`, with no permutation search. This is intentionally a partial canonicalizer, not general graph-isomorphism or near-copy certification.

Regressions cover:

- simultaneous node/terminal/link/contact/job renaming, dictionary insertion reversal and unordered-list reversal;
- policy split rejection and feedback split rejection with independently valid, newly bound reports/replay records for the renamed copy;
- preservation of changed price, jurisdiction, compute power and quality;
- distinction between one shared physical link versus separate links, and shared versus distinct terminal allocation;
- 32-node unresolved symmetry, stable structured refusal at the tool boundary and explicit work-budget exhaustion;
- unchanged success, correction/retry, held authority, verifier and feedback non-promotion behavior.

The existing dense platform workload is retained: 20 jobs, three separately evaluated policies, three nodes and two contacts. Its scaling receipt now explicitly records delivered hops and resource reservations, so success-path coverage is distinguishable from refused random cases. Composition remains single-pass and conservative, with no hidden rescheduling after dynamic failure.

Reproduce from the repository root:

```
python3 -m unittest capacity.orbital.test_platform -v
python3 -m capacity.orbital.evidence.platform.reproduce
```

Independent Claude review and designated acceptance remain open for the corrected exact commit. All inputs and feedback remain synthetic; no baseline promotion, actual permission change, live execution or acceptance occurred.
