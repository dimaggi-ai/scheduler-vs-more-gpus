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

## Reserved subtree case-alias correction

Independent QA reproduced a real guard defect at8890122: on a case-insensitive filesystem, `CHECKPOINT_BUNDLE/nested/new.json` resolved with its alias spelling and passed the lexical subtree check. Earlier failed evidence remains with that immutable candidate and the independent QA receipt; no claim is made that the initial guard covered this case.

The corrected guard walks existing ancestor directory identities, including ancestors above nonexistent directories, and rejects an alias of the reserved own package. Exact hashed parent directory checks remain nonrecursive so the evidence directory is still permitted. A copied-source subprocess regression verifies ordinary and uppercase nested paths refuse without publication, while a fresh evidence path succeeds and verifies. The test conditionally exercises actual case aliases when the filesystem supports them; `path-identity.json` records that this host did support the case-alias branch.

All nine bundle methods passed in7.809s on CPython3.12.6. The new path regression and refreshed committed fixture also passed under3.14.6 and3.9.6 (two methods each). Portable fixtures and source hashes were regenerated. The earlier197 composed-test result above predates this narrowly scoped output guard correction; parent/model bytes remain unchanged. Current candidate review and hosted CI remain pending.

## Review206 correction (current)

Explicitly composed checkpoint correction73d0e28; its source hash is d44b77ac4b085d83e8234bb282d486f023cd17cb3bb4d09583e3720a0328d3aa. Parent production remains unchanged. Earlier counts, dependency pins and fixtures above describe dated candidates, not current validation.

Sixteen directed guard mutations are caught by behavioral assertions with the committed-fixture test excluded; an inert comment-only source edit passes the same behavioral suite. `review206-mutations.json` records the targeted checks, not a coverage percentage. Added controls exercise symlink imports, malformed inventories, sibling source outputs, early numeric-count refusal and path-loop errors. Portable evidence is regenerated from this corrected source; no acceptance or new-head hosted result is inferred.

Current observed checks: all13 bundle methods passed10.257s on CPython3.12.6; composed discovery (`python3 -m unittest discover -s capacity/orbital -t . -p 'test_*.py' -q`) passed207 tests in43.957s. Four focused fixture/import-alias/inventory/path-loop/early-budget controls passed on CPython3.14.6 (1.631s) and3.9.6 (1.823s). An initial discovery command omitted `-t .` and produced19 import-loader errors, then was corrected; that invocation failure is retained here and is not a product failure. A read-only process-list convenience check was sandbox-blocked; test completion was obtained from the original process handle.

The exact request was exported and verified in separate fresh subprocesses. Existing checkpoint production matches73d0e28 byte-for-byte, including its unchanged accepted parent. New-head CI and other-tool review remain pending. Budget, source, canonical and output protections are functional consistency controls, not authentication or adversarial filesystem isolation.
