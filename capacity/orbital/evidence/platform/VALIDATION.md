# Task110 integrated candidate receipt

Implementer: codex generic builder applying reviewed role instructions. Base task108 `39d1c36f6693cb7cdc93402e49d72cd567895337`; exact task107 and task109 sources were locally cherry-picked as recorded in platform/composition.json. No GitHub PR/default-branch merge or designated acceptance occurred. Source files of composed modules remain unchanged.

Validation commands:

- `python3 -m unittest capacity.orbital.test_platform capacity.orbital.test_network capacity.orbital.test_dynamics capacity.orbital.test_agentic capacity.orbital.test_diligence capacity.orbital.test_orbital -q`:121 composed tests passed before the final paired-log assertion/source-manifest clarification; platform13 tests reran afterward and passed.
- Existing planning environment Python `-m pytest -q capacity/tests calculator/test_stranded_capacity.py sim/test_sim.py sim/test_validation.py capacity/orbital/test_orbital.py capacity/orbital/test_dynamics.py capacity/orbital/test_network.py capacity/orbital/test_agentic.py capacity/orbital/test_diligence.py capacity/orbital/test_platform.py`:203 passed,25 subtests passed in10.38s.
- `python3 -m capacity.orbital.evidence.platform.reproduce`: generates source-bound nominal/refused/corrected/held comparisons, independent verification results, fixed policy evaluation, synthetic replay improvement/worsening examples and measured scaling. All18 retained route verification reports are valid, including intentionally refused diagnostic proposals.
- CLI journeys: nominal0, all-battery-refused3, corrected-solar0; JSON requests cover no-UI policy and synthetic-feedback journeys. Actual output rendering remains browser-policy blocked; static HTML, units and source inspection only.

Coupling tests cover compute-before-output, input-before-ground-processing, final useful deadline beyond packet arrival, both serial compute lanes, raw input storage, memory refusal, transfer+compute energy, shared network resources, authority held/refused/expired, source/input binding and corruption despite recomputed hashes. Verification separately checks timing/byte/power/storage/cost relationships and then replay. Lifecycle sensitivity uses explicitly separate year horizons/units; no lifecycle total is inferred for a300-second mission.

Fixed-loop defects found and corrected before freeze:

1. Reordered jobs/contacts could masquerade as held-out workloads. Unordered collections are now canonicalized, with a renamed/reordered duplicate regression.
2. Equal aggregate training failures could hide sacrificing a baseline-successful mission. Such candidates are now excluded before training ranking, with an explicit swapped-success regression; held-out is not used to reselect.
3. Feedback initially exposed aggregate error only. It now returns source/mission/proposal/job-bound prediction/replay pairs and signed baseline residuals alongside separate MAEs. Missing, wrong-source or falsely-labelled measured records refuse. A1.1 training winner facing0.9 held-out replay gets no recommendation.

Synthetic replay fixtures deliberately scale predictions; they are not observed telemetry or proof of generalization. Calibration affects diagnostic duration/energy predictions only. It never changes feasibility, authority, prices, jobs, deadlines, baseline state or promotion. Unknown/live integrations remain explicitly absent.

Measured scaling.json retains1/5/10/20-job comparisons with3nodes/2contacts, traced memory and execution time. These are local observations, not SLOs. Unmeasured cost/intervention timings remain unknown. The new read-only integrated workflow runs all composed orbital suites; hosted status belongs to the PR and is not inferred from local checks.

Open gates: Claude pinned source review, Dmitry physical/isolated-fault qualification, Ronnie independent reproduction, actual visual QA and designated acceptance. Missing production capabilities: live payload/telemetry adapters, real Tool Guard integration, geometry/calibration, production metering/signing, actual control execution and spacecraft/domain qualification. Synthetic API fields and test counts do not close these gates.
