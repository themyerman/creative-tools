"""Tests for photo_scout CV metrics."""
import numpy as np
import pytest

from arttools.photo_scout import (
    _calc_colorfulness,
    _calc_contrast,
    _calc_exposure,
    _calc_sharpness,
    _normalize_col,
    _apply_scores,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic images as numpy arrays
# ---------------------------------------------------------------------------

def gray(value: int, size: int = 100) -> np.ndarray:
    """Solid gray image."""
    return np.full((size, size), value, dtype=np.uint8)


def noise_gray(size: int = 100) -> np.ndarray:
    """Random noise — sharp by Laplacian standards."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, (size, size), dtype=np.uint8)


def gradient_gray(size: int = 100) -> np.ndarray:
    """Smooth gradient — blurry by Laplacian standards."""
    row = np.linspace(0, 255, size, dtype=np.uint8)
    return np.tile(row, (size, 1))


def solid_rgb(r: int, g: int, b: int, size: int = 100) -> np.ndarray:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:, :, 0] = r
    img[:, :, 1] = g
    img[:, :, 2] = b
    return img


# ---------------------------------------------------------------------------
# Sharpness
# ---------------------------------------------------------------------------

def test_sharpness_noise_beats_gradient():
    """Random noise should score sharper than a smooth gradient."""
    sharp = _calc_sharpness(noise_gray())
    soft = _calc_sharpness(gradient_gray())
    assert sharp > soft


def test_sharpness_solid_is_zero():
    """A solid image has zero Laplacian variance."""
    assert _calc_sharpness(gray(128)) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------

def test_exposure_midtone_scores_high():
    """A well-exposed midtone image should score near 1.0."""
    score = _calc_exposure(gray(128))
    assert score > 0.9


def test_exposure_pure_black_scores_low():
    """A pure-black image is severely clipped and underexposed."""
    score = _calc_exposure(gray(0))
    assert score < 0.2


def test_exposure_pure_white_scores_low():
    """A pure-white image is severely clipped and overexposed."""
    score = _calc_exposure(gray(255))
    assert score < 0.2


def test_exposure_range():
    """Exposure always returns a value in [0, 1]."""
    for v in [0, 64, 128, 192, 255]:
        s = _calc_exposure(gray(v))
        assert 0.0 <= s <= 1.0, f"Out of range for brightness={v}: {s}"


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------

def test_contrast_solid_is_zero():
    assert _calc_contrast(gray(128)) == pytest.approx(0.0)


def test_contrast_noise_beats_near_solid():
    """Random noise should have higher contrast than a near-uniform image."""
    near_solid = np.full((100, 100), 128, dtype=np.uint8)
    near_solid[50, 50] = 130  # tiny variation
    assert _calc_contrast(noise_gray()) > _calc_contrast(near_solid)


# ---------------------------------------------------------------------------
# Colorfulness
# ---------------------------------------------------------------------------

def test_colorfulness_gray_is_zero():
    """A perfectly gray image (R=G=B) has zero colorfulness."""
    img = solid_rgb(128, 128, 128)
    assert _calc_colorfulness(img) == pytest.approx(0.0, abs=0.1)


def test_colorfulness_saturated_beats_gray():
    """A saturated red image should outscore a gray one."""
    red = solid_rgb(255, 0, 0)
    gray_img = solid_rgb(128, 128, 128)
    assert _calc_colorfulness(red) > _calc_colorfulness(gray_img)


def test_colorfulness_nonnegative():
    for r, g, b in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 64, 32)]:
        assert _calc_colorfulness(solid_rgb(r, g, b)) >= 0.0


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_normalize_col_range():
    """Normalized values should all be in [0, 10]."""
    vals = [1.0, 2.0, 3.0, 100.0, 0.5, 50.0]
    result = _normalize_col(vals)
    assert all(0.0 <= v <= 10.0 for v in result)


def test_normalize_col_constant_returns_fives():
    """A constant column should normalize to 5.0 for all entries."""
    result = _normalize_col([7.0] * 10)
    assert all(v == pytest.approx(5.0) for v in result)


def test_normalize_col_length_preserved():
    vals = [float(i) for i in range(20)]
    assert len(_normalize_col(vals)) == 20


# ---------------------------------------------------------------------------
# Scoring pipeline
# ---------------------------------------------------------------------------

def _make_raw(path: str, pixels: int, sharpness: float, exposure: float,
              contrast: float, colorfulness: float) -> dict:
    return {
        "path": path,
        "filename": path.split("/")[-1],
        "pixels": pixels,
        "sharpness": sharpness,
        "exposure": exposure,
        "contrast": contrast,
        "colorfulness": colorfulness,
    }


def test_apply_scores_returns_sorted():
    """Results from _apply_scores should be sorted best-first."""
    raw = [
        _make_raw("/a.jpg", 8_000_000, 500.0, 0.9, 60.0, 80.0),
        _make_raw("/b.jpg", 2_000_000, 10.0,  0.2, 10.0, 5.0),
        _make_raw("/c.jpg", 5_000_000, 200.0, 0.7, 40.0, 40.0),
    ]
    scored = _apply_scores(raw)
    scores = [r["score"] for r in scored]
    assert scores == sorted(scores, reverse=True)


def test_apply_scores_fields_present():
    """Each scored result must have all expected fields."""
    raw = [_make_raw(f"/{i}.jpg", 4_000_000, float(i * 10), 0.5, 30.0, 20.0) for i in range(5)]
    scored = _apply_scores(raw)
    required = {
        "score", "path", "filename", "pixels",
        "sharpness_score", "exposure_score", "contrast_score",
        "colorfulness_score", "resolution_score",
        "sharpness_raw", "exposure_raw", "contrast_raw", "colorfulness_raw",
    }
    for row in scored:
        assert required.issubset(row.keys())


def test_apply_scores_score_range():
    """Final scores should be in [0, 10]."""
    raw = [_make_raw(f"/{i}.jpg", 4_000_000, float(i), float(i) / 10, float(i * 5), float(i * 3))
           for i in range(1, 11)]
    for row in _apply_scores(raw):
        assert 0.0 <= row["score"] <= 10.0
