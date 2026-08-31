import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

import colour
import numpy as np
from colour.plotting import lines_spectral_locus
from PyQt5 import QtCore, QtGui, QtWidgets

from analysis_dialogs import (
    CRIDialog,
    GamutDialog,
    SPDComparisonDialog,
    SpectralRatioDialog,
)
from chromaticity_field import chromaticity_image
from core.PR788_Service import (
    HistoryCsvItem,
    MeasurementRecord,
    build_template_variables,
    load_preview_from_csv,
    list_serial_ports,
    list_history_csv_files,
    measure_with_template,
    render_filename_template,
    sanitize_filename_part,
)
from core.PR788_Utils import PR788


CMFS_NAME = "CIE 1931 2 Degree Standard Observer"

# folder names never shown in the project file tree (besides dot-folders)
NOISY_DIR_NAMES = frozenset({"__pycache__", "node_modules"})

CHROMATICITY_SYSTEMS = {
    "CIE 1931 xy": {
        "locus_method": "CIE 1931",
        "x_range": (0.0, 0.80),
        "y_range": (0.0, 0.85),
        "x_label": "x",
        "y_label": "y",
        "ticks": [0.2, 0.4, 0.6, 0.8],
    },
    "CIE 1976 u'v'": {
        "locus_method": "CIE 1976 UCS",
        "x_range": (0.0, 0.65),
        "y_range": (0.0, 0.62),
        "x_label": "u'",
        "y_label": "v'",
        "ticks": [0.2, 0.4, 0.6],
    },
}

# Wavelengths covered by lines_spectral_locus positions (1 nm steps);
# index = wavelength - 360, so the line of purples spans 380 nm -> 780 nm.
_LOCUS_START_WAVELENGTH = 360
_PURPLE_LINE_WAVELENGTHS = (380, 780)

_chromaticity_cache: dict[str, dict] = {}


def _get_chromaticity_data(method: str) -> dict:
    if method in _chromaticity_cache:
        return _chromaticity_cache[method]

    lines, _ = lines_spectral_locus(method=method)
    positions = np.asarray(lines["position"], dtype=float)

    # D65 white point, transformed into the same chromaticity space.
    # CIE 1976 is converted directly (this colour version's XYZ_to_UVW does
    # not yield u'v): u' = 4X/(X+15Y+3Z), v' = 9Y/(X+15Y+3Z) -> (0.1978, 0.4683).
    d65_xyz = np.asarray(
        colour.sd_to_XYZ(colour.SDS_ILLUMINANTS["D65"], colour.MSDS_CMFS[CMFS_NAME]), dtype=float
    )
    if method == "CIE 1931":
        d65_point = np.asarray(colour.XYZ_to_xy(d65_xyz), dtype=float)
    else:
        denom = d65_xyz[0] + 15.0 * d65_xyz[1] + 3.0 * d65_xyz[2]
        d65_point = np.array([4.0 * d65_xyz[0] / denom, 9.0 * d65_xyz[1] / denom])

    data = {"positions": positions, "d65": d65_point}
    _chromaticity_cache[method] = data
    return data


class TaskWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, func: Callable[[], object]) -> None:
        super().__init__()
        self._func = func

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            result = self._func()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class MetricCard(QtWidgets.QFrame):
    def __init__(
        self,
        title: str,
        value: str = "--",
        compact: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("metric", True)
        if compact:
            self.setProperty("compact", True)
        layout = QtWidgets.QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(7, 4, 7, 4)
            layout.setSpacing(2)
        else:
            layout.setContentsMargins(8, 7, 8, 7)
            layout.setSpacing(4)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setProperty("metricTitle", True)
        self.value_label = QtWidgets.QLabel(value)
        self.value_label.setProperty("metricValue", True)
        if compact:
            self.value_label.setProperty("compact", True)
        self.value_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class ColorSwatchWidget(QtWidgets.QFrame):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("metric", True)
        self.setFixedWidth(92)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(4)

        self.title_label = QtWidgets.QLabel("sRGB Preview")
        self.title_label.setProperty("metricTitle", True)
        self.title_label.setProperty("swatchLabel", True)
        self.title_label.setFixedWidth(58)
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)

        self.swatch = QtWidgets.QFrame()
        self.swatch.setMinimumSize(72, 46)
        self.swatch.setMaximumHeight(50)
        self.swatch.setStyleSheet(
            "background-color: rgb(127, 127, 127); border: 1px solid rgb(67, 71, 77); border-radius: 6px;"
        )

        self.value_label = QtWidgets.QLabel("RGB 127, 127, 127")
        self.value_label.setProperty("metricTitle", True)
        self.value_label.setProperty("swatchLabel", True)
        self.value_label.setFixedWidth(76)
        self.value_label.setAlignment(QtCore.Qt.AlignCenter)

        layout.addWidget(self.title_label, 0, QtCore.Qt.AlignHCenter)
        layout.addWidget(self.swatch, 0, QtCore.Qt.AlignHCenter)
        layout.addWidget(self.value_label, 0, QtCore.Qt.AlignHCenter)
        layout.addStretch(1)

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        r, g, b = rgb
        self.swatch.setStyleSheet(
            f"background-color: rgb({r}, {g}, {b}); border: 1px solid rgb(67, 71, 77); border-radius: 6px;"
        )
        self.value_label.setText(f"RGB {r}, {g}, {b}")


class SPDPlotWidget(QtWidgets.QFrame):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("plot", True)
        self.setMinimumHeight(240)
        self._rows = []
        self._curve_color = QtGui.QColor(255, 255, 255)
        self._peak_color = QtGui.QColor(255, 194, 82)

    def set_rows(self, rows) -> None:
        self._rows = list(rows)
        self.update()

    @staticmethod
    def _wavelength_to_color(wavelength: float) -> QtGui.QColor:
        wl = max(380.0, min(780.0, wavelength))
        if wl < 440:
            r = -(wl - 440.0) / (440.0 - 380.0)
            g = 0.0
            b = 1.0
        elif wl < 490:
            r = 0.0
            g = (wl - 440.0) / (490.0 - 440.0)
            b = 1.0
        elif wl < 510:
            r = 0.0
            g = 1.0
            b = -(wl - 510.0) / (510.0 - 490.0)
        elif wl < 580:
            r = (wl - 510.0) / (580.0 - 510.0)
            g = 1.0
            b = 0.0
        elif wl < 645:
            r = 1.0
            g = -(wl - 645.0) / (645.0 - 580.0)
            b = 0.0
        else:
            r = 1.0
            g = 0.0
            b = 0.0

        if wl < 420:
            factor = 0.3 + 0.7 * (wl - 380.0) / (420.0 - 380.0)
        elif wl <= 700:
            factor = 1.0
        else:
            factor = 0.3 + 0.7 * (780.0 - wl) / (780.0 - 700.0)

        gamma = 0.8
        red = int((max(r, 0.0) * factor) ** gamma * 255)
        green = int((max(g, 0.0) * factor) ** gamma * 255)
        blue = int((max(b, 0.0) * factor) ** gamma * 255)
        return QtGui.QColor(red, green, blue, 140)

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
        top_info_band = label_metrics.height() + 4
        tick_band = label_metrics.height() + 6
        axis_label_band = label_metrics.height() + 8
        plot_top = rect.top() + title_band
        plot_height = rect.height() - title_band - top_info_band - tick_band - axis_label_band - 4
        plot_height = max(plot_height, 140)

        title_rect = QtCore.QRect(rect.left(), rect.top(), rect.width(), title_band)
        painter.setPen(QtGui.QColor(235, 235, 235))
        painter.setFont(title_font)
        painter.drawText(title_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "SPD Preview 380-780 nm")

        plot_rect = QtCore.QRect(rect.left(), plot_top, rect.width(), plot_height)
        painter.setPen(QtGui.QPen(QtGui.QColor(67, 71, 77), 1))
        painter.drawRoundedRect(plot_rect, 10, 10)

        if not self._rows:
            painter.setPen(QtGui.QColor(220, 220, 220))
            painter.drawText(plot_rect, QtCore.Qt.AlignCenter, "No measurement data")
            return

        inner = plot_rect.adjusted(20, 14, -20, -14)
        wavelengths = [row[0] for row in self._rows]
        values = [row[1] for row in self._rows]
        min_wl = 380
        max_wl = 780
        max_value = max(values) if values else 1.0
        if max_value <= 0:
            max_value = 1.0

        grid_pen = QtGui.QPen(QtGui.QColor(55, 58, 64), 1)
        grid_pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(grid_pen)
        for fraction in (0.25, 0.5, 0.75):
            y = inner.bottom() - int(inner.height() * fraction)
            painter.drawLine(inner.left(), y, inner.right(), y)
        for wavelength in (380, 480, 580, 680, 780):
            x = inner.left() + int((wavelength - min_wl) / (max_wl - min_wl) * inner.width())
            painter.drawLine(x, inner.top(), x, inner.bottom())

        axis_pen = QtGui.QPen(QtGui.QColor(210, 210, 210), 1)
        painter.setPen(axis_pen)
        painter.drawLine(inner.left(), inner.bottom(), inner.right(), inner.bottom())
        painter.drawLine(inner.left(), inner.top(), inner.left(), inner.bottom())

        path = QtGui.QPainterPath()
        for index, (wavelength, value) in enumerate(self._rows):
            x_ratio = (wavelength - min_wl) / (max_wl - min_wl)
            y_ratio = value / max_value
            x = inner.left() + x_ratio * inner.width()
            y = inner.bottom() - y_ratio * inner.height()
            point = QtCore.QPointF(x, y)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)

        area_path = QtGui.QPainterPath(path)
        area_path.lineTo(inner.right(), inner.bottom())
        area_path.lineTo(inner.left(), inner.bottom())
        area_path.closeSubpath()

        gradient = QtGui.QLinearGradient(inner.left(), inner.top(), inner.right(), inner.top())
        gradient_stops = [
            (380, QtGui.QColor(110, 70, 255, 170)),
            (430, QtGui.QColor(50, 120, 255, 170)),
            (470, QtGui.QColor(0, 190, 255, 170)),
            (510, QtGui.QColor(0, 220, 140, 170)),
            (560, QtGui.QColor(170, 230, 40, 170)),
            (590, QtGui.QColor(255, 210, 0, 170)),
            (620, QtGui.QColor(255, 130, 0, 170)),
            (700, QtGui.QColor(255, 50, 50, 170)),
            (780, QtGui.QColor(180, 40, 40, 170)),
        ]
        for wavelength, color in gradient_stops:
            stop = (wavelength - min_wl) / (max_wl - min_wl)
            gradient.setColorAt(stop, color)

        painter.save()
        painter.setClipPath(area_path)
        painter.fillRect(inner, gradient)
        painter.restore()

        painter.setPen(QtGui.QPen(self._curve_color, 2.2))
        painter.drawPath(path)

        peak_index = max(range(len(values)), key=lambda idx: values[idx])
        peak_wl = wavelengths[peak_index]
        peak_val = values[peak_index]
        peak_x = inner.left() + ((peak_wl - min_wl) / (max_wl - min_wl)) * inner.width()
        peak_y = inner.bottom() - ((peak_val / max_value) * inner.height())

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(self._peak_color)
        painter.drawEllipse(QtCore.QPointF(peak_x, peak_y), 4, 4)

        text_pen = QtGui.QPen(QtGui.QColor(230, 230, 230), 1)
        painter.setPen(text_pen)
        painter.setFont(label_font)
        tick_candidates = [380, 480, 580, 680, 780]
        if inner.width() < 520:
            tick_candidates = [380, 580, 780]

        peak_rect = QtCore.QRect(
            inner.left(),
            rect.top() + title_band,
            inner.width(),
            top_info_band,
        )
        painter.drawText(
            peak_rect,
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
            f"Peak {peak_wl} nm",
        )

        tick_top = plot_rect.bottom() + 2
        last_text_right = None
        for wavelength in tick_candidates:
            x = inner.left() + int((wavelength - min_wl) / (max_wl - min_wl) * inner.width())
            text_rect = QtCore.QRect(x - 24, tick_top, 48, tick_band)
            if last_text_right is not None and text_rect.left() <= last_text_right + 6:
                continue
            painter.drawText(text_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, str(wavelength))
            last_text_right = text_rect.right()

        axis_label_top = tick_top + tick_band - 1
        painter.drawText(
            QtCore.QRect(inner.left(), axis_label_top, inner.width(), axis_label_band),
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
            "Wavelength (nm)",
        )


class ChromaticityCanvas(QtWidgets.QWidget):
    """Painter-backed canvas for the CIE chromaticity diagram."""

    def __init__(self, owner: "ChromaticityDiagramWidget", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._owner = owner
        self._locus_pen = QtGui.QPen(QtGui.QColor(150, 153, 160), 1.0)
        self._purple_pen = QtGui.QPen(QtGui.QColor(105, 108, 116), 0.8)
        # primary layer: the measured point is bright neutral white with a
        # dark ring (legible over bright field areas); D65 is subordinate gray
        self._point_brush = QtGui.QBrush(QtGui.QColor(245, 247, 252))
        self._point_ring = QtGui.QPen(QtGui.QColor(35, 37, 43), 1.2)
        self._d65_brush = QtGui.QBrush(QtGui.QColor(158, 161, 168))

    def _map(self, inner: QtCore.QRect, value: float, minimum: float, maximum: float) -> float:
        return (value - minimum) / (maximum - minimum)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(4, 4, -4, -4)
        label_font = QtGui.QFont("Open Sans", 7)
        axis_font = QtGui.QFont("Open Sans", 8)
        label_metrics = QtGui.QFontMetrics(label_font)
        tick_band = label_metrics.height() + 4
        left_band = label_metrics.horizontalAdvance("0.80") + 8

        spec = CHROMATICITY_SYSTEMS[self._owner._system_key]
        data = _get_chromaticity_data(spec["locus_method"])
        x_min, x_max = spec["x_range"]
        y_min, y_max = spec["y_range"]

        avail = QtCore.QRect(
            rect.left() + left_band,
            rect.top(),
            rect.width() - left_band - 4,
            rect.height() - tick_band - 2,
        )
        # Strict equal pixel scale on both axes: the diagram keeps its true
        # proportions no matter how the surrounding splitters are dragged.
        aspect = (x_max - x_min) / (y_max - y_min)
        if avail.height() <= 0 or avail.width() <= 0:
            return
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

        def to_x(value: float) -> float:
            return inner.left() + self._map(inner, value, x_min, x_max) * inner.width()

        def to_y(value: float) -> float:
            return inner.bottom() - self._map(inner, value, y_min, y_max) * inner.height()

        painter.setPen(QtGui.QPen(QtGui.QColor(67, 71, 77), 1))
        painter.drawRoundedRect(plot_rect, 8, 8)

        if data is None:
            painter.setPen(QtGui.QColor(220, 220, 220))
            painter.drawText(inner, QtCore.Qt.AlignCenter, "No locus data")
            return

        # Grid lines at the spec ticks.
        grid_pen = QtGui.QPen(QtGui.QColor(55, 58, 64), 1)
        grid_pen.setStyle(QtCore.Qt.DashLine)
        painter.setPen(grid_pen)
        for value in spec["ticks"]:
            if x_min < value < x_max:
                x = to_x(value)
                painter.drawLine(QtCore.QPointF(x, inner.top()), QtCore.QPointF(x, inner.bottom()))
            if y_min < value < y_max:
                y = to_y(value)
                painter.drawLine(QtCore.QPointF(inner.left(), y), QtCore.QPointF(inner.right(), y))

        # Spectral locus path (shared by the colored fill and the outline).
        positions = data["positions"]
        locus_points = [QtCore.QPointF(to_x(point[0]), to_y(point[1])) for point in positions]
        locus_path = QtGui.QPainterPath()
        locus_path.moveTo(locus_points[0])
        for point in locus_points[1:]:
            locus_path.lineTo(point)

        # Colored CIE background, pre-masked to the visible locus (alpha channel).
        system = "uv" if spec["locus_method"] != "CIE 1931" else "cie1931"
        field = chromaticity_image(
            system, x_min, x_max, y_min, y_max, inner.width(), inner.height(),
            locus=np.asarray(positions, dtype=float),
        )
        if not field.isNull():
            painter.drawImage(inner, field)

        axis_pen = QtGui.QPen(QtGui.QColor(120, 123, 130), 1)
        painter.setPen(axis_pen)
        painter.drawLine(inner.left(), inner.bottom(), inner.right(), inner.bottom())
        painter.drawLine(inner.left(), inner.top(), inner.left(), inner.bottom())

        painter.save()
        painter.setClipRect(inner)

        # Spectral locus outline.
        painter.setPen(self._locus_pen)
        painter.drawPath(locus_path)

        # Line of purples (380 nm -> 780 nm endpoints).
        start_index = _PURPLE_LINE_WAVELENGTHS[0] - _LOCUS_START_WAVELENGTH
        end_index = _PURPLE_LINE_WAVELENGTHS[1] - _LOCUS_START_WAVELENGTH
        if 0 <= start_index < len(positions) and 0 <= end_index < len(positions):
            painter.setPen(self._purple_pen)
            painter.drawLine(locus_points[start_index], locus_points[end_index])

        # D65 white point.
        d65 = data["d65"]
        d65_point = QtCore.QPointF(to_x(float(d65[0])), to_y(float(d65[1])))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(self._d65_brush)
        painter.drawEllipse(d65_point, 1.6, 1.6)
        painter.setPen(QtGui.QColor(158, 161, 168))
        painter.setFont(label_font)
        painter.drawText(QtCore.QRectF(d65_point.x() + 5, d65_point.y() - 12, 40, 14), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "D65")

        # Measured point (primary layer): white with a dark ring.
        measured = self._owner._point
        if measured is not None:
            x_value, y_value = measured
            if x_min <= x_value <= x_max and y_min <= y_value <= y_max:
                point_pos = QtCore.QPointF(to_x(x_value), to_y(y_value))
                painter.setPen(self._point_ring)
                painter.setBrush(self._point_brush)
                painter.drawEllipse(point_pos, 2.6, 2.6)
        painter.restore()

        if self._owner._point is None:
            painter.setPen(QtGui.QColor(150, 153, 160))
            empty_rect = inner.adjusted(40, 40, -40, -40)
            if empty_rect.width() > 0 and empty_rect.height() > 0:
                painter.drawText(empty_rect, QtCore.Qt.AlignCenter, "No measurement data")

        # Tick labels and axis names.
        painter.setPen(QtGui.QColor(190, 190, 195))
        painter.setFont(label_font)
        tick_top = plot_rect.bottom() + 2
        for value in spec["ticks"]:
            if x_min < value < x_max:
                x = to_x(value)
                painter.drawText(QtCore.QRectF(x - 20, tick_top, 40, tick_band), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, f"{value:.1f}")
            if y_min < value < y_max:
                y = to_y(value)
                painter.drawText(QtCore.QRectF(rect.left(), y - 7, left_band - 4, 14), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, f"{value:.1f}")

        painter.setFont(axis_font)
        painter.setPen(QtGui.QColor(170, 172, 178))
        axis_rect = QtCore.QRect(inner.left(), tick_top + 2, inner.width(), label_metrics.height())
        painter.drawText(axis_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, f"{spec['x_label']}")
        y_label_rect = QtCore.QRect(rect.left(), inner.top(), left_band - 4, 14)
        painter.drawText(y_label_rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignTop, f"{spec['y_label']}")


class ChromaticityDiagramWidget(QtWidgets.QFrame):
    """Card holding a switchable CIE chromaticity diagram with the measured point."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("plot", True)
        self.setMinimumHeight(240)
        self._system_key = next(iter(CHROMATICITY_SYSTEMS))
        self._point: Optional[tuple[float, float]] = None
        self._point_xy: Optional[tuple[float, float]] = None
        self._point_uv: Optional[tuple[float, float]] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(6)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Chromaticity")
        title.setProperty("section", True)
        self.system_combo = QtWidgets.QComboBox()
        for key in CHROMATICITY_SYSTEMS:
            self.system_combo.addItem(key)
        self.system_combo.currentIndexChanged.connect(self._on_system_changed)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.system_combo)

        self.canvas = ChromaticityCanvas(self)
        layout.addLayout(header)
        layout.addWidget(self.canvas, 1)

    def _on_system_changed(self, index: int) -> None:
        self._system_key = list(CHROMATICITY_SYSTEMS)[index]
        if self._system_key == "CIE 1931 xy":
            self._point = self._point_xy
        else:
            self._point = self._point_uv
        self.canvas.update()

    def set_point(self, x: float, y: float, u_prime: float, v_prime: float) -> None:
        self._point_xy = (x, y)
        self._point_uv = (u_prime, v_prime)
        if self._system_key == "CIE 1931 xy":
            self._point = self._point_xy
        else:
            self._point = self._point_uv
        self.canvas.update()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PR788 Spectral Capture")

        self.pr788: Optional[PR788] = None
        self._task_thread: Optional[QtCore.QThread] = None
        self._task_worker: Optional[TaskWorker] = None
        self._after_task: Optional[Callable[[object], None]] = None
        self._settings = QtCore.QSettings("ClassicColour", "PR788UI")
        self._current_counter_value = 0
        self._current_preview_path: Optional[str] = None

        self._build_ui()
        self._resize_for_screen()
        self._load_settings()
        self._restore_splitter_states()
        self.refresh_ports()
        self.update_counter_state()
        self.update_filename_preview()
        self.refresh_project_tree()
        self._start_port_timer()

    def _build_ui(self) -> None:
        control_panel = self._build_control_panel()
        preview_panel = self._build_preview_panel()
        history_panel = self._build_history_panel()

        self.root_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.root_splitter.setProperty("surface", True)
        self.root_splitter.setHandleWidth(4)
        self.root_splitter.setChildrenCollapsible(False)
        self.root_splitter.setContentsMargins(12, 12, 12, 12)
        self.root_splitter.addWidget(control_panel)
        self.root_splitter.addWidget(preview_panel)
        self.root_splitter.addWidget(history_panel)
        self.root_splitter.setStretchFactor(0, 0)
        self.root_splitter.setStretchFactor(1, 1)
        self.root_splitter.setStretchFactor(2, 0)
        self.setCentralWidget(self.root_splitter)

    def _resize_for_screen(self) -> None:
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            self.resize(1680, 920)
            return

        available = screen.availableGeometry()
        width = min(1680, int(available.width() * 0.92))
        height = min(920, int(available.height() * 0.9))
        self.resize(width, height)

    def _build_control_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setProperty("card", True)
        frame.setProperty("sidebar", True)
        frame.setMinimumWidth(300)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("Capture Console")
        title.setProperty("title", True)
        subtitle = QtWidgets.QLabel("Serial control, file naming, and one-tap acquisition for field use.")
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)
        attribution = QtWidgets.QLabel("Developed by 北京电影学院智能影像工程学院")
        attribution.setProperty("attribution", True)
        attribution.setWordWrap(True)
        attribution.setAlignment(QtCore.Qt.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._build_serial_section())
        layout.addWidget(self._build_output_section())
        layout.addWidget(self._build_counter_section())
        layout.addWidget(self._build_action_section())
        layout.addWidget(self._build_analysis_section())
        layout.addStretch(1)
        layout.addWidget(attribution)
        return frame

    def _build_serial_section(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setProperty("card", True)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        label = QtWidgets.QLabel("Connection")
        label.setProperty("section", True)
        layout.addWidget(label)

        port_row = QtWidgets.QHBoxLayout()
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.currentIndexChanged.connect(self.update_filename_preview)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.setProperty("secondary", True)
        self.refresh_button.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_button)

        status_row = QtWidgets.QHBoxLayout()
        self.status_dot = QtWidgets.QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setStyleSheet("border-radius: 4px; background: #8a5d3b;")
        self.status_label = QtWidgets.QLabel("Disconnected")
        self.status_label.setProperty("status", "disconnected")
        self.status_label.setProperty("chip", True)
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)

        button_row = QtWidgets.QHBoxLayout()
        self.connect_button = QtWidgets.QPushButton("Connect PR788")
        self.connect_button.clicked.connect(self.handle_connect)
        self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        self.disconnect_button.setProperty("danger", True)
        self.disconnect_button.clicked.connect(self.handle_disconnect)
        self.disconnect_button.setEnabled(False)
        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.disconnect_button)

        hint_label = QtWidgets.QLabel("Actual success should be confirmed on the PR788 screen: REMOTE MODE.")
        hint_label.setProperty("muted", True)
        hint_label.setWordWrap(True)

        layout.addLayout(port_row)
        layout.addLayout(status_row)
        layout.addLayout(button_row)
        layout.addWidget(hint_label)
        return box

    def _build_output_section(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setProperty("card", True)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Output And Naming")
        title.setProperty("section", True)
        layout.addWidget(title)

        output_label = QtWidgets.QLabel("Project Folder")
        output_label.setProperty("fieldLabel", True)
        layout.addWidget(output_label)

        dir_row = QtWidgets.QHBoxLayout()
        self.output_dir_edit = QtWidgets.QLineEdit()
        self.output_dir_edit.setPlaceholderText("Choose a project folder")
        self.output_dir_edit.textChanged.connect(self.update_filename_preview)
        self.output_dir_edit.textChanged.connect(self.refresh_project_tree)
        browse_button = QtWidgets.QPushButton("Browse")
        browse_button.setProperty("secondary", True)
        browse_button.clicked.connect(self.choose_output_dir)
        dir_row.addWidget(self.output_dir_edit, 1)
        dir_row.addWidget(browse_button)

        self.template_edit = QtWidgets.QLineEdit()
        self.template_edit.setPlaceholderText("{counter}_{timestamp}")
        self.template_edit.textChanged.connect(self.update_filename_preview)

        template_label = QtWidgets.QLabel("Filename Template")
        template_label.setProperty("fieldLabel", True)
        template_hint = QtWidgets.QLabel(
            "Keep it simple. Use / in the template to create subfolders, "
            "e.g. {date}/{counter}_{timestamp}."
        )
        template_hint.setProperty("muted", True)
        template_hint.setWordWrap(True)

        token_wrap = QtWidgets.QGridLayout()
        token_wrap.setHorizontalSpacing(4)
        token_wrap.setVerticalSpacing(7)
        tokens = [
            ("+counter", "{counter}"),
            ("+timestamp", "{timestamp}"),
            ("+date", "{date}"),
            ("+slash", "/"),
        ]
        for index, (label, token) in enumerate(tokens):
            button = QtWidgets.QPushButton(label)
            button.setProperty("token", True)
            button.clicked.connect(lambda _checked=False, value=token: self.insert_template_token(value))
            token_wrap.addWidget(button, index // 3, index % 3)

        self.filename_preview_label = QtWidgets.QLabel("--")
        self.filename_preview_label.setProperty("previewName", True)
        self.filename_preview_label.setWordWrap(True)
        self.path_preview_label = QtWidgets.QLabel("--")
        self.path_preview_label.setProperty("muted", True)
        self.path_preview_label.setWordWrap(True)

        layout.addLayout(dir_row)
        layout.addWidget(template_label)
        layout.addWidget(self.template_edit)
        layout.addWidget(template_hint)
        layout.addLayout(token_wrap)
        preview_label = QtWidgets.QLabel("Resolved Filename")
        preview_label.setProperty("fieldLabel", True)
        layout.addWidget(preview_label)
        layout.addWidget(self.filename_preview_label)
        layout.addWidget(self.path_preview_label)
        return box

    def _build_counter_section(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setProperty("card", True)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Auto Counter")
        title.setProperty("section", True)
        layout.addWidget(title)

        self.counter_enabled_check = QtWidgets.QCheckBox("Enable auto counter")
        self.counter_enabled_check.toggled.connect(self.update_counter_state)
        self.counter_enabled_check.toggled.connect(self.update_filename_preview)

        start_row = QtWidgets.QHBoxLayout()
        start_row.setSpacing(8)
        self.counter_start_spin = QtWidgets.QSpinBox()
        self.counter_start_spin.setRange(0, 100000000)
        self.counter_start_spin.valueChanged.connect(self.handle_counter_start_changed)
        self.step_spin = QtWidgets.QSpinBox()
        self.step_spin.setRange(1, 100000)
        self.step_spin.setValue(10)
        self.step_spin.valueChanged.connect(self.update_counter_state)
        self.step_spin.valueChanged.connect(self.update_filename_preview)
        start_row.addWidget(QtWidgets.QLabel("Start"))
        start_row.addWidget(self.counter_start_spin)
        start_row.addWidget(QtWidgets.QLabel("Step"))
        start_row.addWidget(self.step_spin)

        current_row = QtWidgets.QHBoxLayout()
        current_row.setSpacing(8)
        self.current_counter_spin = QtWidgets.QSpinBox()
        self.current_counter_spin.setRange(0, 100000000)
        self.current_counter_spin.valueChanged.connect(self.handle_current_counter_changed)
        self.next_counter_label = QtWidgets.QLabel("Next: --")
        self.next_counter_label.setProperty("muted", True)
        reset_button = QtWidgets.QPushButton("Reset To Start")
        reset_button.setProperty("secondary", True)
        reset_button.clicked.connect(self.reset_counter_to_start)
        current_row.addWidget(QtWidgets.QLabel("Current"))
        current_row.addWidget(self.current_counter_spin)
        current_row.addWidget(reset_button)

        self.counter_value_label = QtWidgets.QLabel("Current Counter: --")
        self.counter_value_label.setProperty("muted", True)

        layout.addWidget(self.counter_enabled_check)
        layout.addLayout(start_row)
        layout.addLayout(current_row)
        layout.addWidget(self.counter_value_label)
        layout.addWidget(self.next_counter_label)
        return box

    def _build_action_section(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setProperty("card", True)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Measurement")
        title.setProperty("section", True)
        layout.addWidget(title)

        self.measure_button = QtWidgets.QPushButton("Capture Measurement")
        self.measure_button.setProperty("primaryAction", True)
        self.measure_button.clicked.connect(self.handle_measure)
        self.measure_button.setMinimumHeight(28)
        layout.addWidget(self.measure_button)
        return box

    def _build_analysis_section(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setProperty("card", True)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Data Analysis（开发中）")
        title.setProperty("section", True)
        layout.addWidget(title)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(6)

        self.compare_button = QtWidgets.QPushButton("Compare SPDs")
        self.compare_button.setMinimumHeight(26)
        self.compare_button.clicked.connect(lambda _=False: self._open_analysis_dialog(SPDComparisonDialog))

        self.ratio_button = QtWidgets.QPushButton("Spectral Ratio")
        self.ratio_button.setMinimumHeight(26)
        self.ratio_button.clicked.connect(lambda _=False: self._open_analysis_dialog(SpectralRatioDialog))

        self.gamut_button = QtWidgets.QPushButton("Gamut Coverage")
        self.gamut_button.setMinimumHeight(26)
        self.gamut_button.clicked.connect(lambda _=False: self._open_analysis_dialog(GamutDialog))

        self.cri_button = QtWidgets.QPushButton("CRI / R-values")
        self.cri_button.setMinimumHeight(26)
        self.cri_button.clicked.connect(lambda _=False: self._open_analysis_dialog(CRIDialog))

        grid.addWidget(self.compare_button, 0, 0)
        grid.addWidget(self.ratio_button, 0, 1)
        grid.addWidget(self.gamut_button, 1, 0)
        grid.addWidget(self.cri_button, 1, 1)
        layout.addLayout(grid)

        hint = QtWidgets.QLabel("Offline processing of the CSVs in the output folder.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return box

    def _open_analysis_dialog(self, dialog_cls: type) -> None:
        csv_dir = self.output_dir_edit.text().strip()
        if not csv_dir:
            QtWidgets.QMessageBox.warning(
                self,
                "Data Analysis",
                "Choose an output folder first — the history CSVs are read from it.",
            )
            self.append_log("Analysis: no output folder set, dialog not opened.")
            return
        self.append_log(f"Opening {dialog_cls.__name__} …")
        dialog = dialog_cls(csv_dir=csv_dir, parent=self)
        dialog.exec_()

    def _build_preview_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setProperty("card", True)
        frame.setProperty("mainpanel", True)
        frame.setMinimumWidth(380)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("Measurement Snapshot")
        title.setProperty("title", True)

        summary = QtWidgets.QFrame()
        summary.setProperty("card", True)
        summary.setProperty("hero", True)
        summary_layout = QtWidgets.QHBoxLayout(summary)
        summary_layout.setContentsMargins(6, 5, 6, 5)
        summary_layout.setSpacing(8)

        summary_text_layout = QtWidgets.QVBoxLayout()
        summary_text_layout.setContentsMargins(0, 0, 0, 0)
        summary_text_layout.setSpacing(6)
        self.saved_name_label = QtWidgets.QLabel("File: --")
        self.saved_name_label.setProperty("savedName", True)
        self.saved_path_label = QtWidgets.QLabel("Path: --")
        self.saved_path_label.setProperty("muted", True)
        self.saved_path_label.setWordWrap(True)
        summary_text_layout.addWidget(self.saved_name_label)
        summary_text_layout.addWidget(self.saved_path_label)

        self.spd_plot = SPDPlotWidget()
        self.spd_plot.setMinimumWidth(260)
        self.chromaticity = ChromaticityDiagramWidget()
        self.chromaticity.setMinimumWidth(260)
        plots_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        plots_splitter.setHandleWidth(4)
        plots_splitter.setChildrenCollapsible(False)
        plots_splitter.addWidget(self.spd_plot)
        plots_splitter.addWidget(self.chromaticity)
        plots_splitter.setStretchFactor(0, 3)
        plots_splitter.setStretchFactor(1, 2)
        self._plots_splitter = plots_splitter

        self.color_swatch = ColorSwatchWidget()
        self.color_swatch.setFixedWidth(88)

        summary_layout.addLayout(summary_text_layout, 1)
        summary_layout.addWidget(self.color_swatch, 0, QtCore.Qt.AlignTop)

        cards_grid = QtWidgets.QGridLayout()
        cards_grid.setHorizontalSpacing(5)
        cards_grid.setVerticalSpacing(5)
        self.metric_cards = {
            "xy": MetricCard("CIE 1931 x y", compact=True),
            "xyz": MetricCard("CIE XYZ", compact=True),
            "uv": MetricCard("CIE 1976 u'v'", compact=True),
            "cct": MetricCard("CCT (Ohno 2013)", compact=True),
            "nit": MetricCard("Luminance", compact=True),
            "tint": MetricCard("Tint (Duv, Ohno 2013)", compact=True),
        }
        positions = [
            ("xy", 0, 0),
            ("uv", 0, 1),
            ("xyz", 0, 2),
            ("cct", 1, 0),
            ("nit", 1, 1),
            ("tint", 1, 2),
        ]
        for key, row, col in positions:
            cards_grid.addWidget(self.metric_cards[key], row, col)

        log_label = QtWidgets.QLabel("Session Log")
        log_label.setProperty("section", True)
        self.log_edit = QtWidgets.QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setProperty("console", True)

        top_section = QtWidgets.QWidget()
        top_layout = QtWidgets.QVBoxLayout(top_section)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        top_layout.addWidget(summary)
        top_layout.addLayout(cards_grid)
        top_section.setMinimumHeight(128)

        plots_splitter.setMinimumHeight(230)

        log_section = QtWidgets.QWidget()
        log_layout = QtWidgets.QVBoxLayout(log_section)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_edit, 1)
        log_section.setMinimumHeight(96)

        self._center_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self._center_splitter.setChildrenCollapsible(False)
        self._center_splitter.addWidget(top_section)
        self._center_splitter.addWidget(plots_splitter)
        self._center_splitter.addWidget(log_section)
        self._center_splitter.setStretchFactor(0, 0)
        self._center_splitter.setStretchFactor(1, 1)
        self._center_splitter.setStretchFactor(2, 1)

        layout.addWidget(title)
        layout.addWidget(self._center_splitter, 1)
        return frame

    def _build_history_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setProperty("card", True)
        frame.setProperty("mainpanel", True)
        frame.setMinimumWidth(210)
        frame.setMaximumWidth(420)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(8)

        history_label = QtWidgets.QLabel("Project Folder")
        history_label.setProperty("title", True)

        self.project_path_label = QtWidgets.QLabel("--")
        self.project_path_label.setProperty("muted", True)
        self.project_path_label.setWordWrap(True)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(6)
        self.history_open_folder_button = QtWidgets.QPushButton("Open Folder")
        self.history_open_folder_button.setProperty("secondary", True)
        self.history_open_folder_button.clicked.connect(self.choose_output_dir)
        self.history_new_folder_button = QtWidgets.QPushButton("New Folder")
        self.history_new_folder_button.setProperty("secondary", True)
        self.history_new_folder_button.clicked.connect(self.create_project_folder)
        self.history_refresh_button = QtWidgets.QPushButton("Refresh")
        self.history_refresh_button.setProperty("secondary", True)
        self.history_refresh_button.clicked.connect(self.refresh_project_tree)
        self.history_open_button = QtWidgets.QPushButton("Open CSV")
        self.history_open_button.setProperty("secondary", True)
        self.history_open_button.clicked.connect(self.choose_history_csv)
        button_row.addWidget(self.history_open_folder_button)
        button_row.addWidget(self.history_new_folder_button)
        button_row.addWidget(self.history_refresh_button)
        button_row.addWidget(self.history_open_button)

        self.history_tree = QtWidgets.QTreeWidget()
        self.history_tree.setHeaderHidden(True)
        self.history_tree.setProperty("historyList", True)
        self.history_tree.setMinimumHeight(96)
        self.history_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.history_tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        self.history_tree.itemClicked.connect(self.handle_history_item_activated)

        layout.addWidget(history_label)
        layout.addWidget(self.project_path_label)
        layout.addLayout(button_row)
        layout.addWidget(self.history_tree, 1)
        return frame

    def _start_port_timer(self) -> None:
        self.port_timer = QtCore.QTimer(self)
        self.port_timer.setInterval(3000)
        self.port_timer.timeout.connect(self._auto_refresh_ports)
        self.port_timer.start()

    def _auto_refresh_ports(self) -> None:
        if self._task_thread is None and self.pr788 is None:
            self.refresh_ports()

    def insert_template_token(self, token: str) -> None:
        self.template_edit.insert(token)
        self.update_filename_preview()

    def choose_output_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose Project Folder",
            self.output_dir_edit.text() or str(Path.cwd()),
        )
        if directory:
            self.output_dir_edit.setText(directory)

    def choose_history_csv(self) -> None:
        start_dir = self.output_dir_edit.text().strip() or str(Path.cwd())
        csv_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Measurement CSV",
            start_dir,
            "CSV Files (*.csv)",
        )
        if not csv_path:
            return
        self.load_history_csv(csv_path)

    def refresh_ports(self) -> None:
        ports = list_serial_ports()
        current_device = self.port_combo.currentData()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for port_info in ports:
            self.port_combo.addItem(port_info.label, port_info.device)
        self.port_combo.blockSignals(False)

        if current_device:
            index = self.port_combo.findData(current_device)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

        if self.port_combo.count() == 0:
            self.port_combo.addItem("No serial ports found", "")

        self.update_filename_preview()

    def refresh_project_tree(self) -> None:
        output_dir = self.output_dir_edit.text().strip()
        root = Path(output_dir) if output_dir else None
        items = list_history_csv_files(output_dir)
        self.project_path_label.setText(output_dir or "--")

        # directories shown in the tree: every folder on disk (hidden and junk
        # folders pruned), plus any folder implied by a CSV relative path
        directory_names: set = set()
        if root is not None and root.exists():
            for entry in root.rglob("*"):
                if not entry.is_dir():
                    continue
                parts = entry.relative_to(root).parts
                if any(part.startswith(".") or part in NOISY_DIR_NAMES for part in parts):
                    continue
                directory_names.add(entry.relative_to(root).as_posix())

        files_by_dir: Dict[str, List[HistoryCsvItem]] = {}
        for item in items:
            parts = item.name.split("/")
            if any(part.startswith(".") or part in NOISY_DIR_NAMES for part in parts[:-1]):
                continue
            rel_dir = "/".join(parts[:-1])
            for index in range(1, len(parts)):
                directory_names.add("/".join(parts[:index]))
            files_by_dir.setdefault(rel_dir, []).append(item)

        folder_icon = self.style().standardIcon(QtWidgets.QStyle.SP_DirIcon)
        file_icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileIcon)

        self.history_tree.blockSignals(True)
        self.history_tree.clear()
        folder_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}

        for rel_dir in sorted(directory_names, key=lambda name: (name.count("/"), name)):
            parent_key, _, part = rel_dir.rpartition("/")
            folder_item = QtWidgets.QTreeWidgetItem([part])
            folder_item.setIcon(0, folder_icon)
            folder_item.setData(0, QtCore.Qt.UserRole, str(root / rel_dir))
            folder_item.setData(0, QtCore.Qt.UserRole + 1, "dir")
            parent = folder_items.get(parent_key)
            if parent is None:
                self.history_tree.addTopLevelItem(folder_item)
            else:
                parent.addChild(folder_item)
            folder_items[rel_dir] = folder_item

        for rel_dir in sorted(files_by_dir):
            parent = folder_items.get(rel_dir)
            for item in sorted(files_by_dir[rel_dir], key=lambda entry: entry.name):
                parts = item.name.split("/")
                leaf_item = QtWidgets.QTreeWidgetItem([parts[-1]])
                leaf_item.setIcon(0, file_icon)
                leaf_item.setData(0, QtCore.Qt.UserRole, item.path)
                leaf_item.setData(0, QtCore.Qt.UserRole + 1, "file")
                modified = QtCore.QDateTime.fromSecsSinceEpoch(int(item.modified_timestamp)).toString(
                    "yyyy-MM-dd HH:mm:ss"
                )
                leaf_item.setToolTip(0, f"{item.path}\nModified: {modified}")
                if parent is None:
                    self.history_tree.addTopLevelItem(leaf_item)
                else:
                    parent.addChild(leaf_item)

        # Expansion only sticks once items are attached to the tree.
        for folder_item in folder_items.values():
            folder_item.setExpanded(True)

        if self.history_tree.topLevelItemCount() == 0:
            placeholder = QtWidgets.QTreeWidgetItem(["No CSV files in this folder"])
            placeholder.setFlags(QtCore.Qt.NoItemFlags)
            self.history_tree.addTopLevelItem(placeholder)
        self.history_tree.blockSignals(False)

        if self._current_preview_path:
            self._select_history_path(self._current_preview_path)

    def create_project_folder(self) -> None:
        root = self.output_dir_edit.text().strip()
        if not root:
            QtWidgets.QMessageBox.warning(
                self, "Missing Project Folder", "Choose a project folder first."
            )
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Folder", "Folder name (inside the project folder):"
        )
        if not ok:
            return
        safe_name = sanitize_filename_part(name)
        if not safe_name:
            QtWidgets.QMessageBox.warning(
                self, "Invalid Folder Name", "Folder name is empty after cleanup."
            )
            return
        target = Path(root) / safe_name
        try:
            target.mkdir(exist_ok=False)
        except FileExistsError:
            QtWidgets.QMessageBox.warning(
                self, "Folder Exists", f"'{safe_name}' already exists in the project folder."
            )
            return
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Create Folder Failed", str(exc))
            return
        self.append_log(f"Created folder {target}.")
        self.refresh_project_tree()

    def _show_tree_context_menu(self, position: QtCore.QPoint) -> None:
        item = self.history_tree.itemAt(position)
        if item is None:
            return
        path = item.data(0, QtCore.Qt.UserRole)
        if not path:
            return
        is_dir = item.data(0, QtCore.Qt.UserRole + 1) == "dir"
        menu = QtWidgets.QMenu(self)
        open_action = menu.addAction("Open in Explorer")
        copy_action = menu.addAction("Copy Path")
        chosen = menu.exec_(self.history_tree.viewport().mapToGlobal(position))
        if chosen == open_action:
            if is_dir:
                subprocess.Popen(["explorer", str(Path(path))])
            else:
                subprocess.Popen(["explorer", f"/select,\"{path}\""])
        elif chosen == copy_action:
            QtWidgets.QApplication.clipboard().setText(str(Path(path)))

    def _select_history_path(self, csv_path: str) -> None:
        normalized_target = str(Path(csv_path))

        def find(node: QtWidgets.QTreeWidgetItem) -> Optional[QtWidgets.QTreeWidgetItem]:
            for index in range(node.childCount()):
                child = node.child(index)
                item_path = child.data(0, QtCore.Qt.UserRole)
                if item_path and str(Path(item_path)) == normalized_target:
                    return child
                found = find(child)
                if found is not None:
                    return found
            return None

        selected = find(self.history_tree.invisibleRootItem())
        if selected is not None:
            ancestor = selected.parent()
            while ancestor is not None:
                ancestor.setExpanded(True)
                ancestor = ancestor.parent()
            self.history_tree.setCurrentItem(selected)
            self.history_tree.scrollToItem(selected)

    def handle_history_item_activated(self, item: QtWidgets.QTreeWidgetItem) -> None:
        if item.data(0, QtCore.Qt.UserRole + 1) != "file":
            return
        csv_path = item.data(0, QtCore.Qt.UserRole)
        if not csv_path:
            return
        self.load_history_csv(csv_path)

    def load_history_csv(self, csv_path: str) -> None:
        def load_task():
            return load_preview_from_csv(csv_path)

        self._start_task("Loading history CSV...", load_task, self._after_load_history)

    def update_counter_state(self) -> None:
        enabled = self.counter_enabled_check.isChecked()
        self.counter_start_spin.setEnabled(enabled)
        self.current_counter_spin.setEnabled(enabled)
        counter_value = str(self.current_counter_spin.value()) if enabled else "--"
        self.counter_value_label.setText(f"Current Counter: {counter_value}")
        if enabled:
            self.next_counter_label.setText(f"Next: {self.current_counter_spin.value() + self.step_spin.value()}")
        else:
            self.next_counter_label.setText("Next: --")

    def handle_counter_start_changed(self, value: int) -> None:
        if not self.counter_enabled_check.isChecked():
            return
        if self.current_counter_spin.value() == self._current_counter_value:
            self.current_counter_spin.setValue(value)
        self.update_counter_state()
        self.update_filename_preview()

    def handle_current_counter_changed(self, value: int) -> None:
        self._current_counter_value = value
        self.update_counter_state()
        self.update_filename_preview()

    def reset_counter_to_start(self) -> None:
        self.current_counter_spin.setValue(self.counter_start_spin.value())

    def build_filename_preview(self) -> tuple[str, str]:
        output_dir = self.output_dir_edit.text().strip()
        template = self.template_edit.text().strip() or "{counter}_{timestamp}"
        counter_value = self.current_counter_spin.value() if self.counter_enabled_check.isChecked() else None

        variables = build_template_variables(
            counter=counter_value,
        )
        file_name = render_filename_template(template, variables)
        full_path = str(Path(output_dir) / file_name) if output_dir else file_name
        return file_name, full_path

    def update_filename_preview(self) -> None:
        try:
            file_name, full_path = self.build_filename_preview()
        except Exception as exc:
            self.filename_preview_label.setText(f"Template error: {exc}")
            self.path_preview_label.setText("--")
            return

        self.filename_preview_label.setText(file_name)
        self.path_preview_label.setText(full_path)

    def handle_connect(self) -> None:
        port_name = self.port_combo.currentData()
        if not port_name:
            QtWidgets.QMessageBox.warning(self, "No Port", "Select a valid serial port first.")
            return

        def connect_task() -> PR788:
            device = PR788(port_name)
            try:
                device.remote_start()
            except Exception:
                device.close_serial()
                raise
            return device

        self._start_task("Connecting to PR788...", connect_task, self._after_connect)

    def _after_connect(self, pr788: PR788) -> None:
        self.pr788 = pr788
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self._set_status("Remote Sent", "connected", "#146c5d")
        self.append_log(
            f"Serial opened on {self.port_combo.currentData()} and remote_start was sent. "
            "Please confirm PR788 screen has entered REMOTE MODE."
        )

    def handle_disconnect(self) -> None:
        if self.pr788 is None:
            return

        current = self.pr788

        def disconnect_task() -> None:
            try:
                current.remote_terminate()
            finally:
                current.close_serial()

        self._start_task("Disconnecting PR788...", disconnect_task, self._after_disconnect)

    def _after_disconnect(self, _result: object) -> None:
        self.pr788 = None
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self._set_status("Disconnected", "disconnected", "#8a5d3b")
        self.append_log("PR788 disconnected.")

    def handle_measure(self) -> None:
        if self.pr788 is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Not Ready",
                "Send remote command first, then confirm PR788 screen has entered REMOTE MODE before measuring.",
            )
            return

        output_dir = self.output_dir_edit.text().strip()
        if not output_dir:
            QtWidgets.QMessageBox.warning(self, "Missing Output Folder", "Choose an output folder first.")
            return

        template = self.template_edit.text().strip() or "{counter}_{timestamp}"
        counter_value = self.current_counter_spin.value() if self.counter_enabled_check.isChecked() else None
        next_counter_value = (
            self.current_counter_spin.value() + self.step_spin.value()
            if self.counter_enabled_check.isChecked()
            else None
        )

        def measure_task() -> MeasurementRecord:
            return measure_with_template(
                pr788=self.pr788,
                csv_dir=output_dir,
                template=template,
                code="5",
                counter_value=counter_value,
                next_counter_value=next_counter_value,
            )

        self._start_task("Measuring and saving...", measure_task, self._after_measure)

    def _after_measure(self, record: MeasurementRecord) -> None:
        preview = record.preview
        saved_path = preview.csv_path or record.csv_path
        self.display_preview(preview, saved_path)
        self.append_log(f"Saved measurement to {saved_path}.")
        if self.counter_enabled_check.isChecked() and record.next_sequence_number >= 0:
            self.current_counter_spin.setValue(record.next_sequence_number)
        self.update_counter_state()
        self.update_filename_preview()
        self.refresh_project_tree()

    def _after_load_history(self, preview) -> None:
        saved_path = preview.csv_path or ""
        self.display_preview(preview, saved_path)
        self.append_log(f"Loaded history CSV {saved_path}.")

    def display_preview(self, preview, saved_path: str) -> None:
        self._current_preview_path = saved_path or None
        self.saved_name_label.setText(f"File: {Path(saved_path).name if saved_path else '--'}")
        self.saved_path_label.setText(f"Path: {saved_path or '--'}")
        self.metric_cards["xy"].set_value(f"{preview.x:.6f}, {preview.y:.6f}")
        self.metric_cards["uv"].set_value(f"{preview.u_prime:.6f}, {preview.v_prime:.6f}")
        self.metric_cards["xyz"].set_value(f"{preview.X:.4f}, {preview.Y:.4f}, {preview.Z:.4f}")
        self.metric_cards["cct"].set_value(f"{preview.cct:.2f} K")
        self.metric_cards["nit"].set_value(f"{preview.luminance_nits:.4f} nit")
        self.metric_cards["tint"].set_value(f"{preview.tint_duv:+.6f}")
        self.spd_plot.set_rows(preview.spectral_rows)
        self.chromaticity.set_point(preview.x, preview.y, preview.u_prime, preview.v_prime)
        self.color_swatch.set_color(preview.srgb_8bit)
        if saved_path:
            self._select_history_path(saved_path)

    def _start_task(
        self,
        busy_text: str,
        func: Callable[[], object],
        after_task: Callable[[object], None],
    ) -> None:
        if self._task_thread is not None:
            return

        self._after_task = after_task
        self._set_busy(True, busy_text)
        self._task_thread = QtCore.QThread(self)
        self._task_worker = TaskWorker(func)
        self._task_worker.moveToThread(self._task_thread)
        self._task_thread.started.connect(self._task_worker.run)
        self._task_worker.finished.connect(self._on_task_finished)
        self._task_worker.failed.connect(self._on_task_failed)
        self._task_worker.finished.connect(self._task_thread.quit)
        self._task_worker.failed.connect(self._task_thread.quit)
        self._task_thread.finished.connect(self._cleanup_task)
        self._task_thread.start()

    def _on_task_finished(self, result: object) -> None:
        if self._after_task is not None:
            self._after_task(result)
        if self.pr788 is None:
            self._set_status("Disconnected", "disconnected", "#8a5d3b")
        else:
            self._set_status("Remote Sent", "connected", "#146c5d")

    def _on_task_failed(self, message: str) -> None:
        self.append_log(f"Error: {message}")
        QtWidgets.QMessageBox.critical(self, "Operation Failed", message)
        if self.pr788 is None:
            self._set_status("Disconnected", "disconnected", "#8a5d3b")
        else:
            self._set_status("Remote Sent", "connected", "#146c5d")

    def _cleanup_task(self) -> None:
        if self._task_worker is not None:
            self._task_worker.deleteLater()
        if self._task_thread is not None:
            self._task_thread.deleteLater()
        self._task_worker = None
        self._task_thread = None
        self._after_task = None
        self._set_busy(False, "")

    def _set_busy(self, busy: bool, text: str) -> None:
        widgets = [
            self.connect_button,
            self.disconnect_button,
            self.measure_button,
            self.refresh_button,
            self.history_open_folder_button,
            self.history_new_folder_button,
            self.history_refresh_button,
            self.history_open_button,
            self.port_combo,
            self.output_dir_edit,
            self.template_edit,
            self.counter_enabled_check,
            self.counter_start_spin,
            self.current_counter_spin,
            self.step_spin,
            self.history_tree,
            self.compare_button,
            self.ratio_button,
            self.gamut_button,
            self.cri_button,
        ]
        for widget in widgets:
            widget.setEnabled(not busy)

        if busy:
            self._set_status(text, "busy", "#8d5f1d")
        elif self.pr788 is None:
            self.connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(False)
        else:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)

    def _set_status(self, text: str, state: str, color: str) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("status", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_dot.setStyleSheet(f"border-radius: 4px; background: {color};")

    def append_log(self, message: str) -> None:
        timestamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.log_edit.append(f"[{timestamp}] {message}")

    def _load_settings(self) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        default_output = str(base_dir / "output")

        self.output_dir_edit.setText(self._settings.value("output_dir", default_output))
        self.template_edit.setText(self._settings.value("template", "{counter}_{timestamp}"))
        self.counter_enabled_check.setChecked(self._settings.value("counter_enabled", True, type=bool))
        self.counter_start_spin.setValue(self._settings.value("counter_start", 0, type=int))
        self.current_counter_spin.setValue(self._settings.value("counter_current", 0, type=int))
        self.step_spin.setValue(self._settings.value("step", 10, type=int))

    def _restore_splitter_states(self) -> None:
        for key, splitter in (
            ("root_splitter", self.root_splitter),
            ("plots_splitter", self._plots_splitter),
            ("center_splitter", self._center_splitter),
        ):
            state = self._settings.value(key, type=QtCore.QByteArray)
            if state is None:
                continue
            try:
                splitter.restoreState(state)
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        self._settings.setValue("root_splitter", self.root_splitter.saveState())
        self._settings.setValue("plots_splitter", self._plots_splitter.saveState())
        self._settings.setValue("center_splitter", self._center_splitter.saveState())
        self._settings.setValue("output_dir", self.output_dir_edit.text().strip())
        self._settings.setValue("template", self.template_edit.text().strip())
        self._settings.setValue("counter_enabled", self.counter_enabled_check.isChecked())
        self._settings.setValue("counter_start", self.counter_start_spin.value())
        self._settings.setValue("counter_current", self.current_counter_spin.value())
        self._settings.setValue("step", self.step_spin.value())

        if self.pr788 is not None:
            try:
                self.pr788.remote_terminate()
            except Exception:
                pass
            try:
                self.pr788.close_serial()
            except Exception:
                pass

        super().closeEvent(event)
