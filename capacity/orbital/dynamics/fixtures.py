"""Authored synthetic hand-oracle fixtures, not vendor data."""
from .contracts import SCENARIO,PROPOSAL


def demo(kind='nominal'):
    if kind not in ('nominal','reserve','thermal','corrected'):
        raise ValueError('unknown dynamics demo')
    horizon=3600 if kind=='nominal' else 1800
    battery=dict(capacity_kwh=2,initial_kwh=1,reserve_kwh=.2,charge_efficiency=1,
                 discharge_efficiency=1,max_charge_kw=2,max_discharge_kw=2)
    thermal=dict(initial_k=300,maximum_k=315,heat_capacity_j_per_k=10000,conductance_w_per_k=100)
    profiles=[dict(start_s=0,end_s=1800,solar_kw=0,background_kw=.2,background_heat_w=1000,sink_k=280)]
    events=[]
    if kind=='nominal':
        profiles.append(dict(start_s=1800,end_s=3600,solar_kw=0,background_kw=0,background_heat_w=1000,sink_k=280))
        events=[dict(id='image-analysis',node='orbital',kind='compute',start_s=1800,end_s=3600,power_kw=1,heat_w=2000)]
    elif kind in ('reserve','corrected'):
        battery['initial_kwh']=.4
        profiles[0]['background_kw']=1 if kind=='reserve' else .2
    else:
        profiles[0].update(background_kw=0,background_heat_w=3000)
        thermal['maximum_k']=305
    scenario=dict(schema=SCENARIO,name='Synthetic '+kind+' coupled-state case',horizon_s=horizon,
                  provenance=dict(kind='synthetic',source='DIMAGGI task106 hand-calculation fixture',
                                  licence='MIT (repository licence)',generated_on='2026-11-05'),
                  nodes={'orbital':dict(battery=battery,thermal=thermal,profiles=profiles)})
    proposal=dict(schema=PROPOSAL,id='demo-'+kind,at_s=0,events=events,
                  authority=dict(disposition='allowed',valid_from_s=0,expires_s=horizon,scope='synthetic-evaluation'))
    return dict(scenario=scenario,proposal=proposal)
