"""Offline data-processing dialogs for PR788 measurement history.

All computation lives in :mod:`core.PR788_Analysis`; this module only presents
it. Everything is drawn with ``QPainter`` (no matplotlib) to match the main
window's dark style.

Dialogs
-------
- :class:`SPDComparisonDialog` — overlay several history spectra, optional
  peak-normalization and per-spectrum difference curves, full color-difference
  table (CIE76/94/2000, CMC, ITP) with CSV export.
- :class:`SpectralRatioDialog` — sample/reference per-wavelength ratio
  (transmittance / reflectance), resulting light color, CSV export.
- :class:`GamutDialog` — N-primary (>= 3) gamut convex hull vs reference
  gamuts, with overlap coverage computed in any of the four UCS
  (CIE 1931 xy, CIE 1976 u'v', CIE 2000 UCS, CAM16-UCS).
- :class:`CRIDialog` — CRI (Ra + individual R values) for one spectrum.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import colour
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from chromaticity_field import chromaticity_image

from core.PR788_Analysis import (
    DEFAULT_GAMUT_SELECTION,
    GAMUT_LIBRARY,
    GamutDefinition,
    Spectrum,
    cri,
    delta_e_matrix,
    gamuts_by_category,
    load_spectrum,
    save_curve_csv,
    spectral_ratio,
)
from core.PR788_GamutUcs import (
    UCS_SYSTEMS,
    GamutResult,
    gamut_coverage_ucs,
    reference_gamut_polygons,
)
from core.PR788_Service import list_history_csv_files


# --------------------------------------------------------------------------- #
# Shared palette / helpers
# --------------------------------------------------------------------------- #
CURVE_COLORS: List[QtGui.QColor] = [
    QtGui.QColor(255, 255, 255),
    QtGui.QColor(255, 194, 82),
    QtGui.QColor(120, 190, 255),
    QtGui.QColor(120, 220, 140),
    QtGui.QColor(230, 120, 220),
    QtGui.QColor(255, 140, 60),
    QtGui.QColor(90, 220, 220),
    QtGui.QColor(255, 90, 90),
    QtGui.QColor(200, 160, 255),
    QtGui.QColor(255, 255, 120),
]

GAMUT_COLORS: Dict[str, Tuple[int, int, int]] = {
    "NTSC (1953)": (255, 90, 90),
    "Rec. 601 / 170M (SDTV)": (255, 150, 110),
    "EBU R 39 (PAL / SECAM)": (255, 180, 90),
    "sRGB / Rec. 709": (120, 190, 255),
    "Rec. 2020 (UHD / HDR)": (230, 120, 220),
    "DCI P3 (ST 428-1)": (120, 220, 140),
    "Display P3 (Apple)": (90, 220, 190),
    "Adobe RGB (1998)": (255, 220, 90),
    "ProPhoto RGB": (190, 160, 255),
    "CIE 1931 RGB": (255, 150, 180),
    "ISO Coated v2 (FOGRA 39)": (200, 165, 100),
    "SWOP v2": (165, 185, 120),
    "GRACoL 2006": (220, 140, 190),
}


def _gamut_color(name: str) -> QtGui.QColor:
    """Muted (low-saturation) reference-gamut color.

    Reference outlines are the *secondary* layer of the diagram: they keep
    their palette hue (so they still match the tree entries) but are
    desaturated and dimmed so the white user gamut reads as the primary.
    """
    r, g, b = GAMUT_COLORS.get(name, (150, 150, 150))
    base = QtGui.QColor(r, g, b)
    h, s, v, _a = base.getHsv()
    return QtGui.QColor.fromHsv(h, int(s * 0.45), int(v * 0.78))

#: User-gamut (measured) marker color — bright neutral white is the primary
#: layer of the chromaticity canvases; orange/gold is deliberately avoided.
HERO = QtGui.QColor(245, 247, 252)
#: Subordinate markers (D65 point) — quiet mid-gray.
SUBTLE = QtGui.QColor(158, 161, 168)

GOLD = QtGui.QColor(255, 194, 82)


def _format_value(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 10000 or magnitude < 0.01:
        return f"{value:.2e}"
    if magnitude >= 100:
        return f"{value:.0f}"
    if magnitude >= 1:
        return f"{value:.1f}"
    return f"{value:.3f}"


def _nice_ticks(v_min: float, v_max: float, count: int = 4) -> List[float]:
    span = v_max - v_min
    if span <= 0:
        return [v_min]
    raw = span / max(count, 1)
    magnitude = 10.0 ** np.floor(np.log10(raw))
    step = 10.0 * magnitude
    for factor in (1.0, 2.0, 2.5, 5.0):
        if raw <= factor * magnitude:
            step = factor * magnitude
            break
    ticks: List[float] = []
    value = float(np.ceil(v_min / step) * step)
    while value <= v_max + 1e-9 * max(1.0, abs(v_max)):
        ticks.append(value)
        value += step
    return ticks


def _srgb_8bit(xyz: np.ndarray) -> Tuple[int, int, int]:
    """Same sRGB preview convention as the main window's sRGB swatch."""
    xyz = np.asarray(xyz, dtype=float)
    normalized = xyz / 100.0 if np.max(xyz) > 1 else xyz
    srgb = np.clip(np.asarray(colour.XYZ_to_sRGB(normalized), dtype=float), 0, 1)
    return tuple(int(round(channel * 255)) for channel in srgb)


def _csv_items(csv_dir: str):
    if not csv_dir:
        return []
    return list_history_csv_files(csv_dir)


@dataclass
class Curve:
    """One named curve for :class:`MultiCurvePlotWidget`."""

    name: str
    wavelength: np.ndarray
    values: np.ndarray
    color: QtGui.QColor
    dashed: bool = False
    width: float = 2.0


class MultiCurvePlotWidget(QtWidgets.QFrame):
    """Generic multi-curve line plot (QPainter, dark theme)."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("plot", True)
        self.setMinimumHeight(220)
        self._title = ""
        self._y_label = ""
        self._x_label = "Wavelength (nm)"
        self._curves: List[Curve] = []
        self._hlines: List[Tuple[float, str]] = []
        self._x_min = 380.0
        self._x_max = 780.0

    def set_data(
        self,
        title: str,
        curves: Sequence[Curve],
        y_label: str = "",
        x_label: str = "Wavelength (nm)",
        hlines: Optional[Sequence[Tuple[float, str]]] = None,
        x_min: float = 380.0,
        x_max: float = 780.0,
    ) -> None:
        self._title = title
        self._curves = list(curves)
        self._y_label = y_label
        self._x_label = x_label
        self._hlines = list(hlines) if hlines else []
        self._x_min = float(x_min)
        self._x_max = float(x_max)
        self.update()

    def clear(self) -> None:
        self._curves = []
        self._hlines = []
        self._title = ""
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(18, 12, -18, -10)
        title_font = QtGui.QFont("Open Sans", 9, QtGui.QFont.DemiBold)
        label_font = QtGui.QFont("Open Sans", 8)
        title_metrics = QtGui.QFontMetrics(title_font)
        label_metrics = QtGui.QFontMetrics(label_font)

        title_band = title_metrics.height() + 4
        tick_band = label_metrics.height() + 6
        axis_label_band = label_metrics.height() + 8
        left_band = 54

        plot_top = rect.top() + title_band
        plot_height = max(rect.height() - title_band - tick_band - axis_label_band - 4, 120)
        plot_rect = QtCore.QRect(rect.left() + left_band, plot_top, rect.width() - left_band, plot_height)
        painter.setPen(QtGui.QPen(QtGui.QColor(67, 71, 77), 1))
        painter.drawRoundedRect(plot_rect, 10, 10)

        # title (left) + legend (right) on the same band
        painter.setPen(QtGui.QColor(235, 235, 235))
        painter.setFont(title_font)
        title_rect = QtCore.QRect(rect.left(), rect.top(), plot_rect.left() - rect.left() - 8, title_band)
        painter.drawText(title_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self._title)
        self._paint_legend(painter, label_metrics, title_band, plot_rect)

        if not self._curves:
            painter.setPen(QtGui.QColor(220, 220, 220))
            painter.setFont(label_font)
            painter.drawText(plot_rect, QtCore.Qt.AlignCenter, "No data")
            return

        # value range across all curves
        all_values = np.concatenate([c.values for c in self._curves])
        v_min = float(np.nanmin(all_values))
        v_max = float(np.nanmax(all_values))
        if not np.isfinite(v_min) or not np.isfinite(v_max) or v_max == v_min:
            v_max = v_min + 1.0
        if v_min > 0:
            y_min, y_max = 0.0, v_max * 1.05
        elif v_max < 0:
            y_min, y_max = v_min * 1.15, 0.0
        else:
            padding = (v_max - v_min) * 0.08
            y_min, y_max = v_min - padding, v_max + padding

        inner = plot_rect.adjusted(4, 6, -4, -6)

        def x_of(wavelength: float) -> float:
            return inner.left() + (wavelength - self._x_min) / (self._x_max - self._x_min) * inner.width()

        def y_of(value: float) -> float:
            return inner.bottom() - (value - y_min) / (y_max - y_min) * inner.height()

        # grid + y ticks
        grid_pen = QtGui.QPen(QtGui.QColor(55, 58, 64), 1)
        grid_pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(grid_pen)
        for tick in _nice_ticks(y_min, y_max, 4):
            y = y_of(tick)
            if y < inner.top() - 1 or y > inner.bottom() + 1:
                continue
            painter.drawLine(inner.left(), int(y), inner.right(), int(y))
            painter.setPen(QtGui.QColor(200, 200, 205))
            label = _format_value(tick)
            painter.drawText(
                QtCore.QRect(rect.left(), int(y) - 9, left_band - 8, 18),
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                label,
            )
            painter.setPen(grid_pen)

        x_ticks = [380, 430, 480, 530, 580, 630, 680, 730, 780]
        if inner.width() < 460:
            x_ticks = [380, 480, 580, 780]
        elif inner.width() < 320:
            x_ticks = [380, 580, 780]
        for wavelength in x_ticks:
            x = x_of(wavelength)
            painter.drawLine(int(x), inner.top(), int(x), inner.bottom())
        painter.setPen(QtGui.QColor(200, 200, 205))
        for wavelength in x_ticks:
            x = x_of(wavelength)
            painter.drawText(
                QtCore.QRect(int(x) - 24, plot_rect.bottom() + 2, 48, tick_band),
                QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                str(wavelength),
            )

        # axes
        axis_pen = QtGui.QPen(QtGui.QColor(210, 210, 210), 1)
        painter.setPen(axis_pen)
        painter.drawLine(inner.left(), inner.bottom(), inner.right(), inner.bottom())
        painter.drawLine(inner.left(), inner.top(), inner.left(), inner.bottom())

        # zero line
        if y_min < 0 < y_max:
            zero_pen = QtGui.QPen(QtGui.QColor(120, 124, 132), 1)
            zero_pen.setStyle(QtCore.Qt.DotLine)
            painter.setPen(zero_pen)
            y = y_of(0.0)
            painter.drawLine(inner.left(), int(y), inner.right(), int(y))

        # horizontal reference lines (e.g. 100 % for ratios)
        painter.setFont(label_font)
        for value, label in self._hlines:
            if value < y_min or value > y_max:
                continue
            y = y_of(value)
            h_pen = QtGui.QPen(QtGui.QColor(150, 155, 165), 1)
            h_pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(h_pen)
            painter.drawLine(inner.left(), int(y), inner.right(), int(y))
            painter.setPen(QtGui.QColor(170, 175, 185))
            painter.drawText(
                QtCore.QRect(inner.right() - 120, int(y) - 14, 116, 13),
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                label,
            )

        # curves (clipped to inner rect)
        painter.save()
        painter.setClipRect(inner)
        for curve in self._curves:
            path = QtGui.QPainterPath()
            for index in range(len(curve.wavelength)):
                point = QtCore.QPointF(x_of(float(curve.wavelength[index])), y_of(float(curve.values[index])))
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            pen = QtGui.QPen(curve.color, curve.width)
            if curve.dashed:
                pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
            painter.drawPath(path)
        painter.restore()

        # axis labels
        painter.setPen(QtGui.QColor(190, 190, 195))
        painter.setFont(label_font)
        x_label_rect = QtCore.QRect(plot_rect.left(), plot_rect.bottom() + tick_band, plot_rect.width(), axis_label_band)
        painter.drawText(x_label_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, self._x_label)
        if self._y_label:
            painter.save()
            painter.translate(rect.left() + 12, plot_rect.top() + plot_rect.height() / 2)
            painter.rotate(-90)
            painter.drawText(
                QtCore.QRect(-plot_rect.height() // 2, -9, plot_rect.height(), 18),
                QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                self._y_label,
            )
            painter.restore()

    def _paint_legend(
        self,
        painter: QtGui.QPainter,
        metrics: QtGui.QFontMetrics,
        title_band: int,
        plot_rect: QtCore.QRect,
    ) -> None:
        painter.setFont(QtGui.QFont("Open Sans", 8))
        entries = [(c.name, c.color) for c in self._curves[:8]]
        if not entries:
            return
        gap = 14
        sample_w = 18
        total = 0
        widths = []
        for name, _color in entries:
            w = sample_w + 5 + metrics.horizontalAdvance(name)
            widths.append(w)
            total += w + gap
        total -= gap
        x = plot_rect.right() - total
        y = title_band // 2
        for (name, color), w in zip(entries, widths):
            painter.setPen(QtGui.QPen(color, 2.4))
            painter.drawLine(int(x), y, int(x + sample_w), y)
            painter.setPen(QtGui.QColor(215, 215, 220))
            painter.drawText(
                QtCore.QRect(int(x + sample_w + 5), 0, w - sample_w, title_band),
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                name,
            )
            x += w + gap


# --------------------------------------------------------------------------- #
# Gamut canvas (any of the four UCS)
# --------------------------------------------------------------------------- #
class GamutCanvasWidget(QtWidgets.QFrame):
    """Chromaticity diagram in the selected UCS (see ``UCS_SYSTEMS``) with the
    user's N-primary gamut (convex hull) and the built-in reference gamuts.
    Strict aspect (x span / y span of the current UCS range) like the main
    window's chromaticity diagram."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("plot", True)
        self.setMinimumHeight(280)
        self._ucs: str = "cie1931"
        self._result: Optional[GamutResult] = None
        self._checked: Optional[set] = None  # None = draw every reference gamut
        self._labels: List[str] = []  # user primary-row labels, in result order
        self._range: Optional[Tuple[float, float, float, float]] = None
        self._locus_cache: Dict[str, np.ndarray] = {}
        self._white_cache: Dict[str, np.ndarray] = {}

    def set_ucs(self, ucs_key: str) -> None:
        if ucs_key != self._ucs:
            self._ucs = ucs_key
            self._range = None
            self.update()

    def set_labels(self, labels: Sequence[str]) -> None:
        self._labels = [str(tag) for tag in labels]
        self.update()

    def set_result(self, result: Optional[GamutResult], checked: Optional[Sequence[str]] = None) -> None:
        self._result = result
        self._checked = set(checked) if checked is not None else None
        self.update()

    def _locus(self) -> np.ndarray:
        if self._ucs not in self._locus_cache:
            self._locus_cache[self._ucs] = UCS_SYSTEMS[self._ucs]["locus_ucs"]()
        return self._locus_cache[self._ucs]

    def _white(self) -> np.ndarray:
        if self._ucs not in self._white_cache:
            self._white_cache[self._ucs] = UCS_SYSTEMS[self._ucs]["white_ucs"]()
        return self._white_cache[self._ucs]

    def _current_range(self) -> Tuple[float, float, float, float]:
        """Locus bbox + 8 % padding, cached per UCS."""
        if self._range is None:
            locus = self._locus()
            x0, x1 = float(locus[:, 0].min()), float(locus[:, 0].max())
            y0, y1 = float(locus[:, 1].min()), float(locus[:, 1].max())
            pad_x, pad_y = 0.08 * (x1 - x0), 0.08 * (y1 - y0)
            self._range = (x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y)
        return self._range

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        label_font = QtGui.QFont("Open Sans", 8)
        title_font = QtGui.QFont("Open Sans", 9, QtGui.QFont.DemiBold)
        label_metrics = QtGui.QFontMetrics(label_font)

        x_min, x_max, y_min, y_max = self._current_range()
        x_ticks = _nice_ticks(x_min, x_max, 5)
        y_ticks = _nice_ticks(y_min, y_max, 5)
        tick_text_w = label_metrics.horizontalAdvance(
            max((f"{v:g}" for v in x_ticks + y_ticks), default="0")
        )

        rect = self.rect().adjusted(18, 12, -18, -10)
        title_band = label_metrics.height() + 8
        tick_band = label_metrics.height() + 6
        avail = QtCore.QRect(
            rect.left() + tick_text_w + 12,
            rect.top() + title_band,
            rect.width() - tick_text_w - 16,
            rect.height() - title_band - tick_band - label_metrics.height() - 12,
        )
        avail.setWidth(max(avail.width(), 40))
        avail.setHeight(max(avail.height(), 40))

        aspect = (x_max - x_min) / (y_max - y_min)
        if avail.width() / float(avail.height()) > aspect:
            plot_height = avail.height()
            plot_width = int(plot_height * aspect)
        else:
            plot_width = avail.width()
            plot_height = int(plot_width / aspect)
        plot_rect = QtCore.QRect(
            avail.left() + (avail.width() - plot_width) // 2,
            avail.top() + (avail.height() - plot_height) // 2,
            plot_width,
            plot_height,
        )
        inner = plot_rect.adjusted(2, 2, -2, -2)

        def x_of(x: float) -> float:
            return inner.left() + (x - x_min) / (x_max - x_min) * inner.width()

        def y_of(y: float) -> float:
            return inner.bottom() - (y - y_min) / (y_max - y_min) * inner.height()

        def to_point(u: float, v: float) -> QtCore.QPointF:
            return QtCore.QPointF(x_of(u), y_of(v))

        system = UCS_SYSTEMS[self._ucs]
        painter.setPen(QtGui.QColor(235, 235, 235))
        painter.setFont(title_font)
        painter.drawText(
            QtCore.QRect(rect.left(), rect.top(), rect.width(), title_band),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            f"Gamut — {system['label']}",
        )

        painter.setPen(QtGui.QPen(QtGui.QColor(67, 71, 77), 1))
        painter.drawRoundedRect(plot_rect, 10, 10)

        # grid
        grid_pen = QtGui.QPen(QtGui.QColor(55, 58, 64), 1)
        grid_pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(grid_pen)
        for value in x_ticks:
            x = x_of(value)
            painter.drawLine(int(x), inner.top(), int(x), inner.bottom())
        for value in y_ticks:
            y = y_of(value)
            painter.drawLine(inner.left(), int(y), inner.right(), int(y))

        # spectral locus + line of purples (ring runs 380 -> 780 nm)
        locus_pts = self._locus()
        locus = QtGui.QPainterPath()
        for index in range(len(locus_pts)):
            point = to_point(float(locus_pts[index, 0]), float(locus_pts[index, 1]))
            if index == 0:
                locus.moveTo(point)
            else:
                locus.lineTo(point)

        # Colored CIE background, pre-masked to the visible locus (alpha
        # channel). CAM systems render at capped resolution, upscaled here.
        field = chromaticity_image(
            self._ucs, x_min, x_max, y_min, y_max, inner.width(), inner.height(), locus=locus_pts
        )
        if not field.isNull():
            painter.drawImage(inner, field)

        painter.setPen(QtGui.QPen(QtGui.QColor(150, 152, 158), 1.0))
        painter.drawPath(locus)
        painter.setPen(QtGui.QPen(QtGui.QColor(150, 152, 158), 0.8))
        painter.drawLine(
            to_point(float(locus_pts[0, 0]), float(locus_pts[0, 1])),
            to_point(float(locus_pts[-1, 0]), float(locus_pts[-1, 1])),
        )

        painter.save()
        painter.setClipRect(inner)

        # reference gamuts (only the checked ones; approximate CMYK ones
        # dashed) — drawn from their convex outlines in the current UCS
        checked = self._checked if self._checked is not None else {g.name for g in GAMUT_LIBRARY}
        polygons = reference_gamut_polygons(self._ucs)
        drawn: List[Tuple[GamutDefinition, np.ndarray]] = []
        for definition in GAMUT_LIBRARY:
            if definition.name not in checked:
                continue
            poly = polygons.get(definition.name)
            if poly is None or len(poly) < 3:
                continue
            path = QtGui.QPainterPath()
            for index in range(len(poly)):
                point = to_point(float(poly[index, 0]), float(poly[index, 1]))
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            path.closeSubpath()
            color = _gamut_color(definition.name)
            pen = QtGui.QPen(QtGui.QColor(color.red(), color.green(), color.blue(), 185), 1.0)
            if definition.approximate:
                pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
            painter.drawPath(path)
            drawn.append((definition, poly))

        # name labels at centroids, only while there are few enough to read
        if len(drawn) <= 4:
            painter.setFont(QtGui.QFont("Open Sans", 7, QtGui.QFont.DemiBold))
            for definition, poly in drawn:
                cx = float(poly[:, 0].mean())
                cy = float(poly[:, 1].mean())
                painter.setPen(_gamut_color(definition.name))
                painter.drawText(
                    QtCore.QRectF(x_of(cx) - 45, y_of(cy) - 26, 90, 14),
                    QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                    definition.name,
                )

        # user gamut (PRIMARY layer): white convex hull of the selected
        # primaries — the one bright element in the plot
        if self._result is not None and len(self._result.hull_ucs) >= 3:
            hull = QtGui.QPainterPath()
            for index, (u, v) in enumerate(self._result.hull_ucs):
                point = to_point(u, v)
                if index == 0:
                    hull.moveTo(point)
                else:
                    hull.lineTo(point)
            hull.closeSubpath()
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(238, 242, 250, 74))
            painter.drawPath(hull)
            painter.setPen(QtGui.QPen(HERO, 1.8))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPath(hull)
        if self._result is not None:
            for (u, v), tag in zip(self._result.primaries_ucs, self._labels):
                if not (np.isfinite(u) and np.isfinite(v)):
                    continue  # imaginary primary outside the CAM model's domain
                point = to_point(u, v)
                # white dot with a thin dark ring: legible even over the
                # brightest (near-white) field areas
                painter.setPen(QtGui.QPen(QtGui.QColor(35, 37, 43), 1.2))
                painter.setBrush(HERO)
                painter.drawEllipse(point, 3.0, 3.0)
                painter.setPen(HERO)
                painter.setFont(QtGui.QFont("Open Sans", 8, QtGui.QFont.DemiBold))
                painter.drawText(QtCore.QRectF(point.x() + 6, point.y() - 14, 14, 16), QtCore.Qt.AlignLeft, tag)
        painter.restore()

        # D65 white point of the UCS (subordinate gray marker)
        white = self._white()
        white_point = to_point(float(white[0]), float(white[1]))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(SUBTLE)
        painter.drawEllipse(white_point, 2.0, 2.0)
        painter.setPen(SUBTLE)
        painter.setFont(label_font)
        painter.drawText(
            QtCore.QRectF(white_point.x() + 6, white_point.y() - 12, 30, 14),
            QtCore.Qt.AlignLeft,
            "D65",
        )

        # ticks
        painter.setPen(QtGui.QColor(200, 200, 205))
        painter.setFont(label_font)
        for value in x_ticks:
            x = x_of(value)
            painter.drawText(
                QtCore.QRect(int(x) - 20, plot_rect.bottom() + 2, 40, tick_band),
                QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                f"{value:g}",
            )
        for value in y_ticks:
            y = y_of(value)
            painter.drawText(
                QtCore.QRect(inner.left() - tick_text_w - 10, int(y) - 9, tick_text_w + 6, 18),
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                f"{value:g}",
            )
        painter.drawText(
            QtCore.QRect(plot_rect.left(), plot_rect.bottom() + tick_band, plot_rect.width(), label_metrics.height() + 4),
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
            system["axis_x"],
        )

        if self._result is None:
            painter.setPen(QtGui.QColor(220, 220, 220))
            painter.drawText(plot_rect, QtCore.Qt.AlignCenter, "Select at least 3 primaries")


# --------------------------------------------------------------------------- #
# CRI bar chart
# --------------------------------------------------------------------------- #
class CriBarWidget(QtWidgets.QFrame):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("plot", True)
        self._r_values: Dict[int, float] = {}

    def set_values(self, r_values: Dict[int, float]) -> None:
        self._r_values = dict(r_values)
        self.setMinimumHeight(max(128, 26 * (len(r_values) + 2)))
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        label_font = QtGui.QFont("Open Sans", 8)
        metrics = QtGui.QFontMetrics(label_font)
        rect = self.rect().adjusted(14, 12, -14, -10)
        if not self._r_values:
            painter.setPen(QtGui.QColor(220, 220, 220))
            painter.setFont(label_font)
            painter.drawText(rect, QtCore.Qt.AlignCenter, "No CRI data")
            return

        left_band = metrics.horizontalAdvance("R10") + 10
        right_band = 44
        top_band = 18
        plot_rect = QtCore.QRect(rect.left() + left_band, rect.top() + top_band, rect.width() - left_band - right_band, rect.height() - top_band)
        painter.setPen(QtGui.QPen(QtGui.QColor(67, 71, 77), 1))
        painter.drawRoundedRect(plot_rect, 8, 8)

        indices = sorted(self._r_values)
        values = [self._r_values[i] for i in indices]
        v_max = max(100.0, max(values))
        v_min = min(0.0, min(values))
        if v_min < 0:
            v_min = max(-30.0, v_min - 5)

        def x_of(value: float) -> float:
            return plot_rect.left() + (value - v_min) / (v_max - v_min) * plot_rect.width()

        # vertical grid at 0/25/50/75/100
        grid_pen = QtGui.QPen(QtGui.QColor(55, 58, 64), 1)
        grid_pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(grid_pen)
        for value in (0, 25, 50, 75, 100):
            if value < v_min or value > v_max:
                continue
            x = x_of(value)
            painter.drawLine(int(x), plot_rect.top(), int(x), plot_rect.bottom())
            painter.setPen(QtGui.QColor(180, 180, 185))
            painter.drawText(
                QtCore.QRect(int(x) - 16, plot_rect.bottom() + 1, 32, 14),
                QtCore.Qt.AlignHCenter,
                str(value),
            )
            painter.setPen(grid_pen)

        row_h = plot_rect.height() / len(indices)
        bar_h = min(14, row_h * 0.6)
        for index, (r_index, value) in enumerate(zip(indices, values)):
            y_center = plot_rect.top() + row_h * (index + 0.5)
            y0 = y_center - bar_h / 2
            x0 = x_of(0.0)
            x1 = x_of(value)
            left = min(x0, x1)
            width = max(abs(x1 - x0), 1.0)
            if value >= 90:
                color = QtGui.QColor(120, 220, 140)
            elif value >= 80:
                color = GOLD
            elif value >= 60:
                color = QtGui.QColor(255, 140, 60)
            else:
                color = QtGui.QColor(255, 90, 90)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(color.red(), color.green(), color.blue(), 220))
            painter.drawRoundedRect(QtCore.QRectF(left, y0, width, bar_h), 3, 3)
            painter.setPen(QtGui.QColor(220, 220, 225))
            painter.setFont(label_font)
            painter.drawText(
                QtCore.QRect(rect.left(), int(y_center) - 9, left_band - 6, 18),
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                f"R{r_index}",
            )
            painter.drawText(
                QtCore.QRect(int(x1) + (6 if value >= 0 else -50), int(y_center) - 9, 44, 18),
                QtCore.Qt.AlignLeft if value >= 0 else QtCore.Qt.AlignRight,
                f"{value:.1f}",
            )


# --------------------------------------------------------------------------- #
# Shared dialog scaffolding
# --------------------------------------------------------------------------- #
class _AnalysisDialog(QtWidgets.QDialog):
    """Base dialog: dark card look, history list of CSVs, cached spectrum loads."""

    def __init__(self, csv_dir: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._csv_dir = csv_dir
        self._items = _csv_items(csv_dir)
        self._spectrum_cache: Dict[str, Spectrum] = {}

    def reload_history(self) -> None:
        self._items = _csv_items(self._csv_dir)
        self._spectrum_cache.clear()

    def spectrum_for(self, index: int) -> Spectrum:
        item = self._items[index]
        key = str(item.path)
        if key not in self._spectrum_cache:
            self._spectrum_cache[key] = load_spectrum(key, item.name)
        return self._spectrum_cache[key]

    @staticmethod
    def _combo_of_items(items, placeholder: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.addItem(placeholder)
        for item in items:
            combo.addItem(item.name)
        return combo

    @staticmethod
    def _compute(func, on_result) -> None:
        cursor = QtGui.QCursor(QtCore.Qt.WaitCursor)
        QtWidgets.QApplication.setOverrideCursor(cursor)
        try:
            result = func()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                QtWidgets.QApplication.activeWindow() or QtWidgets.QWidget(),
                "Analysis failed",
                str(exc),
            )
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if result is not None:
            on_result(result)

    @staticmethod
    def _build_list(items) -> QtWidgets.QListWidget:
        list_widget = QtWidgets.QListWidget()
        list_widget.setProperty("historyList", True)
        list_widget.setMinimumWidth(210)
        for item in items:
            list_item = QtWidgets.QListWidgetItem(item.name)
            list_item.setData(QtCore.Qt.UserRole, str(item.path))
            list_item.setToolTip(str(item.path))
            list_widget.addItem(list_item)
        if not items:
            placeholder = QtWidgets.QListWidgetItem("No CSV history in the output folder")
            placeholder.setFlags(QtCore.Qt.NoItemFlags)
            list_widget.addItem(placeholder)
        return list_widget


# --------------------------------------------------------------------------- #
# 1) SPD comparison
# --------------------------------------------------------------------------- #
DE_HEADERS = ["Pair", "ΔE76", "ΔE94", "ΔE2000", "CMC 2:1", "CMC 1:1", "ITP (BT.2124)", "ITP (P.143)"]


class SPDComparisonDialog(_AnalysisDialog):
    def __init__(self, csv_dir: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(csv_dir, parent)
        self.setWindowTitle("SPD Comparison（开发中）")
        self.resize(1020, 620)
        self._build()
        self._recompute()

    def _build(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # left: selection
        left = QtWidgets.QFrame()
        left.setProperty("card", True)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(9, 9, 9, 9)
        left_layout.setSpacing(8)
        title = QtWidgets.QLabel("Spectra")
        title.setProperty("section", True)
        self.list_widget = self._build_list(self._items)
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.list_widget.itemSelectionChanged.connect(self._recompute)
        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setProperty("secondary", True)
        reload_button.clicked.connect(self._handle_reload)
        select_all_button = QtWidgets.QPushButton("Select All")
        select_all_button.setProperty("secondary", True)
        select_all_button.clicked.connect(lambda: self.list_widget.selectAll())
        clear_button = QtWidgets.QPushButton("Clear")
        clear_button.setProperty("secondary", True)
        clear_button.clicked.connect(lambda: self.list_widget.clearSelection())
        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(reload_button)
        button_row.addWidget(select_all_button)
        button_row.addWidget(clear_button)
        hint = QtWidgets.QLabel("Ctrl/Shift-click to pick several curves.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        self.detail_label = QtWidgets.QLabel("--")
        self.detail_label.setProperty("muted", True)
        self.detail_label.setWordWrap(True)
        left_layout.addWidget(title)
        left_layout.addWidget(self.list_widget, 1)
        left_layout.addLayout(button_row)
        left_layout.addWidget(hint)
        left_layout.addWidget(self.detail_label)

        # right: plot + options + table
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(9)
        self.plot = MultiCurvePlotWidget()
        options_row = QtWidgets.QHBoxLayout()
        self.normalize_check = QtWidgets.QCheckBox("Normalize to peak (100%)")
        self.normalize_check.setChecked(True)
        self.normalize_check.toggled.connect(self._recompute)
        self.difference_check = QtWidgets.QCheckBox("Difference vs first selected")
        self.difference_check.setChecked(False)
        self.difference_check.toggled.connect(self._recompute)
        export_button = QtWidgets.QPushButton("Export ΔE CSV")
        export_button.setProperty("secondary", True)
        export_button.clicked.connect(self._export_table)
        options_row.addWidget(self.normalize_check)
        options_row.addWidget(self.difference_check)
        options_row.addStretch(1)
        options_row.addWidget(export_button)

        note = QtWidgets.QLabel(
            "ΔE metrics are chromaticity-based (each SPD normalized to unit Y). ITP is ITU's "
            "display-oriented metric: absolute values are large for light sources; compare "
            "BT.2124 (T halved) vs P.143 (no halving) relative behavior."
        )
        note.setProperty("muted", True)
        note.setWordWrap(True)

        self.table = QtWidgets.QTableWidget(0, len(DE_HEADERS))
        self.table.setHorizontalHeaderLabels(DE_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, len(DE_HEADERS)):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(108)

        right.addWidget(self.plot, 3)
        right.addLayout(options_row)
        right.addWidget(self.table, 2)
        right.addWidget(note)

        root.addWidget(left, 2)
        root.addLayout(right, 3)

    def _selected_spectra(self) -> List[Spectrum]:
        spectra: List[Spectrum] = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.isSelected() and item.data(QtCore.Qt.UserRole):
                spectra.append(self.spectrum_for(index))
        return spectra

    def _export_table(self) -> None:
        if self.table.rowCount() < 1 or "at least two" in self.table.item(0, 0).text():
            QtWidgets.QMessageBox.information(self, "Export", "Select at least two spectra first.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export ΔE Report", str(Path(self._csv_dir) / "delta_e_report.csv"), "CSV (*.csv)"
        )
        if not path:
            return
        lines = [",".join(DE_HEADERS)]
        for row in range(self.table.rowCount()):
            cells = []
            for column in range(len(DE_HEADERS)):
                item = self.table.item(row, column)
                text = item.text() if item else ""
                cells.append(f'"{text}"' if column == 0 else text)
            lines.append(",".join(cells))
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        QtWidgets.QMessageBox.information(self, "Export", f"Saved to:\n{path}")

    def _handle_reload(self) -> None:
        self.reload_history()
        self._replace_list()
        self._recompute()

    def _replace_list(self) -> None:
        selection = self._selected_paths()
        self.list_widget.clear()
        if not self._items:
            placeholder = QtWidgets.QListWidgetItem("No CSV history in the output folder")
            placeholder.setFlags(QtCore.Qt.NoItemFlags)
            self.list_widget.addItem(placeholder)
        else:
            for item in self._items:
                list_item = QtWidgets.QListWidgetItem(item.name)
                list_item.setData(QtCore.Qt.UserRole, str(item.path))
                list_item.setToolTip(str(item.path))
                self.list_widget.addItem(list_item)
        for index in range(self.list_widget.count()):
            list_item = self.list_widget.item(index)
            if list_item.data(QtCore.Qt.UserRole) in selection:
                list_item.setSelected(True)

    def _selected_paths(self) -> set:
        return {
            self.list_widget.item(index).data(QtCore.Qt.UserRole)
            for index in range(self.list_widget.count())
            if self.list_widget.item(index).isSelected()
        }

    def _recompute(self) -> None:
        spectra = self._selected_spectra()
        if not spectra:
            self.plot.clear()
            self.table.setRowCount(0)
            self.detail_label.setText("No spectra selected")
            return

        normalize = self.normalize_check.isChecked()
        show_diff = self.difference_check.isChecked()

        def run():
            curves: List[Curve] = []
            details: List[str] = []
            base = spectra[0]
            for index, spectrum in enumerate(spectra):
                values = spectrum.values.astype(float).copy()
                if normalize and np.max(values) > 0:
                    values = values / np.max(values) * 100.0
                color = CURVE_COLORS[index % len(CURVE_COLORS)]
                curves.append(Curve(spectrum.name, spectrum.wavelengths.astype(float), values, color))
                details.append(f"{spectrum.name}: x {spectrum.x:.4f}, y {spectrum.y:.4f}")
                if show_diff and index > 0:
                    grid, base_vals, this_vals = self._aligned(base, spectrum, normalize)
                    diff_color = QtGui.QColor(color.red(), color.green(), color.blue(), 160)
                    curves.append(
                        Curve(
                            f"{spectrum.name} − {base.name}",
                            grid,
                            this_vals - base_vals,
                            diff_color,
                            dashed=True,
                            width=1.6,
                        )
                    )
            reports = delta_e_matrix(spectra) if len(spectra) >= 2 else []
            return curves, details, reports

        def apply(result):
            curves, details, reports = result
            y_label = "Relative intensity (%)" if normalize else "Relative intensity"
            self.plot.set_data("SPD Overlay", curves, y_label=y_label)
            self.detail_label.setText("  ·  ".join(details))
            self.table.setRowCount(0)
            for report in reports:
                row = self.table.rowCount()
                self.table.insertRow(row)
                pair_item = QtWidgets.QTableWidgetItem(f"{report.name_a}  ↔  {report.name_b}")
                self.table.setItem(row, 0, pair_item)
                for column, value in enumerate(report.as_row(), start=1):
                    item = QtWidgets.QTableWidgetItem(f"{value:.3f}")
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    self.table.setItem(row, column, item)
            if len(spectra) < 2:
                self.table.insertRow(0)
                hint_item = QtWidgets.QTableWidgetItem("Select at least two spectra for ΔE")
                hint_item.setForeground(QtGui.QColor(160, 160, 170))
                self.table.setItem(0, 0, hint_item)

        self._compute(run, apply)

    @staticmethod
    def _aligned(base: Spectrum, other: Spectrum, normalize: bool):
        grid, base_vals, other_vals = _common_curves(base, other)
        if normalize:
            base_max = np.max(base_vals)
            other_max = np.max(other_vals)
            if base_max > 0:
                base_vals = base_vals / base_max * 100.0
            if other_max > 0:
                other_vals = other_vals / other_max * 100.0
        return grid, base_vals, other_vals


def _common_curves(a: Spectrum, b: Spectrum):
    lo = max(int(a.wavelengths[0]), int(b.wavelengths[0]))
    hi = min(int(a.wavelengths[-1]), int(b.wavelengths[-1]))
    grid = np.arange(lo, hi + 1, 1, dtype=float)
    va = np.interp(grid, a.wavelengths.astype(float), a.values)
    vb = np.interp(grid, b.wavelengths.astype(float), b.values)
    return grid, va, vb


# --------------------------------------------------------------------------- #
# 2) Spectral ratio (transmittance / reflectance)
# --------------------------------------------------------------------------- #
class SpectralRatioDialog(_AnalysisDialog):
    def __init__(self, csv_dir: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(csv_dir, parent)
        self.setWindowTitle("Spectral Ratio（开发中）— Transmittance / Reflectance")
        self.resize(960, 600)
        self._build()
        self._recompute()

    def _build(self) -> None:
        self._stat_values: Dict[str, QtWidgets.QLabel] = {}
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        left = QtWidgets.QFrame()
        left.setProperty("card", True)
        left.setMinimumWidth(250)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(9, 9, 9, 9)
        left_layout.setSpacing(8)

        title = QtWidgets.QLabel("Inputs")
        title.setProperty("section", True)

        mode_label = QtWidgets.QLabel("Quantity")
        mode_label.setProperty("fieldLabel", True)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("Transmittance T(λ) = sample / reference")
        self.mode_combo.addItem("Reflectance R(λ) = sample / reference")
        self.mode_combo.currentIndexChanged.connect(self._recompute)

        ref_label = QtWidgets.QLabel("Reference (bare / illumination)")
        ref_label.setProperty("fieldLabel", True)
        self.ref_combo = self._combo_of_items(self._items, "— reference —")
        self.ref_combo.currentIndexChanged.connect(self._recompute)

        sample_label = QtWidgets.QLabel("Sample (through sample / off surface)")
        sample_label.setProperty("fieldLabel", True)
        self.sample_combo = self._combo_of_items(self._items, "— sample —")
        self.sample_combo.currentIndexChanged.connect(self._recompute)

        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setProperty("secondary", True)
        reload_button.clicked.connect(self._handle_reload)

        hint = QtWidgets.QLabel(
            "Measure the reference first (e.g. bare probe or illumination), then the same "
            "setup with the sample in the beam. The ratio per wavelength is the sample's "
            "transmittance (or reflectance) in percent."
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)

        left_layout.addWidget(title)
        left_layout.addWidget(mode_label)
        left_layout.addWidget(self.mode_combo)
        left_layout.addWidget(ref_label)
        left_layout.addWidget(self.ref_combo)
        left_layout.addWidget(sample_label)
        left_layout.addWidget(self.sample_combo)
        left_layout.addWidget(reload_button)
        left_layout.addStretch(1)
        left_layout.addWidget(hint)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(9)
        self.plot = MultiCurvePlotWidget()

        stats_row = QtWidgets.QHBoxLayout()
        stats_row.addWidget(self._stat_card("Min"))
        stats_row.addWidget(self._stat_card("Mean"))
        stats_row.addWidget(self._stat_card("Max"))

        color_frame = QtWidgets.QFrame()
        color_frame.setProperty("card", True)
        color_layout = QtWidgets.QHBoxLayout(color_frame)
        color_layout.setContentsMargins(9, 7, 9, 7)
        color_layout.setSpacing(10)
        self.swatch = QtWidgets.QFrame()
        self.swatch.setFixedSize(76, 42)
        self.swatch.setStyleSheet(
            "background-color: rgb(127,127,127); border: 1px solid rgb(67,71,77); border-radius: 6px;"
        )
        swatch_text = QtWidgets.QVBoxLayout()
        swatch_text.setSpacing(2)
        color_title = QtWidgets.QLabel("Resulting light (sample SPD)")
        color_title.setProperty("section", True)
        self.color_xy_label = QtWidgets.QLabel("x, y: --")
        self.color_uv_label = QtWidgets.QLabel("u', v': --")
        self.color_meta_label = QtWidgets.QLabel("CCT / Y: --")
        for label in (self.color_xy_label, self.color_uv_label, self.color_meta_label):
            label.setProperty("muted", True)
        swatch_text.addWidget(color_title)
        swatch_text.addWidget(self.color_xy_label)
        swatch_text.addWidget(self.color_uv_label)
        swatch_text.addWidget(self.color_meta_label)
        color_layout.addWidget(self.swatch)
        color_layout.addLayout(swatch_text)
        color_layout.addStretch(1)

        save_button = QtWidgets.QPushButton("Save Ratio CSV")
        save_button.setProperty("secondary", True)
        save_button.clicked.connect(self._save_curve)

        right.addWidget(self.plot, 1)
        right.addLayout(stats_row)
        right.addWidget(color_frame)
        right.addWidget(save_button, 0, QtCore.Qt.AlignRight)

        root.addWidget(left)
        root.addLayout(right, 1)

    def _stat_card(self, name: str) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setProperty("card", True)
        frame.setProperty("metric", True)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.setSpacing(2)
        title = QtWidgets.QLabel(name)
        title.setProperty("metricTitle", True)
        value = QtWidgets.QLabel("--")
        value.setProperty("metricValue", True)
        value.setProperty("compact", True)
        layout.addWidget(title)
        layout.addWidget(value)
        self._stat_values[name] = value
        return frame

    def _handle_reload(self) -> None:
        self.reload_history()
        ref_index = self.ref_combo.currentIndex()
        sample_index = self.sample_combo.currentIndex()
        self.ref_combo.blockSignals(True)
        self.sample_combo.blockSignals(True)
        self.ref_combo.clear()
        self.sample_combo.clear()
        self.ref_combo.addItem("— reference —")
        self.sample_combo.addItem("— sample —")
        for item in self._items:
            self.ref_combo.addItem(item.name)
            self.sample_combo.addItem(item.name)
        self.ref_combo.setCurrentIndex(min(ref_index, self.ref_combo.count() - 1))
        self.sample_combo.setCurrentIndex(min(sample_index, self.sample_combo.count() - 1))
        self.ref_combo.blockSignals(False)
        self.sample_combo.blockSignals(False)
        self._recompute()

    def _save_curve(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Ratio Curve", str(Path(self._csv_dir) / "ratio.csv"), "CSV (*.csv)"
        )
        if not path:
            return
        if getattr(self, "_last_curve", None) is None:
            QtWidgets.QMessageBox.information(self, "Nothing to save", "Compute a ratio first.")
            return
        grid, values = self._last_curve
        save_curve_csv(path, grid, values)

    def _recompute(self) -> None:
        ref_index = self.ref_combo.currentIndex()
        sample_index = self.sample_combo.currentIndex()
        if ref_index < 1 or sample_index < 1:
            self.plot.clear()
            self._last_curve = None
            return
        reference = self.spectrum_for(ref_index - 1)
        sample = self.spectrum_for(sample_index - 1)
        is_transmittance = self.mode_combo.currentIndex() == 0

        def run():
            grid, ratio = spectral_ratio(reference, sample, as_percent=True)
            srgb = _srgb_8bit(sample.xyz)
            return grid, ratio, sample, srgb

        def apply(result):
            grid, ratio, sample, srgb = result
            self._last_curve = (grid, ratio)
            curves = [
                Curve(
                    "ratio %",
                    grid,
                    ratio,
                    GOLD,
                    width=2.2,
                )
            ]
            title = "Transmittance" if is_transmittance else "Reflectance"
            self.plot.set_data(f"{title} (%)", curves, y_label="Percent (%)", hlines=[(100.0, "100%")])
            with np.errstate(invalid="ignore"):
                finite = ratio[np.isfinite(ratio)]
            if finite.size:
                self._stat_values["Min"].setText(f"{float(np.min(finite)):.1f}%")
                self._stat_values["Mean"].setText(f"{float(np.mean(finite)):.1f}%")
                self._stat_values["Max"].setText(f"{float(np.max(finite)):.1f}%")
            r, g, b = srgb
            self.swatch.setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border: 1px solid rgb(67,71,77); border-radius: 6px;"
            )
            self.color_xy_label.setText(f"x, y: {sample.x:.4f}, {sample.y:.4f}")
            self.color_uv_label.setText(f"u', v': {sample.u_prime:.4f}, {sample.v_prime:.4f}")
            try:
                cct_duv = colour.uv_to_CCT([sample.u_prime, (2.0 / 3.0) * sample.v_prime], method="Ohno 2013")
                cct_text = f"{float(cct_duv[0]):.0f} K"
            except Exception:
                cct_text = "n/a"
            self.color_meta_label.setText(f"CCT {cct_text} · Y {sample.Y:.4e}")

        self._compute(run, apply)


# --------------------------------------------------------------------------- #
# 3) Gamut coverage
# --------------------------------------------------------------------------- #
GAMUT_TABLE_HEADERS = [
    "Gamut",
    "Standard",
    "White",
    "Area (UCS²)",
    "% visible",
    "Covers ref %",
    "Ref covers you %",
]

MIN_PRIMARY_ROWS = 3
MAX_PRIMARY_ROWS = 8


class GamutDialog(_AnalysisDialog):
    """Gamut coverage of any N >= 3 primaries (convex hull of all mixtures)
    against the reference gamuts, in the chosen UCS. Coverage figures are
    overlap figures — see :mod:`core.PR788_GamutUcs`."""

    def __init__(self, csv_dir: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(csv_dir, parent)
        self.setWindowTitle("Gamut Coverage（开发中）— Multi-Primary")
        self.resize(1060, 650)
        self._last_result: Optional[GamutResult] = None
        self._rows: List[Dict] = []
        self._build()
        self._recompute()

    # -- construction ------------------------------------------------------ #
    def _build(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        left = QtWidgets.QFrame()
        left.setProperty("card", True)
        left.setMinimumWidth(300)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(9, 9, 9, 9)
        left_layout.setSpacing(8)

        title = QtWidgets.QLabel("Primaries")
        title.setProperty("section", True)

        ucs_label = QtWidgets.QLabel("Color space (UCS)")
        ucs_label.setProperty("fieldLabel", True)
        self.ucs_combo = QtWidgets.QComboBox()
        for key, system in UCS_SYSTEMS.items():
            self.ucs_combo.addItem(system["label"], key)
        self.ucs_note = QtWidgets.QLabel(
            "Viewing conditions: D65-adapted, L = 40 (80 cd·m⁻²), average surround, "
            "CIE standard coefficients (IEC 61966-2-1)."
        )
        self.ucs_note.setProperty("muted", True)
        self.ucs_note.setWordWrap(True)
        self.ucs_note.setVisible(False)
        self.ucs_combo.currentIndexChanged.connect(self._on_ucs_changed)

        self._primaries_box = QtWidgets.QVBoxLayout()
        self._primaries_box.setSpacing(4)
        for tag in ("R", "G", "B"):
            self._add_primary_row(tag)

        self.add_primary_button = QtWidgets.QPushButton("+ Add primary")
        self.add_primary_button.setProperty("secondary", True)
        self.add_primary_button.clicked.connect(lambda: self._add_primary_row(self._next_tag()))

        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setProperty("secondary", True)
        reload_button.clicked.connect(self._handle_reload)

        ref_title = QtWidgets.QLabel("Reference gamuts")
        ref_title.setProperty("section", True)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemChanged.connect(self._on_tree_changed)
        self._build_tree()

        tree_buttons = QtWidgets.QHBoxLayout()
        select_all_button = QtWidgets.QPushButton("All")
        select_all_button.setProperty("secondary", True)
        select_all_button.clicked.connect(lambda: self._set_all_checked(QtCore.Qt.Checked))
        clear_button = QtWidgets.QPushButton("None")
        clear_button.setProperty("secondary", True)
        clear_button.clicked.connect(lambda: self._set_all_checked(QtCore.Qt.Unchecked))
        tree_buttons.addWidget(select_all_button)
        tree_buttons.addWidget(clear_button)

        hint = QtWidgets.QLabel(
            "The gamut is the convex hull of all selected primaries (>= 3; WRGB and other "
            "multi-channel sources work). Percentages are overlap figures: % visible = "
            "your gamut ∩ visible locus; Covers ref = you ∩ ref ÷ ref. Dashed outlines "
            "are CMYK process approximations (the standards define ink tolerances, not "
            "coordinates). Hover an entry for its standard and white point."
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)

        left_layout.addWidget(title)
        left_layout.addWidget(ucs_label)
        left_layout.addWidget(self.ucs_combo)
        left_layout.addWidget(self.ucs_note)
        left_layout.addLayout(self._primaries_box)
        left_layout.addWidget(self.add_primary_button)
        left_layout.addWidget(reload_button)
        left_layout.addWidget(ref_title)
        left_layout.addWidget(self.tree, 1)
        left_layout.addLayout(tree_buttons)
        left_layout.addWidget(hint)
        self._update_row_limits()

        # right: hero + canvas + table
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(9)

        hero = QtWidgets.QFrame()
        hero.setProperty("card", True)
        hero_layout = QtWidgets.QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 8, 12, 8)
        hero_layout.setSpacing(20)
        self.hero_values: Dict[str, QtWidgets.QLabel] = {}
        for key, title_text in (("area", "Gamut area (UCS²)"),
                                ("visible", "% visible (overlap)"),
                                ("srgb", "Covers sRGB (overlap)")):
            block = QtWidgets.QVBoxLayout()
            block.setSpacing(2)
            block_title = QtWidgets.QLabel(title_text)
            block_title.setProperty("metricTitle", True)
            value = QtWidgets.QLabel("--")
            value.setProperty("metricValue", True)
            block.addWidget(block_title)
            block.addWidget(value)
            hero_layout.addLayout(block)
            self.hero_values[key] = value
        hero_layout.addStretch(1)

        self.canvas = GamutCanvasWidget()

        self.table = QtWidgets.QTableWidget(0, len(GAMUT_TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(GAMUT_TABLE_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, len(GAMUT_TABLE_HEADERS)):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(150)

        right.addWidget(hero)
        right.addWidget(self.canvas, 3)
        right.addWidget(self.table, 2)

        root.addWidget(left)
        root.addLayout(right, 1)

    # -- primary rows (N >= 3, up to 8) ------------------------------------- #
    def _add_primary_row(self, tag: str, insert_at: int = -1) -> None:
        widget = QtWidgets.QFrame()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(4)
        tag_edit = QtWidgets.QLineEdit(tag)
        tag_edit.setMaxLength(1)
        tag_edit.setFixedWidth(26)
        tag_edit.setAlignment(QtCore.Qt.AlignCenter)
        tag_edit.setToolTip("Short label shown on the canvas")
        combo = self._combo_of_items(self._items, "—")
        remove_button = QtWidgets.QPushButton("×")
        remove_button.setFixedWidth(24)
        remove_button.setProperty("secondary", True)
        remove_button.setToolTip("Remove this primary")
        top.addWidget(tag_edit)
        top.addWidget(combo, 1)
        top.addWidget(remove_button)
        xy_label = QtWidgets.QLabel("x, y: --")
        xy_label.setProperty("muted", True)
        layout.addLayout(top)
        layout.addWidget(xy_label)

        row = {
            "widget": widget,
            "tag": tag_edit,
            "combo": combo,
            "xy": xy_label,
            "remove": remove_button,
        }
        # connect only after the combo is populated (populating fires signals)
        tag_edit.textChanged.connect(self._recompute)
        combo.currentIndexChanged.connect(self._recompute)
        remove_button.clicked.connect(lambda _checked=False, r=row: self._remove_primary_row(r))
        if insert_at < 0:
            self._primaries_box.addWidget(widget)
        else:
            self._primaries_box.insertWidget(insert_at, widget)
        self._rows.append(row)
        self._update_row_limits()

    def _remove_primary_row(self, row: Dict) -> None:
        if len(self._rows) <= MIN_PRIMARY_ROWS:
            return
        self._rows.remove(row)
        self._primaries_box.removeWidget(row["widget"])
        row["widget"].setParent(None)
        row["widget"].deleteLater()
        self._update_row_limits()
        self._recompute()

    def _update_row_limits(self) -> None:
        count = len(self._rows)
        if hasattr(self, "add_primary_button"):
            self.add_primary_button.setEnabled(count < MAX_PRIMARY_ROWS)
        for row in self._rows:
            row["remove"].setEnabled(count > MIN_PRIMARY_ROWS)

    def _next_tag(self) -> str:
        used = {row["tag"].text() for row in self._rows}
        for candidate in "WRGBOYMB":
            if candidate not in used:
                return candidate
        return f"P{len(self._rows) + 1}"

    def _selected_rows(self) -> List[Dict]:
        return [row for row in self._rows if row["combo"].currentIndex() >= 1]

    def _build_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        checked_by_default = set(DEFAULT_GAMUT_SELECTION)
        by_category = gamuts_by_category()
        for category, definitions in by_category.items():
            branch = QtWidgets.QTreeWidgetItem([category])
            font = branch.font(0)
            font.setBold(True)
            branch.setFont(0, font)
            self.tree.addTopLevelItem(branch)
            for definition in definitions:
                label = definition.name + (" ≈" if definition.approximate else "")
                child = QtWidgets.QTreeWidgetItem([label])
                child.setFlags(child.flags() | QtCore.Qt.ItemIsUserCheckable)
                child.setCheckState(
                    0, QtCore.Qt.Checked if definition.name in checked_by_default else QtCore.Qt.Unchecked
                )
                child.setData(0, QtCore.Qt.UserRole, definition.name)
                color = _gamut_color(definition.name)
                child.setForeground(0, QtGui.QColor(color.red(), color.green(), color.blue(), 230))
                white = definition.white_xy
                tooltip = (
                    f"Standard: {definition.standard}\n"
                    f"White point: {definition.white_label} ({white[0]:.4f}, {white[1]:.4f})\n"
                )
                if definition.note:
                    tooltip += definition.note
                child.setToolTip(0, tooltip)
                branch.addChild(child)
            branch.setExpanded(True)
        self.tree.blockSignals(False)

    # -- reference-gamut selection ----------------------------------------- #
    def _iter_gamut_items(self):
        for index in range(self.tree.topLevelItemCount()):
            branch = self.tree.topLevelItem(index)
            for child_index in range(branch.childCount()):
                yield branch.child(child_index)

    def _checked_names(self) -> set:
        return {
            item.data(0, QtCore.Qt.UserRole)
            for item in self._iter_gamut_items()
            if item.checkState(0) == QtCore.Qt.Checked
        }

    def _set_all_checked(self, state: QtCore.Qt.CheckState) -> None:
        self.tree.blockSignals(True)
        for item in self._iter_gamut_items():
            item.setCheckState(0, state)
        self.tree.blockSignals(False)
        self._refresh_views()

    def _on_tree_changed(self) -> None:
        self._refresh_views()

    # -- recomputation ------------------------------------------------------ #
    def _handle_reload(self) -> None:
        self.reload_history()
        for row in self._rows:
            combo = row["combo"]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("—")
            for item in self._items:
                combo.addItem(item.name)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._recompute()

    def _on_ucs_changed(self) -> None:
        key = self.ucs_combo.currentData()
        self.ucs_note.setVisible(key in ("cie2000ucs", "cam16ucs"))
        self._recompute()

    def _recompute(self) -> None:
        selected = self._selected_rows()
        ucs_key = self.ucs_combo.currentData()
        # canvas follows the UCS even with < 3 primaries selected (the
        # empty-state early return below would otherwise leave it on the
        # previous system's field/grid/title)
        self.canvas.set_ucs(ucs_key)
        if len(selected) < MIN_PRIMARY_ROWS:
            self._last_result = None
            self._refresh_views()
            for row in self._rows:
                row["xy"].setText("x, y: --")
            return

        def run():
            primaries = [self.spectrum_for(row["combo"].currentIndex() - 1) for row in selected]
            result = gamut_coverage_ucs(primaries, ucs_key)
            return primaries, result, [row["tag"].text() or "?" for row in selected]

        def apply(payload):
            primaries, result, labels = payload
            self._last_result = result
            primary_for = {id(row): primary for row, primary in zip(selected, primaries)}
            for row in self._rows:
                primary = primary_for.get(id(row))
                row["xy"].setText(
                    f"x, y: {primary.x:.4f}, {primary.y:.4f}"
                    if primary is not None
                    else "x, y: --"
                )
            self.canvas.set_ucs(ucs_key)
            self.canvas.set_labels(labels)
            self._refresh_views()

        self._compute(run, apply)

    def _refresh_views(self) -> None:
        checked = self._checked_names()
        self.canvas.set_result(self._last_result, checked)
        self._refresh_table(checked)
        if self._last_result is None:
            for value in self.hero_values.values():
                value.setText("--")
            return
        result = self._last_result
        self.hero_values["area"].setText(_format_value(result.hull_area))
        self.hero_values["visible"].setText(f"{result.percent_of_visible:.1f} %")
        srgb = result.reference.get("sRGB / Rec. 709")
        self.hero_values["srgb"].setText(
            f"{srgb.covers_reference:.1f} %" if srgb is not None else "--"
        )

    def _refresh_table(self, checked: set) -> None:
        self.table.setRowCount(0)
        if self._last_result is None:
            return
        for definition in GAMUT_LIBRARY:
            name = definition.name
            if name not in checked:
                continue
            ref = self._last_result.reference[name]
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QtWidgets.QTableWidgetItem(name + (" ≈" if definition.approximate else ""))
            name_item.setForeground(_gamut_color(name))
            name_item.setToolTip(f"Standard: {definition.standard}")
            if definition.approximate and definition.note:
                name_item.setToolTip(f"{name_item.toolTip()}\n{definition.note}")
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(definition.standard))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(definition.white_label))
            self.table.setItem(row, 3, self._right_item(_format_value(ref.area)))
            self.table.setItem(row, 4, self._right_item(f"{ref.percent_of_visible:.1f} %"))
            self.table.setItem(row, 5, self._right_item(f"{ref.covers_reference:.1f} %"))
            self.table.setItem(row, 6, self._right_item(f"{ref.reference_covers_you:.1f} %"))

    @staticmethod
    def _right_item(text: str) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(text)
        item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        return item


# --------------------------------------------------------------------------- #
# 4) CRI
# --------------------------------------------------------------------------- #
class CRIDialog(_AnalysisDialog):
    def __init__(self, csv_dir: str, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(csv_dir, parent)
        self.setWindowTitle("Color Rendering Index (CRI)（开发中）")
        self.resize(780, 580)
        self._build()
        self._recompute()

    def _build(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        left = QtWidgets.QFrame()
        left.setProperty("card", True)
        left.setMinimumWidth(250)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(9, 9, 9, 9)
        left_layout.setSpacing(8)

        title = QtWidgets.QLabel("Spectrum")
        title.setProperty("section", True)
        self.combo = self._combo_of_items(self._items, "— spectrum —")
        self.combo.currentIndexChanged.connect(self._recompute)
        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setProperty("secondary", True)
        reload_button.clicked.connect(self._handle_reload)
        hint = QtWidgets.QLabel(
            "Ra is the average of R1–R8. Individual R values (this colour build provides "
            "R1–R14; R15 is unavailable) are shown as bars; green ≥ 90, amber ≥ 80, red < 80."
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        left_layout.addWidget(title)
        left_layout.addWidget(self.combo)
        left_layout.addWidget(reload_button)
        left_layout.addStretch(1)
        left_layout.addWidget(hint)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(9)
        hero = QtWidgets.QFrame()
        hero.setProperty("card", True)
        hero.setProperty("hero", True)
        hero_layout = QtWidgets.QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 8, 12, 8)
        hero_layout.setSpacing(20)
        ra_block = QtWidgets.QVBoxLayout()
        ra_block.setSpacing(2)
        ra_title = QtWidgets.QLabel("Ra (general)")
        ra_title.setProperty("metricTitle", True)
        self.ra_value = QtWidgets.QLabel("--")
        self.ra_value.setProperty("metricValue", True)
        ra_block.addWidget(ra_title)
        ra_block.addWidget(self.ra_value)
        cct_block = QtWidgets.QVBoxLayout()
        cct_block.setSpacing(2)
        cct_title = QtWidgets.QLabel("CCT (Ohno 2013)")
        cct_title.setProperty("metricTitle", True)
        self.cct_value = QtWidgets.QLabel("--")
        self.cct_value.setProperty("metricValue", True)
        cct_block.addWidget(cct_title)
        cct_block.addWidget(self.cct_value)
        xy_block = QtWidgets.QVBoxLayout()
        xy_block.setSpacing(2)
        xy_title = QtWidgets.QLabel("x, y")
        xy_title.setProperty("metricTitle", True)
        self.xy_value = QtWidgets.QLabel("--")
        self.xy_value.setProperty("metricValue", True)
        xy_block.addWidget(xy_title)
        xy_block.addWidget(self.xy_value)
        hero_layout.addLayout(ra_block)
        hero_layout.addLayout(cct_block)
        hero_layout.addLayout(xy_block)
        hero_layout.addStretch(1)

        self.bars = CriBarWidget()
        right.addWidget(hero)
        right.addWidget(self.bars, 1)

        root.addWidget(left)
        root.addLayout(right, 1)

    def _handle_reload(self) -> None:
        self.reload_history()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("— spectrum —")
        for item in self._items:
            self.combo.addItem(item.name)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self._recompute()

    def _recompute(self) -> None:
        index = self.combo.currentIndex()
        if index < 1:
            self.ra_value.setText("--")
            self.cct_value.setText("--")
            self.xy_value.setText("--")
            self.bars.set_values({})
            return
        spectrum = self.spectrum_for(index - 1)

        def run() -> CriResult:
            return cri(spectrum)

        def apply(result: CriResult) -> None:
            self.ra_value.setText(f"{result.ra:.2f}")
            self.cct_value.setText(f"{result.cct:.0f} K" if result.cct else "n/a")
            self.xy_value.setText(f"{spectrum.x:.4f}, {spectrum.y:.4f}")
            self.bars.set_values(result.r_indices)

        self._compute(run, apply)
