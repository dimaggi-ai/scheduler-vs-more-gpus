"""Evidence labels and deterministic planning receipts. Pure; no IO.

Named evidence_record because the directory `evidence/` holds the checked-in outputs.
"""
from . import VERSION
from .contracts import digest

RECEIPT_SCHEMA = 'capacity-orbital/receipt-v2'
CLASSIFICATION = 'synthetic offline plan; not measured execution or flight qualification'
ASSUMPTIONS = ('All jobs originate in space and results terminate on the ground.',
               'Ground quality 1.0 is a synthetic reference assumption, not measured perfect AI accuracy.',
               'Each route is a separate counterfactual with the same workload and resource inputs.',
               'One serial compute lane per node; one shared downlink terminal.',
               'One assumed job power_kw applies on both nodes; hardware-specific power profiles are not modeled.',
               'Release-time then job-id greedy planning; no optimality guarantee.',
               'Static power and heat rejection envelopes, total compute-energy budgets; no orbital/thermal dynamics.',
               'Transfer energy, lifecycle capex, qualification, radiation and unplanned runtime failures excluded.',
               'Refused plans reserve nothing; no claim that failed execution is free.',
               'Receipts are deterministic planning IDs, not signatures or production metering.')


def validate_source(value):
    if value is not None and (not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('source_sha256 must be lowercase hex SHA-256 or None (unbound API call)')


def receipt_id(input_sha256, source_sha256, row, events):
    return digest({'schema': RECEIPT_SCHEMA, 'input_sha256': input_sha256,
                   'source_sha256': source_sha256, 'version': VERSION,
                   'outcome': {k: v for k, v in row.items() if k != 'receipt_id'}, 'events': events})
