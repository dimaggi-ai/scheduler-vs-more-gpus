"""SLO-native inference under an explicit single-device service model.

Prefill is compute-bound; batched decode is a compute/HBM roofline. FCFS
prefill batches and decode iterations share one serialized device. No measured
vLLM/SGLang performance, attention kernel calibration or cache router is claimed.
"""
from dataclasses import dataclass,asdict
import math
from itertools import islice


@dataclass(frozen=True)
class Hardware:
    name: str
    compute_flops_s: float
    memory_bytes: float
    memory_bandwidth_bytes_s: float
    efficiency: float = .5

    def __post_init__(self):
        for name in ('compute_flops_s','memory_bytes','memory_bandwidth_bytes_s','efficiency'):
            value=getattr(self,name)
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0: raise ValueError(name)
        if self.efficiency>1: raise ValueError('efficiency')


@dataclass(frozen=True)
class Request:
    arrival_s: float
    input_tokens: int
    output_tokens: int
    cached_prefix_tokens: int = 0

    def __post_init__(self):
        if type(self.arrival_s) not in (int,float) or not math.isfinite(self.arrival_s) or self.arrival_s<0:
            raise ValueError('arrival_s')
        for name in ('input_tokens','output_tokens','cached_prefix_tokens'):
            if type(getattr(self,name)) is not int or getattr(self,name)<0: raise ValueError(name)
        if min(self.input_tokens,self.output_tokens)<1 or self.cached_prefix_tokens>self.input_tokens:
            raise ValueError('invalid token counts')


MAX_EXACT_BYTES = 2**53 - 1
MAX_EXPLICIT_REQUESTS = 128
MAX_EXPLICIT_OUTPUT_TOKENS = 100000


def _explicit_memory(requests, hardware, reservations, global_bytes, parameters,
                     bytes_per_parameter, kv_bytes_per_token, max_batch):
    """Validate a bounded declaration and snapshot it before simulation."""
    def integer(name, value, minimum=1):
        if type(value) is not int or not minimum <= value <= MAX_EXACT_BYTES:
            raise ValueError(name)
        return value

    if type(reservations) not in (list, tuple):
        raise ValueError('request_reservations_bytes must be a finite list or tuple')
    if len(reservations) != len(requests) or len(reservations) > MAX_EXPLICIT_REQUESTS:
        raise ValueError('reservation count')
    reservations = tuple(reservations)
    global_bytes = 0 if global_bytes is None else global_bytes
    for name, value in (('memory_bytes', hardware.memory_bytes), ('parameters', parameters),
                        ('bytes_per_parameter', bytes_per_parameter),
                        ('kv_bytes_per_token', kv_bytes_per_token)):
        integer(name, value)
    integer('workspace_headroom_bytes', global_bytes, 0)
    if max_batch > MAX_EXPLICIT_REQUESTS:
        raise ValueError('max_batch exceeds explicit-mode bound')
    weight = integer('resident weight bytes', parameters * bytes_per_parameter)
    integer('fixed reserved bytes', weight + global_bytes)
    if weight + global_bytes > hardware.memory_bytes:
        raise ValueError('fixed reservations exceed memory')
    for req, reservation in zip(requests, reservations):
        if type(req) is not Request:
            raise ValueError('explicit mode requires Request values')
        integer('request reservation bytes', reservation)
        raw = integer('raw maximum context KV bytes',
                      (req.input_tokens + req.output_tokens) * kv_bytes_per_token)
        if reservation < raw:
            raise ValueError('request reservation below raw maximum context KV')
    integer('aggregate reservation bytes', sum(reservations), 0)
    output_tokens = sum(r.output_tokens for r in requests)
    if output_tokens > MAX_EXPLICIT_OUTPUT_TOKENS:
        raise ValueError('aggregate output token bound')
    # Permanently memory-infeasible requests perform no service work.
    service_requests = [r for r, reservation in zip(requests, reservations)
                        if reservation <= hardware.memory_bytes - weight - global_bytes]
    if not service_requests:
        return reservations, global_bytes, weight
    # Bound every service step and total elapsed time before entering the loop.
    # Reserving allocator overhead does not add traffic to these raw-KV formulas.
    compute_rate = hardware.compute_flops_s * hardware.efficiency
    bandwidth = hardware.memory_bandwidth_bytes_s * hardware.efficiency
    if not all(math.isfinite(x) and x > 0 for x in (compute_rate, bandwidth)):
        raise ValueError('nonfinite or zero effective service rate')
    prefill = 2 * parameters * sum(r.input_tokens-r.cached_prefix_tokens for r in service_requests) / compute_rate
    step_bound = max(2 * parameters * max_batch / compute_rate,
                     (weight + sum((r.input_tokens+r.output_tokens)*kv_bytes_per_token
                                   for r in service_requests)) / bandwidth)
    elapsed_bound = prefill + sum(r.output_tokens for r in service_requests) * step_bound
    if not math.isfinite(elapsed_bound) or not math.isfinite(
            max((r.arrival_s for r in requests), default=0) + elapsed_bound):
        raise ValueError('nonfinite service arithmetic')
    return reservations, global_bytes, weight


def simulate(requests, hardware, *, parameters=7e9, bytes_per_parameter=2,
             kv_bytes_per_token=131072, ttft_slo_s=1., itl_slo_s=.05,
             max_batch=16, policy='decode-first', request_reservations_bytes=None,
             workspace_headroom_bytes=None):
    explicit = request_reservations_bytes is not None or workspace_headroom_bytes is not None
    requests = list(islice(requests, MAX_EXPLICIT_REQUESTS + 1)) if explicit else list(requests)
    if explicit and len(requests) > MAX_EXPLICIT_REQUESTS:
        raise ValueError('explicit request count bound')
    if policy not in ('decode-first','prefill-first'): raise ValueError('unknown policy')
    if type(max_batch) is not int or max_batch<1: raise ValueError('max_batch')
    if explicit:
        for name, value in (('parameters', parameters), ('bytes_per_parameter', bytes_per_parameter),
                            ('kv_bytes_per_token', kv_bytes_per_token)):
            if type(value) is not int or not 1 <= value <= MAX_EXACT_BYTES:
                raise ValueError(name)
    for name,value in dict(parameters=parameters,bytes_per_parameter=bytes_per_parameter,
                           kv_bytes_per_token=kv_bytes_per_token,ttft_slo_s=ttft_slo_s,itl_slo_s=itl_slo_s).items():
        try:
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0: raise ValueError(name)
        except OverflowError:
            if explicit: raise ValueError(name) from None
            raise
    weight=parameters*bytes_per_parameter
    if explicit:
        reservations, global_bytes, weight = _explicit_memory(
            requests, hardware, request_reservations_bytes, workspace_headroom_bytes,
            parameters, bytes_per_parameter, kv_bytes_per_token, max_batch)
    elif weight>=hardware.memory_bytes: raise ValueError('weights leave no KV memory')
    ordered=sorted(enumerate(requests),key=lambda x:(x[1].arrival_s,x[0]))
    pending=[];active=[];done=[];cursor=0;now=0.;peak_concurrency=0
    remaining=hardware.memory_bytes-weight-(global_bytes if explicit else 0)
    budget=remaining
    peak_reserved=0
    # Reserve each admitted request's maximum KV allocation, including cached
    # prefix storage; cache hit saves prefill work but never magically frees KV.
    while cursor<len(ordered) or pending or active:
        if not pending and not active and cursor<len(ordered): now=max(now,ordered[cursor][1].arrival_s)
        while cursor<len(ordered) and ordered[cursor][1].arrival_s<=now:
            ident,req=ordered[cursor];cursor+=1
            memory=reservations[ident] if explicit else (req.input_tokens+req.output_tokens)*kv_bytes_per_token
            if memory>remaining and not active:
                done.append(dict(id=ident,rejected=True,reason='request exceeds available KV capacity'));continue
            pending.append(dict(id=ident,request=req,reserved=memory,tokens=0,emitted=[]))
        # decode-first admits at most one prefill batch between decode rounds.
        # Both policies use the same max batch and memory envelope.
        can_prefill=pending and len(active)<max_batch and pending[0]['reserved']<=remaining
        if can_prefill:
            admitted=[]
            while pending and len(active)+len(admitted)<max_batch and pending[0]['reserved']<=remaining:
                job=pending.pop(0);remaining-=job['reserved'];admitted.append(job)
                if explicit: peak_reserved=max(peak_reserved,budget-remaining)
                if policy=='decode-first' and active: break
            prefill_tokens=sum(j['request'].input_tokens-j['request'].cached_prefix_tokens for j in admitted)
            now+=2*parameters*prefill_tokens/(hardware.compute_flops_s*hardware.efficiency)
            active.extend(admitted)
            peak_concurrency=max(peak_concurrency,len(active))
        if active:
            context=sum(j['request'].input_tokens+j['tokens'] for j in active)
            compute=2*parameters*len(active)/(hardware.compute_flops_s*hardware.efficiency)
            memory=(weight+context*kv_bytes_per_token)/(hardware.memory_bandwidth_bytes_s*hardware.efficiency)
            now+=max(compute,memory)
            for job in list(active):
                job['tokens']+=1;job['emitted'].append(now)
                if job['tokens']==job['request'].output_tokens:
                    active.remove(job);remaining+=job['reserved']
                    times=job['emitted'];ttft=times[0]-job['request'].arrival_s
                    worst_itl=max((b-a for a,b in zip(times,times[1:])),default=0.)
                    done.append(dict(id=job['id'],rejected=False,ttft_s=ttft,max_itl_s=worst_itl,
                                     output_tokens=job['tokens'],slo_met=ttft<=ttft_slo_s and worst_itl<=itl_slo_s))
        elif pending and pending[0]['reserved']>remaining:
            job=pending.pop(0);done.append(dict(id=job['id'],rejected=True,reason='KV capacity'))
    horizon=now-min((r.arrival_s for r in requests),default=0)
    successful=[r for r in done if not r['rejected'] and r['slo_met']]
    result = dict(evidence_class='simulated',input_class='scenario',hardware=asdict(hardware),policy=policy,
                peak_concurrency=peak_concurrency,makespan_s=horizon,requests=sorted(done,key=lambda r:r['id']),
                slo_attainment=len(successful)/max(1,len(done)),
                slo_goodput_output_tokens_s=sum(r['output_tokens'] for r in successful)/horizon if horizon>0 else 0.,
                assumptions=['FCFS admission; no request dropping except memory infeasibility; finite-window queueing.',
                             'Single device; no tensor-parallel/network/disaggregated serving penalties.',
                             'Dense 2*parameters FLOPs/token approximation; no quadratic prefill attention cost.',
                             'Decode reads weights once per batch and KV per context; no kernel-level validation.',
                             'Prefix hits are declared exact reused tokens; no cache eviction or live router.',
                             'Output counts only requests meeting TTFT and every modeled ITL bound.',
                             'Hardware efficiency and KV footprint are assumptions; not measured service capacity.'])
    if explicit:
        if not all(math.isfinite(value) for value in
                   (result['makespan_s'], result['slo_goodput_output_tokens_s'],
                    *(r[key] for r in done if not r['rejected'] for key in ('ttft_s','max_itl_s')))):
            raise ValueError('nonfinite service result')
        result['memory_accounting'] = dict(
            basis='declared_per_request_reservations', usable_hbm_bytes=hardware.memory_bytes,
            resident_weights_bytes=weight, workspace_headroom_bytes=global_bytes,
            kv_budget_bytes=budget, request_reservations_bytes=list(reservations),
            peak_reserved_bytes=peak_reserved, final_remaining_bytes=remaining)
        result['assumptions'] += [
            'Explicit reservations affect admission only; allocator overhead timing costs are not modeled.',
            'FCFS head-of-line blocking means observed peak is not a packing limit.',
            'Reservation declarations are not authenticated or hardware-qualified.']
    return result
