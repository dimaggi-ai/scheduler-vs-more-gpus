"""Original authored synthetic examples; no vendor or private strategy inputs."""
from .api import REQUEST
from .lifecycle import SCHEMA

PROVENANCE={'kind':'synthetic','source':'DIMAGGI task109 authored hand-computable fixture',
            'licence':'MIT (repository licence)','generated_on':'2026-11-05'}


def lifecycle_example():
    return {'schema':SCHEMA,'name':'Two-year synthetic capacity sensitivity','currency':'USD',
            'horizon_years':2,'discount_rate':.1,'cash_flows':[
                {'id':'payload','category':'payload','year':0,'amount':1000,'currency':'USD'},
                {'id':'operation1','category':'operation','year':1,'amount':100,'currency':'USD'},
                {'id':'operation2','category':'operation','year':2,'amount':100,'currency':'USD'}],
            'cohorts':[{'id':'cohort1','count':1,'commission_year':0,'retirement_year':2,
                        'capacity_kw':1,'utilization':1,'availability':1}],
            'provenance':dict(PROVENANCE)}


def thermal_example():
    return {'schema':'capacity-orbital/claim-v1','name':'Synthetic uniform-temperature emitting-area screen',
            'kind':'thermal','parameters':{'heat_w':400,'temperature_k':300,'sink_temperature_k':0,
            'emissivity':1,'fin_efficiency':1,'absorbed_flux_w_m2':0,'area_m2':1,'area_basis':'emitting','view_factor':1},
            'provenance':dict(PROVENANCE)}


def request(tool,value,ident):
    return {'schema':REQUEST,'id':ident,'tool':tool,'input':value}
