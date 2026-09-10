from capacity.philly import analyze, attempts


def fixture(date):
    return dict(submitted_time=f'{date} 00:00:00',attempts=[dict(start_time=f'{date} 01:00:00',
                end_time=f'{date} 03:00:00',detail=[dict(ip='node',gpus=['gpu0','gpu1'])])])


def test_attempt_accounting_and_temporal_split():
    # Original synthetic unit fixtures; not excerpts from public trace data.
    report=analyze([fixture('2017-11-01'),fixture('2017-12-01')])
    assert report['calibration']['mean_allocated_gpu_hours']==4
    assert report['validation']['attempts']==1
    assert report['held_out_size_total_variation']==0


def test_censored_and_duplicate_devices_not_silently_accepted():
    a=fixture('2017-11-01');a['attempts'][0]['end_time']=None
    b=fixture('2017-11-01');b['attempts'][0]['detail'][0]['gpus']=['gpu0','gpu0']
    rows,excluded=attempts([a,b])
    assert rows==[] and excluded['incomplete_or_invalid_attempt']==2


def test_cross_cutoff_completion_cannot_leak_into_calibration():
    cross=fixture('2017-11-01');cross['attempts'][0]['end_time']='2017-12-01 03:00:00'
    report=analyze([fixture('2017-11-01'),fixture('2017-12-01'),cross])
    assert report['calibration']['attempts']==1
    assert report['validation']['attempts']==1
    assert report['excluded']['cross_cutoff_attempts']==1
