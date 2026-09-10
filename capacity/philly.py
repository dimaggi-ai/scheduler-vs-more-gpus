"""Philly workload-shape validation; allocated time is NOT useful GPU work.

Source: Microsoft Research, Analysis of Large-Scale Multi-Tenant GPU Clusters
for DNN Training Workloads (ATC 2019), msr-fiddle/philly-traces, CC-BY-4.0.
No GPU telemetry or identifiers are redistributed by the aggregate report.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import tarfile

REVISION = '29a1b87fa2d9ed80b83c9e3a37f3a88d382b031d'
SHA256 = '2037ccf63a725a02be718b0e1aeee6142c90b7f62d0d849295120e9f6ba13d2c'
URL = f'https://media.githubusercontent.com/media/msr-fiddle/philly-traces/{REVISION}/trace-data.tar.gz'


def attempts(records):
    valid, excluded = [], Counter()
    for job in records:
        try:
            submitted = datetime.strptime(job['submitted_time'], '%Y-%m-%d %H:%M:%S')
        except (ValueError,TypeError,KeyError):
            excluded['missing_or_invalid_submission'] += 1; continue
        if not job.get('attempts'): excluded['no_attempts'] += 1
        for attempt in job.get('attempts',[]):
            try:
                start = datetime.strptime(attempt['start_time'],'%Y-%m-%d %H:%M:%S')
                end = datetime.strptime(attempt['end_time'],'%Y-%m-%d %H:%M:%S')
                devices = [(d['ip'],gpu) for d in attempt['detail'] for gpu in d['gpus']]
                if len(set(devices)) != len(devices): raise ValueError('duplicate allocation')
                n = len(devices)
                hours = (end-start).total_seconds()/3600
                if n <= 0 or hours <= 0 or start < submitted: raise ValueError('invalid attempt')
            except (ValueError,TypeError,KeyError):
                excluded['incomplete_or_invalid_attempt'] += 1; continue
            valid.append(dict(submitted=submitted,start=start,end=end,size=n,hours=hours))
    return valid, dict(excluded)


def summary(rows):
    if not rows: raise ValueError('empty calibration or validation partition')
    count = Counter(r['size'] for r in rows)
    total = sum(r['size']*r['hours'] for r in rows)
    return dict(attempts=len(rows),mean_allocated_gpu_hours=total/len(rows),
                small_attempt_share=sum(r['size']<8 for r in rows)/len(rows),
                large_allocated_time_share=sum(r['size']*r['hours'] for r in rows if r['size']>=256)/total,
                size_probability={str(k):v/len(rows) for k,v in sorted(count.items())})


def analyze(records, cutoff='2017-11-20'):
    rows, excluded=attempts(records)
    date=datetime.fromisoformat(cutoff)
    train=summary([r for r in rows if r['submitted']<date and r['end']<date])
    test=summary([r for r in rows if r['submitted']>=date])
    excluded['cross_cutoff_attempts']=sum(r['submitted']<date and r['end']>=date for r in rows)
    keys=train['size_probability'].keys() | test['size_probability'].keys()
    tv=.5*sum(abs(train['size_probability'].get(k,0)-test['size_probability'].get(k,0)) for k in keys)
    return dict(schema_version='philly-workload-validation/v1', evidence_class='external-observed',
                source=URL, source_revision=REVISION, source_sha256=SHA256, license='CC-BY-4.0',
                attribution='Microsoft Research Project Fiddle, ATC 2019 Philly trace',
                calibration_before=cutoff,validation_on_or_after=cutoff,excluded=excluded,
                calibration=train,validation=test,held_out_size_total_variation=tv,
                assumptions=['Training jobs submitted AND attempts ended before cutoff; validation jobs submitted after cutoff.',
                             'Cross-cutoff attempts excluded, so future completion data cannot leak into calibration.',
                             'Timestamps are used as recorded; timezone is not inferred.',
                             'Attempts, not unique jobs; retries remain observed allocation demand.',
                             'Incomplete/censored attempts excluded and counted; survivorship bias remains.',
                             'Allocated GPU-hours include stalls/lost work; not scheduler-productive GPU-hours.',
                             '2017 hardware/workload is not a calibration of modern accelerator performance.',
                             'Held-out comparison tests workload-shape stability, not scheduler goodput accuracy.'])


def load_archive(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024): digest.update(chunk)
    if digest.hexdigest()!=SHA256: raise ValueError('Philly archive checksum mismatch')
    with tarfile.open(path,'r|gz') as archive:
        for member in archive:
            if member.isfile() and Path(member.name).name in ('cluster_job_log','cluster_job_log.json'):
                if member.size>512*1024*1024: raise ValueError('job log exceeds bounded parser size')
                return json.load(archive.extractfile(member))
    raise ValueError('cluster_job_log not found in archive')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path); p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(); report=analyze(load_archive(a.archive))
    a.out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('calibration','validation')},indent=2))
