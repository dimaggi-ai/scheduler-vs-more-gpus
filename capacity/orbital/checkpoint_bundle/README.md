# Portable checkpoint mission evidence

This additive offline module exports one selected ground/onboard/hybrid checkpoint-aware mission and verifies it in a same-source checkout. It preserves the original request JSON text, including exact numeric lexemes and request ID. It does not choose the best route, execute a mission, establish authenticity, promote a policy or activate Tool Guard.

Development is provisionally pinned to checkpoint PR17 source55792ab. Its re-review and integrated technical acceptance remain separate. Changes to that dependency require an explicit source update and regenerated portable evidence before final delivery; earlier private-runtime qualification does not qualify this package.

## Agent journey

```python
from capacity.orbital.checkpoint_bundle import export_checkpoint_bundle, verify_checkpoint_bundle
from capacity.orbital.checkpoint_bundle.tools import dispatch
text = open('capacity/orbital/examples/checkpoint-bundle-request.json').read()
exported = export_checkpoint_bundle(text)
# Store/transfer exported['bundle_json'] exactly, including its terminal newline.
# Obtain the expected digest through a separately trusted channel.
checked = verify_checkpoint_bundle(exported['bundle_json'], exported['sha256'])
assert checked['valid']
```

`tools.dispatch` accepts exactly `{schema,id,tool,input}`, schema `capacity-orbital/checkpoint-bundle-tool-v1`, and a nonempty delivery ID up to128 characters. Export input is `{request_json: <original text>}`; export result is `{bundle_json,sha256}`. Verify input is `{bundle_json: <that exact text>,expected_sha256: <lowercase64hex or null>}`. No reserialization is required between tools. `dispatch_json` supports raw typed JSON transport. Input strings never name files, callbacks, imports or commands. IDs identify deliveries, not approval, semantics or durable idempotency. No persistent cache exists.

Success fields are `schema,id,status,result,execution_performed`; refusal fields are `schema,id,status,code,reason,execution_performed`. Known valid IDs survive dispatch refusals. Reasons are bounded to512 characters; errors to64 sorted unique strings of at most256 characters. Missing source, malformed/schema/limit/IO failures refuse. A well-formed inconsistent bundle returns status`ok` with `valid:false` and `admissible:null`. A consistent physically inadmissible diagnostic returns `valid:true,admissible:false`: feasibility and evidence consistency are separate.

## Source-guarded file CLI

```sh
python3 capacity/orbital/checkpoint_bundle/cli.py export --request capacity/orbital/examples/checkpoint-bundle-request.json --output /tmp/fresh-checkpoint-bundle.json
python3 capacity/orbital/checkpoint_bundle/cli.py verify --bundle /tmp/fresh-checkpoint-bundle.json --expected-sha256 EXPECTED_DIGEST_FROM_TRUSTED_CHANNEL
```

Export writes exactly the returned canonical `bundle_json`; it also returns that text and digest in its stdout result. Export success and valid verification exit0. Refusals **and invalid verification** exit2, so shell `&&` does not continue on invalid evidence; JSON distinguishes refusal from status`ok,valid:false`. Correct input plus a fresh permitted path is the recovery journey. No files are published on refusal.

Only this CLI interprets filesystem paths. It rejects existing outputs, output=input, the whole bundle source subtree, and exact parent directories covered by imported source inventories/globs. Existing symlink ancestors and directory identities are resolved, including aliases of orbital root. Ancestor identity checks also reject case-insensitive aliases anywhere below the reserved own package, including paths with nonexistent intermediate directories. Nonrecursive source globs do not ban their evidence/example subdirectories. The existing publisher preserves other files on ordinary errors; this is not an adversarial concurrent-filesystem guarantee or a crash-atomic transaction.

The standalone launcher reads both explicit source inventories before eager imports, puts the repository first and checks the imported capacity tree. Known absent/unreadable inventoried files yield structured `SOURCE_UNAVAILABLE`; unrelated import/programmer defects propagate. The launcher and Python standard library must themselves be runnable. The convenience `python3 -m capacity.orbital.checkpoint_bundle` still depends on successful package initialization before its entry point; use the standalone launcher for guarded startup.

## Exact transport and trusted pins

Portable schema is `capacity-orbital/checkpoint-evidence-bundle-v1`. The envelope is exactly `{content,sha256}`. Its hash binds the precise original request text, full report, semantic scenario hash and source bindings. The external expected digest is compared against **recomputed content**, not merely an untrusted claimed hash. Mode `self-consistent` means no external pin was supplied; `expected-pin` means a supplied pin matched. Neither establishes authenticity or approval origin.

The outer envelope must be byte-for-byte compact sorted canonical JSON with exactly one newline (ASCII escaping, no NaN). Whitespace, alternate outer numeric spelling, duplicates and key order changes refuse. Original inner JSON whitespace/numeric spelling is retained verbatim: equivalent inputs can have different envelope hashes while sharing the normalized scenario hash. Verification parses the stored plan request without dispatching it, then invokes checkpoint verification once for deterministic replan and independent relationships. It does not call plan dispatch and replan a second time.

The bounded grammar checks outer numeric tokens before int/float conversion; inner request parsing remains the pinned checkpoint parser. Limits are1,000,000 UTF-8 bytes for original plan text,8,000,000 canonical bytes for a report,10,000,000 raw/canonical bytes for a portable envelope (including newline), and21,000,000 bytes for typed requests/responses. The larger typed cap allows JSON escaping of a valid10MB bundle string; it does not enlarge the inner limit. Outer depth is64 with1,000,000 nodes; inner checkpoint limits remain32/50,000. Escaping or a combined request/report can exceed the envelope cap even if each component is individually legal; export then refuses instead of truncating. These are serialized limits, not process-memory limits.

Source hashes require exact bytes and pinned dependencies. CRLF conversion, comments or source edits invalidate evidence. Strict floating-point replay can also differ across Python/platform math libraries; no tolerance is introduced for portability. The workflow verifies the committed fixture unchanged in its configured CI matrix (Ubuntu24.04/macOS15, CPython3.12); local additional interpreter results are in the validation receipt. A passing test count is not physical or operational qualification.
