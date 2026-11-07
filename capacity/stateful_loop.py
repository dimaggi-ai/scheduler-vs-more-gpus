"""Synthetic dependency-only lower bounds, with unlimited stage resources.

No scheduler, execution, calibration, measurement or crash recovery is performed.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
import hashlib
import json

MAX_STAGES = 256
MAX_EDGES = 4096
MAX_ITERATIONS = 1_000_000
KINDS = frozenset({"host", "compute", "memory", "fabric", "state"})


@dataclass(frozen=True)
class Stage:
    id: str
    kind: str
    duration_seconds: float | None
    dependencies: tuple[str, ...] = ()
    provenance_class: str = "synthetic"
    source_id: str = ""


@dataclass(frozen=True)
class SyntheticProvenance:
    fixture_id: str
    source: str
    licence: str
    date: str
    sha256: str


@dataclass(frozen=True)
class Loop:
    stages: tuple[Stage, ...]
    persisted_completion_id: str
    iterations: int
    workload: str
    quality: str
    protocol: str
    provenance: SyntheticProvenance


@dataclass(frozen=True)
class Analysis:
    elapsed_lower_bound_s: float
    total_lower_bound_s: float
    serial_sum_s: float
    total_serial_sum_s: float
    graph_context_sha256: str
    input_sha256: str
    stage_slack_seconds: tuple[tuple[str, float], ...]
    iteration_semantics: str
    critical_path: tuple[str, ...]
    stage_finish_seconds: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Comparison:
    baseline: Analysis
    candidate: Analysis
    lower_bound_speedup: float
    lower_bound_saved_seconds: float


def _text(value: object) -> bool:
    return (type(value) is str and 0 < len(value) <= 512
            and value == value.strip() and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def _finite(value) -> float:
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError("output overflow") from exc
    if not math.isfinite(value):
        raise ValueError("nonfinite arithmetic result")
    return value


def _record_hash(loop: Loop, *, include_durations: bool = False) -> str:
    p = loop.provenance
    signature = (sorted((s.id, s.kind, sorted(s.dependencies), s.provenance_class,
                         s.source_id) for s in loop.stages),
                 loop.persisted_completion_id, loop.iterations, loop.workload,
                 loop.quality, loop.protocol,
                 (p.fixture_id, p.source, p.licence, p.date, p.sha256))
    if include_durations:
        signature += (sorted((s.id, s.duration_seconds) for s in loop.stages),)
    return hashlib.sha256(json.dumps(signature, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def analyze(loop: Loop) -> Analysis:
    """Calculate an ideal DAG makespan; each iteration waits for state persistence.

    Every duration must be explicitly positive; no zero or missing defaults.
    Raises ValueError on invalid/unknown input; never partially evaluates it.
    """
    return _analyze(loop)[0]


def _analyze(loop: Loop) -> tuple[Analysis, Fraction]:
    if type(loop) is not Loop or type(loop.stages) is not tuple:
        raise ValueError("expected immutable Loop and stage tuple")
    if not 1 <= len(loop.stages) <= MAX_STAGES:
        raise ValueError("stage count outside bounds")
    if type(loop.iterations) is not int or not 1 <= loop.iterations <= MAX_ITERATIONS:
        raise ValueError("iteration count outside bounds")
    if not all(_text(x) for x in (loop.workload, loop.quality, loop.protocol,
                                  loop.persisted_completion_id)):
        raise ValueError("explicit context and completion required")
    p = loop.provenance
    if type(p) is not SyntheticProvenance or not all(
        _text(x) for x in (p.fixture_id, p.source, p.licence, p.date, p.sha256)
    ):
        raise ValueError("synthetic fixture provenance required")
    # Provenance strings are declarations, not verified dates, hashes or signatures.
    nodes = {}
    durations = {}
    edges = 0
    for stage in loop.stages:
        if type(stage) is not Stage or not _text(stage.id) or stage.id in nodes:
            raise ValueError("invalid or duplicate stage")
        if type(stage.kind) is not str or stage.kind not in KINDS:
            raise ValueError("unsupported stage kind")
        d = stage.duration_seconds
        if type(d) not in (int, float):
            raise ValueError("explicit numeric duration required")
        try:
            d = float(d)
        except OverflowError as exc:
            raise ValueError("duration overflow") from exc
        if not math.isfinite(d) or d <= 0:
            raise ValueError("duration must be finite and positive")
        if type(stage.provenance_class) is not str or stage.provenance_class != "synthetic" or not _text(stage.source_id):
            raise ValueError("each duration requires synthetic provenance and source id")
        deps = stage.dependencies
        if type(deps) is not tuple or len(deps) > MAX_STAGES:
            raise ValueError("bounded immutable dependencies required")
        if not all(_text(x) for x in deps) or len(set(deps)) != len(deps):
            raise ValueError("invalid or duplicate dependencies")
        edges += len(deps)
        if edges > MAX_EDGES:
            raise ValueError("too many edges")
        nodes[stage.id] = stage
        durations[stage.id] = Fraction.from_float(d)
    if {s.kind for s in nodes.values()} != KINDS:
        raise ValueError("host, compute, memory, fabric and state must be explicit")
    final = loop.persisted_completion_id
    if final not in nodes or nodes[final].kind != "state":
        raise ValueError("completion must be a state stage")
    if any(dep not in nodes for s in nodes.values() for dep in s.dependencies):
        raise ValueError("unknown dependency")
    ancestors = set()
    stack = [final]
    while stack:
        node = stack.pop()
        if node not in ancestors:
            ancestors.add(node)
            stack.extend(nodes[node].dependencies)
    if ancestors != set(nodes):
        raise ValueError("all stages must contribute to persisted completion")
    successors = {n: [] for n in nodes}
    for n, stage in nodes.items():
        for dep in stage.dependencies:
            successors[dep].append(n)
    if {n for n in nodes if not successors[n]} != {final}:
        raise ValueError("exactly one state completion sink required")
    pending = set(nodes)
    order = []
    finishes = {}
    paths = {}
    while pending:
        ready = sorted(n for n in pending if all(d in finishes for d in nodes[n].dependencies))
        if not ready:
            raise ValueError("dependency cycle")
        for n in ready:
            deps = nodes[n].dependencies
            # Lexically smallest full critical path wins exact duration ties.
            parent = min(deps, key=lambda d: (-finishes[d], paths[d])) if deps else None
            finishes[n] = (finishes[parent] if parent else Fraction(0)) + durations[n]
            order.append(n)
            paths[n] = (paths[parent] if parent else ()) + (n,)
            pending.remove(n)
    duration = finishes[final]
    if duration <= 0:
        raise ValueError("zero-total graph")
    total = _finite(duration * loop.iterations)
    serial = sum(durations.values(), Fraction(0))
    latest_start = {}
    slack = {}
    for n in reversed(order):
        latest_finish = min(latest_start[k] for k in successors[n]) if successors[n] else duration
        latest_start[n] = latest_finish - durations[n]
        earliest_start = max((finishes[d] for d in nodes[n].dependencies), default=Fraction(0))
        slack[n] = _finite(latest_start[n] - earliest_start)
    result = Analysis(_finite(duration), total, _finite(serial), _finite(serial * loop.iterations),
                    _record_hash(loop), _record_hash(loop, include_durations=True), tuple(sorted(slack.items())),
                    "sequential_persisted_completion_barrier", paths[final],
                    tuple((n, _finite(finishes[n])) for n in sorted(finishes)))
    return result, duration * loop.iterations


def compare(baseline: Loop, candidate: Loop) -> Comparison:
    """Compare matched synthetic declarations differing only in stage durations."""
    (before, before_exact), (after, after_exact) = _analyze(baseline), _analyze(candidate)
    if before.graph_context_sha256 != after.graph_context_sha256:
        raise ValueError("comparison may change durations only")
    speedup = _finite(before_exact / after_exact)
    if speedup <= 0:
        raise ValueError("speedup underflow")
    return Comparison(before, after, speedup, _finite(before_exact - after_exact))
