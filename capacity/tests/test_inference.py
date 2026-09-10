import pytest
from capacity.inference import Hardware,Request,simulate

HW=Hardware('synthetic',100e12,80e9,2e12)


def test_tokens_latency_and_determinism():
    req=[Request(0,128,10)]
    a=simulate(req,HW)
    assert a==simulate(req,HW)
    assert a['requests'][0]['output_tokens']==10
    assert a['requests'][0]['ttft_s']>0
    assert a['requests'][0]['max_itl_s']>0


def test_generator_preserves_nonzero_arrival_window():
    requests=[Request(100,128,10),Request(101,128,10)]
    assert simulate(iter(requests),HW)==simulate(requests,HW)


def test_contention_and_cache_cannot_evade_memory():
    a=simulate([Request(0,1024,100)],HW)
    b=simulate([Request(0,1024,100) for _ in range(32)],HW,max_batch=1)
    assert b['requests'][-1]['ttft_s']>a['requests'][0]['ttft_s']
    cached=simulate([Request(0,1024,100,1024)],HW)
    assert cached['requests'][0]['ttft_s']<a['requests'][0]['ttft_s']
    huge=simulate([Request(0,1000000,100,1000000)],HW)
    assert huge['requests'][0]['rejected']


def test_strict_slo_and_input_validation():
    a=simulate([Request(0,1024,10)],HW,ttft_slo_s=1e-9)
    assert a['slo_goodput_output_tokens_s']==0
    with pytest.raises(ValueError): Request(float('nan'),1,1)
    with pytest.raises(ValueError): Hardware('bad',1,1,float('inf'))
    with pytest.raises(ValueError): simulate([],HW,max_batch=0)
