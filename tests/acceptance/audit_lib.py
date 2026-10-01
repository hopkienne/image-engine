#!/usr/bin/env python3
"""Shared helpers for the G1 independent audit suite.

The oracle of record is RAW_Engine_Independent_Audit_v1/reference/oracle.py
(copied verbatim under oracle/ and hash-pinned). numpy is used ONLY as a
cross-checked accelerator; see audit_policy.json.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import struct
import subprocess
import time
import unicodedata
from pathlib import Path

import numpy as np

AUDIT_DIR = Path(__file__).resolve().parent
COMMAND_DIR = None
COMMAND_SEQUENCE = 0


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CaseResult(dict):
    pass


def make_result(case_id: str, variant: str, claim: str, status: str, *,
                command=None, exit_code=None, expected=None, actual=None,
                metric=None, artifacts=None, reason=None, level="CORE",
                oracle_ref=None) -> CaseResult:
    return CaseResult({
        "caseId": case_id, "variant": variant, "level": level, "claim": claim,
        "status": status, "reason": reason, "command": command,
        "exitCode": exit_code, "expected": expected, "actual": actual,
        "metric": metric, "oracle": oracle_ref, "artifacts": artifacts or [],
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


def run(cmd, timeout=900, env=None, cwd=None):
    global COMMAND_SEQUENCE
    t0 = time.time()
    argv = [str(c) for c in cmd]
    result = None
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, env=env, cwd=cwd)
        result = {"exit": proc.returncode, "stdout": proc.stdout,
                  "stderr": proc.stderr, "seconds": round(time.time() - t0, 3)}
        return result
    except subprocess.TimeoutExpired as exc:
        result = {"exit": None, "timeout": True, "seconds": round(time.time() - t0, 3),
                  "stdout": str(exc.stdout or ""), "stderr": str(exc.stderr or "")}
        raise
    finally:
        if COMMAND_DIR is not None:
            COMMAND_DIR.mkdir(parents=True, exist_ok=True)
            COMMAND_SEQUENCE += 1
            (COMMAND_DIR / f"command-{COMMAND_SEQUENCE:05d}.json").write_text(
                json.dumps({"argv": argv, "cwd": str(cwd), "timeoutSeconds": timeout,
                            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "fault": (env or {}).get("PE_AUDIT_FAULT"),
                            "result": result}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- dumps ----

def load_f32(path) -> np.ndarray:
    data = np.fromfile(path, dtype="<f4")
    return data


def load_stage(ckpt_dir: Path, stage: str):
    """Loads a checkpoint written by the engine; validates the descriptor
    against the actual file bytes (wrapper-level shape check, AUD-002)."""
    desc = json.loads((ckpt_dir / f"{stage}.json").read_text(encoding="utf-8"))
    path = ckpt_dir / f"{stage}.f32"
    expected_bytes = desc["width"] * desc["height"] * desc["channels"] * 4
    actual_bytes = path.stat().st_size
    if desc["channels"] != 3 or desc["channelOrder"] != "RGB" or \
            desc["sampleType"] != "float32" or desc["byteOrder"] != "little":
        raise AssertionError(f"{stage}: unexpected descriptor layout: {desc}")
    if actual_bytes != expected_bytes:
        raise AssertionError(
            f"{stage}: descriptor/file mismatch: {desc['width']}x{desc['height']}"
            f"x3 f32 needs {expected_bytes} bytes, file has {actual_bytes}")
    if desc.get("rowStrideBytes") != desc["width"] * 3 * 4 or \
            desc.get("byteLength") != expected_bytes:
        raise AssertionError(f"{stage}: descriptor stride/byteLength mismatch")
    arr = load_f32(path).reshape(desc["height"], desc["width"], 3)
    if not np.isfinite(arr).all():
        raise AssertionError(f"{stage}: non-finite samples")
    return desc, arr


def check_stage_shape(desc, expected_width: int, expected_height: int, stage: str):
    """Wrapper-level shape authority check (AUD-002): descriptor dimensions must
    match dimensions derived independently (probe/report), because a raw byte
    stream cannot carry its own shape - same-byte-count lies must be caught here."""
    if desc["width"] != expected_width or desc["height"] != expected_height:
        raise AssertionError(
            f"{stage}: descriptor shape {desc['width']}x{desc['height']} does "
            f"not match expected {expected_width}x{expected_height}")


def delete_stage_dumps(ckpt_dir: Path, keep=()):
    """Disk-budget enforcement: checkpoints are large (~1 GB per render)."""
    if not ckpt_dir.exists():
        return
    for p in ckpt_dir.iterdir():
        if p.suffix == ".f32" and p.stem not in keep:
            p.unlink()


# ------------------------------------------------- accelerated oracle ----

class AcceleratedOracle:
    """Vectorized float64 implementation of the same closed-form formulas as
    reference/oracle.py. Cross-checked against the reference comparator on a
    random sample of every compared image (see check_against_reference)."""

    def __init__(self, ref_module):
        self.ref = ref_module

    @staticmethod
    def encode(v: np.ndarray) -> np.ndarray:
        return np.where(v <= 0.0031308, 12.92 * v,
                        1.055 * np.power(np.clip(v, 0, 1), 1 / 2.4) - 0.055)

    @staticmethod
    def decode(v: np.ndarray) -> np.ndarray:
        return np.where(v <= 0.04045, v / 12.92,
                        np.power((np.clip(v, 0, 1) + 0.055) / 1.055, 2.4))

    @staticmethod
    def square_grid_1d(v: np.ndarray, n: int) -> np.ndarray:
        s = n - 1
        i = np.minimum(np.floor(v * s).astype(np.int64), s - 1)
        f = v * s - i
        i = i.astype(np.float64)
        return ((1 - f) * i * i + f * (i + 1) * (i + 1)) / (s * s)

    def formula(self, kind: str, x: np.ndarray, n: int) -> np.ndarray:
        r, g, b = x[..., 0], x[..., 1], x[..., 2]
        if kind == "identity":
            y = x
        elif kind == "permute":
            y = np.stack([g, b, r], axis=-1)
        elif kind == "constant":
            y = np.broadcast_to(np.array([0.125, 0.5, 0.875]), x.shape).copy()
        elif kind == "affine":
            y = np.stack([0.5 * r + 0.25 * g + 0.125 * b + 0.0625,
                          0.125 * r + 0.5 * g + 0.0625 * b + 0.125,
                          0.0625 * r + 0.125 * g + 0.625 * b + 0.03125], axis=-1)
        elif kind == "multiaffine":
            y = np.stack([0.0625 + 0.5 * r + 0.25 * g * b,
                          0.125 + 0.375 * g + 0.25 * r * b,
                          0.03125 + 0.25 * b + 0.25 * r * g + 0.125 * r * g * b],
                         axis=-1)
        elif kind == "squaregrid":
            y = np.stack([self.square_grid_1d(r, n),
                          self.square_grid_1d(g, n),
                          self.square_grid_1d(b, n)], axis=-1)
        else:
            raise ValueError(kind)
        return np.clip(y, 0.0, 1.0)

    def expected(self, kind, x: np.ndarray, amount: float, domain: str, n: int):
        if domain == "encoded":
            enc = x
        else:
            enc = self.encode(x)
        looked = self.formula(kind, enc, n)
        mixed = (1 - amount) * enc + amount * looked
        if amount == 0:
            mixed = x  # declared bypass
        return mixed if domain == "encoded" else self.decode(mixed)

    def compare(self, base_arr, actual_arr, *, kind, amount, domain, dimension,
                atol) -> dict:
        x = base_arr.astype(np.float64)
        y = actual_arr.astype(np.float64)
        if x.shape != y.shape:
            raise AssertionError(f"shape mismatch {x.shape} vs {y.shape}")
        if not np.isfinite(y).all():
            raise AssertionError("non-finite actual sample; never skipped")
        exp = self.expected(kind, x, amount, domain, dimension)
        diff = np.abs(y - exp)
        max_err = float(diff.max())
        # Correctness of the accelerated path against float32 inputs: the
        # engine computed in FP32; recompute expected from FP32-rounded inputs.
        failed = int((diff > atol).sum())
        return {"status": "PASS" if failed == 0 else "FAIL",
                "kind": kind, "amount": amount, "domain": domain,
                "dimension": dimension,
                "tolerance": {"maxAbsoluteError": atol},
                "metrics": {"maxAbsoluteError": max_err,
                            "mae": float(diff.mean()),
                            "rmse": float(np.sqrt((diff ** 2).mean())),
                            "failedChannels": failed,
                            "totalChannels": int(diff.size)},
                "oracle": "closed-form-v1-numpy-accelerated-float64"}

    def check_against_reference(self, ref_compare_fn, base_arr, actual_arr, *,
                                kind, amount, domain, dimension, atol,
                                sample_dir: Path, min_samples=200000):
        """Runs the provided reference comparator on a random sample saved as
        packed RGB FP32 files; any disagreement is a FAIL of the accelerator."""
        rng = np.random.default_rng(20260930)
        flat_x = base_arr.reshape(-1, 3)
        flat_y = actual_arr.reshape(-1, 3)
        count = min(min_samples, flat_x.shape[0])
        idx = np.sort(rng.choice(flat_x.shape[0], size=count, replace=False))
        sample_x = flat_x[idx]
        sample_y = flat_y[idx]
        sample_dir.mkdir(parents=True, exist_ok=True)
        w = count
        h = 1
        bx = sample_dir / "sample_base.f32le"
        ax = sample_dir / "sample_actual.f32le"
        sample_x.astype("<f4").tofile(bx)
        sample_y.astype("<f4").tofile(ax)
        ref_report = sample_dir / "reference_report.json"
        if ref_report.exists():
            ref_report.unlink()
        cmd = ["python", str(ref_compare_fn), "compare", "--base", str(bx),
               "--actual", str(ax), "--width", str(w), "--height", str(h),
               "--kind", kind, "--amount", str(amount), "--domain", domain,
               "--dimension", str(dimension), "--max-error", str(atol),
               "--report", str(ref_report)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode not in (0, 1):
            raise AssertionError(f"reference comparator blocked: {proc.stderr}")
        ref = json.loads(ref_report.read_text(encoding="utf-8"))
        accel = self.compare(flat_x[idx], flat_y[idx], kind=kind, amount=amount,
                             domain=domain, dimension=dimension, atol=atol)
        ref_max = ref["metrics"]["maxAbsoluteError"]
        accel_max = accel["metrics"]["maxAbsoluteError"]
        agree = abs(ref_max - accel_max) <= max(1e-9, 0.05 * max(ref_max, 1e-9)) or \
            (ref_max <= atol and accel_max <= atol)
        if not agree:
            raise AssertionError(
                f"accelerator/reference disagreement: ref max={ref_max} "
                f"accel max={accel_max}")
        return {"referenceMaxAbsoluteError": ref_max,
                "acceleratedMaxAbsoluteError": accel_max,
                "referenceStatus": ref["status"], "samples": count,
                "agreement": True}


# ------------------------------------------------------------ helpers ----

def write_recipe(path: Path, *, source_sha: str, manifest_sha: str, look_id: str,
                 amount=1.0, ev=0.0, wb_mode="asShot", multipliers=None,
                 quality=92, long_edge=None, crop=None, rotate=0, flip=False,
                 subsampling="444"):
    multipliers = multipliers or [1.9609375, 1.0, 1.51171875, 1.0]
    crop = crop or {"left": 0, "top": 0, "width": 1, "height": 1}
    recipe = {
        "schemaVersion": 1, "recipeId": "audit-recipe",
        "source": {"id": "audit-src", "sha256": source_sha, "kind": "cameraRaw"},
        "execution": {"engineCompatibility": "photo-engine-major-1-proposed",
                      "pipelineId": "baseline-v0", "pipelineVersion": "0.1.0",
                      "developerBuild": "photo-engine-g1-libraw-0.22.2",
                      "cameraProfile": None},
        "adjustments": {"exposureEV": ev,
                        "whiteBalance": {"mode": wb_mode,
                                         "resolvedCameraMultipliers": multipliers}},
        "look": {"id": look_id, "version": "1.0.0",
                 "manifestSha256": manifest_sha, "amount": amount},
        "geometry": {"crop": crop, "rotationQuarterTurns": rotate,
                     "flipHorizontal": flip},
        "grain": {"enabled": False, "algorithm": "grain-v1-proposed", "seed": 0,
                  "amount": 0, "referenceLongEdge": 2048},
        "output": {"format": "jpeg", "colorSpace": "srgb", "bitDepth": 8,
                   "quality": quality, "subsampling": subsampling,
                   "longEdge": long_edge, "metadataPolicy": "strip_location"},
    }
    path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    return recipe


def extract_icc(jpeg_path: Path) -> bytes:
    jpeg = jpeg_path.read_bytes()
    i, prof = 2, bytearray()
    while i < len(jpeg):
        if jpeg[i] != 0xFF:
            break
        marker = jpeg[i + 1]
        seg_len = int.from_bytes(jpeg[i + 2:i + 4], "big")
        if marker == 0xE2 and jpeg[i + 4:i + 18] == b"ICC_PROFILE\x00\x01\x01":
            prof.extend(jpeg[i + 18:i + 2 + seg_len])
        elif marker == 0xDA:
            break
        i += 2 + seg_len
    return bytes(prof)


def sof0_sampling(jpeg_path: Path):
    """Parses SOF0 marker: returns list of (component_id, h, v) sampling."""
    jpeg = jpeg_path.read_bytes()
    i = 2
    while i < len(jpeg):
        if jpeg[i] != 0xFF:
            i += 1
            continue
        marker = jpeg[i + 1]
        seg_len = int.from_bytes(jpeg[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1):
            ncomp = jpeg[i + 9]
            comps = []
            for c in range(ncomp):
                base = i + 10 + c * 3
                comps.append((jpeg[base], jpeg[base + 1] >> 4,
                              jpeg[base + 1] & 0xF))
            return comps
        if marker == 0xDA:
            break
        i += 2 + seg_len
    return None
