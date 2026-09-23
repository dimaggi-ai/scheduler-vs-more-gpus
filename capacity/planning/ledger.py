"""Transactional, immutable DuckDB snapshots and explicit incomplete reports."""
from pathlib import Path
import json
import math
import duckdb

from capacity.report import canonical
from .model import ACCOUNT, validate_plan, validate_actual, provenance

SQL = Path(__file__).parent / 'sql'
FIELDS = ('hour', *ACCOUNT, 'rate_usd_per_allocated_gpu_h')


class Ledger:
    def __init__(self, path=':memory:'):
        self.db = duckdb.connect(str(path))
        self.db.execute((SQL / 'schema.sql').read_text())

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def ingest(self, plan, actual=None):
        validate_plan(plan)
        if actual is not None:
            validate_actual(plan, actual)
        self.db.execute('BEGIN TRANSACTION')
        try:
            self._insert(plan, 'plan')
            if actual is not None:
                self._insert(actual, 'actual')
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def _insert(self, artifact, kind):
        identifier = artifact[f'{kind}_id']
        payload = canonical(artifact)
        prior = self.db.execute('SELECT payload FROM artifacts WHERE id=?', [identifier]).fetchone()
        if prior:
            if prior[0] != payload:
                raise ValueError('immutable artifact collision')
            return  # exact repeated ingestion is idempotent
        self.db.execute('INSERT INTO artifacts VALUES (?, ?, ?, ?)',
                        [identifier, kind, artifact['plan_id'], payload])
        if kind == 'plan':
            prefix, table = [identifier], 'plans'
        else:
            prefix, table = [identifier, artifact['plan_id']], 'actuals'
        records = [prefix + [r[k] for k in FIELDS] for r in artifact['rows']]
        if records:
            marks = ','.join('?' for _ in records[0])
            self.db.executemany(f'INSERT INTO {table} VALUES ({marks})', records)

    def report(self, actual_id):
        artifact = self.db.execute("SELECT plan_id,payload FROM artifacts WHERE id=? AND kind='actual'", [actual_id]).fetchone()
        if artifact is None:
            raise ValueError('unknown actual artifact')
        plan_id, payload = artifact
        actual = json.loads(payload)
        stored_plan = self.db.execute("SELECT payload FROM artifacts WHERE id=? AND kind='plan'", [plan_id]).fetchone()
        if stored_plan is None:
            raise ValueError('ledger missing parent plan')
        plan = json.loads(stored_plan[0])
        validate_actual(plan, actual)
        # Detect materialized-table corruption rather than trusting a valid JSON manifest.
        for table, key, value, source in (('plans', 'plan_id', plan_id, plan),
                                           ('actuals', 'actual_id', actual_id, actual)):
            columns = ','.join(FIELDS)
            materialized = self.db.execute(f'SELECT {columns} FROM {table} WHERE {key}=? ORDER BY hour', [value]).fetchall()
            expected_records = [tuple(r[k] for k in FIELDS) for r in source['rows']]
            if materialized != expected_records:
                raise ValueError('ledger rows differ from immutable artifact')
        counts = self.db.execute((SQL / 'quality.sql').read_text(), [plan_id, actual_id, actual_id]).fetchone()
        expected, observed, orphans = counts
        cursor = self.db.execute((SQL / 'variance.sql').read_text(), [actual_id, plan_id])
        names = [d[0] for d in cursor.description]
        rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        missing = [r['hour'] for r in rows if r['missing']]
        complete = expected == observed and not missing and not orphans
        summary = None
        if complete:
            summary = {k: math.fsum(r[k] for r in rows) for k in names if k not in ('hour', 'missing', 'max_absolute_change')}
            summary['productive_reconciliation_residual_gpu_h'] = summary['productive_delta_gpu_h'] - sum(summary[k] for k in ('nominal_effect_gpu_h', 'availability_effect_gpu_h', 'idle_effect_gpu_h', 'reservation_effect_gpu_h', 'training_loss_effect_gpu_h'))
            summary['cost_reconciliation_residual_usd'] = summary['cost_delta_usd'] - summary['allocation_cost_effect_usd'] - summary['rate_cost_effect_usd']
            if abs(summary['productive_reconciliation_residual_gpu_h']) > 1e-5 or abs(summary['cost_reconciliation_residual_usd']) > 1e-5:
                raise ValueError('variance decomposition failed reconciliation')
        status = 'incomplete' if not complete else ('no_change' if max(r['max_absolute_change'] for r in rows) < 1e-8 else 'changed')
        return {'schema': 'capacity-variance/v1', 'status': status, 'plan_id': plan_id,
                'actual_id': actual_id, 'scenario': actual['scenario'], 'evidence_kind': 'synthetic',
                'execution_authority': False, 'analysis_provenance': provenance(), 'duckdb': duckdb.__version__, 'expected_hours': expected, 'observed_hours': observed,
                'missing_hours': missing, 'summary': summary, 'hourly': rows,
                'limits': ['Accounting attribution is not causal inference.',
                           'Cost is a synthetic allocated-GPU-hour tariff, not energy spend, TCO or savings.',
                           'Inference demand error is separate from additive capacity-loss effects.',
                           'Negative training productivity can reverse progress from earlier hours.',
                           'Missing actuals suppress all aggregate variance totals.']}
