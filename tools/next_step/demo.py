"""Loopback-only minimal preview demo backed by a persistent production core process."""
import argparse, json, subprocess, threading, time, sys
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.next_step.core import OLD, HARNESS, load
HTML='''<!doctype html><meta charset="utf-8"><title>Core v0 preview lab</title>
<style>body{font:16px system-ui;background:#181b20;color:#eee;max-width:1280px;margin:30px auto}button,input,select{font:inherit;padding:8px;margin:6px}img{max-width:100%;max-height:72vh}pre{white-space:pre-wrap}.note{color:#b9c6d6}</style>
<h1>Core v0 · preview lab</h1><p class="note">Local RAW → production core → preview. Synthetic LUT for cache testing. No product color acceptance.</p>
<label>RAW <select id="source"><option>R025</option><option>R039</option><option>R001</option></select></label>
<label>Amount <input id="amount" type="number" min="0" max="1" step="0.1" value="0"></label>
<label>EV <input id="ev" type="number" min="-5" max="5" step="0.5" value="0"></label>
<label>Custom R gain factor <input id="wbFactor" type="number" min="0.5" max="2" step="0.1" value="1"></label>
<button onclick="render()">Render preview</button><button onclick="render(true)">Export full size</button>
<p id="status">Ready. First open develops RAW; look/EV reuse the full-resolution base; WB invalidates it.</p><img id="image"><pre id="metrics"></pre>
<script>let latest=0;const el=id=>document.getElementById(id);async function render(exp=false){let ticket=++latest;el('status').textContent='Rendering…';let payload={source:el('source').value,amount:+el('amount').value,ev:+el('ev').value,wbFactor:+el('wbFactor').value,export:exp};try{let r=await fetch('/render',{method:'POST',headers:{'Content-Type':'application/json','X-Preview-Lab':'1'},body:JSON.stringify(payload)});let data=await r.json();if(ticket!==latest)return;el('status').textContent=data.status===0?'Rendered by core':'Error';el('metrics').textContent=JSON.stringify(data,null,2);if(data.image)el('image').src=data.image;}catch(e){el('status').textContent=String(e);}}</script>'''
def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,default=ROOT/'artifacts/next-step/run-v2/core');p.add_argument('--port',type=int,default=8766);a=p.parse_args();run=a.run.resolve()
    dest=run/'demo'/str(time.time_ns());dest.mkdir(parents=True)
    corpus={i['source_id']:i for i in load(OLD/'corpus.manifest.json')['items']}
    lock=threading.Lock();state={'process':None,'source':None,'generation':0};logs=[]
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(dest),**kwargs)
        def do_GET(self):
            if self.path=='/':
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(HTML.encode());return
            return super().do_GET()
        def do_POST(self):
            if self.path!='/render' or self.headers.get('X-Preview-Lab')!='1':self.send_error(403);return
            try:
                n=int(self.headers.get('Content-Length',0));assert 0<n<4096
                command=json.loads(self.rfile.read(n));sid=command.pop('source');assert sid in ['R025','R039','R001']
                assert set(command)<= {'amount','ev','wbFactor','export'}
                with lock:
                    if state['source']!=sid:
                        if state['process']:state['process'].stdin.close();state['process'].wait(timeout=30)
                        folder=dest/f'{sid}-{time.time_ns()}';folder.mkdir()
                        log=(folder/'stderr.log').open('w');logs.append(log)
                        state['process']=subprocess.Popen([str(HARNESS),'session',str(OLD/corpus[sid]['path']),str(run/'looks/cache-test'),str(run/'recipes'/f'{sid}-cache-test.json'),str(folder)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True)
                        state.update(source=sid,folder=folder,generation=0)
                    state['generation']+=1;command.update(name=f'render-{state["generation"]}',generation=state['generation'])
                    process=state['process'];process.stdin.write(json.dumps(command)+'\n');process.stdin.flush()
                    response=json.loads(process.stdout.readline())
                    if response['status']==0:
                        from PIL import Image
                        file=state['folder']/(command['name']+'.png');Image.open(file.with_suffix('.ppm')).save(file)
                        response['image']='/'+file.relative_to(dest).as_posix()
                        if command.get('export'):response['fullSizeExport']='/'+file.with_suffix('.jpg').relative_to(dest).as_posix()
                data=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
            except Exception as e:self.send_error(400,str(e))
    print(f'http://127.0.0.1:{a.port}/',flush=True)
    try:ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
    finally:
        if state['process']:state['process'].stdin.close();state['process'].wait(timeout=30)
if __name__=='__main__':main()
