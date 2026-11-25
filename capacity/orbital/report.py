"""Escaped, self-contained HTML with no network assets or executable JavaScript."""
from html import escape


def html_report(report):
    esc = lambda v: escape(str(v), quote=True)
    summaries, rows = [], []
    max_cost = max((r['summary']['cost_usd'] for r in report['comparisons']), default=0) or 1
    for comparison in report['comparisons']:
        s = comparison['summary']
        width = s['cost_usd'] / max_cost * 100
        qualities = [j['quality'] for j in comparison['jobs']]
        quality_range = f'{min(qualities):.3f}–{max(qualities):.3f}'
        unit_cost = 'undefined (no planned results)' if s['cost_per_planned_result_usd'] is None else f"${s['cost_per_planned_result_usd']:.3f}"
        summaries.append(f'''<article><h2>{esc(comparison['route'].title())}</h2>
<p class="count">{esc(s['planned'])} planned <span>/ {esc(s['planned']+s['refused'])} jobs</span></p>
<p>{esc(s['refused'])} refused · {s['downlink_gb']:.3f} GB downlinked</p>
<p>Assumed quality: {quality_range} (not measured accuracy)</p>
<p>{unit_cost} per planned result · compare quality and counts</p>
<p>{s['energy_kwh']:.4f} kWh compute energy · ${s['cost_usd']:.3f} modeled cost</p>
<div class="bar" aria-label="Modeled cost relative to highest route"><i style="width:{width:.3f}%"></i></div></article>''')
        for j in comparison['jobs']:
            completion = '—' if j['completion_s'] is None else f"{j['completion_s']:.3f}"
            rows.append(f'''<tr><th scope="row">{esc(j['job_id'])}</th><td>{esc(j['route'])}</td>
<td class="{esc(j['status'])}">{esc(j['status'])}</td><td>{completion}</td><td>{j['deadline_s']:.3f}</td>
<td>{j['quality']:.3f} / {j['required_quality']:.3f}</td><td>{esc(j['reason'] or 'Within stated envelopes')}</td></tr>''')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Capacity Orbital — scenario comparison</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#172438;font:16px/1.55 system-ui,sans-serif}main{max-width:1150px;margin:auto;padding:36px 24px}h1{font-size:clamp(2rem,5vw,3.2rem);line-height:1.1;margin:12px 0}h2{margin-top:0}small,.muted{color:#42546c}.badge{display:inline-block;background:#dce7f7;color:#183d74;padding:5px 12px;border-radius:20px;font-weight:700}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:28px 0}article,section{background:white;border:1px solid #cbd6e3;border-radius:12px;padding:20px;margin:16px 0}.count{font-size:24px;font-weight:750}.count span{font-size:15px;font-weight:400}.bar{height:12px;background:#e6edf6;border-radius:8px;overflow:hidden}.bar i{display:block;height:100%;background:#245bb0}table{border-collapse:collapse;min-width:800px;width:100%;font-size:14px}td,th{text-align:left;border-bottom:1px solid #d5dee9;padding:10px;vertical-align:top}.scroll{overflow:auto}.planned{color:#136437;font-weight:700}.refused{color:#9a2828;font-weight:700}code{overflow-wrap:anywhere}li{margin:8px 0}@media(max-width:740px){main{padding:20px 14px}.cards{grid-template-columns:1fr;gap:0}article{margin:7px 0}section{padding:14px}}
</style><main><span class="badge">Offline synthetic planning</span><h1>Capacity Orbital</h1><p>Ground, onboard and hybrid processing — one workload, explicit constraints.</p>
<h2>''' + esc(report['name']) + '</h2><p class="muted">' + esc(report['classification']) + '</p><div class="cards">' + ''.join(summaries) + '''</div>
<section><h2>Every job has an outcome</h2><p>Times are seconds from scenario start. Quality is an assumed retained-quality score / required minimum. No measured AI accuracy is claimed.</p><div class="scroll"><table><thead><tr><th>Job</th><th>Route</th><th>Outcome</th><th>Completion (s)</th><th>Deadline (s)</th><th>Quality / min.</th><th>Reason</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></div></section>
<section><h2>What this comparison means</h2><p>Costs are partial synthetic compute, electricity and transfer costs. Refused work is not equivalent to completed work; compare completion counts before comparing costs.</p><ul>''' + ''.join('<li>'+esc(x)+'</li>' for x in report['assumptions']) + '''</ul></section>
<section><h2>Reproduce and inspect</h2><p>Input SHA-256: <code>''' + esc(report['input_sha256']) + '</code></p><p>Model version: ' + esc(report['version']) + '</p><p>Source SHA-256: <code>' + esc(report.get('source_sha256') or 'Not supplied by caller; receipts are not code-bound') + '</code></p><p>Source: ' + esc(report['provenance']['source']) + '</p></section></main></html>'
