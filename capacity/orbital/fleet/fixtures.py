def demo():
    return dict(schema='capacity-orbital/fleet-v1',id='synthetic-fleet',horizon_years=3,demand_kw=[16,16,16],provenance=dict(kind='synthetic',source='DIMAGGI authored fleet arithmetic example',licence='MIT (repository licence)',generated_on='2026-11-05'),cohorts=[dict(id='initial',count=10,planned_commission_year=0,delay_years=0,retirement_year=3,capacity_kw=2,hazard_per_year=.1,utilization=.8,availability=.95),dict(id='replacement',count=3,planned_commission_year=1,delay_years=.5,retirement_year=3,capacity_kw=2,hazard_per_year=.1,utilization=.8,availability=.95)])

def request(scenario=None):return dict(schema='capacity-orbital/fleet-tool-v1',id='synthetic-evaluation',tool='evaluate',input=demo() if scenario is None else scenario)
