"""Pure computation layer for offline spectral data-processing.

This module has **no Qt dependency** so the math can be unit-tested and reused
by any front-end. It builds on :mod:`core.PR788_Preview` for CSV loading and
tristimulus integration, and adds:

- :class:`Spectrum` — one loaded measurement with derived colourimetry.
- Color-difference metrics (CIE76 / 1994 / 2000 / CMC / ITP) between spectra.
- Per-wavelength difference and ratio (transmittance / reflectance) curves.
- Single-spectrum statistics (power, peak, FWHM, centroid).
- Color-gamut definitions and the multi-primary / UCS coverage math
  (see :mod:`core.PR788_GamutUcs`).
- CRI (Ra + R1..Rn) via the installed ``colour`` build.

Conventions
-----------
These are *emitted-light* spectra (relative SPDs), so all color differences are
computed on **chromaticity only**: each spectrum is normalized to unit *Y*
before Lab and to *Y* = 100 before ICtCp. Two measurements of the same source at
different gain therefore compare as the same colour. Absolute luminance (the raw
*Y* in the 683 lm/W scale) is still carried on each :class:`Spectrum` so callers
can show it separately.

Note on ITP: the installed ``colour`` build's ``delta_E_ITP`` implements
ITU-R BT.2124 (the T channel is halved). ITU-T P.143 ITP does not halve T. Both
are computed here directly from the verified ICtCp matrix so the two figures can
be shown side by side.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import colour
import colour.difference as _delta_e
import numpy as np

from core.PR788_Preview import csv_to_rows, rows_to_sd

CMFS_NAME = "CIE 1931 2 Degree Standard Observer"
ILLUMINANT_NAME = "E"
K = 683.0

#: Visible span used for the CIE 1931 chromaticity-diagram (gamut) reference.
VISIBLE_RANGE = (380, 780)

#: CIE XYZ (Y = 100) -> ICtCp, ITU-R BT.2124 / ITU-T P.143. Verified: D65
#: (95.047, 100, 108.883) maps to I' = 207.196 (literature 207.19).
_XYZ_TO_ICTCP = np.array(
    [
        [0.409619125403, 1.668425812597, 0.013042499109],
        [-0.071683130767, -1.004058663239, 2.513144105036],
        [-0.082143903925, 0.998154892010, -0.254967111700],
    ]
)


# --------------------------------------------------------------------------- #
# Spectrum
# --------------------------------------------------------------------------- #
@dataclass
class Spectrum:
    """One loaded spectral measurement plus its derived colourimetry."""

    name: str
    csv_path: Optional[str]
    wavelengths: np.ndarray  # (n,) int, nm
    values: np.ndarray  # (n,) float, relative SPD
    xyz: np.ndarray  # (3,) absolute tristimulus (k = 683)
    x: float
    y: float
    Y: float  # luminance, 683 lm/W scale
    u_prime: float
    v_prime: float
    lab: np.ndarray  # (3,) chromaticity Lab (Y normalized to 1)
    ictcp: np.ndarray  # (3,) ICtCp (Y normalized to 100)


def _xyz_to_lab_unit_y(xyz: np.ndarray) -> np.ndarray:
    """Chromaticity-only CIE L*a*b*: normalize Y to 1, use the installed
    ``XYZ_to_Lab`` (which expects scale-1 XYZ and D65 white by default)."""
    xyz = np.asarray(xyz, dtype=float)
    if xyz[1] <= 0:
        raise ValueError("Spectrum has non-positive Y; cannot derive Lab.")
    return np.asarray(colour.XYZ_to_Lab(xyz / xyz[1]), dtype=float)


def _xyz_to_ictcp_unit_y100(xyz: np.ndarray) -> np.ndarray:
    """ICtCp for a light source: normalize Y to 100, apply the BT.2124 matrix."""
    xyz = np.asarray(xyz, dtype=float)
    if xyz[1] <= 0:
        raise ValueError("Spectrum has non-positive Y; cannot derive ICtCp.")
    return _XYZ_TO_ICTCP @ (xyz * 100.0 / xyz[1])


def load_spectrum(csv_path: str, name: Optional[str] = None) -> Spectrum:
    """Load a two-column ``wavelength,value`` CSV into a :class:`Spectrum`."""
    rows = csv_to_rows(csv_path)
    wavelengths = np.array([w for w, _ in rows], dtype=int)
    values = np.array([v for _, v in rows], dtype=float)

    sd = rows_to_sd(rows, name=name or "Spectrum")
    illuminant = colour.SDS_ILLUMINANTS[ILLUMINANT_NAME]
    cmfs = colour.MSDS_CMFS[CMFS_NAME]
    xyz = np.asarray(colour.sd_to_XYZ(sd, cmfs, illuminant, K), dtype=float)
    xyy = colour.XYZ_to_xyY(xyz)
    denom = xyz[0] + 15 * xyz[1] + 3 * xyz[2]

    label = name or (
        str(csv_path).rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    )

    return Spectrum(
        name=label,
        csv_path=str(csv_path),
        wavelengths=wavelengths,
        values=values,
        xyz=xyz,
        x=float(xyy[0]),
        y=float(xyy[1]),
        Y=float(xyy[2]),
        u_prime=float(4 * xyz[0] / denom),
        v_prime=float(9 * xyz[1] / denom),
        lab=_xyz_to_lab_unit_y(xyz),
        ictcp=_xyz_to_ictcp_unit_y100(xyz),
    )


def load_spectra(
    csv_paths: Sequence[str],
    names: Optional[Sequence[str]] = None,
) -> List[Spectrum]:
    if not csv_paths:
        raise ValueError("No CSV paths were provided.")
    if names is None:
        names = [None] * len(csv_paths)
    return [
        load_spectrum(path, nm) for path, nm in zip(csv_paths, names)
    ]


# --------------------------------------------------------------------------- #
# Color difference
# --------------------------------------------------------------------------- #
@dataclass
class DeltaEReport:
    """All supported color-difference metrics between two spectra."""

    name_a: str
    name_b: str
    dE_cie1976: float
    dE_cie1994: float
    dE_cie2000: float
    dE_cmc_2_1: float
    dE_cmc_1_1: float
    dE_itp_bt2124: float
    dE_itp_p143: float

    def as_row(self) -> List[float]:
        """Values in display order (for a table widget)."""
        return [
            self.dE_cie1976,
            self.dE_cie1994,
            self.dE_cie2000,
            self.dE_cmc_2_1,
            self.dE_cmc_1_1,
            self.dE_itp_bt2124,
            self.dE_itp_p143,
        ]


def _itp(dI: float, dT: float, dP: float, halve_t: bool) -> float:
    t2 = (dT * 0.5) ** 2 if halve_t else dT**2
    return float(720.0 * np.sqrt(dI**2 + t2 + dP**2))


def delta_e_report(a: Spectrum, b: Spectrum) -> DeltaEReport:
    """Compute the full color-difference set between two spectra.

    Lab-based metrics (76/94/2000/CMC) use each spectrum's chromaticity Lab;
    ITP metrics use each spectrum's ICtCp. All are luminance-invariant.
    """
    lab_a, lab_b = np.asarray(a.lab, float), np.asarray(b.lab, float)
    dE76 = float(_delta_e.delta_E_CIE1976(lab_a, lab_b))
    dE94 = float(_delta_e.delta_E_CIE1994(lab_a, lab_b))
    dE2000 = float(_delta_e.delta_E_CIE2000(lab_a, lab_b))
    dEcmc21 = float(_delta_e.delta_E_CMC(lab_a, lab_b, 2, 1))
    dEcmc11 = float(_delta_e.delta_E_CMC(lab_a, lab_b, 1, 1))

    ict_a, ict_b = np.asarray(a.ictcp, float), np.asarray(b.ictcp, float)
    dI = ict_a[0] - ict_b[0]
    dT = ict_a[1] - ict_b[1]
    dP = ict_a[2] - ict_b[2]

    return DeltaEReport(
        name_a=a.name,
        name_b=b.name,
        dE_cie1976=dE76,
        dE_cie1994=dE94,
        dE_cie2000=dE2000,
        dE_cmc_2_1=dEcmc21,
        dE_cmc_1_1=dEcmc11,
        dE_itp_bt2124=_itp(dI, dT, dP, halve_t=True),
        dE_itp_p143=_itp(dI, dT, dP, halve_t=False),
    )


def delta_e_matrix(spectra: Sequence[Spectrum]) -> List[DeltaEReport]:
    """All-pairs color differences (i < j) for a set of spectra."""
    reports: List[DeltaEReport] = []
    for i in range(len(spectra)):
        for j in range(i + 1, len(spectra)):
            reports.append(delta_e_report(spectra[i], spectra[j]))
    return reports


# --------------------------------------------------------------------------- #
# Per-wavelength difference / ratio
# --------------------------------------------------------------------------- #
def _common_grid(wl_a: np.ndarray, wl_b: np.ndarray) -> np.ndarray:
    lo = max(int(wl_a[0]), int(wl_b[0]))
    hi = min(int(wl_a[-1]), int(wl_b[-1]))
    if hi <= lo:
        raise ValueError("Spectra have no overlapping wavelength range.")
    return np.arange(lo, hi + 1, 1, dtype=float)


def align_spectra(
    a: Spectrum, b: Spectrum
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Interpolate both spectra onto their common 1 nm grid.

    Returns ``(wavelengths, values_a, values_b)``.
    """
    grid = _common_grid(a.wavelengths, b.wavelengths)
    va = np.interp(grid, a.wavelengths.astype(float), a.values)
    vb = np.interp(grid, b.wavelengths.astype(float), b.values)
    return grid, va, vb


def spectral_difference(
    a: Spectrum, b: Spectrum
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-wavelength difference ``a - b`` on the common grid."""
    grid, va, vb = align_spectra(a, b)
    return grid, va - vb


def spectral_ratio(
    reference: Spectrum,
    sample: Spectrum,
    as_percent: bool = True,
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-wavelength ratio ``sample / reference`` (transmittance / reflectance).

    With ``as_percent`` (default) the result is scaled to percent. Wavelengths
    where the reference is ~0 produce 0 (avoids divide-by-zero blow-ups).
    """
    grid, vref, vsample = align_spectra(reference, sample)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(vref > 1e-12, vsample / np.where(vref > 1e-12, vref, 1.0), 0.0)
    if as_percent:
        ratio *= 100.0
    return grid, ratio


def save_curve_csv(
    csv_path: str,
    wavelengths: np.ndarray,
    values: np.ndarray,
    header: str = "wavelength,value",
) -> None:
    """Write a two-column curve CSV in the PR788 on-disk format."""
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        if header:
            fh.write(header + "\n")
        for wl, val in zip(wavelengths, values):
            fh.write(f"{int(round(wl))},{val:.6e}\n")


# --------------------------------------------------------------------------- #
# Single-spectrum statistics
# --------------------------------------------------------------------------- #
@dataclass
class SpectrumStats:
    total_power: float  # integrated (trapezoid) relative power
    peak_wavelength: int
    peak_value: float
    fwhm_nm: float  # full width at half maximum
    centroid_wavelength: float  # first moment of the SPD
    Y: float  # luminance (683 lm/W scale)


def _fwhm(wavelengths: np.ndarray, values: np.ndarray) -> float:
    peak = float(np.max(values))
    if peak <= 0:
        return 0.0
    half = peak / 2.0
    wl_f = wavelengths.astype(float)
    # left crossing: last index left of the peak where value >= half
    peak_i = int(np.argmax(values))
    left_vals = values[: peak_i + 1]
    right_vals = values[peak_i:]
    if np.max(left_vals) < half or np.max(right_vals) < half:
        # curve does not cross half-max on one side -> span to that edge
        return float(wl_f[-1] - wl_f[0])
    left_mask = np.where(left_vals >= half)[0]
    right_mask = peak_i + np.where(right_vals >= half)[0]
    left_i = int(left_mask.min())
    right_i = int(right_mask.max())
    # linear interpolation for sub-sample edges
    def _interp_edge(i0: int, i1: int, direction: int) -> float:
        v0, v1 = values[i0], values[i1]
        if v1 == v0:
            return float(wl_f[i1])
        t = (half - v0) / (v1 - v0)
        return float(wl_f[i0] + t * (wl_f[i1] - wl_f[i0]))

    wl_left = _interp_edge(left_i - 1, left_i, -1) if left_i > 0 else float(wl_f[0])
    wl_right = _interp_edge(right_i, right_i + 1, 1) if right_i < len(values) - 1 else float(wl_f[-1])
    return wl_right - wl_left


def spectrum_stats(sp: Spectrum) -> SpectrumStats:
    wl_f = sp.wavelengths.astype(float)
    total_power = float(np.trapz(sp.values, wl_f))
    peak_i = int(np.argmax(sp.values))
    weighted = np.sum(wl_f * sp.values)
    centroid = float(weighted / np.sum(sp.values)) if np.sum(sp.values) > 0 else 0.0
    return SpectrumStats(
        total_power=total_power,
        peak_wavelength=int(sp.wavelengths[peak_i]),
        peak_value=float(sp.values[peak_i]),
        fwhm_nm=_fwhm(sp.wavelengths, sp.values),
        centroid_wavelength=centroid,
        Y=float(sp.Y),
    )


# --------------------------------------------------------------------------- #
# Gamut definitions (coverage math lives in core.PR788_GamutUcs)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GamutDefinition:
    """One named reference gamut with its standard, white point and notes.

    ``primaries`` are the (R, G, B) CIE 1931 xy chromaticities. For CMYK print
    processes the ISO 12647-x standards define ink spectral tolerances rather
    than chromaticity coordinates, so those entries are marked
    ``approximate``: the triangle corners are the most saturated red / green /
    blue the process can print, taken from published measured process data.
    """

    name: str
    category: str
    standard: str
    primaries: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]
    white_xy: Tuple[float, float]
    white_label: str
    note: str = ""
    approximate: bool = False


GAMUT_CATEGORIES: Tuple[str, ...] = (
    "Display / Video",
    "Cinema (SMPTE)",
    "Design / RGB working spaces",
    "Print / CMYK (approx.)",
)

_D50 = (0.3457, 0.3585)
_D65 = (0.3127, 0.3290)

#: Curated reference gamut library (ITU-R / SMPTE / EBU / design / print).
GAMUT_LIBRARY: Tuple[GamutDefinition, ...] = (
    GamutDefinition(
        "NTSC (1953)",
        "Display / Video",
        "NTSC 1953 broadcast colours",
        ((0.67, 0.33), (0.21, 0.71), (0.14, 0.08)),
        _D65,
        "D65",
        "Original NTSC broadcast primaries; the source of the folklore '67.8 % of CIE' figure.",
    ),
    GamutDefinition(
        "Rec. 601 / 170M (SDTV)",
        "Display / Video",
        "ITU-R BT.601 / SMPTE 170M",
        ((0.64, 0.33), (0.29, 0.60), (0.15, 0.06)),
        _D65,
        "D65",
    ),
    GamutDefinition(
        "EBU R 39 (PAL / SECAM)",
        "Display / Video",
        "EBU R 39-2005 (Tech 3255)",
        ((0.63, 0.34), (0.29, 0.60), (0.15, 0.06)),
        _D65,
        "D65",
    ),
    GamutDefinition(
        "sRGB / Rec. 709",
        "Display / Video",
        "ITU-R BT.709 / SMPTE 274M, 347M / IEC 61966-2-1",
        ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06)),
        _D65,
        "D65",
    ),
    GamutDefinition(
        "Rec. 2020 (UHD / HDR)",
        "Display / Video",
        "ITU-R BT.2020 / 2100 / SMPTE ST 2084, 2094, 2110",
        ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
        _D65,
        "D65",
        "Primaries of PQ (ST 2084), HLG (BT.2100) and ST 2110.",
    ),
    GamutDefinition(
        "DCI P3 (ST 428-1)",
        "Cinema (SMPTE)",
        "SMPTE ST 428-1 / 428-7 (D-Cinema)",
        ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
        (0.314, 0.351),
        "DCI",
        "D-Cinema white is D63-like (0.314, 0.351), not D65.",
    ),
    GamutDefinition(
        "Display P3 (Apple)",
        "Cinema (SMPTE)",
        "Apple Display P3",
        ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
        _D65,
        "D65",
        "Same primaries as SMPTE ST 428-1, D65 white.",
    ),
    GamutDefinition(
        "Adobe RGB (1998)",
        "Design / RGB working spaces",
        "Adobe (1998)",
        ((0.64, 0.33), (0.21, 0.71), (0.15, 0.06)),
        _D65,
        "D65",
        "Common print/design RGB working space.",
    ),
    GamutDefinition(
        "ProPhoto RGB",
        "Design / RGB working spaces",
        "Adobe ProPhoto",
        ((0.7347, 0.2653), (0.1596, 0.8404), (0.0366, 0.0001)),
        _D50,
        "D50",
        "Blue primary is imaginary (outside the horseshoe); D50 white.",
    ),
    GamutDefinition(
        "CIE 1931 RGB",
        "Design / RGB working spaces",
        "CIE 1931 colour system",
        ((0.64, 0.33), (0.21, 0.71), (0.15, 0.06)),
        (1 / 3, 1 / 3),
        "E",
        "Historical CIE RGB system; source of the Adobe RGB primaries.",
    ),
    GamutDefinition(
        "ISO Coated v2 (FOGRA 39)",
        "Print / CMYK (approx.)",
        "ISO 12647-2",
        ((0.610, 0.350), (0.458, 0.482), (0.219, 0.187)),
        _D50,
        "D50",
        "Approximate: the CMYK gamut is not a triangle; corners are the most "
        "saturated red/green/blue of the process (published measured data).",
        approximate=True,
    ),
    GamutDefinition(
        "SWOP v2",
        "Print / CMYK (approx.)",
        "ISO 12647-4",
        ((0.588, 0.347), (0.436, 0.462), (0.224, 0.184)),
        _D50,
        "D50",
        "Approximate, same convention as ISO Coated v2.",
        approximate=True,
    ),
    GamutDefinition(
        "GRACoL 2006",
        "Print / CMYK (approx.)",
        "ECP G7 (65# coated)",
        ((0.601, 0.349), (0.445, 0.471), (0.222, 0.188)),
        _D50,
        "D50",
        "Approximate, same convention as ISO Coated v2.",
        approximate=True,
    ),
)

#: Names shown checked by default in the UI.
DEFAULT_GAMUT_SELECTION: Tuple[str, ...] = (
    "NTSC (1953)",
    "sRGB / Rec. 709",
    "DCI P3 (ST 428-1)",
    "Rec. 2020 (UHD / HDR)",
    "Adobe RGB (1998)",
)

#: Flat view (name -> primaries) kept for simple consumers / back-compat.
REFERENCE_GAMUTS: Dict[str, Tuple[Tuple[float, float], ...]] = {
    g.name: g.primaries for g in GAMUT_LIBRARY
}


def gamut_definition(name: str) -> Optional[GamutDefinition]:
    for definition in GAMUT_LIBRARY:
        if definition.name == name:
            return definition
    return None


def gamuts_by_category() -> Dict[str, List[GamutDefinition]]:
    out: Dict[str, List[GamutDefinition]] = {}
    for definition in GAMUT_LIBRARY:
        out.setdefault(definition.category, []).append(definition)
    return out


# --------------------------------------------------------------------------- #
# CRI
# --------------------------------------------------------------------------- #
@dataclass
class CriResult:
    ra: float
    r_indices: Dict[int, float]  # R1..Rn (this colour build has TCS01..TCS14)
    cct: Optional[float]

    @property
    def max_r_index(self) -> int:
        return max(self.r_indices) if self.r_indices else 0


def _cri_cct(sp: Spectrum) -> Optional[float]:
    try:
        from colour import uv_to_CCT

        uv = [sp.u_prime, (2.0 / 3.0) * sp.v_prime]
        cct_duv = uv_to_CCT(uv, method="Ohno 2013")
        return float(cct_duv[0])
    except Exception:
        return None


def cri(sp: Spectrum) -> CriResult:
    """CIE general color-rendering index for one spectrum (Ra + individual R)."""
    from colour.quality.cri import colour_rendering_index

    sd = rows_to_sd(
        [(int(w), float(v)) for w, v in zip(sp.wavelengths, sp.values)],
        name=sp.name,
    )
    spec = colour_rendering_index(sd, additional_data=True)
    r_indices = {int(k): float(v.Q_a) for k, v in spec.Q_as.items()}
    return CriResult(
        ra=float(spec.Q_a),
        r_indices=r_indices,
        cct=_cri_cct(sp),
    )
