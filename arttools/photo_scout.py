"""photo-scout — score and rank photos by technical quality using pure CV metrics.

Metrics (no AI, no API calls):
  sharpness    Laplacian variance — detects blur and soft focus
  exposure     Histogram analysis — penalizes clipped shadows/highlights
  contrast     RMS contrast (luminance std dev)
  colorfulness Hasler & Süsstrunk (2003) colorfulness formula
  resolution   Pixel count bonus — rewards higher-res images

All metrics are normalized to 0–10 within the scanned batch, then combined
into a weighted score. Scores are relative to your own library, not absolute.
"""
from __future__ import annotations

import csv
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import click
import cv2
import numpy as np
from PIL import Image

# Register HEIC/HEIF support if available (common in Apple Photos libraries)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _HEIC_OK = True
except ImportError:
    _HEIC_OK = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp"}
if _HEIC_OK:
    IMAGE_EXTS |= {".heic", ".heif"}

PHOTOS_LIBRARY = Path.home() / "Pictures" / "Photos Library.photoslibrary" / "originals"

# Scoring weights — must sum to 1.0
WEIGHTS = {
    "sharpness":    0.35,
    "exposure":     0.25,
    "contrast":     0.15,
    "colorfulness": 0.15,
    "resolution":   0.10,
}

# Resize images to this longest dimension before analysis.
# Large enough to preserve sharpness signal; small enough to be fast.
_ANALYSIS_DIM = 1200


# ---------------------------------------------------------------------------
# Worker-level functions (must be top-level for ProcessPoolExecutor pickling)
# ---------------------------------------------------------------------------

def _pixel_count(path: Path) -> int:
    """Read image dimensions without loading pixel data."""
    try:
        img = Image.open(path)
        w, h = img.size
        return w * h
    except Exception:
        return 0


def _load_rgb(path: Path) -> np.ndarray | None:
    """Load image as RGB numpy array, downsampled for analysis."""
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        longest = max(w, h)
        if longest > _ANALYSIS_DIM:
            scale = _ANALYSIS_DIM / longest
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        return np.array(img)
    except Exception:
        return None


def _calc_sharpness(gray: np.ndarray) -> float:
    """Laplacian variance — higher = sharper. Very sensitive to blur."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _calc_exposure(gray: np.ndarray) -> float:
    """
    Exposure score 0–1.
    Penalizes images with clipped shadows (near-black) or highlights (near-white).
    Rewards images with mean brightness near the midpoint.
    """
    total = float(gray.size)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    # Clipping: pixels at the extreme ends of the tonal range
    clipped = (hist[:8].sum() + hist[248:].sum()) / total
    # Center reward: how close is mean brightness to 128?
    mean_brightness = float(gray.mean())
    center_score = 1.0 - abs(mean_brightness - 128.0) / 128.0
    return max(0.0, center_score - clipped * 3.0)


def _calc_contrast(gray: np.ndarray) -> float:
    """RMS contrast — std dev of luminance values."""
    return float(gray.std())


def _calc_colorfulness(rgb: np.ndarray) -> float:
    """
    Hasler & Süsstrunk (2003) colorfulness metric.
    Returns ~0 for grayscale, higher for vivid/saturated images.
    """
    R = rgb[:, :, 0].astype(np.float32)
    G = rgb[:, :, 1].astype(np.float32)
    B = rgb[:, :, 2].astype(np.float32)
    rg = np.abs(R - G)
    yb = np.abs(0.5 * (R + G) - B)
    return float(
        np.sqrt(rg.std() ** 2 + yb.std() ** 2)
        + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )


def _analyze_one(args: tuple[str, int]) -> dict | None:
    """
    Analyze a single image. Returns raw metric dict or None on failure.
    Runs in a worker process — must be a top-level function.
    """
    path_str, pixels = args
    path = Path(path_str)

    rgb = _load_rgb(path)
    if rgb is None:
        return None

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    try:
        return {
            "path": path_str,
            "filename": path.name,
            "pixels": pixels,
            "sharpness":    _calc_sharpness(gray),
            "exposure":     _calc_exposure(gray),
            "contrast":     _calc_contrast(gray),
            "colorfulness": _calc_colorfulness(rgb),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Normalization and scoring
# ---------------------------------------------------------------------------

def _normalize_col(values: list[float], p_low: float = 5.0, p_high: float = 95.0) -> list[float]:
    """
    Normalize a list of raw metric values to 0–10.
    Uses percentile clipping to avoid outliers dominating the scale.
    """
    arr = np.array(values, dtype=np.float64)
    lo = np.percentile(arr, p_low)
    hi = np.percentile(arr, p_high)
    if hi <= lo:
        return [5.0] * len(values)
    clipped = np.clip(arr, lo, hi)
    return ((clipped - lo) / (hi - lo) * 10.0).tolist()


def _apply_scores(raw_results: list[dict]) -> list[dict]:
    """
    Normalize each metric column across the batch, compute weighted scores,
    and return results sorted best-first.
    """
    metrics = ["sharpness", "exposure", "contrast", "colorfulness", "resolution"]

    # Build normalized columns
    norm: dict[str, list[float]] = {}
    for m in metrics:
        if m == "resolution":
            vals = [float(r["pixels"]) for r in raw_results]
        else:
            vals = [r[m] for r in raw_results]
        norm[m] = _normalize_col(vals)

    scored = []
    for i, row in enumerate(raw_results):
        norm_vals = {m: norm[m][i] for m in metrics}
        final_score = sum(WEIGHTS[m] * norm_vals[m] for m in metrics)
        scored.append({
            "score":              round(final_score, 2),
            "path":               row["path"],
            "filename":           row["filename"],
            "pixels":             row["pixels"],
            "sharpness_score":    round(norm_vals["sharpness"], 2),
            "exposure_score":     round(norm_vals["exposure"], 2),
            "contrast_score":     round(norm_vals["contrast"], 2),
            "colorfulness_score": round(norm_vals["colorfulness"], 2),
            "resolution_score":   round(norm_vals["resolution"], 2),
            # Raw values for reference
            "sharpness_raw":      round(row["sharpness"], 1),
            "exposure_raw":       round(row["exposure"], 3),
            "contrast_raw":       round(row["contrast"], 1),
            "colorfulness_raw":   round(row["colorfulness"], 1),
        })

    return sorted(scored, key=lambda r: r["score"], reverse=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("source", default="", required=False)
@click.option("--output", "-o", default="", help="CSV output path [default: ~/Desktop/photo-scout-TIMESTAMP.csv]")
@click.option("--top", "-n", default=0, show_default=True, help="Create a symlink folder of top N photos (0 = disabled)")
@click.option("--top-dir", default="", help="Where to write top-N symlinks [default: ~/Desktop/photo-scout-top/]")
@click.option("--min-pixels", default=1_000_000, show_default=True, help="Skip images below this pixel count (default 1MP)")
@click.option("--sample", default=0, show_default=True, help="Analyze only N randomly chosen images (0 = all)")
@click.option("--workers", default=0, show_default=True, help="Parallel worker processes (0 = half of CPU count)")
def cli(source, output, top, top_dir, min_pixels, sample, workers):
    """Score and rank photos by technical quality using CV metrics.

    SOURCE is a directory to scan. Defaults to your Apple Photos library.

    Metrics: sharpness, exposure, contrast, colorfulness, resolution.
    All are normalized within the scanned batch — scores are relative to
    your own library, not an external standard.

    Examples:\n
      photo-scout\n
      photo-scout ~/Desktop/trip-photos\n
      photo-scout --sample 500 --top 50\n
      photo-scout --min-pixels 2000000 --workers 8
    """
    if not _HEIC_OK:
        click.echo("  Note: pillow-heif not installed — HEIC/HEIF files will be skipped.", err=True)
        click.echo("  Install with: pip install pillow-heif\n", err=True)

    # Resolve source directory
    source_dir = Path(source) if source else PHOTOS_LIBRARY
    if not source_dir.exists():
        click.echo(f"Source not found: {source_dir}", err=True)
        raise SystemExit(1)

    # Resolve output CSV path
    if not output:
        ts = time.strftime("%Y%m%d-%H%M%S")
        output_path = Path.home() / "Desktop" / f"photo-scout-{ts}.csv"
    else:
        output_path = Path(output)

    # Resolve top-dir
    top_dir_path = Path(top_dir) if top_dir else Path.home() / "Desktop" / "photo-scout-top"

    n_workers = workers if workers > 0 else max(1, (os.cpu_count() or 4) // 2)

    click.echo(f"\n  Scanning {source_dir} ...", err=True)

    # Collect all candidate image paths
    candidates: list[tuple[str, int]] = []
    for f in source_dir.rglob("*"):
        if f.suffix.lower() not in IMAGE_EXTS:
            continue
        px = _pixel_count(f)
        if px >= min_pixels:
            candidates.append((str(f), px))

    if not candidates:
        click.echo("  No images found meeting the minimum pixel requirement.", err=True)
        raise SystemExit(1)

    click.echo(f"  Found {len(candidates):,} images >= {min_pixels:,} pixels.", err=True)

    # Apply sample if requested
    if sample > 0 and sample < len(candidates):
        candidates = random.sample(candidates, sample)
        click.echo(f"  Sampling {sample:,} images.", err=True)

    click.echo(f"  Analyzing with {n_workers} workers...\n", err=True)

    # Process in parallel
    raw_results: list[dict] = []
    failed = 0
    start = time.time()

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_analyze_one, c): c for c in candidates}
        with click.progressbar(
            as_completed(futures),
            length=len(futures),
            label="  Scoring",
            file=__import__("sys").stderr,
        ) as bar:
            for future in bar:
                result = future.result()
                if result is not None:
                    raw_results.append(result)
                else:
                    failed += 1

    elapsed = time.time() - start
    click.echo(
        f"\n  Scored {len(raw_results):,} images in {elapsed:.0f}s"
        f" ({failed} skipped/failed).\n",
        err=True,
    )

    if not raw_results:
        click.echo("  No images could be scored.", err=True)
        raise SystemExit(1)

    # Normalize and score
    click.echo("  Normalizing and ranking...", err=True)
    scored = _apply_scores(raw_results)

    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "score", "filename", "pixels",
        "sharpness_score", "exposure_score", "contrast_score",
        "colorfulness_score", "resolution_score",
        "sharpness_raw", "exposure_raw", "contrast_raw", "colorfulness_raw",
        "path",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scored)

    click.echo(f"  Results written to: {output_path}", err=True)

    # Print top 20 summary to stdout
    click.echo(f"\n{'Rank':<5} {'Score':>6}  {'Sharp':>6} {'Exp':>5} {'Con':>5} {'Color':>6}  Filename")
    click.echo("-" * 75)
    for rank, row in enumerate(scored[:20], 1):
        click.echo(
            f"{rank:<5} {row['score']:>6.2f}  "
            f"{row['sharpness_score']:>6.1f} "
            f"{row['exposure_score']:>5.1f} "
            f"{row['contrast_score']:>5.1f} "
            f"{row['colorfulness_score']:>6.1f}  "
            f"{row['filename']}"
        )

    # Create top-N symlink folder if requested
    if top > 0:
        top_dir_path.mkdir(parents=True, exist_ok=True)
        # Clear existing symlinks in the folder
        for existing in top_dir_path.iterdir():
            if existing.is_symlink():
                existing.unlink()

        created = 0
        for row in scored[:top]:
            src = Path(row["path"])
            # Use rank-prefixed name so they sort by score in Finder
            dest = top_dir_path / f"{created + 1:04d}_{src.name}"
            try:
                dest.symlink_to(src)
                created += 1
            except Exception:
                pass

        click.echo(f"\n  Top {created} photos symlinked to: {top_dir_path}", err=True)

    click.echo(f"\n  Done. {len(scored):,} photos ranked. Full results in CSV.\n", err=True)
