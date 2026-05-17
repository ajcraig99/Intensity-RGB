"""Smoke tests for the render harness in ``tests/render_preview.py``.

These synthesize tiny point clouds and confirm the harness writes non-empty PNGs.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402

from tests.render_preview import render_diff, render_preview  # noqa: E402

ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "artifacts")


def _make_grid(n_side: int = 224) -> tuple[np.ndarray, np.ndarray]:
    """Build an ~n_side^2 grid (~50k points by default) with a gradient color ramp."""
    xs = np.linspace(-1.0, 1.0, n_side, dtype=np.float32)
    ys = np.linspace(-1.0, 1.0, n_side, dtype=np.float32)
    gx, gy = np.meshgrid(xs, ys)
    z = 0.25 * np.sin(3.0 * gx) * np.cos(3.0 * gy)
    xyz = np.stack([gx.ravel(), gy.ravel(), z.ravel()], axis=1)

    # Gradient: R follows x, G follows y, B follows radius.
    r = ((gx.ravel() + 1.0) * 127.5).astype(np.uint8)
    g = ((gy.ravel() + 1.0) * 127.5).astype(np.uint8)
    radius = np.sqrt(gx.ravel() ** 2 + gy.ravel() ** 2)
    b = (np.clip(radius / np.sqrt(2.0), 0.0, 1.0) * 255).astype(np.uint8)
    rgb = np.stack([r, g, b], axis=1)
    return xyz, rgb


def test_render_preview_writes_png() -> None:
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    xyz, rgb = _make_grid(n_side=224)
    assert xyz.shape[0] >= 50_000

    out_path = os.path.join(ARTIFACTS_DIR, "test_render_preview.png")
    if os.path.exists(out_path):
        os.remove(out_path)

    render_preview(xyz, rgb, out_path, title="grid preview")

    assert os.path.exists(out_path), "render_preview did not write the PNG"
    size = os.path.getsize(out_path)
    assert size > 1024, f"PNG is unexpectedly small: {size} bytes"


def test_render_diff_writes_png() -> None:
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    xyz, rgb_a = _make_grid(n_side=224)

    # Perturb rgb in a spatial pattern so the diff has visible structure.
    rgb_b = rgb_a.copy().astype(np.int16)
    # Big diff in upper-right quadrant, small noise elsewhere.
    upper_right = (xyz[:, 0] > 0) & (xyz[:, 1] > 0)
    rgb_b[upper_right, 0] = np.clip(rgb_b[upper_right, 0] + 90, 0, 255)
    rng = np.random.default_rng(1)
    noise = rng.integers(-3, 4, size=rgb_b.shape)
    rgb_b = np.clip(rgb_b + noise, 0, 255).astype(np.uint8)

    out_path = os.path.join(ARTIFACTS_DIR, "test_render_diff.png")
    if os.path.exists(out_path):
        os.remove(out_path)

    render_diff(xyz, rgb_a, rgb_b, out_path, title="grid diff")

    assert os.path.exists(out_path), "render_diff did not write the PNG"
    size = os.path.getsize(out_path)
    assert size > 1024, f"PNG is unexpectedly small: {size} bytes"
