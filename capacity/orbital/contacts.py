"""One shared downlink terminal with preemptible transfers across contact windows."""
from .economics import transfer_cost_usd
from .resources import Refusal
from bisect import bisect_right


def transfer(scenario, state, job, earliest, gb):
    remaining = gb
    end = earliest
    for i in range(bisect_right(state['contact_ends'], earliest), len(scenario['contacts'])):
        c = scenario['contacts'][i]
        if remaining <= 0:
            break
        start = max(earliest, state['contact_updates'].get(i, state['contacts'][i]), c['start_s'])
        stop = min(c['end_s'], job['deadline_s'])
        if start >= stop:
            continue
        capacity_gb = (stop - start) * c['goodput_gbps'] / 8
        amount = min(remaining, capacity_gb)
        # Float rounding can put the recomputed end past the window; never report past stop.
        end = min(start + amount * 8 / c['goodput_gbps'], stop)
        state['contact_updates'][i] = end
        state['events'].append(dict(job_id=job['id'], kind='downlink', resource=c['id'],
                                    start_s=start, end_s=end, gb=amount, cost_usd=transfer_cost_usd(c, amount)))
        remaining -= amount
    if remaining > 0:
        raise Refusal('insufficient contact capacity before deadline')
    return end
