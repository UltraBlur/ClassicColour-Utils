"""Multi-primary gamut coverage in uniform color spaces (UCS).

Replaces the old fixed-3-primaries / CIE 1931-only ``gamut_coverage``. The
gamut of *any* N >= 3 primaries is the convex hull of all additive mixtures,
and the coverage figures are **overlap** figures in the chosen UCS:

- ``% visible``      = 100 * area(you ∩ visible) / area(visible)
- ``covers ref``     = 100 * area(you ∩ ref)   / area(ref)      (industry
                      "99 % of DCI-P3" convention)
- ``ref covers you`` = 100 * area(you ∩ ref)   / area(you)

Supported UCS (see :data:`UCS_SYSTEMS`): CIE 1931 xy, CIE 1976 u'v',
CIE 2000 UCS (Luo 2006) and CAM16-UCS (Li 2017). The two CAM-based spaces
use the IEC 61966-2-1 viewing conditions (D65 white, L = 40, Cb = 0.63,
average surround), which are exactly the CIE 2000 UCS standard conditions;
the installed ``colour`` build's ``XYZ_to_UCS_Luo2006`` /
``XYZ_to_UCS_Li2017`` default kwargs implement them, so no explicit
condition arguments are passed.

All polygon geometry is self-implemented in numpy (the environment has no
shapely): monotone-chain convex hull, Sutherland-Hodgman convex clipping,
and row-slab integration for the hull ∩ visible-ring overlap (with
ear-clipping triangulation + per-triangle clipping kept as the exact
fallback for a non y-simple ring).

Caveat for non-linear UCS: a gamut triangle in xy maps to a curvilinear
region, so the gamut boundary is approximated by densely sampling the xy
gamut outline (24 segments per edge), mapping it into the UCS and taking
the convex hull of the samples — the outer boundary of the image region to
sub-pixel accuracy for gamut-sized triangles.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import colour
import numpy as np

from colour.models.cam02_ucs import (
    COEFFICIENTS_UCS_LUO2006,
    UCS_Luo2006_to_XYZ,
    XYZ_to_UCS_Luo2006,
)
from colour.models.cam16_ucs import UCS_Li2017_to_XYZ, XYZ_to_UCS_Li2017
from colour.plotting import lines_spectral_locus

from core.PR788_Analysis import GAMUT_LIBRARY, Spectrum, VISIBLE_RANGE

CMFS_NAME = "CIE 1931 2 Degree Standard Observer"
_WL_LO, _WL_HI = VISIBLE_RANGE
#: the 360-830 nm series indexes wavelengths as ``index = wavelength - 360``
_SLICE = slice(_WL_LO - 360, _WL_HI - 360 + 1)  # 380..780, 401 points

#: CIE 2000 UCS / CAM16-UCS standard coefficients (K_L=1, c1=0.007, c2=0.0228).
_UCS_COEFF = COEFFICIENTS_UCS_LUO2006["CAM02-UCS"]

#: how many segments per xy-gamut edge when mapping the outline into a UCS
_OUTLINE_PER_EDGE = 24

_D65_XYZ_UNIT: Optional[np.ndarray] = None


def _d65_xyz_unit() -> np.ndarray:
    """D65 illuminant XYZ normalized to Y = 1 (colour's D65 is Y = 100)."""
    global _D65_XYZ_UNIT
    if _D65_XYZ_UNIT is None:
        xyz = np.asarray(
            colour.sd_to_XYZ(
                colour.SDS_ILLUMINANTS["D65"], colour.MSDS_CMFS[CMFS_NAME]
            ),
            dtype=float,
        )
        _D65_XYZ_UNIT = xyz / xyz[1]
    return _D65_XYZ_UNIT


# --------------------------------------------------------------------------- #
# Polygon geometry (numpy; the environment has no shapely)
# --------------------------------------------------------------------------- #
def _signed_area(poly: np.ndarray) -> float:
    pts = np.asarray(poly, dtype=float)
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def polygon_area(poly: Sequence[Sequence[float]]) -> float:
    """Shoelace area of a closed polygon (absolute value; 0 if < 3 points)."""
    return abs(_signed_area(np.asarray(poly, dtype=float)))


def _cross2(a, b, c) -> float:
    """Z-component of (b - a) x (c - a); > 0 iff a->b->c is counter-clockwise."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def convex_hull(points: Sequence[Sequence[float]]) -> np.ndarray:
    """Andrew monotone chain; returns the CCW hull (no repeated endpoint).

    Collinear points are dropped, so fully collinear input yields <= 2 points
    (zero area) instead of a degenerate polygon — safe for the area code.
    """
    pts = np.unique(np.asarray(points, dtype=float), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half_chain(order: np.ndarray) -> List:
        chain: List = []
        for p in order:
            while len(chain) >= 2 and _cross2(chain[-2], chain[-1], p) <= 0:
                chain.pop()
            chain.append(p)
        return chain

    lower = half_chain(pts)
    upper = half_chain(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def _ensure_ccw(poly: np.ndarray) -> np.ndarray:
    p = np.asarray(poly, dtype=float)
    return p if _signed_area(p) >= 0 else p[::-1]


def _seg_intersect(p1, p2, p3, p4):
    """Intersection of segments p1p2 and p3p4 (assumed non-parallel)."""
    d = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
    if abs(d) < 1e-15:  # (near-)parallel: fall back to a stable interior point
        return ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    t = ((p1[0] - p3[0]) * (p3[1] - p4[1]) - (p1[1] - p3[1]) * (p3[0] - p4[0])) / d
    return (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))


def _sh_clip(subject, clip) -> List[tuple]:
    """Sutherland-Hodgman: clip a simple polygon by the convex CCW polygon
    ``clip`` by iterating over its edge half-planes (left = inside)."""
    out = [tuple(p) for p in subject]
    m = len(clip)
    for i in range(m):
        if not out:
            return []
        e1, e2 = tuple(clip[i]), tuple(clip[(i + 1) % m])
        inp = out
        out = []
        for j in range(len(inp)):
            cur, prev = inp[j], inp[j - 1]
            cur_in = _cross2(e1, e2, cur) >= 0.0
            prev_in = _cross2(e1, e2, prev) >= 0.0
            if cur_in:
                if not prev_in:
                    out.append(_seg_intersect(prev, cur, e1, e2))
                out.append(cur)
            elif prev_in:
                out.append(_seg_intersect(prev, cur, e1, e2))
    return out


def convex_pair_area(a, b) -> float:
    """Area of the intersection of two convex polygons (any winding)."""
    A = _ensure_ccw(np.asarray(a, dtype=float))
    B = _ensure_ccw(np.asarray(b, dtype=float))
    if len(A) < 3 or len(B) < 3:
        return 0.0
    inter = _sh_clip(A, B)
    return abs(_signed_area(np.array(inter))) if len(inter) >= 3 else 0.0


def _ear_clip(ring_ccw: np.ndarray) -> List[np.ndarray]:
    """Ear-clipping triangulation of a simple CCW polygon (O(n^2)).

    Triangles are interior-disjoint and their areas sum to the ring area;
    that is all :func:`convex_vs_ring_area` needs. Falls back to a fan for
    pathological inputs (the 401-point locus rings are clean).
    """
    idx = list(range(len(ring_ccw)))
    tris: List[np.ndarray] = []
    while len(idx) > 3:
        n = len(idx)
        cut = -1
        for i in range(n):
            a, b, c = (
                ring_ccw[idx[(i - 1) % n]],
                ring_ccw[idx[i]],
                ring_ccw[idx[(i + 1) % n]],
            )
            if _cross2(a, b, c) <= 0:  # reflex or collinear: not an ear tip
                continue
            ear = True
            for j in range(n):
                if j % n in ((i - 1) % n, i, (i + 1) % n):
                    continue
                p = ring_ccw[idx[j]]
                if (
                    _cross2(a, b, p) >= 0
                    and _cross2(b, c, p) >= 0
                    and _cross2(c, a, p) >= 0
                ):
                    ear = False
                    break
            if ear:
                cut = i
                break
        if cut < 0:  # no ear found: degenerate, fall back to a fan
            for i in range(1, len(idx) - 1):
                tris.append(
                    np.array([ring_ccw[idx[0]], ring_ccw[idx[i]], ring_ccw[idx[i + 1]]])
                )
            break
        tris.append(
            np.array(
                [
                    ring_ccw[idx[(cut - 1) % n]],
                    ring_ccw[idx[cut]],
                    ring_ccw[idx[(cut + 1) % n]],
                ]
            )
        )
        del idx[cut]
    tris.append(np.array([ring_ccw[idx[0]], ring_ccw[idx[1]], ring_ccw[idx[2]]]))
    return tris


_ring_cache: Dict[str, Tuple[List[np.ndarray], np.ndarray]] = {}


def _ring_triangles(ucs_key: str):
    """Cached ear-clip triangles of the UCS visible ring + their bboxes."""
    hit = _ring_cache.get(ucs_key)
    if hit is None:
        ring = _ensure_ccw(UCS_SYSTEMS[ucs_key]["locus_ucs"]())
        tris = _ear_clip(ring)
        bboxes = np.array(
            [
                [t[:, 0].min(), t[:, 1].min(), t[:, 0].max(), t[:, 1].max()]
                for t in tris
            ]
        )
        hit = (tris, bboxes)
        _ring_cache[ucs_key] = hit
    return hit


def _row_intervals(poly: np.ndarray, ys: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Per-row [L, R] horizontal sections of a closed polygon at row centers ``ys`` (ascending).

    Each non-horizontal edge contributes its crossing x to the rows it spans
    (a searchsorted row band, the same slicing as
    ``chromaticity_field._points_in_ring``); for a *y-simple* polygon — one
    interior interval per horizontal line, which the locus rings are and any
    convex hull is — the section is exactly [min, max] of the crossings,
    because a row through a vertex only duplicates the crossing at the same
    x. Rows that miss the polygon come back with R < L.
    """
    n = len(ys)
    lo = np.full(n, np.inf)
    hi = np.full(n, -np.inf)
    m = len(poly)
    for i in range(m):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % m]
        dy = y2 - y1
        if dy == 0.0:  # horizontal edges never cross a horizontal row
            continue
        r0 = int(np.searchsorted(ys, min(y1, y2), side="right"))
        r1 = int(np.searchsorted(ys, max(y1, y2), side="left"))
        if r0 >= r1:
            continue
        xs = x1 + (ys[r0:r1] - y1) * (x2 - x1) / dy
        lo[r0:r1] = np.minimum(lo[r0:r1], xs)
        hi[r0:r1] = np.maximum(hi[r0:r1], xs)
    return lo, hi


#: fixed midpoint row grid for the per-UCS ring sections (see ``_ring_slab``):
#: 2048 rows keep the midpoint-rule error a few e-4 relative, far below the
#: 0.3-point test tolerances on the overlap percentages
_SLAB_ROWS = 2048
_slab_cache: Dict[str, Tuple[bool, np.ndarray, np.ndarray, np.ndarray]] = {}


def _ring_slab(ucs_key: str) -> Tuple[bool, np.ndarray, np.ndarray, np.ndarray]:
    """Cached ``(ok, ys, L, R)``: the ring's per-row sections on a fixed grid.

    ``ok`` is a runtime y-simplicity self-test — the row-slab area of the
    ring against its own shoelace area. If any horizontal line cut the ring
    in more than one interval, min/max would over-cover and the two areas
    would diverge by a whole lobe (>> the midpoint error), so ``ok=False``
    sends the caller to the exact triangle-clip fallback.
    """
    hit = _slab_cache.get(ucs_key)
    if hit is None:
        ring = _ensure_ccw(UCS_SYSTEMS[ucs_key]["locus_ucs"]())
        yb, yt = float(ring[:, 1].min()), float(ring[:, 1].max())
        ys = yb + (yt - yb) * (np.arange(_SLAB_ROWS) + 0.5) / _SLAB_ROWS
        L, R = _row_intervals(ring, ys)
        slab_area = float(np.sum(np.maximum(R - L, 0.0)) * (ys[1] - ys[0]))
        true_area = abs(_signed_area(ring))
        ok = slab_area > 0.0 and abs(slab_area - true_area) / true_area < 1e-2
        hit = (ok, ys, L, R)
        _slab_cache[ucs_key] = hit
    return hit


def _convex_vs_ring_area_exact(hull, ucs_key: str) -> float:
    """Exact fallback (non y-simple ring): bbox-cull the ear-clip ring
    triangles, then a Sutherland-Hodgman clip of each survivor against the
    convex hull. There is deliberately NO "all vertices outside -> 0" fast
    path: a small hull can sit entirely inside one ring triangle, which a
    vertex test cannot see."""
    H = _ensure_ccw(np.asarray(hull, dtype=float))
    tris, bboxes = _ring_triangles(ucs_key)
    hx0, hy0, hx1, hy1 = H[:, 0].min(), H[:, 1].min(), H[:, 0].max(), H[:, 1].max()
    hit = (
        (bboxes[:, 0] <= hx1)
        & (bboxes[:, 2] >= hx0)
        & (bboxes[:, 1] <= hy1)
        & (bboxes[:, 3] >= hy0)
    )
    total = 0.0
    for tri, h in zip(tris, hit):
        if not h:
            continue
        inter = _sh_clip(tri, H)
        if len(inter) >= 3:
            total += abs(_signed_area(np.array(inter)))
    return total


def convex_vs_ring_area(hull, ucs_key: str) -> float:
    """Area of a convex polygon inside the UCS visible-chromaticity ring.

    Row-slab integration instead of clipping every ear-clip ring triangle:
    on a fixed grid of row centers (cached per UCS, see :func:`_ring_slab`)
    both the y-simple ring and the convex hull have one horizontal section,
    and the per-row overlap of the two intervals is integrated with the
    midpoint rule. Cost is O(ring edges + hull edges + rows), independent of
    the hull's vertex count — a CAM-UCS gamut hull carries ~65 curved
    vertices and the old per-triangle Sutherland-Hodgman loop scaled with
    them (0.5-1 s cold per UCS for the 13-gamut reference table, ~20 ms
    now). The midpoint error is a few e-4 relative (piecewise-linear
    integrand), far below the test tolerances; the runtime y-simplicity
    self-test falls back to the exact clip if a future UCS ring is not
    y-simple.
    """
    H = _ensure_ccw(np.asarray(hull, dtype=float))
    if len(H) < 3:
        return 0.0
    ok, ys, Lr, Rr = _ring_slab(ucs_key)
    if not ok:
        return _convex_vs_ring_area_exact(H, ucs_key)
    if H[:, 1].max() < ys[0] or H[:, 1].min() > ys[-1]:
        return 0.0
    Lh, Rh = _row_intervals(H, ys)
    valid = (Rr >= Lr) & (Rh >= Lh)
    if not valid.any():
        return 0.0
    ov = np.minimum(Rr, Rh) - np.maximum(Lr, Lh)
    return float(np.sum(np.maximum(ov[valid], 0.0)) * (ys[1] - ys[0]))


# --------------------------------------------------------------------------- #
# UCS systems
# --------------------------------------------------------------------------- #
def _xy_to_xyz_unit(xy: np.ndarray) -> np.ndarray:
    """CIE 1931 xy chromaticity row vectors -> unit-Y XYZ."""
    xy = np.asarray(xy, dtype=float)
    x, y = xy[:, 0], xy[:, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        X = np.where(y > 1e-12, x / y, 0.0)
        Z = np.where(y > 1e-12, (1.0 - x - y) / y, 0.0)
    X = np.where(np.isfinite(X), X, 0.0)
    Z = np.where(np.isfinite(Z), Z, 0.0)
    return np.stack([X, np.ones_like(x), Z], axis=1)


def _xy_to_uv(xy: np.ndarray) -> np.ndarray:
    """CIE 1931 xy -> CIE 1976 u'v'.

    u' = 4x/(x + 15y + 3z), v' = 9y/(x + 15y + 3z) — D65 (0.3127, 0.3290)
    maps to (0.19783, 0.46832); keep any test anchor on that value, it is
    the externally-verified one.
    """
    xy = np.asarray(xy, dtype=float)
    x, y = xy[:, 0], xy[:, 1]
    z = 1.0 - x - y
    denom = x + 15.0 * y + 3.0 * z
    with np.errstate(divide="ignore", invalid="ignore"):
        u = np.where(np.abs(denom) > 1e-12, 4.0 * x / denom, 0.0)
        v = np.where(np.abs(denom) > 1e-12, 9.0 * y / denom, 0.0)
    return np.stack([u, v], axis=1)


def _uv_to_xyz_unit(uv: np.ndarray) -> np.ndarray:
    """CIE 1976 u'v' row vectors -> unit-Y XYZ."""
    uv = np.asarray(uv, dtype=float)
    u, v = uv[:, 0], uv[:, 1]
    # X/Y = 9u'/(4v'), Z/Y = (12 - 3u' - 20v')/(4v')  (inverse of the
    # 15y + 3z forward; D65 -> Z/Y = 1.0889)
    with np.errstate(divide="ignore", invalid="ignore"):
        X = np.where(v > 1e-9, 9.0 * u / (4.0 * v), 0.0)
        Z = np.where(v > 1e-9, (12.0 - 3.0 * u - 20.0 * v) / (4.0 * v), 0.0)
    X = np.where(np.isfinite(X), X, 0.0)
    Z = np.where(np.isfinite(Z), Z, 0.0)
    return np.stack([X, np.ones_like(u), Z], axis=1)


def _make_cam_inverse(ucs_to_xyz, j0: float):
    """(a', b') -> unit-Y XYZ for the CAM-based UCS.

    In CAM-UCS (a', b') and lightness are entangled — (a', b') drift with Y
    (verified empirically, so there is no fixed-J shortcut). Every
    representable (a', b') still has a J whose inverse image has Y = 1, but
    Y(J) is NOT monotonic (slightly negative at both J extremes, a hump in
    the middle) and can cross Y = 1 more than once — the (a', b') surface is
    multi-valued across J. The convention is the *display-lightness branch*:
    among all crossings (bracketed by a log-spaced J grid) pick the one
    nearest the J of D65 white (``j0`` ~ 100 under IEC 61966-2-1 conditions),
    then sign-bisection refines the bracket. Batched for the color field:
    the grid sweep is ONE vectorized inverse call, the bisection reuses the
    grid endpoint Y values (no extra bracket evaluations) and runs 10
    iterations (relative J precision ~3e-4 -> chromaticity error < 5e-5 xy,
    sub-pixel at field scale — the field is a smooth background, and this
    halves the ~40 batched inverse calls that dominate its render cost). A
    fixed-J inversion would displace saturated hues by tens of UCS units.
    """
    grid = np.logspace(-2.0, 3.0, 13)
    grid_next = np.concatenate([grid[1:], grid[:1]])

    def ucs_to_xyz_unit(ab: np.ndarray) -> np.ndarray:
        ab = np.atleast_2d(np.asarray(ab, dtype=float))
        n, g = ab.shape[0], grid.size
        idx = np.arange(n)

        def y_of(rows: np.ndarray):
            with np.errstate(all="ignore"):
                xyz = np.asarray(ucs_to_xyz(rows, _UCS_COEFF), dtype=float)
            y = xyz[:, 1]
            return np.where(np.isfinite(y), y, -1.0), xyz

        # 1) grid sweep — one inverse call for all (point, J) pairs
        rows = np.concatenate(
            [np.tile(grid[None, :, None], (n, 1, 1)), np.repeat(ab[:, None, :], g, axis=1)],
            axis=2,
        ).reshape(-1, 3)
        y_grid, _ = y_of(rows)
        y_grid = y_grid.reshape(n, g)
        cross = (
            ((y_grid < 1.0) & (np.roll(y_grid, -1, axis=1) >= 1.0))
            | ((y_grid >= 1.0) & (np.roll(y_grid, -1, axis=1) < 1.0))
        )
        mid = 0.5 * (grid + grid_next)
        cost = np.where(cross, np.abs(mid[None, :] - j0), np.inf)
        k = np.argmin(cost, axis=1)
        has_cross = np.isfinite(cost.min(axis=1))
        best = np.argmin(np.abs(y_grid - 1.0), axis=1)
        j_lo = np.where(has_cross, grid[k], grid[best])
        j_hi = np.where(has_cross, grid_next[k], j_lo)
        # bracket endpoint Y values come straight from the sweep (no re-eval);
        # no-cross points keep j_lo == j_hi == grid[best] and are fixed points
        # of the bisection, so they refine to that grid value as intended
        y_lo = np.where(has_cross, y_grid[idx, k], y_grid[idx, best]) - 1.0
        y_hi = np.where(has_cross, y_grid[idx, (k + 1) % g], y_lo) - 1.0
        # 2) sign bisection
        for _ in range(10):
            j_mid = 0.5 * (j_lo + j_hi)
            y_mid = y_of(np.column_stack([j_mid, ab]))[0] - 1.0
            root_left = y_lo * y_mid <= 0.0
            j_hi = np.where(root_left, j_mid, j_hi)
            y_hi = np.where(root_left, y_mid, y_hi)
            j_lo = np.where(root_left, j_lo, j_mid)
            y_lo = np.where(root_left, y_lo, y_mid)
        # 3) final inverse at the solved J, renormalized to Y = 1. Converged
        # rows satisfy Y = 1 to bisection precision (~1e-3); anything else
        # (no Y = 1 crossing in the grid, i.e. (a', b') not representable on
        # the display-lightness branch — always outside the locus ring, where
        # the field is masked anyway) is zeroed instead of leaking garbage.
        j = 0.5 * (j_lo + j_hi)
        _, xyz = y_of(np.column_stack([j, ab]))
        y = xyz[:, 1]
        ok = np.isfinite(y) & (y > 0.0) & (np.abs(y - 1.0) < 0.5)
        y = np.where(ok, y, 1.0)
        out = xyz / y[:, None]
        bad = (~ok) | (~np.isfinite(out).all(axis=1))
        if bad.any():
            out[bad] = 0.0
        return out

    return ucs_to_xyz_unit


def _make_cam_forward(xyz_to_ucs):
    def xy_to_ucs(pts: np.ndarray) -> np.ndarray:
        xyz = _xy_to_xyz_unit(pts)
        with np.errstate(all="ignore"):  # extreme (imaginary) chromaticities
            out = np.asarray(xyz_to_ucs(xyz, _UCS_COEFF), dtype=float)
        return out[:, 1:]

    return xy_to_ucs


def _spectral_locus_ucs(method: str) -> np.ndarray:
    lines, _ = lines_spectral_locus(method=method)
    return np.asarray(lines["position"], dtype=float)[_SLICE]


def _monochromatic_locus_ucs(xyz_to_ucs) -> np.ndarray:
    """Unit-Y monochromatic locus 380-780 nm mapped into a CAM-based UCS."""
    cmf = np.asarray(colour.MSDS_CMFS[CMFS_NAME].values, dtype=float)[_SLICE]
    cmf = cmf / cmf[:, 1:2]  # unit Y per monochromatic stimulus
    with np.errstate(all="ignore"):
        out = np.asarray(xyz_to_ucs(cmf, _UCS_COEFF), dtype=float)[:, 1:]
    return out[np.isfinite(out).all(axis=1)]


def _make_ucs(
    key: str,
    label: str,
    axis_x: str,
    axis_y: str,
    xy_to_ucs,
    ucs_to_xyz_unit,
    locus_fn,
) -> Dict:
    cache: Dict[str, object] = {}

    def locus_ucs() -> np.ndarray:
        if "locus" not in cache:
            cache["locus"] = _ensure_ccw(np.asarray(locus_fn(), dtype=float))
        return cache["locus"]

    def white_ucs() -> np.ndarray:
        if "white" not in cache:
            d65 = np.asarray(colour.XYZ_to_xy(_d65_xyz_unit()), dtype=float)
            cache["white"] = np.asarray(xy_to_ucs(d65.reshape(1, 2)), dtype=float)[0]
        return cache["white"]

    def visible_area() -> float:
        if "area" not in cache:
            # the 401-point arc + closing purple line; shoelace closes it
            cache["area"] = polygon_area(locus_ucs())
        return cache["area"]

    return {
        "key": key,
        "label": label,
        "axis_x": axis_x,
        "axis_y": axis_y,
        "xy_to_ucs": xy_to_ucs,
        "ucs_to_xyz_unit": ucs_to_xyz_unit,
        "locus_ucs": locus_ucs,
        "white_ucs": white_ucs,
        "visible_area": visible_area,
    }


def _cam_j0(xyz_to_ucs) -> float:
    """J of the unit-Y D65 white point (the display-lightness reference)."""
    with np.errstate(all="ignore"):
        j = np.asarray(xyz_to_ucs(_d65_xyz_unit().reshape(1, 3), _UCS_COEFF), dtype=float)
    return float(j[0, 0])


UCS_SYSTEMS: Dict[str, Dict] = {
    s["key"]: s
    for s in (
        _make_ucs(
            "cie1931",
            "CIE 1931 xy",
            "x",
            "y",
            lambda p: np.asarray(p, dtype=float),
            _xy_to_xyz_unit,
            lambda: _spectral_locus_ucs("CIE 1931"),
        ),
        _make_ucs(
            "uv",
            "CIE 1976 u'v'",
            "u'",
            "v'",
            _xy_to_uv,
            _uv_to_xyz_unit,
            lambda: _spectral_locus_ucs("CIE 1976 UCS"),
        ),
        _make_ucs(
            "cie2000ucs",
            "CIE 2000 UCS (Luo 2006)",
            "a'",
            "b'",
            _make_cam_forward(XYZ_to_UCS_Luo2006),
            _make_cam_inverse(UCS_Luo2006_to_XYZ, _cam_j0(XYZ_to_UCS_Luo2006)),
            lambda: _monochromatic_locus_ucs(XYZ_to_UCS_Luo2006),
        ),
        _make_ucs(
            "cam16ucs",
            "CAM16-UCS (Li 2017)",
            "a'",
            "b'",
            _make_cam_forward(XYZ_to_UCS_Li2017),
            _make_cam_inverse(UCS_Li2017_to_XYZ, _cam_j0(XYZ_to_UCS_Li2017)),
            lambda: _monochromatic_locus_ucs(XYZ_to_UCS_Li2017),
        ),
    )
}


def ucs_label(ucs_key: str) -> str:
    return UCS_SYSTEMS[ucs_key]["label"]


# --------------------------------------------------------------------------- #
# Gamut coverage
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _RefEntry:
    polygon: np.ndarray  # convex polygon in the UCS (CCW)
    area: float
    percent_of_visible: float


_ref_cache: Dict[str, Dict[str, _RefEntry]] = {}


def _gamut_outline_ucs(
    primaries_xy: Sequence[Sequence[float]], ucs_key: str
) -> np.ndarray:
    """UCS polygon of the gamut of N primaries (hull of all mixtures).

    The mixture gamut projects to the convex hull of the primaries in CIE
    1931 xy (a perspective projection commutes with convex hulls while Y > 0).
    Its xy outline is densely sampled, mapped into the (possibly non-linear)
    UCS and re-hulled, which tightly bounds the curvilinear image region.
    Degenerate (collinear) input returns the <= 2-point line as-is.
    """
    hull_xy = convex_hull(np.asarray(primaries_xy, dtype=float))
    if len(hull_xy) < 3:
        return hull_xy
    n = len(hull_xy)
    segs = []
    for i in range(n):
        a, b = hull_xy[i], hull_xy[(i + 1) % n]
        t = np.linspace(0.0, 1.0, _OUTLINE_PER_EDGE + 1)[:-1]
        segs.append(a + t[:, None] * (b - a))
    mapped = UCS_SYSTEMS[ucs_key]["xy_to_ucs"](np.concatenate(segs))
    # imaginary primaries (e.g. ProPhoto blue) leave the CAM model's valid
    # domain and map to NaN; keep only the representable boundary samples
    mapped = mapped[np.isfinite(mapped).all(axis=1)]
    if len(mapped) < 3:
        return mapped
    return convex_hull(mapped)


def _reference_table(ucs_key: str) -> Dict[str, _RefEntry]:
    hit = _ref_cache.get(ucs_key)
    if hit is None:
        visible = UCS_SYSTEMS[ucs_key]["visible_area"]()
        out: Dict[str, _RefEntry] = {}
        for definition in GAMUT_LIBRARY:
            poly = _ensure_ccw(_gamut_outline_ucs(definition.primaries, ucs_key))
            area = polygon_area(poly)
            in_visible = convex_vs_ring_area(poly, ucs_key) if area > 0 else 0.0
            out[definition.name] = _RefEntry(
                polygon=poly,
                area=area,
                percent_of_visible=100.0 * in_visible / visible if visible > 0 else 0.0,
            )
        hit = out
        _ref_cache[ucs_key] = hit
    return hit


def reference_gamut_polygons(ucs_key: str) -> Dict[str, np.ndarray]:
    """Convex polygon (CCW, in the UCS) of each reference gamut, keyed by
    GAMUT_LIBRARY name. Cached per UCS; for the canvas overlays."""
    return {name: entry.polygon for name, entry in _reference_table(ucs_key).items()}


@dataclass(frozen=True)
class RefGamutArea:
    """Overlap figures of the user's gamut against one reference gamut."""

    area: float  # reference gamut area in the UCS (UCS^2)
    percent_of_visible: float  # 100 * area(ref ∩ visible) / area(visible)
    covers_reference: float  # 100 * area(you ∩ ref) / area(ref)
    reference_covers_you: float  # 100 * area(you ∩ ref) / area(you)


@dataclass(frozen=True)
class GamutResult:
    ucs_key: str
    primaries_xy: List[Tuple[float, float]]  # as measured
    primaries_ucs: List[Tuple[float, float]]  # same points in the UCS
    hull_ucs: List[Tuple[float, float]]  # gamut outline (convex, CCW)
    hull_area: float  # in UCS^2
    percent_of_visible: float  # 100 * area(you ∩ visible) / area(visible)
    reference: Dict[str, RefGamutArea]  # keyed by GAMUT_LIBRARY name


def gamut_coverage_ucs(
    primaries: Sequence[Spectrum], ucs_key: str = "cie1931"
) -> GamutResult:
    """Overlap-based coverage of the N-primary gamut in UCS ``ucs_key``.

    ``primaries`` may be any number of spectra (>= 3); the gamut is the convex
    hull of all their additive mixtures, so white/WRGB or other multi-channel
    sources work. Areas are in UCS^2; percentages follow the industry
    "99 % of P3" overlap convention (see module docstring).
    """
    if len(primaries) < 3:
        raise ValueError("Gamut coverage requires at least three primaries.")
    system = UCS_SYSTEMS[ucs_key]
    pts_xy = [(float(sp.x), float(sp.y)) for sp in primaries]
    pts_ucs = np.asarray(system["xy_to_ucs"](np.array(pts_xy)), dtype=float)
    your = _ensure_ccw(_gamut_outline_ucs(pts_xy, ucs_key))
    your_area = polygon_area(your)
    visible = system["visible_area"]()
    your_visible = convex_vs_ring_area(your, ucs_key) if your_area > 0 else 0.0
    reference: Dict[str, RefGamutArea] = {}
    for name, entry in _reference_table(ucs_key).items():
        inter = (
            convex_pair_area(your, entry.polygon)
            if your_area > 0 and entry.area > 0
            else 0.0
        )
        reference[name] = RefGamutArea(
            area=entry.area,
            percent_of_visible=entry.percent_of_visible,
            covers_reference=100.0 * inter / entry.area if entry.area > 0 else 0.0,
            reference_covers_you=100.0 * inter / your_area if your_area > 0 else 0.0,
        )
    return GamutResult(
        ucs_key=ucs_key,
        primaries_xy=pts_xy,
        primaries_ucs=[tuple(map(float, p)) for p in pts_ucs],
        hull_ucs=[tuple(map(float, p)) for p in your],
        hull_area=float(your_area),
        percent_of_visible=100.0 * your_visible / visible if visible > 0 else 0.0,
        reference=reference,
    )
