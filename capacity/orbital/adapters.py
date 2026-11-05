"""Synthetic fixture adapters share one scenario contract. No vendor SDK or IO."""
from .contracts import SCHEMA


def synthetic(adapter='continuous', jobs=3):
    if adapter not in ('continuous', 'intermittent'):
        raise ValueError('unknown synthetic adapter')
    if isinstance(jobs, bool) or not isinstance(jobs, int) or not 1 <= jobs <= 10000:
        raise ValueError('jobs must be an integer in [1, 10000]')
    horizon = max(600, jobs * 200)
    node = dict(memory_gb=16, max_power_kw=2, max_heat_kw=2, energy_budget_kwh=jobs,
                compute_usd_per_hour=2, electricity_usd_per_kwh=0.2)
    contacts = ([dict(id='continuous', start_s=0, end_s=horizon, goodput_gbps=1, usd_per_gb=0.2)]
                if adapter == 'continuous' else [dict(id=f'pass-{i}', start_s=i*200+60, end_s=i*200+160,
                                                      goodput_gbps=1, usd_per_gb=0.2) for i in range(jobs)])
    return dict(schema=SCHEMA, name='Synthetic ' + adapter + ' EO comparison', horizon_s=horizon,
                provenance=dict(kind='synthetic', source='DIMAGGI task105 hand-computable fixture, not vendor data',
                                licence='MIT (repository licence)', generated_on='2026-11-05'),
                nodes={'orbital': dict(node), 'ground': dict(node)}, contacts=contacts,
                jobs=[dict(id=f'image-{i:05}', release_s=i*200, deadline_s=i*200+180,
                           raw_gb=10, result_gb=0.1, compressed_gb=1, memory_gb=4, power_kw=1,
                           ground_s=20, onboard_s=30, preprocess_s=10, hybrid_ground_s=10,
                           required_quality=0.95, onboard_quality=0.98, hybrid_quality=0.98) for i in range(jobs)])
