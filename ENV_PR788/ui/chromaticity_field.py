"""Shared CIE chromaticity color field for the diagram canvases.

Renders the visible spectrum as a pixel-accurate sRGB image over the chosen
UCS coordinate range (unit-luminance stimulus, D65-referenced sRGB), so the
chromaticity diagrams get an intuitive colored background instead of a flat
dark one. The colour pipeline mirrors colour-science's RGB chromaticity
field (``plot_chromaticity_diagram_colours``): unit-Y XYZ -> sRGB with the
encoding transfer function applied -> per-pixel max normalisation -> clip at
display, with a slight desaturation (``_FIELD_SATURATION``) on top so the
background does not dominate the data drawn on top. The field is rendered
once per (system, range) at a capped, *window-size independent* resolution
(longest side = cap, aspect from the coordinate range) and smoothly scaled to
the requested size at draw time, so resizes / splitter drags are cache hits —
the expensive numpy render never runs per frame. xy / u'v' are additionally
supersampled and box-downsampled so the spectral-locus edge is antialiased
(quarter-coverage alpha) instead of a jagged 1-bit boundary. Supported
systems are the four keys of
``core.PR788_GamutUcs.UCS_SYSTEMS``: CIE 1931 xy, CIE 1976 u'v', CIE 2000 UCS
and CAM16-UCS. The two CAM-based fields need a per-pixel CAM inversion
(per-pixel J solve, see that module) and are capped lower than xy / u'v'.

When a ``locus`` ring is supplied the image is pre-masked with an alpha
channel (transparent outside the ring) instead of relying on
``QPainter.setClipPath(path, Qt.IntersectClipMode)`` — that specific call
segfaults the raster engine in this Qt 5.15.2 build (default ReplaceClipMode
works, but the numpy mask is robust in both on- and offscreen).
"""
from typing import Dict, Optional, Tuple

import numpy as np
from PyQt5 import QtGui
from PyQt5.QtCore import Qt

from core.PR788_GamutUcs import UCS_SYSTEMS

#: CAM-based systems: per-pixel J solve makes a native-resolution field
#: multi-second; the field is a smooth background, so cap the render size
#: and let the draw scale it up. 320 keeps the one-shot render under ~1 s
#: (384 is ~40 % slower — the CIE 2000 range is square) and the upscale
#: blur is invisible on a smooth field.
_CAM_SYSTEMS = ("cie2000ucs", "cam16ucs")
_CAM_MAX_DIM = 320

# CIE XYZ (D65) -> linear sRGB
_XYZ_TO_LINEAR_SRGB = np.array(
    [
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ],
    dtype=float,
)

_MAX_CACHED = 8
_image_cache: Dict[Tuple, Tuple[QtGui.QImage, bytes]] = {}

#: Second-level LRU for the draw-sized (scaled) images. The base render is
#: size independent, so steady-state repaints and repeated resizes back to a
#: previous size hit here instead of re-running the SmoothTransformation
#: scale every frame.
_MAX_SCALED = 16
_scaled_cache: Dict[Tuple, QtGui.QImage] = {}

#: Slight desaturation of the (otherwise colour-science) field, applied in
#: gamma space *after* the per-pixel max normalisation: 1.0 = the library's
#: full-vivid look, lower values ease the background.
_FIELD_SATURATION = 0.80

#: Capped render size (longest side, aspect preserved) for xy / u'v': the
#: cache key is then window-size independent (a resize is a cache hit) and
#: the final image is smoothly scaled to the requested size at draw time.
_FIELD_MAX_DIM = 512

#: xy / u'v' render the field and the ring mask at this supersampling
#: factor and box-downsample: the ring edge then gets quarter-coverage
#: alpha steps (0/64/128/192/255) instead of a jagged 1-bit boundary.
#: CAM systems stay 1x — their per-pixel J inversion is too expensive to
#: supersample, and the capped render is already smooth-upscaled.
_SS = 2

#: The 401-pt spectral-locus ring is smooth; for the alpha mask every 4th
#: point (101 pts, both ends of the line of purples kept) is well under a
#: supersample pixel and cuts the ray-casting cost ~4x.
_MASK_RING_STEP = 4


def _unit_luminance_xyz(system: str, u: np.ndarray, v: np.ndarray):
    """(X, Y, Z) with Y = 1 for chromaticity coordinate arrays (u, v)."""
    if system == "uv":
        # u'v' -> XYZ (inverse of u' = 4x/(x+15y+3z), v' = 9y/(x+15y+3z)):
        # X/Y = 9u'/(4v'), Z/Y = (12 - 3u' - 20v')/(4v')
        with np.errstate(divide="ignore", invalid="ignore"):
            X = np.where(v > 1e-9, 9.0 * u / (4.0 * v), 0.0)
            Z = np.where(v > 1e-9, (12.0 - 3.0 * u - 20.0 * v) / (4.0 * v), 0.0)
    else:  # CIE 1931 xy
        with np.errstate(divide="ignore", invalid="ignore"):
            X = np.where(v > 1e-9, u / v, 0.0)
            Z = np.where(v > 1e-9, (1.0 - u - v) / v, 0.0)
    Y = np.ones_like(u)
    X = np.where(np.isfinite(X), X, 0.0)
    Z = np.where(np.isfinite(Z), Z, 0.0)
    return X, Y, Z


def _srgb_gamma(linear: np.ndarray) -> np.ndarray:
    """sRGB encoding transfer function, applied *before* normalisation.

    Mirrors colour-science's sRGB to-cCTF: no pre-clipping, so out-of-display
    values (a unit-Y spectral stimulus is usually outside sRGB) keep their
    magnitude. Values at or below the 0.0031308 linear knee — including
    negatives, which the library routes through the linear 12.92 segment —
    scale as 12.92 * x; above it, 1.055 * x^(1/2.4) - 0.055. Clipping to
    [0, 1] happens only at display, after the per-pixel max normalisation.
    """
    return np.where(
        linear <= 0.0031308,
        12.92 * linear,
        # np.maximum keeps the unselected power branch finite for negatives
        1.055 * np.power(np.maximum(linear, 0.0), 1.0 / 2.4) - 0.055,
    )


def _points_in_ring(px: np.ndarray, py: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Even-odd ray casting; True where pixel centers (px, py) lie inside the ring.

    ``ring`` is an (N, 2) closed polygon (the wrap-around edge N-1 -> 0 is
    included, so the spectral locus' line of purples closes it for free).

    Row-sliced per edge: the crossing test is only defined on the rows an
    edge actually spans (``(y1 > py) != (y2 > py)`` is False elsewhere), so
    each edge touches only its own row band instead of the whole grid. For a
    closed ring every row lies inside exactly two bands, so total work is
    ~2 * H * W instead of N * H * W — the difference between a ~0.2 s and a
    ~10 s mask on the supersampled field. Bit-identical to the full-grid
    version. ``py`` rows must be monotonic (they are: linspace top -> bottom).
    """
    x1 = np.concatenate([ring[:, 0], ring[:1, 0]])
    y1 = np.concatenate([ring[:, 1], ring[:1, 1]])
    x2 = np.roll(ring[:, 0], -1)
    y2 = np.roll(ring[:, 1], -1)
    inside = np.zeros(px.shape, dtype=bool)
    # ascending coordinate per row, for the band lookups (py runs max -> min)
    asc = -py[:, 0]
    for i in range(len(ring)):
        dy = y2[i] - y1[i]
        if dy == 0.0:  # horizontal edges never cross a horizontal ray
            continue
        lo, hi = min(y1[i], y2[i]), max(y1[i], y2[i])
        r0 = int(np.searchsorted(asc, -hi, side="left"))
        r1 = int(np.searchsorted(asc, -lo, side="right"))
        if r0 >= r1:
            continue
        with np.errstate(divide="ignore", invalid="ignore"):
            xs = x1[i] + (py[r0:r1] - y1[i]) * (x2[i] - x1[i]) / dy
        crossing = ((y1[i] > py[r0:r1]) != (y2[i] > py[r0:r1])) & (px[r0:r1] < xs)
        inside[r0:r1] ^= crossing
    return inside


def _mask_ring(ring: np.ndarray) -> np.ndarray:
    """Decimated ring for the alpha mask (see ``_MASK_RING_STEP``)."""
    if len(ring) > 256 and (len(ring) - 1) % _MASK_RING_STEP == 0:
        return ring[::_MASK_RING_STEP]
    return ring


def chromaticity_image(
    system: str,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    width: int,
    height: int,
    locus: Optional[np.ndarray] = None,
) -> QtGui.QImage:
    """Color field over [x_min, x_max] x [y_min, y_max]; top-left pixel = (x_min, y_max).

    ``system`` is one of the ``UCS_SYSTEMS`` keys: ``"cie1931"`` (x, y),
    ``"uv"`` (u', v'), ``"cie2000ucs"`` / ``"cam16ucs"`` (a', b'). With
    ``locus`` (an (N, 2) ring of coordinates in the same system) the result
    is an ARGB image transparent outside the ring; otherwise a plain RGB888
    image. The field is rendered once at a capped, window-size independent
    resolution (xy / u'v': ``_FIELD_MAX_DIM``, CAM: ``_CAM_MAX_DIM``, longest
    side; aspect from the coordinate range) and, for xy / u'v, at ``_SS``
    supersampling with a box downsample; the returned image is always
    (width, height), smoothly scaled from that render. The result is cached
    per (system, range, locus) — resizes are cache hits plus one scale — and
    the draw-sized scaled images keep a small second LRU; both caches keep
    only the newest entries.
    """
    if width < 2 or height < 2:
        return QtGui.QImage()
    # fixed base render size: longest side = cap, aspect from the coordinate
    # range (independent of the widget, so every resize is a cache hit and
    # the numpy render runs exactly once per system/range per process)
    cap = _CAM_MAX_DIM if system in _CAM_SYSTEMS else _FIELD_MAX_DIM
    aspect = (x_max - x_min) / (y_max - y_min)
    if aspect >= 1.0:
        rw, rh = cap, max(2, round(cap / aspect))
    else:
        rh, rw = cap, max(2, round(cap * aspect))
    # xy / u'v': supersample + box-downsample for an antialiased ring edge;
    # CAM fields stay 1x (per-pixel J inversion too expensive to supersample)
    ss = 1 if system in _CAM_SYSTEMS else _SS
    sw, sh = rw * ss, rh * ss
    locus_tag = None if locus is None else hash(np.round(np.asarray(locus, dtype=float), 6).tobytes())
    key = (system, x_min, x_max, y_min, y_max, sw, sh, locus_tag)
    cached = _image_cache.get(key)
    if cached is not None:
        image = cached[0]
    else:
        u = np.linspace(x_min, x_max, sw)
        v = np.linspace(y_max, y_min, sh)  # rows run y_max (top) -> y_min (bottom)
        U, V = np.meshgrid(u, v)
        if system in _CAM_SYSTEMS:
            # per-pixel unit-Y solve (display-lightness branch); pixels the
            # branch cannot represent come back zero and are outside the ring
            xyz = np.asarray(
                UCS_SYSTEMS[system]["ucs_to_xyz_unit"](np.stack([U.ravel(), V.ravel()], axis=1)),
                dtype=float,
            )
            X, Y, Z = (c.reshape(U.shape) for c in (xyz[:, 0], xyz[:, 1], xyz[:, 2]))
        else:
            X, Y, Z = _unit_luminance_xyz(system, U, V)
        # colour-science's RGB field pipeline
        # (plot_chromaticity_diagram_colours -> XYZ_to_plotting_colourspace
        # + normalise_maximum): unit-Y XYZ -> sRGB *with the CCTF encoding
        # applied before the normalisation* (so out-of-display values keep
        # their relative magnitudes through gamma) -> per-pixel max
        # normalisation -> clip -> slight desaturation (see
        # _FIELD_SATURATION) -> display. The clip must come before the
        # desaturation: a spectral stimulus normalises some channels far
        # below zero (the green of a deep red), and the luma mix must see
        # displayable values or those drag the whole pixel dark. The matrix
        # is defined as rgb = M @ xyz; row vectors are xyz @ M.T.
        linear = np.stack([X, Y, Z], axis=-1) @ _XYZ_TO_LINEAR_SRGB.T
        srgb = _srgb_gamma(linear)
        m = srgb.max(axis=-1)
        srgb = srgb / np.where(m > 0.0, m, 1.0)[..., None]
        srgb = np.clip(srgb, 0.0, 1.0)
        if _FIELD_SATURATION < 1.0:
            luma = srgb @ np.array([0.2126, 0.7152, 0.0722])
            srgb = luma[..., None] + (srgb - luma[..., None]) * _FIELD_SATURATION
        rgb8 = srgb * 255.0 + 0.5

        if locus is None:
            rgba = rgb8[..., None]
        else:
            mask = _points_in_ring(U, V, _mask_ring(np.asarray(locus, dtype=float)))
            rgba = np.dstack([rgb8, np.where(mask, 255.0, 0.0)])
        # box-downsample the supersampled field: (sh, sw, C) with
        # sh = rh*ss, sw = rw*ss -> (rh, rw, C); at ss=2 the alpha picks up
        # quarter-coverage steps (0/64/128/192/255), antialiasing the edge
        if ss > 1:
            rgba = rgba.reshape(rh, ss, rw, ss, rgba.shape[2]).mean(axis=(1, 3))
        out = rgba.astype(np.uint8)
        if locus is None:
            buffer = out.tobytes()
            image = QtGui.QImage(buffer, rw, rh, rw * 3, QtGui.QImage.Format_RGB888)
        else:
            buffer = out.tobytes()
            image = QtGui.QImage(buffer, rw, rh, rw * 4, QtGui.QImage.Format_RGBA8888)
        _image_cache[key] = (image, buffer)
        if len(_image_cache) > _MAX_CACHED:
            _image_cache.pop(next(iter(_image_cache)))
    if (rw, rh) != (width, height):
        # draw-sized result through a small LRU: steady-state repaints (and
        # resizes back to a seen size) skip the SmoothTransformation scale
        skey = (key, width, height)
        scaled = _scaled_cache.get(skey)
        if scaled is not None:
            return scaled
        # IgnoreAspectRatio: the canvases enforce the exact range aspect on
        # their plot rects, so stretching to (width, height) corrects the
        # sub-0.5 % rounding gap of the capped render (and drawImage(inner,
        # field) would stretch anyway) — the result is always exactly
        # (width, height).
        scaled = image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        _scaled_cache[skey] = scaled
        if len(_scaled_cache) > _MAX_SCALED:
            _scaled_cache.pop(next(iter(_scaled_cache)))
        return scaled
    return image
