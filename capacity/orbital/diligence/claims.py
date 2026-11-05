"""Synthetic mathematical consistency screens, never physical certification."""
from .contracts import fields,number,text,provenance,Refuse,finite_result

SIGMA=5.670374419e-8  # W m^-2 K^-4, Stefan-Boltzmann constant
SCHEMA='capacity-orbital/claim-v1'
PARAMS={
    'power':('generation_kw auxiliary_kw compute_kw conversion_efficiency',{}),
    'battery':('initial_kwh reserve_kwh load_kw discharge_efficiency claimed_duration_h',{}),
    'link':('data_gb goodput_gbps window_s claimed_duration_s',{}),
    'thermal':('heat_w temperature_k sink_temperature_k emissivity fin_efficiency absorbed_flux_w_m2 area_m2 area_basis view_factor emitting_faces',{}),
}


def check_claim(claim):
    fields(claim,'schema name kind parameters provenance','claim')
    if claim['schema']!=SCHEMA:raise Refuse('UNSUPPORTED_SCHEMA','unsupported claim schema')
    text(claim['name'],'name');text(claim['kind'],'kind');provenance(claim['provenance'])
    p=claim['parameters']
    if not isinstance(p,dict):raise Refuse('INVALID_ARGUMENT','parameters must be an object')
    result=dict(schema='capacity-orbital/claim-result-v1',model=claim['kind']+'-synthetic-screen-v1',
                status='unknown',reason_code='UNSUPPORTED_MODEL',prediction=None,missing_assumptions=[],
                assumptions=p,provenance=claim['provenance'],limitations=[
                    'Consistency only against supplied mathematical assumptions; not physical verification or vendor certification.',
                    'No permission, flight qualification, reliability prediction or production guarantee is granted.',
                    'Transient thermal behaviour and radiation qualification are unsupported.'])
    if claim['kind'] not in PARAMS:
        # Unsupported physics never receives a favourable outcome. Validate basic
        # numeric domains even though no model-specific assumptions are known.
        for key,value in p.items():
            if isinstance(value,(int,float)) or isinstance(value,bool):number(value,key)
            elif value is not None and not isinstance(value,str):raise Refuse('INVALID_ARGUMENT','unsupported parameter type')
        return result
    allowed=set(PARAMS[claim['kind']][0].split())
    if set(p)-allowed:raise Refuse('INVALID_ARGUMENT','unknown parameter name')
    for key,value in p.items():
        if value is None:continue
        if key=='area_basis':
            if value not in ('emitting','panel_footprint'):raise Refuse('INVALID_ARGUMENT','unknown area basis')
        else:
            number(value,key,positive=key in ('load_kw','goodput_gbps','temperature_k','area_m2','discharge_efficiency','emissivity','fin_efficiency','view_factor','conversion_efficiency'),
                   maximum=1 if key in ('discharge_efficiency','emissivity','fin_efficiency','view_factor','conversion_efficiency') else 2 if key=='emitting_faces' else None,
                   integer=key=='emitting_faces')
            if key=='emitting_faces' and value not in (1,2):raise Refuse('INVALID_ARGUMENT','one or two emitting faces required')
    required=allowed.copy()
    if claim['kind']=='thermal' and p.get('area_basis')=='emitting':
        required.remove('emitting_faces')
        if 'emitting_faces' in p:raise Refuse('INVALID_ARGUMENT','emitting_faces applies only to panel footprint')
    missing=sorted(k for k in required if p.get(k) is None)
    if missing:
        result.update(reason_code='MISSING_ASSUMPTIONS',missing_assumptions=missing)
        return result
    kind=claim['kind']
    if kind=='power':
        available=p['generation_kw']*p['conversion_efficiency']-p['auxiliary_kw']
        prediction=dict(available_compute_kw=available,margin_kw=available-p['compute_kw'])
        okay=available>=p['compute_kw']
        result['limitations'].append('Instantaneous power balance only; generation, conversion efficiency and auxiliary load are supplied assumptions.')
    elif kind=='battery':
        if p['reserve_kwh']>p['initial_kwh']:
            result.update(status='inconsistent',reason_code='INSUFFICIENT_ENVELOPE',prediction=dict(usable_duration_h=0.0,reserve_deficit_kwh=p['reserve_kwh']-p['initial_kwh']))
            return result
        duration=(p['initial_kwh']-p['reserve_kwh'])*p['discharge_efficiency']/p['load_kw']
        if p['initial_kwh']>p['reserve_kwh'] and duration==0:
            raise Refuse('ARITHMETIC_RESOLUTION','positive battery duration underflows')
        prediction=dict(usable_duration_h=duration,margin_h=duration-p['claimed_duration_h'])
        okay=p['claimed_duration_h']<=duration
        result['limitations'].append('Constant supplied load includes all assumed drains; no recharge, ageing, power limit or temperature dependence.')
    elif kind=='link':
        duration=p['data_gb']*8/p['goodput_gbps'];capacity=p['window_s']*p['goodput_gbps']/8
        if p['data_gb']>0 and duration==0:
            raise Refuse('ARITHMETIC_RESOLUTION','positive transfer duration underflows')
        prediction=dict(required_duration_s=duration,capacity_gb=capacity,
                        window_margin_s=p['window_s']-duration,claim_margin_s=p['claimed_duration_s']-duration)
        okay=duration<=p['window_s'] and duration<=p['claimed_duration_s']
        result['limitations'].append('Decimal GB/Gbps; supplied effective goodput already includes overhead; no propagation delay, contention, outage or route model.')
    else:
        area=p['area_m2']*(p['emitting_faces'] if p['area_basis']=='panel_footprint' else 1)
        flux=SIGMA*p['emissivity']*p['fin_efficiency']*p['view_factor']*(p['temperature_k']**4-p['sink_temperature_k']**4)
        rejected=area*(flux-p['absorbed_flux_w_m2'])
        prediction=dict(total_emitting_area_m2=area,radiative_flux_w_m2=flux,net_heat_rejection_w=rejected,
                        margin_w=rejected-p['heat_w'])
        okay=rejected>=p['heat_w']
        result['limitations'].append('Steady uniform temperature and supplied view factor; absorbed flux per emitting area; no transient storage, pump/coolant limit or mission environment validation.')
    result.update(status='consistent' if okay else 'inconsistent',reason_code='WITHIN_STATED_MODEL' if okay else 'INSUFFICIENT_ENVELOPE',prediction=prediction)
    return finite_result(result)
