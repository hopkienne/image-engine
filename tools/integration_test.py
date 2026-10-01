#!/usr/bin/env python3
"""G1 RAW integration test runner.

Drives photo-cli end-to-end against a real RAW fixture:
  1. probe                 -> JSON with hashes/metadata
  2. init-recipe           -> recipe pins source hash + look hashes
  3. render (x2)           -> byte-identical pre-quantize dumps and JPEGs;
                              source hash unchanged after rendering
  4. identity amount 0/1   -> pre-quantize pixels equal within 1e-6
  5. negative paths        -> source hash mismatch, tampered look, existing
                              output path, unsupported recipe fields
  6. JPEG facts            -> size matches, ICC APP2 present, profile parses
                              (Pillow only, skipped when unavailable)

Python 3.10+, stdlib only. Pillow is optional tooling.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

FAILED: list[str] = []


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def run_cli(cli: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([str(cli), *args], capture_output=True, text=True)


def load_f32(p: Path) -> list[float]:
    data = p.read_bytes()
    n = len(data) // 4
    return list(struct.unpack(f"<{n}f", data[: n * 4]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", required=True, type=Path)
    ap.add_argument("--fixture", required=True, type=Path)
    ap.add_argument("--looks", required=True, type=Path, help="directory containing look packages")
    ap.add_argument("--work", required=True, type=Path)
    args = ap.parse_args()
    cli: Path = args.cli.resolve()
    fixture: Path = args.fixture.resolve()
    looks: Path = args.looks.resolve()
    work: Path = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    look_dir = next(p for p in looks.iterdir() if (p / "manifest.json").exists())

    source_before = sha256_file(fixture)

    # ---- 1. probe ---------------------------------------------------------
    proc = run_cli(cli, ["probe", str(fixture), "--json"])
    check("probe exits 0", proc.returncode == 0, proc.stderr.strip()[:200])
    if proc.returncode != 0:
        return 1
    probe = json.loads(proc.stdout)
    check("probe sha256 matches file hash", probe["sha256"] == source_before)
    check("probe classifies cameraRaw", probe["kind"] == "cameraRaw", probe["kind"])
    check("probe reports decoder data",
          probe["dimensions"]["rawWidth"] > 0 and probe["levels"]["whiteLevel"] > 0)

    # ---- 2. init-recipe ----------------------------------------------------
    recipe_path = work / "recipe.json"
    proc = run_cli(cli, ["init-recipe", str(fixture), "--look", str(look_dir),
                         "--out", str(recipe_path)])
    check("init-recipe exits 0", proc.returncode == 0, proc.stderr.strip()[:200])
    if proc.returncode != 0:
        return 1
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    check("recipe pins source sha256", recipe["source"]["sha256"] == source_before)
    check("recipe pins look manifest hash",
          recipe["look"]["manifestSha256"] ==
          sha256_file(look_dir / "manifest.json"))
    check("recipe records pipeline", recipe["execution"]["pipelineId"] == "baseline-v0")
    check("recipe WB resolved from file",
          all(m > 0 for m in recipe["adjustments"]["whiteBalance"]["resolvedCameraMultipliers"]))

    # ---- 3. render twice -> determinism ------------------------------------
    dump1 = work / "run1"
    out1 = work / "run1.jpg"
    rep1 = work / "run1.json"
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(recipe_path),
                         "--look", str(look_dir), "--out", str(out1),
                         "--report", str(rep1), "--diagnostic-pixels", str(dump1)])
    check("render #1 exits 0", proc.returncode == 0, proc.stderr.strip()[:200])
    if proc.returncode != 0:
        return 1
    report1 = json.loads(rep1.read_text(encoding="utf-8"))

    dump2 = work / "run2"
    out2 = work / "run2.jpg"
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(recipe_path),
                         "--look", str(look_dir), "--out", str(out2),
                         "--report", str(work / "run2.json"),
                         "--diagnostic-pixels", str(dump2)])
    check("render #2 exits 0", proc.returncode == 0, proc.stderr.strip()[:200])

    check("pre-quantize dumps byte-identical across runs",
          dump1.with_suffix(".f32").read_bytes() == dump2.with_suffix(".f32").read_bytes())
    check("JPEGs byte-identical across runs",
          sha256_file(out1) == sha256_file(out2))
    check("source hash unchanged after rendering",
          report1["source"]["hashUnchangedAfterRender"] is True)
    check("report carries stage timings",
          report1["timings"]["totalPipelineMs"] > 0 and
          report1["timings"]["developMs"] > 0)
    check("report carries build fingerprint",
          "libraw" in report1["build"] and report1["build"]["developerBuild"] != "")

    # ---- 4. identity amount 0 vs 1 ------------------------------------------
    r0 = work / "recipe_amount0.json"
    proc = run_cli(cli, ["init-recipe", str(fixture), "--look", str(look_dir),
                         "--out", str(r0), "--amount", "0"])
    check("init-recipe amount=0 exits 0", proc.returncode == 0, proc.stderr.strip()[:200])
    dump0 = work / "run_amount0"
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(r0),
                         "--look", str(look_dir), "--out", str(work / "amount0.jpg"),
                         "--report", str(work / "amount0.json"),
                         "--diagnostic-pixels", str(dump0)])
    check("render amount=0 exits 0", proc.returncode == 0, proc.stderr.strip()[:200])
    a = load_f32(dump1.with_suffix(".f32"))
    b = load_f32(dump0.with_suffix(".f32"))
    check("amount=0 dump has same length as amount=1", len(a) == len(b) and len(a) > 0)
    max_diff = max(abs(x - y) for x, y in zip(a, b)) if len(a) == len(b) and a else 1.0
    check("identity look leaves pixels within 1e-6 (amount 0 vs 1)",
          max_diff <= 1e-6, f"max_abs_diff={max_diff:.2e}")

    # ---- 5. negative paths ---------------------------------------------------
    bad_recipe = work / "recipe_bad_hash.json"
    bad = json.loads(recipe_path.read_text(encoding="utf-8"))
    bad["source"]["sha256"] = "0" * 64
    bad_recipe.write_text(json.dumps(bad, indent=2), encoding="utf-8")
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(bad_recipe),
                         "--look", str(look_dir), "--out", str(work / "bad.jpg"),
                         "--report", str(work / "bad.json")])
    check("source hash mismatch rejected (PE_ASSET_MISMATCH)",
          proc.returncode == 1 and "PE_ASSET_MISMATCH" in proc.stderr,
          proc.stderr.strip()[:160])

    tampered_look = work / "tampered_look"
    shutil.copytree(look_dir, tampered_look)
    manifest = json.loads((tampered_look / "manifest.json").read_text(encoding="utf-8"))
    manifest["notes"] = "tampered for test"
    (tampered_look / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                                 encoding="utf-8")
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(recipe_path),
                         "--look", str(tampered_look), "--out", str(work / "bad2.jpg"),
                         "--report", str(work / "bad2.json")])
    check("tampered look package rejected",
          proc.returncode == 1 and "PE_ASSET_MISMATCH" in proc.stderr,
          proc.stderr.strip()[:160])

    existing = work / "exists.jpg"
    existing.write_bytes(b"x")
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(recipe_path),
                         "--look", str(look_dir), "--out", str(existing),
                         "--report", str(work / "exists.json")])
    check("existing output path refused (no overwrite)",
          proc.returncode == 1, proc.stderr.strip()[:160])

    bad_crop = work / "recipe_bad_crop.json"
    bad = json.loads(recipe_path.read_text(encoding="utf-8"))
    bad["geometry"]["crop"]["left"] = 0.5
    bad["geometry"]["crop"]["top"] = 0.5
    bad_crop.write_text(json.dumps(bad, indent=2), encoding="utf-8")
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(bad_crop),
                         "--look", str(look_dir), "--out", str(work / "bad3.jpg"),
                         "--report", str(work / "bad3.json")])
    check("out-of-bounds crop rejected",
          proc.returncode == 1 and "PE_RECIPE_INVALID" in proc.stderr,
          proc.stderr.strip()[:160])

    bad_grain = work / "recipe_grain.json"
    bad = json.loads(recipe_path.read_text(encoding="utf-8"))
    bad["grain"]["enabled"] = True
    bad["grain"]["amount"] = 0.5
    bad_grain.write_text(json.dumps(bad, indent=2), encoding="utf-8")
    proc = run_cli(cli, ["render", str(fixture), "--recipe", str(bad_grain),
                         "--look", str(look_dir), "--out", str(work / "bad4.jpg"),
                         "--report", str(work / "bad4.json")])
    check("grain enabled rejected (not implemented in this build)",
          proc.returncode == 1 and "PE_RECIPE_INVALID" in proc.stderr,
          proc.stderr.strip()[:160])

    # ---- 6. output JPEG facts -------------------------------------------------
    check("output JPEG exists and is non-trivial",
          out1.exists() and out1.stat().st_size > 10_000)
    jpeg = out1.read_bytes()
    check("output JPEG has ICC APP2 marker", b"ICC_PROFILE" in jpeg[:8192])
    check("output JPEG has JFIF APP0 marker", jpeg[2:4] == b"\xff\xe0")
    try:
        from PIL import Image, ImageCms  # optional tooling
        with Image.open(out1) as im:
            check("Pillow opens export with expected size",
                  im.size == (report1["output"]["width"], report1["output"]["height"]),
                  str(im.size))
        icc = report1 and None  # placeholder to keep lints quiet
        del icc
        import io
        prof_bytes = None
        # extract ICC from JPEG APP2
        i, prof = 2, bytearray()
        while i < len(jpeg):
            if jpeg[i] != 0xFF:
                break
            marker = jpeg[i + 1]
            seg_len = int.from_bytes(jpeg[i + 2 : i + 4], "big")
            if marker == 0xE2 and jpeg[i + 4 : i + 16] == b"ICC_PROFILE\x00":
                prof.extend(jpeg[i + 18 : i + 2 + seg_len])
            elif marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pass
            elif marker == 0xDA:
                break
            i += 2 + seg_len
        prof_bytes = bytes(prof)
        ImageCms.ImageCmsProfile(io.BytesIO(prof_bytes))
        check("embedded ICC profile parses with Pillow/ImageCms", True)
    except ImportError:
        print("[SKIP] Pillow not installed - ICC parse check skipped")
    except Exception as exc:  # noqa: BLE001
        check("embedded ICC profile parses with Pillow/ImageCms", False, str(exc))

    print()
    if FAILED:
        print(f"FAILED checks: {len(FAILED)}")
        for f in FAILED:
            print("  -", f)
        return 1
    print("ALL INTEGRATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
