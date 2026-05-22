from pathlib import Path
from typing import Callable, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from core.PR788_Service import (
    MeasurementRecord,
    build_template_variables,
    load_preview_from_csv,
    list_serial_ports,
    list_history_csv_files,
    measure_with_template,
    render_filename_template,
)
from core.PR788_Utils import PR788


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
    def __init__(self, title: str, value: str = "--", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("metric", True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(5)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setProperty("metricTitle", True)
        self.value_label = QtWidgets.QLabel(value)
        self.value_label.setProperty("metricValue", True)
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
        self.setFixedWidth(100)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.title_label = QtWidgets.QLabel("sRGB Preview")
        self.title_label.setProperty("metricTitle", True)
        self.title_label.setProperty("swatchLabel", True)
        self.title_label.setFixedWidth(62)
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)

        self.swatch = QtWidgets.QFrame()
        self.swatch.setMinimumSize(78, 52)
        self.swatch.setMaximumHeight(58)
        self.swatch.setStyleSheet(
            "background-color: rgb(127, 127, 127); border: 1px solid rgb(67, 71, 77); border-radius: 6px;"
        )

        self.value_label = QtWidgets.QLabel("RGB 127, 127, 127")
        self.value_label.setProperty("metricTitle", True)
        self.value_label.setProperty("swatchLabel", True)
        self.value_label.setFixedWidth(80)
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
        self.setMinimumHeight(230)
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
        title_font = QtGui.QFont("Open Sans", 10, QtGui.QFont.DemiBold)
        label_font = QtGui.QFont("Open Sans", 9)
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
        self.refresh_ports()
        self.update_counter_state()
        self.update_filename_preview()
        self.refresh_history_list()
        self._start_port_timer()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setProperty("surface", True)
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(14)

        control_panel = self._build_control_panel()
        preview_panel = self._build_preview_panel()
        history_panel = self._build_history_panel()

        root.addWidget(control_panel, 0)
        root.addWidget(preview_panel, 1)
        root.addWidget(history_panel, 0)

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
        frame.setMaximumWidth(400)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Capture Console")
        title.setProperty("title", True)
        subtitle = QtWidgets.QLabel("Serial control, file naming, and one-tap acquisition for field use.")
        subtitle.setProperty("muted", True)
        subtitle.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._build_serial_section())
        layout.addWidget(self._build_output_section())
        layout.addWidget(self._build_counter_section())
        layout.addWidget(self._build_action_section())
        layout.addStretch(1)
        return frame

    def _build_serial_section(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setProperty("card", True)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(9)

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
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(9)

        title = QtWidgets.QLabel("Output And Naming")
        title.setProperty("section", True)
        layout.addWidget(title)

        output_label = QtWidgets.QLabel("Output Folder")
        output_label.setProperty("fieldLabel", True)
        layout.addWidget(output_label)

        dir_row = QtWidgets.QHBoxLayout()
        self.output_dir_edit = QtWidgets.QLineEdit()
        self.output_dir_edit.setPlaceholderText("Choose an output folder")
        self.output_dir_edit.textChanged.connect(self.update_filename_preview)
        self.output_dir_edit.textChanged.connect(self.refresh_history_list)
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
        template_hint = QtWidgets.QLabel("Keep it simple. Use only counter and timestamp.")
        template_hint.setProperty("muted", True)

        token_wrap = QtWidgets.QGridLayout()
        token_wrap.setHorizontalSpacing(4)
        token_wrap.setVerticalSpacing(7)
        tokens = [
            ("+counter", "{counter}"),
            ("+timestamp", "{timestamp}"),
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
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(9)

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
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(9)

        title = QtWidgets.QLabel("Measurement")
        title.setProperty("section", True)
        layout.addWidget(title)

        self.measure_button = QtWidgets.QPushButton("Capture Measurement")
        self.measure_button.setProperty("primaryAction", True)
        self.measure_button.clicked.connect(self.handle_measure)
        self.measure_button.setMinimumHeight(32)
        layout.addWidget(self.measure_button)
        return box

    def _build_preview_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setProperty("card", True)
        frame.setProperty("mainpanel", True)
        frame.setMinimumWidth(380)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Measurement Snapshot")
        title.setProperty("title", True)
        subtitle = QtWidgets.QLabel("Fast visual check of the latest spectrum export and key color metrics.")
        subtitle.setProperty("muted", True)

        summary = QtWidgets.QFrame()
        summary.setProperty("card", True)
        summary.setProperty("hero", True)
        summary_layout = QtWidgets.QHBoxLayout(summary)
        summary_layout.setContentsMargins(10, 10, 10, 10)
        summary_layout.setSpacing(10)

        summary_text_layout = QtWidgets.QVBoxLayout()
        summary_text_layout.setContentsMargins(0, 0, 0, 0)
        summary_text_layout.setSpacing(7)
        self.saved_name_label = QtWidgets.QLabel("File: --")
        self.saved_name_label.setProperty("savedName", True)
        self.saved_path_label = QtWidgets.QLabel("Path: --")
        self.saved_path_label.setProperty("muted", True)
        self.saved_path_label.setWordWrap(True)
        summary_text_layout.addWidget(self.saved_name_label)
        summary_text_layout.addWidget(self.saved_path_label)

        self.spd_plot = SPDPlotWidget()
        self.color_swatch = ColorSwatchWidget()
        self.color_swatch.setFixedWidth(96)

        summary_layout.addLayout(summary_text_layout, 1)
        summary_layout.addWidget(self.color_swatch, 0, QtCore.Qt.AlignTop)

        cards_grid = QtWidgets.QGridLayout()
        cards_grid.setHorizontalSpacing(6)
        cards_grid.setVerticalSpacing(10)
        self.metric_cards = {
            "xy": MetricCard("CIE 1931 x y"),
            "xyz": MetricCard("CIE XYZ"),
            "uv": MetricCard("CIE 1976 u'v'"),
            "cct": MetricCard("CCT (Ohno 2013)"),
            "nit": MetricCard("Luminance"),
            "tint": MetricCard("Tint (Duv, Ohno 2013)"),
        }
        positions = [
            ("xy", 0, 0),
            ("uv", 0, 1),
            ("xyz", 1, 0),
            ("cct", 1, 1),
            ("nit", 2, 0),
            ("tint", 2, 1),
        ]
        for key, row, col in positions:
            cards_grid.addWidget(self.metric_cards[key], row, col)

        log_label = QtWidgets.QLabel("Session Log")
        log_label.setProperty("section", True)
        self.log_edit = QtWidgets.QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setProperty("console", True)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(summary)
        layout.addWidget(self.spd_plot)
        layout.addLayout(cards_grid)
        layout.addWidget(log_label)
        layout.addWidget(self.log_edit, 1)
        return frame

    def _build_history_panel(self) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setProperty("card", True)
        frame.setProperty("mainpanel", True)
        frame.setMinimumWidth(210)
        frame.setMaximumWidth(290)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(9)

        history_label = QtWidgets.QLabel("History Measurements")
        history_label.setProperty("title", True)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(7)
        self.history_refresh_button = QtWidgets.QPushButton("Refresh")
        self.history_refresh_button.setProperty("secondary", True)
        self.history_refresh_button.clicked.connect(self.refresh_history_list)
        self.history_open_button = QtWidgets.QPushButton("Open CSV")
        self.history_open_button.setProperty("secondary", True)
        self.history_open_button.clicked.connect(self.choose_history_csv)
        button_row.addWidget(self.history_refresh_button)
        button_row.addWidget(self.history_open_button)

        self.history_list = QtWidgets.QListWidget()
        self.history_list.setProperty("historyList", True)
        self.history_list.setMinimumHeight(110)
        self.history_list.itemActivated.connect(self.handle_history_item_activated)
        self.history_list.itemClicked.connect(self.handle_history_item_activated)

        layout.addWidget(history_label)
        layout.addLayout(button_row)
        layout.addWidget(self.history_list, 1)
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
            "Choose Output Folder",
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

    def refresh_history_list(self) -> None:
        output_dir = self.output_dir_edit.text().strip()
        items = list_history_csv_files(output_dir)

        self.history_list.clear()
        for item in items:
            list_item = QtWidgets.QListWidgetItem(item.name)
            list_item.setData(QtCore.Qt.UserRole, item.path)
            modified = QtCore.QDateTime.fromSecsSinceEpoch(int(item.modified_timestamp)).toString(
                "yyyy-MM-dd HH:mm:ss"
            )
            list_item.setToolTip(f"{item.path}\nModified: {modified}")
            self.history_list.addItem(list_item)

        if not items:
            placeholder = QtWidgets.QListWidgetItem("No CSV history in current output folder")
            placeholder.setFlags(QtCore.Qt.NoItemFlags)
            self.history_list.addItem(placeholder)
            return

        if self._current_preview_path:
            self._select_history_path(self._current_preview_path)

    def _select_history_path(self, csv_path: str) -> None:
        normalized_target = str(Path(csv_path))
        for index in range(self.history_list.count()):
            item = self.history_list.item(index)
            item_path = item.data(QtCore.Qt.UserRole)
            if item_path and str(Path(item_path)) == normalized_target:
                self.history_list.setCurrentItem(item)
                break

    def handle_history_item_activated(self, item: QtWidgets.QListWidgetItem) -> None:
        csv_path = item.data(QtCore.Qt.UserRole)
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
        self.refresh_history_list()

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
            self.history_refresh_button,
            self.history_open_button,
            self.port_combo,
            self.output_dir_edit,
            self.template_edit,
            self.counter_enabled_check,
            self.counter_start_spin,
            self.current_counter_spin,
            self.step_spin,
            self.history_list,
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

    def closeEvent(self, event) -> None:
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
