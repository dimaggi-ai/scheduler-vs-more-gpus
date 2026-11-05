"""Explicit synthetic contacts, not orbital geometry or measured link data."""
from .contracts import SCHEMA

def demo(kind='relay'):
    def node():return dict(jurisdiction='synthetic-zone',buffer_gb=2,commissioned_s=0,retired_s=300,unavailable=[],preserve_storage=False,capacity_kw=1,terminals=['radio'],tx_kw=1,rx_kw=1,tx_heat_w=100,rx_heat_w=100)
    def contact(name,source,destination,start,end):return dict(id=name,link_id=name,source=source,destination=destination,source_terminal='radio',destination_terminal='radio',start_s=start,end_s=end,goodput_gbps=1,propagation_s=0,cost_per_gb=.1)
    s=dict(schema=SCHEMA,name='Synthetic relay',horizon_s=300,provenance=dict(kind='synthetic',source='hand arithmetic fixture; no ephemeris',licence='repository licence',generated_on='2026-11-05'),nodes={x:node() for x in ('A','B','G')},contacts=[contact('AB','A','B',0,8),contact('BG','B','G',10,18)],jobs=[dict(id='job-1',source='A',destination='G',release_s=0,deadline_s=30,data_gb=1,allowed_jurisdictions=['synthetic-zone'])])
    if kind=='outage':s['nodes']['B']['unavailable']=[dict(start_s=8,end_s=10)]
    elif kind=='corrected':s['nodes']['B']['unavailable']=[dict(start_s=8,end_s=10)];s['nodes']['B']['preserve_storage']=True
    elif kind=='contention':s['jobs'].append(dict(s['jobs'][0],id='job-2'))
    elif kind!='relay':raise ValueError('unknown demo')
    return s

def dynamics_fixture(scenario,constrained=False):
    nodes={}
    for name in scenario['nodes']:
        nodes[name]=dict(battery=dict(capacity_kwh=1,initial_kwh=.001 if constrained else 1,reserve_kwh=0,charge_efficiency=1,discharge_efficiency=1,max_charge_kw=10,max_discharge_kw=10),thermal=dict(initial_k=300,maximum_k=400,heat_capacity_j_per_k=10000,conductance_w_per_k=100),profiles=[dict(start_s=0,end_s=scenario['horizon_s'],solar_kw=0,background_kw=0,background_heat_w=0,sink_k=300)])
    return dict(schema='capacity-orbital/dynamics-v1',name='Synthetic transfer energy',horizon_s=scenario['horizon_s'],provenance=scenario['provenance'].copy(),nodes=nodes)
