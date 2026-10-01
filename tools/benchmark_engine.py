"""Paired CLI benchmark: pinned recipes, wall/CPU time, OS peak memory, JPEG hashes.

Windows memory uses GetProcessMemoryInfo's lifetime peaks, sampled every 10 ms.
Run baseline before changing the binary, then candidate in the same directory.
The first repetition is warm-up and excluded from medians. No audit dumps.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def jpeg_without_icc_sha(path):
    data = path.read_bytes()
    if data[:2] != b'\xff\xd8':
        raise ValueError('not JPEG')
    segments = bytearray(data[:2]); at = 2
    while at < len(data):
        if data[at] != 0xff:
            raise ValueError('invalid JPEG marker')
        marker = data[at+1]
        if marker == 0xda:
            segments.extend(data[at:]); break
        size = int.from_bytes(data[at+2:at+4], 'big')
        segment = data[at:at+2+size]
        if not (marker == 0xe2 and segment[4:16] == b'ICC_PROFILE\x00'):
            segments.extend(segment)
        at += 2+size
    return hashlib.sha256(segments).hexdigest()


class MemoryCounters(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
            'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]


def run_measured(command, prefix):
    if platform.system() != 'Windows':
        raise RuntimeError('This benchmark currently requires Windows OS counters')
    api = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    api.restype = wintypes.BOOL
    times = ctypes.WinDLL('kernel32', use_last_error=True).GetProcessTimes
    times.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    times.restype = wintypes.BOOL
    peak_ws = peak_commit = samples = 0
    start = time.perf_counter()
    with prefix.with_suffix('.stdout.txt').open('wb') as out, prefix.with_suffix('.stderr.txt').open('wb') as err:
        process = subprocess.Popen(command, stdout=out, stderr=err)
        while True:
            counters = MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if api(int(process._handle), ctypes.byref(counters), counters.cb):
                peak_ws = max(peak_ws, counters.PeakWorkingSetSize)
                peak_commit = max(peak_commit, counters.PeakPagefileUsage)
                samples += 1
            if process.poll() is not None:
                break
            if time.perf_counter() - start > 180:
                process.kill()
                process.wait()
                raise TimeoutError(command)
            time.sleep(0.01)
        wall = (time.perf_counter() - start) * 1000
        values = [wintypes.FILETIME() for _ in range(4)]
        cpu = None
        if times(int(process._handle), *[ctypes.byref(v) for v in values]):
            cpu = sum((v.dwHighDateTime << 32) | v.dwLowDateTime for v in values[2:]) / 10000
    if process.returncode or not samples:
        raise RuntimeError(f'benchmark failed: exit={process.returncode}, memory samples={samples}; {prefix}')
    return {'wallMs': wall, 'cpuMs': cpu, 'peakWorkingSetBytes': peak_ws,
            'peakCommitBytes': peak_commit, 'memorySamples': samples}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cli', type=Path, required=True)
    ap.add_argument('--phase', choices=['baseline', 'candidate'], required=True)
    ap.add_argument('--artifact-dir', type=Path, required=True)
    ap.add_argument('--repeats', type=int, default=3)
    ap.add_argument('--target', choices=['cli', 'preview'], default='cli')
    ap.add_argument('--recipe-cli', type=Path, help='CLI used to initialize recipes for preview benchmark')
    ap.add_argument('--allow-icc-correction', action='store_true', help='allow changed ICC only; all other JPEG bytes must be identical')
    args = ap.parse_args()
    if args.repeats < 3:
        ap.error('at least 3 measured repetitions required')
    root = Path(__file__).resolve().parents[1]
    cli, out = args.cli.resolve(), args.artifact_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    look = root/'fixtures/looks/identity-technical-fixture'
    rows = []
    for fixture in sorted((root/'fixtures/raw').glob('*.NEF')):
        for edge in ((None, 2048) if args.target == 'cli' else (512, 2048)):
            name = fixture.stem + ('-full' if edge is None else f'-{edge}')
            recipe = out/(name + '.recipe.json')
            if args.phase == 'baseline':
                if recipe.exists():
                    raise RuntimeError('use a fresh artifact directory')
                recipe_cli = cli if args.target == 'cli' else args.recipe_cli
                if recipe_cli is None:
                    raise RuntimeError('preview requires --recipe-cli')
                p = subprocess.run([str(recipe_cli.resolve()), 'init-recipe', str(fixture), '--look', str(look), '--out', str(recipe)], capture_output=True)
                if p.returncode:
                    raise RuntimeError(p.stderr.decode('utf-8', 'replace'))
                model = json.loads(recipe.read_text(encoding='utf-8'))
                model['output']['longEdge'] = edge
                recipe.write_text(json.dumps(model, indent=2), encoding='utf-8')
            elif not recipe.exists():
                raise RuntimeError('candidate requires the baseline pinned recipe')
            runs = []
            for i in range(args.repeats + 1):
                folder = out/args.phase/name/str(i)
                folder.mkdir(parents=True, exist_ok=False)
                jpeg, report = folder/'output.jpg', folder/'report.json'
                if args.target == 'cli':
                    command = [str(cli), 'render', str(fixture), '--recipe', str(recipe), '--look', str(look), '--out', str(jpeg), '--report', str(report)]
                else:
                    jpeg = folder/'preview.f32'
                    command = [str(cli), 'preview-dump', str(fixture), str(look), str(recipe), str(edge), str(jpeg), str(report)]
                metrics = run_measured(command, folder/'process')
                metrics.update({'warmup': i == 0, 'jpegSha256': sha(jpeg), 'report': str(report.relative_to(out)), 'command': command})
                metrics['stages'] = json.loads(report.read_text(encoding='utf-8')).get('timings')
                runs.append(metrics)
                print(f'{args.phase} {name} {i}: {metrics["wallMs"]:.1f} ms, {metrics["peakWorkingSetBytes"]/(1<<20):.1f} MiB', flush=True)
            measured = runs[1:]
            rows.append({'name': name, 'fixtureSha256': sha(fixture), 'recipeSha256': sha(recipe), 'runs': runs,
                         'median': {key: statistics.median(r[key] for r in measured) for key in ('wallMs', 'cpuMs', 'peakWorkingSetBytes', 'peakCommitBytes')}})
            result = {'phase': args.phase, 'target': args.target, 'binarySha256': sha(cli), 'platform': platform.platform(),
                      'warmupExcluded': True, 'repeats': args.repeats, 'memoryMethod': 'GetProcessMemoryInfo lifetime peak working set and peak commit, sampled 10ms', 'rows': rows}
            (out/(args.phase+'.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    if args.phase == 'candidate':
        before = json.loads((out/'baseline.json').read_text(encoding='utf-8'))
        comparison = []
        for old, new in zip(before['rows'], rows):
            assert (old['name'],old['fixtureSha256'],old['recipeSha256']) == (new['name'],new['fixtureSha256'],new['recipeSha256'])
            same = len({r['jpegSha256'] for r in old['runs']+new['runs']}) == 1
            same_without_icc = same
            if not same and args.target == 'cli' and args.allow_icc_correction:
                paths = [Path(r['command'][r['command'].index('--out')+1]) for r in old['runs']+new['runs']]
                same_without_icc = len({jpeg_without_icc_sha(p) for p in paths}) == 1
            comparison.append({'name': new['name'], 'jpegByteIdentical': same,
                               'jpegIdenticalExceptICC': same_without_icc,
                               'wallReductionPercent': 100*(1-new['median']['wallMs']/old['median']['wallMs']),
                               'workingSetReductionPercent': 100*(1-new['median']['peakWorkingSetBytes']/old['median']['peakWorkingSetBytes']),
                               'baseline': old['median'], 'candidate': new['median']})
        (out/'comparison.json').write_text(json.dumps(comparison, indent=2), encoding='utf-8')
        if not all(r['jpegByteIdentical'] or (args.allow_icc_correction and r['jpegIdenticalExceptICC']) for r in comparison):
            raise RuntimeError('JPEG output changed')


if __name__ == '__main__':
    main()
