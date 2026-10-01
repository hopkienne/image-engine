#!/usr/bin/env python3
"""Independent analytical look oracle; no engine, LibRaw or NumPy dependency.

This does NOT validate RAW development, stage tagging, geometry, ICC or an app.
`compare` expects explicitly adapted packed, little-endian RGB FP32 checkpoint
files, not arbitrary native RGBA buffers. It never clips or auto-aligns inputs.
Analytical formulae, not a copy of the engine's LUT interpolator, are the oracle.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
import struct
import sys
from pathlib import Path
from typing import Iterable

KINDS = ('identity', 'permute', 'constant', 'affine', 'multiaffine', 'squaregrid')
DIMS = (17, 33, 65)
RGB = tuple[float, float, float]


def validate_rgb(rgb: Iterable[float]) -> RGB:
    values = tuple(float(v) for v in rgb)
    if len(values) != 3 or not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
        raise ValueError('Expected three finite RGB samples in [0,1]; no implicit clamp.')
    return values  # type: ignore[return-value]


def encode_srgb(v: float) -> float:
    if not math.isfinite(v) or not 0 <= v <= 1:
        raise ValueError('encode_srgb expects bounded linear [0,1].')
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def decode_srgb(v: float) -> float:
    if not math.isfinite(v) or not 0 <= v <= 1:
        raise ValueError('decode_srgb expects encoded [0,1].')
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def square_grid_1d(v: float, dimension: int) -> float:
    # Independent closed-form line segment through samples (i/(N-1))**2.
    # The correct off-grid answer is NOT v**2.
    scale = dimension - 1
    i = min(math.floor(v * scale), scale - 1)
    f = v * scale - i
    return ((1 - f) * i * i + f * (i + 1) * (i + 1)) / (scale * scale)


def formula(kind: str, rgb: Iterable[float], dimension: int = 17) -> RGB:
    r, g, b = validate_rgb(rgb)
    if dimension not in DIMS:
        raise ValueError(f'dimension must be one of {DIMS}')
    if kind == 'identity':
        return r, g, b
    if kind == 'permute':
        return g, b, r
    if kind == 'constant':
        return .125, .5, .875
    if kind == 'affine':
        return (.5*r + .25*g + .125*b + .0625,
                .125*r + .5*g + .0625*b + .125,
                .0625*r + .125*g + .625*b + .03125)
    if kind == 'multiaffine':
        return (.0625 + .5*r + .25*g*b,
                .125 + .375*g + .25*r*b,
                .03125 + .25*b + .25*r*g + .125*r*g*b)
    if kind == 'squaregrid':
        return tuple(square_grid_1d(v, dimension) for v in (r, g, b))  # type: ignore[return-value]
    raise ValueError(f'Unknown look: {kind}')


def expected(kind: str, rgb: Iterable[float], amount: float = 1.0,
             domain: str = 'encoded', dimension: int = 17) -> RGB:
    x = validate_rgb(rgb)
    if not math.isfinite(amount) or not 0 <= amount <= 1:
        raise ValueError('amount must be finite and in [0,1].')
    if domain not in ('encoded', 'linear'):
        raise ValueError('domain must be encoded or linear.')
    if amount == 0:
        return x  # Declared bypass; avoids an unnecessary transfer round trip.
    encoded = x if domain == 'encoded' else tuple(encode_srgb(v) for v in x)
    looked = formula(kind, encoded, dimension)
    mixed = tuple((1 - amount) * v + amount * w for v, w in zip(encoded, looked))
    return mixed if domain == 'encoded' else tuple(decode_srgb(v) for v in mixed)  # type: ignore[return-value]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def dump_json(path: Path, data: object) -> None:
    # Deliberately exclusive: never clobber an existing report or asset.
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def generate(root: Path, dimension: int) -> None:
    if root.exists():
        raise FileExistsError('Output directory already exists; select a new audit directory.')
    root.mkdir(parents=True)
    index = []
    for kind in KINDS:
        folder = root / f'{kind}-{dimension}'
        folder.mkdir()
        cube = folder / 'color.cube'
        with cube.open('x', encoding='ascii', newline='\n') as f:
            f.write(f'TITLE "audit-{kind}-{dimension}"\nLUT_3D_SIZE {dimension}\n')
            f.write('DOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
            # Red fastest, green next, blue slowest. Formula is independent of index.
            for bi in range(dimension):
                for gi in range(dimension):
                    for ri in range(dimension):
                        x = (ri/(dimension-1), gi/(dimension-1), bi/(dimension-1))
                        values = formula(kind, x, dimension)
                        f.write(' '.join(format(v, '.17g') for v in values) + '\n')
        (folder / 'LICENSE.txt').write_text(
            'Original synthetic mathematical test data. Permission is granted to use, '
            'copy, modify and distribute these fixtures for any purpose, without warranty.\n',
            encoding='utf-8')
        manifest = {
            'schemaVersion': 1, 'id': f'audit-{kind}-{dimension}', 'version': '1.0.0',
            'name': f'Audit {kind} {dimension}', 'status': 'prototype',
            'domain': 'srgb-display-v1',
            'sourceKinds': ['cameraRaw', 'linearDng', 'proRaw', 'renderedImage'],
            'compatiblePipelines': ['baseline-v0'],
            'amountPolicy': 'encoded-domain-linear-blend-v1',
            'operator': {'type': 'cube3d', 'opVersion': 1, 'asset': 'color.cube',
                'assetSha256': sha256_file(cube), 'dimension': dimension,
                'interpolation': 'trilinear', 'axisOrder': 'red-fastest',
                'domainMin': [0,0,0], 'domainMax': [1,1,1]},
            'licenseFile': 'LICENSE.txt',
            'notes': 'Synthetic audit fixture; not a photographic look or support certification.'
        }
        dump_json(folder / 'manifest.json', manifest)
        index.append({'kind': kind, 'dimension': dimension, 'package': folder.name,
                      'manifestSha256': sha256_file(folder/'manifest.json'),
                      'assetSha256': sha256_file(cube)})
    dump_json(root / 'index.json', {'generator': 'analytic-oracle-v1', 'packages': index})


def compare(base: Path, actual: Path, *, width: int, height: int, kind: str,
            amount: float, domain: str, dimension: int, atol: float) -> dict:
    if width <= 0 or height <= 0 or width * height > 250_000_000:
        raise ValueError('Invalid dimensions or audit pixel budget exceeded.')
    if not math.isfinite(atol) or not 0 <= atol <= 1e-3:
        raise ValueError('Invalid tolerance; review policy before increasing it.')
    if base.resolve() == actual.resolve():
        raise ValueError('Base and actual must be distinct artifacts, not the same path.')
    expected_bytes = width * height * 3 * 4
    if base.stat().st_size != expected_bytes or actual.stat().st_size != expected_bytes:
        raise ValueError('Wrong byte length for declared packed little-endian RGB FP32.')
    maximum = 0.0
    sum_abs = sum_sq = 0.0
    failed_channels = failed_pixels = 0
    location = None
    index = 0
    # Full scan, bounded memory. No percentile-only pass, NaN omission or sample skipping.
    with base.open('rb') as fb, actual.open('rb') as fa:
        while True:
            xb = fb.read(12 * 16384)
            yb = fa.read(12 * 16384)
            if not xb:
                break
            if len(xb) != len(yb) or len(xb) % 12:
                raise ValueError('Truncated/inconsistent checkpoint during comparison.')
            for xv, yv in zip(struct.iter_unpack('<fff', xb), struct.iter_unpack('<fff', yb)):
                ref = expected(kind, xv, amount, domain, dimension)
                if not all(math.isfinite(v) for v in yv):
                    raise ValueError(f'Non-finite actual sample at pixel {index}; never skip NaN/Inf.')
                pixel_failed = False
                for ch, (a, e) in enumerate(zip(yv, ref)):
                    d = abs(a-e)
                    sum_abs += d
                    sum_sq += d*d
                    if d > maximum:
                        maximum, location = d, {'x': index % width, 'y': index // width,
                                                'channel': 'RGB'[ch], 'actual': a, 'expected': e}
                    if d > atol:
                        failed_channels += 1
                        pixel_failed = True
                failed_pixels += int(pixel_failed)
                index += 1
    if index != width * height:
        raise ValueError('Checkpoint changed during read or incorrect pixel count.')
    n = index*3
    return {
        'schemaVersion': 1, 'scope': 'look-checkpoint-only-not-RAW-or-engine-certification',
        'status': 'PASS' if failed_channels == 0 else 'FAIL',
        'kind': kind, 'dimension': dimension, 'amount': amount, 'domain': domain,
        'format': 'packed-rgb-f32le', 'width': width, 'height': height,
        'tolerance': {'maxAbsoluteError': atol, 'relativeTolerance': 0},
        'metrics': {'maxAbsoluteError': maximum, 'mae': sum_abs/n,
                    'rmse': math.sqrt(sum_sq/n), 'failedChannels': failed_channels,
                    'failedPixels': failed_pixels, 'worstSample': location},
        'inputSha256': sha256_file(base), 'actualSha256': sha256_file(actual),
        'oracle': 'closed-form-v1-no-engine-import'
    }


def self_test() -> dict:
    checks = 0
    def check(condition: bool, text: str) -> None:
        nonlocal checks
        if not condition:
            raise AssertionError(text)
        checks += 1
    def close(got: Iterable[float], ref: Iterable[float], tol: float = 1e-12) -> bool:
        return max(abs(a-b) for a,b in zip(got,ref)) <= tol
    x = (.25,.5,.75)
    check(formula('affine',x) == (.40625,.453125,.578125), 'Hand-calculated affine vector')
    check(formula('multiaffine',x) == (.28125,.359375,.26171875), 'Hand-calculated multiaffine vector')
    check(formula('permute',x) == (.5,.75,.25), 'Permutation vector')
    check(formula('constant',x) == (.125,.5,.875), 'Constant vector')
    check(close((encode_srgb(.5),), (.7353569830524495,)), 'Published sRGB .5 reference')
    check(close((decode_srgb(.5),), (.21404114048223255,)), 'sRGB encoded .5 reference')
    check(close((encode_srgb(.0031308),), (.040449936,), 1e-14), 'Encoding lower branch at knee')
    check(close((decode_srgb(.04045),), (.0031308049535603713,), 1e-14), 'Decoding lower branch at knee')
    # Standard rounded sRGB breakpoints have a tiny mismatch: do not demand exact inverse here.
    check(abs(decode_srgb(encode_srgb(.0031308))-.0031308) < 1e-7, 'Knee round-trip')
    check(formula('squaregrid',(1/32,0,1),17) == (1/512,0,1), 'Piecewise grid, not analytic square')
    for value in ((float('nan'),0,0), (float('inf'),0,0), (-.01,0,0), (1.01,0,0)):
        try:
            formula('affine', value)
        except ValueError:
            checks += 1
        else:
            raise AssertionError('Non-finite/out-of-domain accepted')
    rng = random.Random(20260930)
    mutants = {'bypass':0.0, 'force_amount_one':0.0, 'double_look':0.0,
               'linear_instead_of_encoded':0.0, 'swap_red_blue':0.0,
               'nearest_grid':0.0}
    for _ in range(1000):
        x = tuple(rng.random() for _ in range(3))
        for kind in KINDS:
            y = formula(kind,x)
            check(all(0<=v<=1 for v in y), 'Bounded formula')
            check(expected(kind,x,0) == x, 'Amount zero')
        a = .375
        target = expected('affine',x,a)
        trials = {'bypass':x, 'force_amount_one':expected('affine',x,1),
                  'double_look':expected('affine',target,a),
                  'linear_instead_of_encoded':expected('affine',x,a,'linear'),
                  'swap_red_blue':expected('affine',(x[2],x[1],x[0]),a),
                  'nearest_grid':expected('affine',tuple(round(v*16)/16 for v in x),a)}
        for name, wrong in trials.items():
            mutants[name] = max(mutants[name], max(abs(v-w) for v,w in zip(target,wrong)))
    for name, gap in mutants.items():
        check(gap > 1e-3, f'Oracle has insufficient separation for {name}')
    return {'status':'PASS','checks':checks,
            'scope':'oracle-self-tests-only-not-tests-of-user-engine',
            'analytic_mutant_max_separation':mutants}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('self-test')
    g = sub.add_parser('make-assets')
    g.add_argument('--out', type=Path, required=True)
    g.add_argument('--dimension',type=int,choices=DIMS,default=17)
    c = sub.add_parser('compare')
    c.add_argument('--base', type=Path,required=True)
    c.add_argument('--actual', type=Path,required=True)
    c.add_argument('--width',type=int,required=True)
    c.add_argument('--height',type=int,required=True)
    c.add_argument('--kind',choices=KINDS,required=True)
    c.add_argument('--amount',type=float,required=True)
    c.add_argument('--domain',choices=('linear','encoded'),required=True)
    c.add_argument('--dimension',type=int,choices=DIMS,default=17)
    c.add_argument('--max-error',type=float,default=1e-6)
    c.add_argument('--report',type=Path,required=True)
    a = p.parse_args()
    try:
        if a.cmd == 'self-test':
            print(json.dumps(self_test(),indent=2,allow_nan=False)); return 0
        if a.cmd == 'make-assets':
            generate(a.out,a.dimension)
            print(json.dumps({'status':'GENERATED','path':str(a.out),'engineTested':False})); return 0
        if a.report.exists():
            raise FileExistsError('Report exists; use a fresh run directory.')
        report = compare(a.base,a.actual,width=a.width,height=a.height,kind=a.kind,
                         amount=a.amount,domain=a.domain,dimension=a.dimension,atol=a.max_error)
        dump_json(a.report,report)
        print(json.dumps(report,indent=2,allow_nan=False))
        return 0 if report['status']=='PASS' else 1
    except (OSError, ValueError, AssertionError, OverflowError) as exc:
        print(json.dumps({'status':'BLOCKED_OR_INVALID_INPUT','error':str(exc),
                          'enginePass':False},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
