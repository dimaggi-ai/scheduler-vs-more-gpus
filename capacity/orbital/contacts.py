"""One shared downlink terminal with preemptible transfers across contact windows."""
from .resources import Refusal


def transfer(scenario, state, job, earliest, gb):
    remaining = gb
    end = earliest
    for i, c in enumerate(scenario['contacts']):
        if remaining <= 0:
            break
        start = max(earliest, state['contacts'][i], c['start_s'])
        stop = min(c['end_s'], job['deadline_s'])
        if start >= stop:
            continue
        capacity_gb = (stop - start) * c['goodput_gbps'] / 8
        amount = min(remaining, capacity_gb)
        end = start + amount * 8 / c['goodput_gbps']
        state['contacts'][i] = end
        state['events'].append(dict(job_id=job['id'], kind='downlink', resource=c['id'],
                                    start_s=start, end_s=end, gb=amount, cost_usd=amount * c['usd_per_gb']))
        remaining -= amount
    if remaining > 0:
        raise Refusal('insufficient contact capacity before deadline')
    return end
