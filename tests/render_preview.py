"""Matplotlib-based render harness for self-verification PNGs of baked point clouds.

Used by pipeline tests to generate visual previews and per-point diff images.
The Agg backend is selected so this works headlessly.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def _decimate(n: int, max_points: int) -> np.ndarray | None:
    """Return a uniform index sample if n > max_points, else None."""
    if n <= max_points:
        return None
    rng = np.random.default_rng(0)
    return rng.choice(n, max_points, replace=False)


def render_preview(
    xyz: np.ndarray,
    rgb: np.ndarray,
    out_path: str,
    *,
    max_points: int = 500_000,
    title: str = "",
) -> None:
    """Render a two-panel (XY top-down + XZ side) preview PNG of a colored point cloud.

    Parameters
    ----------
    xyz : (N, 3) float array of point coordinates.
    rgb : (N, 3) uint8 array of per-point RGB color.
    out_path : path to write the PNG.
    max_points : decimation cap. If N exceeds this, points are uniformly subsampled
        using a seeded RNG (`np.random.default_rng(0)`) for determinism.
    title : figure title.
    """
    n = xyz.shape[0]
    idx = _decimate(n, max_points)
    if idx is not None:
        xyz = xyz[idx]
        rgb = rgb[idx]

    colors = rgb.astype(np.float32) / 255.0

    fig, (ax_xy, ax_xz) = plt.subplots(1, 2, figsize=(12, 6))

    ax_xy.scatter(xyz[:, 0], xyz[:, 1], c=colors, s=0.5, marker=",")
    ax_xy.set_aspect("equal")
    ax_xy.set_xlabel("X")
    ax_xy.set_ylabel("Y")
    ax_xy.set_title("Top-down (XY)")

    ax_xz.scatter(xyz[:, 0], xyz[:, 2], c=colors, s=0.5, marker=",")
    ax_xz.set_aspect("equal")
    ax_xz.set_xlabel("X")
    ax_xz.set_ylabel("Z")
    ax_xz.set_title("Side (XZ)")

    if title:
        fig.suptitle(title)

    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def render_diff(
    xyz: np.ndarray,
    rgb_a: np.ndarray,
    rgb_b: np.ndarray,
    out_path: str,
    *,
    max_points: int = 500_000,
    title: str = "",
) -> None:
    """Render an XY top-down PNG colored by the per-channel max-abs-diff between rgb_a and rgb_b.

    Small diffs render grey; large diffs render hot. Used to visualize where a
    recolor moved values vs. a source baseline.

    Parameters
    ----------
    xyz : (N, 3) float array of point coordinates.
    rgb_a, rgb_b : (N, 3) uint8 arrays of per-point RGB color. Must be the same shape.
    out_path : path to write the PNG.
    max_points : decimation cap. Subsampling uses the seeded RNG.
    title : figure title.
    """
    n = xyz.shape[0]
    idx = _decimate(n, max_points)
    if idx is not None:
        xyz = xyz[idx]
        rgb_a = rgb_a[idx]
        rgb_b = rgb_b[idx]

    # Per-channel max-abs-diff in [0, 255], normalize to [0, 1].
    a_i = rgb_a.astype(np.int16)
    b_i = rgb_b.astype(np.int16)
    diff = np.max(np.abs(a_i - b_i), axis=1).astype(np.float32) / 255.0

    fig, ax = plt.subplots(figsize=(8, 8))
    sc = ax.scatter(
        xyz[:, 0],
        xyz[:, 1],
        c=diff,
        cmap="inferno",
        vmin=0.0,
        vmax=1.0,
        s=0.5,
        marker=",",
    )
    ax.set_aspect("equal")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_title("Recolor diff (max-abs per channel)")
    fig.colorbar(sc, ax=ax, label="max |Δ| / 255")

    if title:
        fig.suptitle(title)

    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
