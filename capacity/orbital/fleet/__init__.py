"""Synthetic expected cohort exposure, not realized fleet or flight prediction."""
import math,hashlib,json
from pathlib import Path
from copy import deepcopy
from ..contracts import digest
from ..diligence.contracts import fields,number,text,provenance,Refuse,finite_result
from ..diligence.lifecycle import lifecycle_cost
SCHEMA='capacity-orbital/fleet-v1'

def source_digest():
    root=Path(__file__).resolve().parents[1]
    paths=list((root/'fleet').glob('*.py'))+list((root/'diligence').glob('*.py'))+[root/'contracts.py',root/'output.py',root/'__init__.py',root.parent/'__init__.py']
    return digest({str(p.relative_to(root.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})

def validate(s):
    fields(s,'schema id horizon_years demand_kw cohorts provenance','fleet')
    if s['schema']!=SCHEMA:raise Refuse('UNSUPPORTED_SCHEMA','unsupported fleet schema')
    text(s['id'],'id');provenance(s['provenance']);h=number(s['horizon_years'],'horizon',positive=True,integer=True,maximum=100)
    if type(s['demand_kw']) is not list or len(s['demand_kw'])!=h:raise Refuse('INVALID_ARGUMENT','one annual average useful demand per year required')
    for x in s['demand_kw']:number(x,'demand_kw',maximum=1e12)
    if type(s['cohorts']) is not list or not 1<=len(s['cohorts'])<=200:raise Refuse('BUDGET_EXCEEDED','one to 200 cohorts required')
    ids=set()
    for c in s['cohorts']:
        fields(c,'id count planned_commission_year delay_years retirement_year capacity_kw hazard_per_year utilization availability','cohort')
        text(c['id'],'cohort.id')
        if c['id'] in ids:raise Refuse('INVALID_ARGUMENT','duplicate cohort ID')
        ids.add(c['id']);number(c['count'],'count',positive=True,integer=True,maximum=1000000)
        start=number(c['planned_commission_year'],'planned commission',maximum=h)
        end=number(c['retirement_year'],'retirement',maximum=h)
        if end<=start:raise Refuse('INVALID_ARGUMENT','fixed retirement must follow planned commissioning')
        number(c['delay_years'],'delay',maximum=h);number(c['capacity_kw'],'capacity',positive=True,maximum=1e9)
        number(c['hazard_per_year'],'hazard',maximum=100)
        for key in ('utilization','availability'):number(c[key],key,maximum=1)
    return s

def integral(c,a,b,start):
    if b<=a:return 0.0
    rate=c['hazard_per_year'];duration=b-a
    scaled=rate*duration
    # Normalize by the rounded product, not the subnormal rate itself.
    # When the product rounds to zero the continuous exprel limit is one.
    mean=1.0 if scaled==0 else -math.expm1(-scaled)/scaled
    value=math.exp(-rate*(a-start))*duration*mean
    if value==0:raise Refuse('ARITHMETIC_RESOLUTION','positive survival exposure below numeric resolution')
    return value

def evaluate(s):
    validate(s);rows=[];annual=[]
    for year in range(1,s['horizon_years']+1):
        useful=[];ideal=[];surviving=[];failed=[];retired=[];not_yet=[]
        for c in s['cohorts']:
            start=c['planned_commission_year']+c['delay_years'];end=c['retirement_year']
            a=max(year-1,start);b=min(year,end)
            exposure=integral(c,a,b,start)*c['count'] if b>a else 0.0
            factor=c['capacity_kw']*c['utilization']*c['availability'];out=exposure*factor
            if exposure>0 and c['utilization']>0 and c['availability']>0 and out==0:raise Refuse('ARITHMETIC_RESOLUTION','positive useful exposure below numeric resolution')
            planned=c['planned_commission_year'];ia=max(year-1,planned);ib=min(year,end)
            ontime=integral(c,ia,ib,planned)*c['count']*factor if ib>ia else 0.0
            if start>=end or year<start:alive=dead=gone=0.0;pending=float(c['count'])
            else:
                age=max(0,min(year,end)-start);survival=c['count']*math.exp(-c['hazard_per_year']*age)
                dead=c['count']-survival;alive=survival if year<end else 0.0;gone=survival if year>=end else 0.0;pending=0.0
            row=dict(cohort_id=c['id'],year_end=year,commission_year=start,active_years=max(0,b-a),expected_node_years=exposure,useful_kw_years=out,expected_surviving_nodes=alive,expected_failed_nodes=dead,expected_retired_nodes=gone,uncommissioned_nodes=pending)
            rows.append(row);useful.append(out);ideal.append(ontime);surviving.append(alive);failed.append(dead);retired.append(gone);not_yet.append(pending)
        capacity=math.fsum(useful);baseline=math.fsum(ideal)
        annual.append(dict(year_end=year,expected_useful_kw_years=capacity,average_useful_kw=capacity,demand_average_kw=s['demand_kw'][year-1],annual_average_capacity_shortfall_kw=max(0,s['demand_kw'][year-1]-capacity),ontime_useful_kw_years=baseline,delay_exposure_delta_kw_years=baseline-capacity,expected_surviving_nodes=math.fsum(surviving),expected_failed_nodes=math.fsum(failed),expected_retired_nodes=math.fsum(retired),uncommissioned_nodes=math.fsum(not_yet)))
    result=dict(schema='capacity-orbital/fleet-result-v1',classification='synthetic expectation, not realized fleet or flight reliability',input_sha256=digest(s),source_sha256=source_digest(),annual=annual,cohort_periods=rows,total_useful_kw_years=math.fsum(x['expected_useful_kw_years'] for x in annual),total_annual_average_capacity_shortfall_kw_years=math.fsum(x['annual_average_capacity_shortfall_kw'] for x in annual),provenance=deepcopy(s['provenance']),execution_performed=False,promoted=False)
    finite_result(result);result['receipt_id']=digest(result);return result

def compare(baseline,candidate,expected_baseline_sha256=None):
    validate(baseline);validate(candidate)
    if expected_baseline_sha256 is not None and expected_baseline_sha256!=digest(baseline):raise Refuse('BASELINE_BINDING','baseline differs from independently supplied digest')
    def fixed(s):
        v=deepcopy(s);v.pop('id');v.pop('provenance');v['cohorts']=sorted(v['cohorts'],key=lambda c:c['id'])
        for c in v['cohorts']:c.pop('hazard_per_year');c.pop('delay_years')
        def normalized(value):
            if type(value) in (int,float):return 0.0 if value==0 else float(value)
            if type(value) is list:return [normalized(x) for x in value]
            if type(value) is dict:return {k:normalized(x) for k,x in value.items()}
            return value
        return normalized(v)
    if digest(fixed(baseline))!=digest(fixed(candidate)):raise Refuse('BASELINE_MISMATCH','only declared hazard and delay assumptions may vary; demand and capacity assumptions fixed')
    a=evaluate(baseline);b=evaluate(candidate)
    result=dict(schema='capacity-orbital/fleet-comparison-v1',baseline=a,candidate=b,useful_exposure_delta_kw_years=b['total_useful_kw_years']-a['total_useful_kw_years'],shortfall_delta_kw_years=b['total_annual_average_capacity_shortfall_kw_years']-a['total_annual_average_capacity_shortfall_kw_years'],recommendation='sensitivity only; no calibrated improvement or automatic promotion',baseline_binding='baseline matched supplied digest' if expected_baseline_sha256 is not None else 'unbound caller-supplied pair',input_sha256=digest(dict(baseline=baseline,candidate=candidate,expected_baseline_sha256=expected_baseline_sha256)),source_sha256=source_digest(),execution_performed=False,promoted=False)
    result['receipt_id']=digest(result);return result

def project_economics(s,template):
    report=evaluate(s)
    if type(template) is not dict or template.get('cohorts')!=[] or template.get('horizon_years')!=s['horizon_years']:raise Refuse('INVALID_ARGUMENT','economics template must have empty cohorts and matching horizon')
    projected=deepcopy(template);cohorts={c['id']:c for c in s['cohorts']};output=[];mapping=[]
    for row in report['cohort_periods']:
        if row['active_years']<=0:continue
        c=cohorts[row['cohort_id']];year=row['year_end'];mean=row['expected_node_years']/c['count']/row['active_years']
        if mean>1+1e-12 or mean<0:raise Refuse('ARITHMETIC_RESOLUTION','projected mean survival exceeds physical bounds beyond roundoff')
        mapping.append(dict(projection_id='projection-'+str(len(output)),source_cohort_id=c['id'],year_end=year,mean_survival=mean,active_years=row['active_years']))
        output.append(dict(id='projection-'+str(len(output)),count=c['count'],commission_year=max(year-1,row['commission_year']),retirement_year=min(year,c['retirement_year']),capacity_kw=c['capacity_kw'],utilization=c['utilization'],availability=min(1,mean)*c['availability']))
    if len(output)>200:raise Refuse('BUDGET_EXCEEDED','existing lifecycle calculator accepts at most 200 projected cohort-year rows')
    projected['cohorts']=output;economics=lifecycle_cost(projected)
    economics['assumptions']=[('For this fleet projection, interval availability is derived mean survival times declared nonfailure availability; utilization remains declared.' if x=='Utilization and availability are declared synthetic constants, not inferred survival probabilities.' else x) for x in economics['assumptions']]
    result=dict(schema='capacity-orbital/fleet-economics-v1',fleet=report,projected_lifecycle=projected,economics=economics,assumption='exact annual exposure projected as mean survival times nonfailure availability; supplied cashflows unchanged',projection_mapping=mapping,scenario_provenance=deepcopy(s['provenance']),template_provenance=deepcopy(template['provenance']),input_sha256=digest(dict(scenario=s,template=template)),source_sha256=source_digest(),execution_performed=False,promoted=False)
    result['receipt_id']=digest(result);return result
