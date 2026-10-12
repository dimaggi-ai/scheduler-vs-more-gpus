# Evidence and provenance

Run from this repository root:

```sh
python tools/validate_evidence.py evidence.json
```

The manifest covers selected consequential inputs, headline results and contract
limitations, not incidental constants. Classifications apply to results separately
from inputs. A simulated result stays simulated even with calibrated inputs.

Local sources and artifacts are SHA-256 bound. A source change must trigger a
review of the dependent claims and regeneration before updating its hash. Do not
refresh hashes just to silence CI. Referenced source ledgers retain citation and
reuse qualifications; structural validation is not independent source verification.

The validator is a byte-identical vendored copy of research/evidence/validate.py,
so CI works without fetching an unpinned second repository. The research portfolio
check tests copy parity. Synchronize copies when changing the convention.

Qualitative contracts use a statement rather than manufacturing numerical results.
Numeric valid_bounds are basic sanity limits, not empirically supported ranges.

The publication gate (`python tools/sync_research.py --check --verify-run`) requires
SHA bindings for the three published experiment PNGs and their generator. An
independent peer review demonstrated that the prior gate accepted a substituted
pre-correction plot or a missing plot even while numerical regeneration passed.
Missing, replaced, unbound or duplicate figure bindings now fail. PNG pixels are
not compared across Matplotlib/font versions: regenerate, inspect the plots,
then explicitly review their hashes before resealing. Neither the numerical
refresh command nor CI automatically updates provenance.
