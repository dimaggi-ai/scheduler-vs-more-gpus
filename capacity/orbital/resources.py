"""Transactional reservations for one serial compute lane per node."""
from copy import deepcopy
from .economics import compute_cost_usd


class Refusal(ValueError):
    pass


def empty_state(scenario):
    return {'nodes': {name: {'free_s': 0.0, 'energy_kwh': 0.0} for name in scenario['nodes']},
            'contacts': [c['start_s'] for c in scenario['contacts']],
            'contact_ends': tuple(c['end_s'] for c in scenario['contacts']), 'contact_updates': {}, 'events': []}


def trial(state):
    # A refused plan commits no reservations. This is planning, not consumed runtime.
    return {'nodes': deepcopy(state['nodes']), 'contacts': state['contacts'],
            'contact_ends': state['contact_ends'], 'contact_updates': {}, 'events': []}


def compute(scenario, state, job, node_name, earliest, duration):
    node = scenario['nodes'][node_name]
    resource = state['nodes'][node_name]
    for actual, limit, reason in ((job['memory_gb'], node['memory_gb'], 'memory'),
                                  (job['power_kw'], node['max_power_kw'], 'power'),
                                  (job['power_kw'], node['max_heat_kw'], 'thermal')):
        if actual > limit:
            raise Refusal(node_name + ': ' + reason + ' envelope exceeded')
    energy = job['power_kw'] * duration / 3600
    if resource['energy_kwh'] + energy > node['energy_budget_kwh']:
        raise Refusal(node_name + ': energy budget exceeded')
    start = max(earliest, resource['free_s'])
    end = start + duration
    if end > job['deadline_s']:
        raise Refusal(node_name + ': deadline exceeded')
    cost = compute_cost_usd(node, duration, energy)
    resource['free_s'] = end
    resource['energy_kwh'] += energy
    state['events'].append(dict(job_id=job['id'], kind='compute', resource=node_name,
                                start_s=start, end_s=end, energy_kwh=energy, cost_usd=cost))
    return end
