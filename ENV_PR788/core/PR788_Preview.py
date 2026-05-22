import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import colour
import numpy as np

from core.PR788_Utils import PR788


SpectralRow = Tuple[int, float]


@dataclass
class PreviewResult:
    """Structured preview payload suitable for CLI or UI consumption."""

    csv_path: Optional[str]
    point_count: int
    wavelength_start: int
    wavelength_end: int
    peak_wavelength: int
    peak_value: float
    X: float
    x: float
    Z: float
    y: float
    Y: float
    luminance_nits: float
    cct: float
    tint_duv: float
    u_prime: float
    v_prime: float
    srgb_8bit: Tuple[int, int, int]
    spectral_rows: List[SpectralRow]

    def to_dict(self) -> dict:
        return asdict(self)


def rows_to_sd(
    rows: Sequence[SpectralRow],
    name: str = "Measured",
) -> colour.SpectralDistribution:
    if not rows:
        raise ValueError("No spectral rows were provided.")

    data = {int(wavelength): float(value) for wavelength, value in rows}
    return colour.SpectralDistribution(data, name=name)


def csv_to_rows(csv_path: str) -> List[SpectralRow]:
    rows: List[SpectralRow] = []
    with Path(csv_path).open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        for row in reader:
            if len(row) < 2:
                continue
            rows.append((int(row[0]), float(row[1])))

    if not rows:
        raise ValueError(f"No spectral rows were found in {csv_path}.")

    return rows


def compute_preview(
    rows: Sequence[SpectralRow],
    illuminant_name: str = "E",
    cmfs_name: str = "CIE 1931 2 Degree Standard Observer",
    k: float = 683,
    csv_path: Optional[str] = None,
) -> PreviewResult:
    if not rows:
        raise ValueError("No spectral rows were provided.")

    wavelengths = np.array([wavelength for wavelength, _ in rows], dtype=int)
    values = np.array([value for _, value in rows], dtype=float)

    peak_index = int(np.argmax(values))
    sd = rows_to_sd(rows)
    illuminant = colour.SDS_ILLUMINANTS[illuminant_name]
    cmfs = colour.MSDS_CMFS[cmfs_name]
    xyz = colour.sd_to_XYZ(sd, cmfs, illuminant, k)
    xyy = colour.XYZ_to_xyY(xyz)
    denominator = xyz[0] + 15 * xyz[1] + 3 * xyz[2]
    u_prime = 4 * xyz[0] / denominator
    v_prime = 9 * xyz[1] / denominator
    uv_1960 = np.array([u_prime, (2 / 3) * v_prime])
    cct_duv = colour.uv_to_CCT(uv_1960, method="Ohno 2013")
    cct = float(cct_duv[0])
    tint_duv = float(cct_duv[1])
    xyz_normalized = xyz / 100 if np.max(xyz) > 1 else xyz
    srgb = colour.XYZ_to_sRGB(xyz_normalized)
    srgb_clipped = np.clip(srgb, 0, 1)
    srgb_8bit = tuple(int(round(channel * 255)) for channel in srgb_clipped)

    return PreviewResult(
        csv_path=str(csv_path) if csv_path else None,
        point_count=len(rows),
        wavelength_start=int(wavelengths[0]),
        wavelength_end=int(wavelengths[-1]),
        peak_wavelength=int(wavelengths[peak_index]),
        peak_value=float(values[peak_index]),
        X=float(xyz[0]),
        x=float(xyy[0]),
        Z=float(xyz[2]),
        y=float(xyy[1]),
        Y=float(xyy[2]),
        luminance_nits=float(xyy[2]),
        cct=cct,
        tint_duv=tint_duv,
        u_prime=float(u_prime),
        v_prime=float(v_prime),
        srgb_8bit=srgb_8bit,
        spectral_rows=[(int(wavelength), float(value)) for wavelength, value in rows],
    )


def format_preview(result: PreviewResult) -> str:
    lines = [
        f"Points: {result.point_count}",
        f"Range: {result.wavelength_start}-{result.wavelength_end} nm",
        f"Peak: {result.peak_wavelength} nm / {result.peak_value:.6e}",
        f"CIE 1931 xyY: x:{result.x:.6f} y:{result.y:.6f} Y:{result.Y:.6f}",
        f"Luminance: {result.luminance_nits:.6f} nit",
        f"CCT: {result.cct:.2f} K",
        f"Tint (Duv): {result.tint_duv:+.6f}",
    ]
    if result.csv_path:
        lines.append(f"Saved: {result.csv_path}")
    return "\n".join(lines)


def preview_from_raw_bytes(
    byte_data: bytes,
    csv_path: Optional[str] = None,
    save_csv: bool = False,
) -> PreviewResult:
    rows = PR788.parse_measurement_bytes(byte_data)
    if save_csv:
        if not csv_path:
            raise ValueError("csv_path is required when save_csv=True.")
        PR788.save_csv(rows, csv_path)
    return compute_preview(rows, csv_path=csv_path if save_csv else None)


def preview_from_csv(csv_path: str) -> PreviewResult:
    rows = csv_to_rows(csv_path)
    return compute_preview(rows, csv_path=csv_path)


def measure_preview_and_save(
    pr788: PR788,
    csv_path: str,
    code: str = "5",
    expected_last_wavelength: int = 780,
    read_timeout: Optional[float] = None,
) -> PreviewResult:
    raw_bytes = pr788.measure(
        code=code,
        expected_last_wavelength=expected_last_wavelength,
        read_timeout=read_timeout,
    )
    rows = PR788.parse_measurement_bytes(raw_bytes)
    PR788.save_csv(rows, csv_path)
    return compute_preview(rows, csv_path=csv_path)
