# Portable bundle local validation

Base platform: dc87c24ac6ab1a06df1c73aaf2e633ab2c4c01e5. New source is isolated in bundle/ and its focused test; existing planner/runtime files are unchanged.

`python3 -m unittest capacity.orbital.test_bundle -q`:4 test groups passed in 1.843s. These groups include multiple tampering and malformed-input cases, four mission scenarios, fresh CLI processes, overwrite/input preservation and optional trusted expected-digest rejection. Counts are test coverage evidence, not product acceptance.

Fresh CLI exported examples/bundle-mission.json to this directory's nominal.json. Separate CLI verification produced verification.json. All scenario data comes from the existing synthetic platform demo; no observed hardware or private runtime records were used. The exported envelope contains source hashes and can be verified using this source tree.

The coordinator extended scope to the existing integrated-platform workflow test command only. It now includes the new bundle module alongside all existing tests; hosted execution is pending, not claimed successful. Browser rendering is not applicable to this JSON-only increment. Claude pinned cross-review, designated technical acceptance and release composition remain open. A valid bundle is not signed/authenticated or evidence of actual execution.

The exact integrated workflow module list including bundle passed locally: 129 tests in 4.154s. Workflow source change adds only capacity.orbital.test_bundle to its existing command. Product Python source and evidence hashes are unchanged.

Claude review at33edca8 found RuntimeError escaping for renamed contact references, Python bool/numeric equality accepting comparison flags, and absent committed-fixture coverage. The correction catches RuntimeError at the bundle boundary while preserving BaseException, compares canonical digests, binds capacity/__init__.py bytes, and intentionally regenerates nominal.json plus expected-sha256.txt. The integrated workflow now runs on Ubuntu and macOS; each executes the committed-fixture test and fresh-process expected-digest check. Prior hosted success at33edca8 is dated evidence; corrected-head hosted results remain pending. No parent planner/physics/source module is edited.

Corrected composed suite:131 tests passed in4.813s before adding explicit fresh-process tampered-contact CLI assertions; final focused result is recorded in the delivery receipt. The expected digest is stored separately in expected-sha256.txt and supplied to the committed-fixture verifier.
