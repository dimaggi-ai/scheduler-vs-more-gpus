from copy import deepcopy
from ..network.fixtures import demo as network_demo,dynamics_fixture

def demo(kind='nominal'):
    net=network_demo();net['jobs']=[]
    net['contacts'][0].update(end_s=200)
    net['contacts'][1].update(start_s=0,end_s=250)
    for n in net['nodes'].values():n['buffer_gb']=10
    physical=dynamics_fixture(net)
    m=dict(schema='capacity-orbital/mission-v1',id='synthetic-EO',origin='A',destination='G',currency='USD',network=net,dynamics=physical,authority=dict(disposition='allowed',valid_from_s=0,expires_s=300,scope='synthetic-evaluation'),compute={n:dict(memory_gb=2,power_kw=1,heat_w=100,cost_per_s_usd=.01) for n in ('A','G')},jobs=[])
    for i in range(2):
        m['jobs'].append(dict(id='job-'+str(i),release_s=0,deadline_s=100,raw_gb=1,result_gb=.1,compressed_gb=.4,memory_gb=1,required_quality=.9,ground_quality=1,onboard_quality=.95,hybrid_quality=.98,ground_s=10,onboard_s=5,preprocess_s=2,hybrid_ground_s=5,allowed_jurisdictions=['synthetic-zone']))
    from ..diligence.fixtures import lifecycle_example
    m['diligence']=dict(mission_id=m['id'],lifecycle=lifecycle_example())
    if kind=='battery':
        for n in physical['nodes'].values():n['battery']['initial_kwh']=.0001
    elif kind=='corrected':
        for n in physical['nodes'].values():n['battery']['initial_kwh']=.0001;n['profiles'][0]['solar_kw']=10
    elif kind=='network-loss':net['contacts']=[]
    elif kind=='late':
        for j in m['jobs']:j['ground_s']=200;j['hybrid_ground_s']=200;j['onboard_s']=200
    elif kind=='held':m['authority']['disposition']='held'
    elif kind!='nominal':raise ValueError('unknown demo')
    return m

def suite():
    a=demo();b=demo();b['id']='heldout-EO';b['diligence']['mission_id']=b['id']
    for j in b['jobs']:j['raw_gb']=1.2;j['release_s']=3
    return dict(schema='capacity-orbital/mission-suite-v1',train=[a],heldout=[b])


def feedback_suite(worsening=False):
    from .mission import plan_mission,source_digest
    from .feedback import predictions
    from ..contracts import digest
    missions=suite();output=dict(schema='capacity-orbital/feedback-suite-v1',train=[],heldout=[])
    for split in ('train','heldout'):
        m=missions[split][0];r=plan_mission(m,'onboard');records=[]
        factor=.9 if worsening and split=='heldout' else 1.1
        for j in m['jobs']:
            pred=predictions(m,r,j['id'])
            records.append(dict(schema='capacity-orbital/synthetic-replay-v1',id=split+':'+j['id'],classification='supplied synthetic replay',mission_input_sha256=digest(m),source_sha256=source_digest(),proposal_receipt_id=r['receipt_id'],job_id=j['id'],completion_s=j['release_s']+pred['duration_s']*factor,energy_kwh=pred['energy_kwh']*factor,link_gb=pred['link_gb'],cost_usd=pred['cost_usd']))
        output[split].append(dict(mission=m,report=r,records=records))
    return output
