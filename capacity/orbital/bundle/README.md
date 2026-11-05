# Capacity Orbital portable evidence bundle

Export one bounded synthetic mission with all three coupled route reports, then verify it offline in another Python process. This reuses the existing mission relationship verifier and deterministic comparison; it is not another planner. No package installation, network request, private runtime artifact, executable payload or authority change is included.

```sh
python3 -m capacity.orbital.bundle export --mission capacity/orbital/examples/bundle-mission.json --output /tmp/new-orbital-bundle.json
python3 -m capacity.orbital.bundle verify --bundle /tmp/new-orbital-bundle.json
```

Agent-callable functions: `export_bundle(mission)` returns the versioned JSON envelope or raises a bounded validation error; `verify_bundle(envelope, expected_sha256=None)` returns `valid`, `errors`, feasible route names and explicit false authenticity/execution flags. CLI exit 0 means export/verification succeeded, even when all routes are infeasible: a valid refusal is evidence too. Exit 2 means malformed/inconsistent evidence or an IO refusal. Export never overwrites an existing path or its input.

The envelope contains the complete mission, ground/onboard/hybrid comparison, input hash, platform-source hash and bundle-source hash. Verification checks exact envelope fields and version, all report relationships, route coverage and deterministic replay. The same platform and bundle source bytes must be available to verify; the bundle does not embed code. The source hash includes the imported platform dependency graph and bundle Python files.

Hashes prove consistency only, not origin or authenticity. An entirely regenerated alternative synthetic mission is legitimately valid. To bind a separately trusted expected bundle, supply `--expected-sha256 DIGEST` or the function argument; that digest must come through an independently trusted channel. Editing a mission/report/source and merely recomputing the outer hash fails. This is not signing, hardware validation, scientific calibration, production qualification or release acceptance.

Inputs and complete envelopes are capped at 8 MiB, depth 64 and 200,000 nodes. JSON duplicate keys and nonfinite values refuse; deep parsing errors are caught. Existing model limits remain stricter where applicable. Export reports are synthetic predictions with declared assumptions, not measured spacecraft behavior. File publication uses the existing no-overwrite publisher; no multi-file/process-crash transaction or filesystem authenticity is claimed.

Run `python3 -m unittest capacity.orbital.test_bundle -v`. Tests cover fresh-process CLI export/verify, immutability, rehashed tampering, exact expected-digest binding, valid infeasible cases, malformed/duplicate/truncated/oversized data and overwrite refusal. The existing integrated-platform workflow now includes this test module alongside all existing composed tests. Hosted execution remains pending until the branch is delivered and the exact-head run completes.

Verification requires the exact source bytes, including capacity/__init__.py and line endings. CRLF conversion or even a comment-only source edit invalidates the old source binding; regenerate evidence intentionally rather than bypassing the check. Floating-point replay is exact and may differ across platform math libraries. The committed Mac-generated fixture is now exercised on Ubuntu and macOS CI, but passing those environments is not a universal portability guarantee. Exports inherit the existing publisher’s 0600 file mode; sharing permissions and directory durability remain operator concerns.
