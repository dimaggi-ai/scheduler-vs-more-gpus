"""Explicit single-job synthetic scenarios, no inferred orbital geometry."""
from ..fixtures import demo as mission_demo

def demo():
    m=mission_demo();m['jobs']=m['jobs'][:1]
    replay={}
    for role,node in (('origin',m['origin']),('destination',m['destination'])):
        replay[role]=dict(policy=dict(version='no-periodic-checkpoint-v1',checkpoint_every_work_s=None,checkpoint_duration_s=2,restart_duration_s=2),power_kw=dict(productive=m['compute'][node]['power_kw'],checkpoint=1,restart=1,down=0),heat_w=dict(productive=m['compute'][node]['heat_w'],checkpoint=50,restart=10,down=70),provenance=dict(kind='synthetic',source='declared integration fixture',licence='CC0-1.0',generated_on='2026-11-05'))
    return dict(schema='capacity-orbital/checkpoint-mission-v2',id='checkpoint-mission-demo',mission=m,replay=replay)

def request(route='hybrid'):
    return dict(schema='capacity-orbital/checkpoint-mission-tool-v2',id='demo-plan',tool='plan',input=dict(scenario=demo(),route=route))
