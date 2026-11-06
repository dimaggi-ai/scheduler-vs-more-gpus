# Portable checkpoint bundle candidate

Provisional dependency base:55792ab6d7f4c61d7528b95204e5e0cb728bfe20. The sibling package does not change checkpoint, parent mission, existing bundle, replay or fleet code. The dependency source remains e6553c039be697a5157dfb1e0c62596f2570c8b43df1e92a8220228db14a47cf; parent mission remains dc7420c8d4be3466d1036eadf39206567d37d2b0bc11ddd8d9f3c00040e0593e. This is provisional development while PR17 re-review is pending, not inherited technical acceptance. Any later dependency correction requires explicit composition and receipt regeneration.

## Observed validation

- Eight bundle test methods passed in7.353s on CPython3.12.6.
- Twelve-module composed suite passed197 tests in36.629s.
- The unchanged committed fixture, bounded numeric/transport controls and missing-source startup/recovery tests passed on CPython3.14.6 and3.9.6 (three methods each,0.631s each). CPython3.12 exercised all tests.
- A real canonical bundle of9,865,052 bytes, retaining999,999 bytes of original plan JSON, passed verification through an11,792,589-byte typed wrapper. This validates the separate21MB transport cap; it does not enlarge the10MB bundle cap. Above-limit report and one-byte-over raw/tool/inner transport controls refused before payload parsing or publication.
- Actual export/verify subprocesses wrote the exact portable bytes and verified a trusted expected digest. `receipt.json` records source/input-output sizes, elapsed time and synthetic classification; `nominal.json` and `expected-sha256.txt` are the portable pair.
- Directed controls cover rehashed request/report/map/route/source/authority substitutions, distinct exact prices sharing a parent float, valid inadmissible diagnostics, single verifier invocation, no-overwrite/input preservation, missing-directory publication refusal/retry, and symlink aliases of hashed source directories. Missing own/parent files refuse via the standalone launcher, and restoring source permits fresh export.

Initial fixture development retained two corrected findings in this narrative: a broad string replacement accidentally changed a heat declaration, so the numeric fixture now sets fields explicitly before retaining the intended exponent token; a broad parser tripwire intercepted source-inventory parsing, and cheap raw input caps were moved before source IO. Initial large-report trials with work0.375/0.4375/0.46875 correctly exceeded the inherited report cap; work0.34375 supplies the admitted near-cap case. No budget was raised to make those trials pass.

The new Ubuntu24.04/macOS15 CPython3.12 workflow uses pinned actions and read-only permissions, without installation, network test dependencies, publication or deployment. It has not yet run for this local candidate. Exact byte/source portability is tested, not universally guaranteed across math libraries. Independent review, final dependency freeze, CI and designated acceptance remain open. No physical hardware, radiation, flight, production or runtime-authority qualification is claimed.
