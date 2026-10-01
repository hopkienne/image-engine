import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import psutil
from . import ROOT

BASE = ROOT / 'benchmark'
RUN = ROOT / 'artifacts/multi-engine-benchmark/20261001/run-v1'
CONFIG = BASE / 'configs'
CONFIG.mkdir(exist_ok=True)

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def output_eligible(record):
    """Successful process execution alone does not establish a usable reference."""
    return (record.get('execution',{}).get('status')=='SUCCESS'
            and bool(record.get('normalized_export')) and bool(record.get('descriptor'))
            and record.get('reference_validation_status') not in ('BLOCKED','FAILED')
            and record.get('reference_eligibility') not in ('BLOCKED','INCONCLUSIVE'))

def rel(path):
    return Path(path).resolve().relative_to(RUN.resolve()).as_posix()

def budget(extra=0):
    policy = load(BASE / 'benchmark.policy.json')['resources']
    # Count storage once for verified byte-identical derivative hardlinks. RAW
    # originals and working copies never use hardlinks. Logical bytes are reported
    # separately by the optional storage compactor.
    seen=set(); used=0
    for p in RUN.rglob('*'):
        if not p.is_file(): continue
        s=p.stat(); identity=(s.st_dev,s.st_ino) if s.st_ino else str(p.resolve())
        if identity not in seen: used+=s.st_size; seen.add(identity)
    if used + extra > policy['max_corpus_and_output_bytes']:
        raise RuntimeError('BLOCKED: corpus/output 30 GiB quota')
    if shutil.disk_usage(RUN).free - extra < policy['minimum_free_bytes']:
        raise RuntimeError('BLOCKED: less than 10 GiB free')
    return used

def process(argv, folder, timeout=240, env_extra=None):
    """argv-only execution, own process-tree sampling; no runner RSS included."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    isolated = folder / 'environment'
    for name in ('config', 'cache', 'temp', 'appdata', 'localappdata', 'home'):
        (isolated / name).mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='4', OMP_THREAD_LIMIT='4', OPENBLAS_NUM_THREADS='4',
               TEMP=str(isolated/'temp'), TMP=str(isolated/'temp'),
               APPDATA=str(isolated/'appdata'), LOCALAPPDATA=str(isolated/'localappdata'),
               HOME=str(isolated/'home'), XDG_CONFIG_HOME=str(isolated/'config'),
               XDG_CACHE_HOME=str(isolated/'cache'), RT_SETTINGS=str(isolated/'config'))
    env.update(env_extra or {})
    out, err = folder / 'stdout.log', folder / 'stderr.log'
    started = now(); t = time.perf_counter(); peak = 0; samples = 0; status='FAILED'
    children = {}
    with out.open('wb') as of, err.open('wb') as ef:
        try:
            p = subprocess.Popen([str(v) for v in argv], cwd=ROOT, env=env, stdout=of, stderr=ef,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            proc = psutil.Process(p.pid)
            try:
                allowed = proc.cpu_affinity()
                proc.cpu_affinity(allowed[:4])
            except (psutil.Error, AttributeError):
                pass
            while True:
                try:
                    group = [proc] + proc.children(recursive=True)
                    rss = 0
                    for c in group:
                        children[(c.pid,c.create_time())] = c
                        try: rss += c.memory_info().rss
                        except psutil.Error: pass
                    peak = max(peak, rss); samples += 1
                except psutil.Error: pass
                if p.poll() is not None:
                    status = 'SUCCESS' if p.returncode == 0 else 'FAILED'
                    break
                if time.perf_counter()-t > timeout:
                    status='TIMEOUT'
                    for c in reversed(list(children.values())):
                        try: c.kill()
                        except psutil.Error: pass
                    p.kill(); p.wait(timeout=10); break
                time.sleep(.05)
            code=p.returncode
        except Exception as exc:
            ef.write(str(exc).encode()); code=None
    result = dict(status=status, argv=[str(v) for v in argv], exit_code=code,
                  started_at=started, wall_seconds=time.perf_counter()-t,
                  peak_memory_bytes=peak, memory_samples=samples,
                  memory_method='psutil process-tree working-set sampled every ~50ms; lower bound on true peak',
                  stdout_path=rel(out), stderr_path=rel(err), cache_hit=False,
                  thread_budget=int(env['OMP_THREAD_LIMIT']),
                  omp_num_threads_requested=int(env['OMP_NUM_THREADS']),
                  omp_thread_limit_requested=int(env['OMP_THREAD_LIMIT']),
                  cpu_affinity='first four allowed logical processors',
                  fresh_process=True, cold_os_cache=False)
    write(folder/'process.json', result)
    return result

def binaries():
    return {'ours': RUN/'baseline-photo-cli.exe',
            'darktable': BASE/'tools/darktable-5.6.1/bin/darktable-cli.exe',
            'rawtherapee': BASE/'tools/rawtherapee-5.13/RawTherapee_5.13_win64_x86_64_release/rawtherapee-cli.exe'}

def code_hash():
    return digest({p.name:sha(p) for p in sorted((ROOT/'raw_benchmark').glob('*.py'))})

def checked_output(path, bytes_expected=None):
    path = Path(path)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('missing output despite process exit status')
    if bytes_expected is not None and path.stat().st_size != bytes_expected:
        raise ValueError('truncated or inconsistent output')
    return dict(path=rel(path), sha256=sha(path), bytes=path.stat().st_size)

def effect(a,b):
    import numpy as np
    if a.shape != b.shape: return False
    return bool(np.max(np.abs(a.astype('float64')-b.astype('float64'))) > 1e-4)
