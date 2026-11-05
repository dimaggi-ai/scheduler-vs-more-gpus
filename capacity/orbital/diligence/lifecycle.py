"""Original standard discounted cash-flow/capacity arithmetic, not financial advice."""
import math
from .contracts import fields,number,text,provenance,Refuse,finite_result,MAX_FLOWS,MAX_COHORTS,MAX_YEARS

CATEGORIES=('development','payload','platform','launch','insurance','operation','replacement',
            'disposal','residual','downlink_marginal','downlink_allocated')
SCHEMA='capacity-orbital/lifecycle-v1'


def discount(rate,year):
    return math.exp(-year*math.log1p(rate))


def validate(s):
    fields(s,'schema name currency horizon_years discount_rate cash_flows cohorts provenance','lifecycle')
    if s['schema']!=SCHEMA:raise Refuse('UNSUPPORTED_SCHEMA','unsupported lifecycle schema')
    text(s['name'],'name');provenance(s['provenance'])
    if not isinstance(s['currency'],str) or len(s['currency'])!=3 or not s['currency'].isascii() or not s['currency'].isalpha() or s['currency']!=s['currency'].upper():
        raise Refuse('INVALID_ARGUMENT','currency requires one declared three-letter uppercase unit')
    horizon=number(s['horizon_years'],'horizon_years',positive=True,maximum=MAX_YEARS,integer=True)
    number(s['discount_rate'],'discount_rate',maximum=1)
    if not isinstance(s['cash_flows'],list) or not s['cash_flows'] or len(s['cash_flows'])>MAX_FLOWS:
        raise Refuse('BUDGET_EXCEEDED','one to1000 cash flows required')
    if not isinstance(s['cohorts'],list) or len(s['cohorts'])>MAX_COHORTS:
        raise Refuse('BUDGET_EXCEEDED','at most200 cohorts required')
    ids=set()
    for flow in s['cash_flows']:
        fields(flow,'id category year amount currency','cash flow')
        text(flow['id'],'flow.id')
        if flow['id'] in ids:raise Refuse('INVALID_ARGUMENT','duplicate cash-flow id')
        ids.add(flow['id'])
        if flow['category'] not in CATEGORIES:raise Refuse('INVALID_ARGUMENT','unsupported cost category; financing flows are excluded')
        number(flow['year'],'flow.year',maximum=horizon)
        number(flow['amount'],'flow.amount',minimum=-1e300 if flow['category']=='residual' else 0)
        if flow['category']=='residual' and flow['amount']>0:raise Refuse('INVALID_ARGUMENT','residual is a nonpositive credit')
        if flow['currency']!=s['currency']:
            raise Refuse('UNSUPPORTED_CURRENCY','mixed currencies refused; no conversion or exchange-rate provenance support in v1')
    ids=set()
    for cohort in s['cohorts']:
        fields(cohort,'id count commission_year retirement_year capacity_kw utilization availability','cohort')
        text(cohort['id'],'cohort.id')
        if cohort['id'] in ids:raise Refuse('INVALID_ARGUMENT','duplicate cohort id')
        ids.add(cohort['id'])
        number(cohort['count'],'cohort.count',positive=True,integer=True,maximum=1_000_000)
        start=number(cohort['commission_year'],'commission_year',maximum=horizon)
        end=number(cohort['retirement_year'],'retirement_year',maximum=horizon)
        if end<=start:raise Refuse('INVALID_ARGUMENT','retirement must follow commissioning')
        number(cohort['capacity_kw'],'capacity_kw',positive=True)
        for k in ('utilization','availability'):number(cohort[k],k,maximum=1)
    return s


def lifecycle_cost(s):
    validate(s)
    rate=s['discount_rate']; horizon=s['horizon_years']
    flows=[]; category={k:{'undiscounted':0.0,'discounted':0.0} for k in CATEGORIES}
    for f in s['cash_flows']:
        pv=f['amount']*discount(rate,f['year'])
        if f['amount']!=0 and pv==0:
            raise Refuse('ARITHMETIC_RESOLUTION','nonzero cash flow discounts below supported numeric resolution')
        flows.append(dict(f,discount_factor=discount(rate,f['year']),discounted_amount=pv))
        category[f['category']]['undiscounted']+=f['amount'];category[f['category']]['discounted']+=pv
    years=[]; cohort_rows=[]
    for year in range(1,horizon+1):
        capacity=0.0
        for c in s['cohorts']:
            active=max(0,min(year,c['retirement_year'])-max(year-1,c['commission_year']))
            useful=active*c['count']*c['capacity_kw']*c['utilization']*c['availability']
            if active>0 and c['utilization']>0 and c['availability']>0 and useful==0:
                raise Refuse('ARITHMETIC_RESOLUTION','positive useful capacity underflows')
            capacity+=useful
            if active:
                cohort_rows.append(dict(cohort_id=c['id'],year_end=year,active_years=active,
                                        useful_kw_years=useful,discounted_useful_kw_years=useful*discount(rate,year)))
        years.append(dict(year_end=year,useful_kw_years=capacity,discount_factor=discount(rate,year),
                          discounted_useful_kw_years=capacity*discount(rate,year)))
    total_cost=sum(f['amount'] for f in flows); pv_cost=sum(f['discounted_amount'] for f in flows)
    total_output=sum(y['useful_kw_years'] for y in years);pv_output=sum(y['discounted_useful_kw_years'] for y in years)
    status='computed' if pv_output>0 and pv_cost>=0 else 'unknown'
    reason='ZERO_USEFUL_OUTPUT' if pv_output<=0 else 'NET_CREDIT_REVIEW' if pv_cost<0 else 'COMPUTED_SYNTHETIC'
    result=dict(schema='capacity-orbital/lifecycle-result-v1',model='event-cashflows/year-end-capacity-v1',
        status=status,reason_code=reason,currency=s['currency'],
        totals=dict(undiscounted_cost=total_cost,discounted_cost=pv_cost,undiscounted_useful_kw_years=total_output,
                    discounted_useful_kw_years=pv_output,cost_per_discounted_useful_kw_year=pv_cost/pv_output if status=='computed' else None),
        cash_flows=flows,cohort_output=cohort_rows,annual_output=years,by_category=category,
        provenance=s['provenance'],assumptions=[
            'Positive cash flows are expenditures; residual entries are nonpositive credits. No revenue or financing cash flows.',
            'Cash flows are discounted at their declared year offset; useful capacity accrues over active interval intersections and is discounted at each year-end.',
            'Both numerator and denominator use the same annual discount factor and time origin; partial-year output is credited at the containing year-end.',
            'No output before commissioning or after retirement. Replacements require their own cohorts and cash flows.',
            'Utilization and availability are declared synthetic constants, not inferred survival probabilities.',
            'Discount rate is a supplied cost-of-capital assumption; interest, debt proceeds, repayments and principal are excluded to avoid financing double-counting.',
            'Allocated/prepaid downlink expense and incremental marginal downlink expense are separate categories; callers must not enter the same invoice twice.',
            'Single declared currency only; no FX lookup/conversion, inflation model, tax model or investment suitability conclusion.',
            'Alternatives are sensitivity scenarios, not forecasts, accepted improvements or automatic calibration.'])
    return finite_result(result)
