"""Self-contained escaped HTML, no scripts or external assets."""
import html
import json


def html_report(response):
    esc=lambda value:html.escape(str(value),quote=True)
    result=response.get('result') or {}
    summary=''
    if 'totals' in result:
        summary='<h2>Lifecycle sensitivity</h2><dl>'+''.join('<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>' for k,v in result['totals'].items())+'</dl>'
    elif 'prediction' in result:
        summary='<h2>Claim screen: '+esc(result.get('status'))+'</h2><p>'+esc(result.get('reason_code'))+'</p>'
        if result.get('missing_assumptions'):summary+='<p>Missing: '+esc(', '.join(result['missing_assumptions']))+'</p>'
        if result.get('prediction'):summary+='<dl>'+''.join('<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>' for k,v in result['prediction'].items())+'</dl>'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Capacity Orbital — diligence</title><style>body{font:17px/1.5 system-ui,sans-serif;max-width:960px;margin:auto;padding:24px;color:#172438;background:#f8fafc}h1,h2{line-height:1.2}dt{font-weight:650}dd{margin:0 0 12px;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;border:1px solid #bac7d8;padding:16px}aside{background:#e9eff7;padding:16px;border-left:4px solid #285c98}code{overflow-wrap:anywhere}</style>
<h1>Capacity Orbital: diligence</h1><aside>Synthetic planning sensitivity and mathematical consistency only. Not physical verification, vendor certification, investment advice or execution authorization.</aside>
<p>Status: '''+esc(response.get('status'))+' · '+esc(response.get('reason_code'))+'</p>'+summary+'<h2>Reproducible evidence</h2><p>Input: <code>'+esc(response.get('input_sha256'))+'</code><br>Source: <code>'+esc(response.get('source_sha256'))+'</code></p><pre>'+esc(json.dumps(response,indent=2,allow_nan=False))+'</pre></html>'
