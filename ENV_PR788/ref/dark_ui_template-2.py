#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dark UI Template - Reusable PyQt5 Dark Theme Interface Template
A professional dark-themed UI template for rapid application development
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QTextEdit, QFrame,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor
import PyQt5.QtCore as QtCore


class DarkUITemplate(QMainWindow):
    """Reusable Dark UI Template Class"""

    def __init__(self):
        super().__init__()
        # Initialize state variables
        self.is_processing = False
        self.selected_option = None
        self.selected_version = "v1"
        self.selected_table_version = "all"

        # Define color schemes for buttons
        self.button_colors = {
            'Primary': (100, 150, 200),       # Blue
            'Secondary': (180, 118, 0),       # Orange
            'Success': (0, 130, 0),           # Green
            'Warning': (135, 135, 45),        # Yellow
            'Danger': (150, 50, 50)           # Red
        }

        # Define button data (text, type)
        self.action_buttons_data = [
            ("按钮1", "Primary"),
            ("按钮2", "Secondary"),
            ("按钮3", "Success"),
            ("按钮4", "Warning"),
            ("按钮5", "Danger")
        ]

        # Initialize UI styles and setup
        self._init_styles()
        self.setup_ui()
        self.setup_styles()

    def _init_styles(self):
        """Initialize common UI styles"""
        self.common_styles = {
            'font_family': "'Open Sans', sans-serif",
            'label_style': "color: rgb(145, 145, 145); font-size: 14px; font-weight: semibold; font-family: 'Open Sans', sans-serif;",
            'button_style': """
                QPushButton {
                    background-color: rgb(40, 40, 46);
                    color: rgb(145, 145, 145);
                    border: 1px solid rgb(100, 100, 100);
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: semibold;
                    font-family: 'Open Sans', sans-serif;
                }
                QPushButton:hover {
                    background-color: rgb(53, 53, 58);
                }
                QPushButton:pressed {
                    background-color: rgb(23, 23, 28);
                }
            """,
            'combobox_style': """
                QComboBox {
                    background-color: rgb(31, 31, 31);
                    color: rgb(145, 145, 145);
                    border: 1px solid rgb(7, 7, 7);
                    border-radius: 3px;
                    padding: 3px 8px;
                    font-size: 12px;
                    font-family: 'Open Sans', sans-serif;
                }
                QComboBox::drop-down {
                    border: none;
                    background: transparent;
                }
                QComboBox::down-arrow {
                    image: none;
                    border: none;
                }
                QComboBox QAbstractItemView {
                    background-color: rgb(31, 31, 31);
                    color: rgb(145, 145, 145);
                    border: 1px solid rgb(7, 7, 7);
                    selection-background-color: rgb(100, 200, 255);
                }
            """,
            'textedit_style': """
                QTextEdit {
                    background-color: rgb(31, 31, 31);
                    color: rgb(145, 145, 145);
                    border: 1px solid rgb(7, 7, 7);
                    border-radius: 3px;
                    padding: 5px;
                    font-size: 12px;
                    font-family: 'Open Sans', sans-serif;
                }
            """
        }

    def setup_ui(self):
        """Setup UI interface"""
        # Main window settings
        self.setWindowTitle("🔧 Dark UI Template")
        self.setMinimumSize(350, 700)
        self.resize(350, 700)
        self.setStyleSheet("background-color: rgb(40, 40, 46);")

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        # Header section
        self.setup_header(main_layout)
        self.add_separator(main_layout)

        # Version selection section
        self.setup_version_selection(main_layout)
        self.add_separator(main_layout)

        # Action buttons section
        self.setup_action_buttons(main_layout)
        self.add_separator(main_layout)

        # Text input section
        self.setup_text_input(main_layout)
        self.add_separator(main_layout)

        # Control buttons section
        self.setup_control_buttons(main_layout)
        self.add_separator(main_layout)

        # Data table section
        self.setup_data_table(main_layout)

    def setup_header(self, layout):
        """Setup header section"""
        title_label = QLabel("Dark UI Template - 深色主题模板")
        title_label.setStyleSheet("color: rgb(255, 255, 255); font-size: 16px; font-weight: regular; font-family: 'Open Sans', sans-serif;")
        title_label.setAlignment(Qt.AlignLeft)
        layout.addWidget(title_label)

    def setup_version_selection(self, layout):
        """Setup version selection"""
        version_label = QLabel("版本选择")
        version_label.setStyleSheet(self.common_styles['label_style'])
        version_label.setFixedHeight(15)
        layout.addWidget(version_label)

        self.version_combo = QComboBox()
        self.version_combo.setFixedSize(80, 25)
        self.version_combo.addItems(["v1", "v2", "v3", "v4", "v5"])
        self.version_combo.setCurrentText(self.selected_version)
        self.version_combo.setStyleSheet(self.common_styles['combobox_style'])
        self.version_combo.currentTextChanged.connect(self.on_version_changed)

        # Add custom arrow
        self._add_combobox_arrow(self.version_combo)
        layout.addWidget(self.version_combo)

    def setup_action_buttons(self, layout):
        """Setup action buttons section"""
        section_label = QLabel("操作按钮")
        section_label.setStyleSheet(self.common_styles['label_style'])
        section_label.setFixedHeight(15)
        layout.addWidget(section_label)

        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)

        # Store button references
        self.action_buttons = {}

        for label, button_type in self.action_buttons_data:
            btn = QPushButton(label)
            btn.setSizePolicy(btn.sizePolicy().Expanding, btn.sizePolicy().Fixed)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _, bt=button_type: self.handle_action(bt))
            button_layout.addWidget(btn)
            self.action_buttons[button_type] = btn

        # Create container widget for buttons
        button_widget = QWidget()
        button_widget.setLayout(button_layout)
        button_widget.setFixedHeight(35)
        layout.addWidget(button_widget)

    def setup_text_input(self, layout):
        """Setup text input section"""
        notes_label = QLabel("文本输入")
        notes_label.setStyleSheet(self.common_styles['label_style'])
        notes_label.setFixedHeight(15)
        layout.addWidget(notes_label)

        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(80)
        self.text_input.setSizePolicy(self.text_input.sizePolicy().Expanding, self.text_input.sizePolicy().Fixed)
        self.text_input.setPlaceholderText("请输入内容...")
        self.text_input.setStyleSheet(self.common_styles['textedit_style'])
        self.text_input.keyPressEvent = self.text_input_key_press_event
        layout.addWidget(self.text_input)

    def setup_control_buttons(self, layout):
        """Setup control buttons"""
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(5)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setFixedHeight(25)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                color: rgb(145, 145, 145);
                font-size: 11px;
                font-style: italic;
            }
        """)
        button_layout.addWidget(self.status_label)

        # Add stretch
        button_layout.addStretch()

        # Cancel button
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(70, 25)
        self.cancel_btn.setStyleSheet(self.common_styles['button_style'])
        self.cancel_btn.clicked.connect(self.cancel_action)
        button_layout.addWidget(self.cancel_btn)

        # Confirm button
        self.confirm_btn = QPushButton("确认")
        self.confirm_btn.setFixedSize(70, 25)
        self.confirm_btn.setStyleSheet(self.common_styles['button_style'])
        self.confirm_btn.clicked.connect(self.confirm_action)
        button_layout.addWidget(self.confirm_btn)

        # Create container widget
        button_widget = QWidget()
        button_widget.setLayout(button_layout)
        button_widget.setFixedHeight(30)
        layout.addWidget(button_widget)

    def setup_data_table(self, layout):
        """Setup data table"""
        table_label = QLabel("数据表格")
        table_label.setStyleSheet(self.common_styles['label_style'])
        table_label.setFixedHeight(15)
        layout.addWidget(table_label)

        # Table controls
        table_controls_layout = QHBoxLayout()
        table_controls_layout.setContentsMargins(0, 0, 0, 0)
        table_controls_layout.setSpacing(5)

        # Table filter combo
        self.table_combo = QComboBox()
        self.table_combo.setFixedSize(80, 25)
        self.table_combo.addItems(["all", "v1", "v2", "v3", "v4", "v5"])
        self.table_combo.setCurrentText(self.selected_table_version)
        self.table_combo.setStyleSheet(self.common_styles['combobox_style'])
        self.table_combo.currentTextChanged.connect(self.on_table_version_changed)

        self._add_combobox_arrow(self.table_combo)
        table_controls_layout.addWidget(self.table_combo)

        # Refresh button
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedSize(60, 25)
        self.refresh_btn.setStyleSheet(self.common_styles['button_style'])
        self.refresh_btn.clicked.connect(self.refresh_table)
        table_controls_layout.addWidget(self.refresh_btn)

        # Add stretch
        table_controls_layout.addStretch()

        # Export button
        self.export_btn = QPushButton("导出")
        self.export_btn.setFixedSize(60, 25)
        self.export_btn.setStyleSheet(self.common_styles['button_style'])
        self.export_btn.clicked.connect(self.export_data)
        table_controls_layout.addWidget(self.export_btn)

        # Create container for controls
        table_controls_widget = QWidget()
        table_controls_widget.setLayout(table_controls_layout)
        table_controls_widget.setFixedHeight(30)
        layout.addWidget(table_controls_widget)

        # Create table
        self.data_table = QTableWidget()
        self.data_table.setMinimumSize(330, 200)
        self.data_table.setSizePolicy(self.data_table.sizePolicy().Expanding, self.data_table.sizePolicy().Expanding)
        self.data_table.setColumnCount(4)
        self.data_table.setHorizontalHeaderLabels(["ID", "名称", "状态", "备注"])
        self.data_table.setEditTriggers(QTableWidget.NoEditTriggers)

        # Set column properties
        header = self.data_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.data_table.setColumnWidth(0, 35)
        self.data_table.setColumnWidth(1, 120)
        self.data_table.setColumnWidth(2, 60)

        # Apply dark table styling
        self.data_table.setStyleSheet("""
            QTableWidget {
                background-color: rgb(40, 40, 46);
                color: rgb(145, 145, 145);
                border: 1px solid rgb(7, 7, 7);
                border-radius: 3px;
                gridline-color: transparent;
                font-size: 11px;
                font-family: 'Helvetica', 'Arial', sans-serif;
                alternate-background-color: rgb(36, 36, 42);
            }
            QTableWidget::item {
                padding: 2px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: rgb(40, 40, 46);
                color: rgb(255, 255, 255);
                border: none;
                outline: none;
            }
            QTableWidget::item:focus {
                background-color: rgb(40, 40, 46);
                color: rgb(255, 255, 255);
                border: none;
                outline: none;
            }
            QHeaderView::section {
                background-color: rgb(33, 33, 38);
                color: rgb(145, 145, 145);
                border-left: 1px solid rgb(67, 71, 77);
                border-right: none;
                border-top: none;
                border-bottom: 1px solid rgb(9, 9, 9);
                padding: 2px;
                font-size: 11px;
                font-weight: normal;
                font-family: 'Helvetica', 'Arial', sans-serif;
            }
            QHeaderView::section:hover {
                background-color: rgb(33, 33, 38);
                color: rgb(145, 145, 145);
                font-weight: normal;
            }
            QHeaderView::section:pressed {
                background-color: rgb(33, 33, 38);
                color: rgb(145, 145, 145);
                font-weight: normal;
            }
            QHeaderView::section:first {
                border-left: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgb(90, 95, 102);
                min-height: 20px;
                border-radius: 4px;
                margin: 0px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgb(110, 115, 122);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                border: none;
                width: 0px;
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        # Set table properties
        self.data_table.setAlternatingRowColors(True)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.setShowGrid(False)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.data_table.setSelectionMode(QTableWidget.SingleSelection)

        # Set fixed row height
        self.data_table.verticalHeader().setDefaultSectionSize(22)
        self.data_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        # Connect double click event
        self.data_table.itemDoubleClicked.connect(self.on_table_double_click)

        layout.addWidget(self.data_table)

        # Initialize table with sample data
        self.refresh_table()

    # Event handlers
    def on_version_changed(self, text):
        """Handle version selection change"""
        self.selected_version = text
        self.show_status(f"版本已切换到: {text}", True)

    def on_table_version_changed(self, text):
        """Handle table version selection change"""
        self.selected_table_version = text
        self.refresh_table()

    def on_table_double_click(self, item):
        """Handle table double click event"""
        row = item.row()
        name_item = self.data_table.item(row, 1)
        if name_item:
            self.show_status(f"双击了: {name_item.text()}", True)

    def text_input_key_press_event(self, event):
        """Handle key press events in text input"""
        if event.key() == QtCore.Qt.Key_Return or event.key() == QtCore.Qt.Key_Enter:
            if event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
                QTextEdit.keyPressEvent(self.text_input, event)
            else:
                self.confirm_action()
        else:
            QTextEdit.keyPressEvent(self.text_input, event)

    def handle_action(self, action_type):
        """Handle action button selection"""
        self.selected_option = action_type
        self.update_button_states()
        self.show_status(f"选择了: {action_type}", True)

    def update_button_states(self):
        """Update visual states of action buttons"""
        for action_type, color in self.button_colors.items():
            if action_type in self.action_buttons:
                btn = self.action_buttons[action_type]
                is_selected = (self.selected_option == action_type)
                self.apply_button_style(btn, color, is_selected)

    # Table and data operations
    def refresh_table(self):
        """Refresh table with sample data"""
        try:
            # Sample data
            sample_data = [
                ("1", "项目A", "完成", "备注1"),
                ("2", "项目B", "进行中", "备注2"),
                ("3", "项目C", "待开始", "备注3"),
            ]

            # Filter by version if not 'all'
            if self.selected_table_version != 'all':
                # Add version-specific filtering logic here
                pass

            # Set table size
            row_count = max(12, len(sample_data))
            self.data_table.setRowCount(row_count)

            # Populate data
            for row, (id_val, name, status, note) in enumerate(sample_data):
                self.data_table.setItem(row, 0, QTableWidgetItem(id_val))
                self.data_table.setItem(row, 1, QTableWidgetItem(name))
                self.data_table.setItem(row, 2, QTableWidgetItem(status))
                self.data_table.setItem(row, 3, QTableWidgetItem(note))

            # Fill empty rows
            for row in range(len(sample_data), row_count):
                for col in range(4):
                    self.data_table.setItem(row, col, QTableWidgetItem(""))

            self.data_table.update()
            self.show_status("表格已刷新", True)

        except Exception as e:
            self.show_status("刷新失败", False)

    def export_data(self):
        """Export table data"""
        self.show_status("数据已导出", True)

    # Action methods
    def confirm_action(self):
        """Handle confirm button click"""
        text_content = self.text_input.toPlainText()
        if self.selected_option and text_content:
            self.show_status(f"执行操作: {self.selected_option}", True)
            self.text_input.clear()
            self.selected_option = None
            self.update_button_states()
        else:
            self.show_status("请选择操作和输入内容", False)

    def cancel_action(self):
        """Handle cancel button click"""
        self.text_input.clear()
        self.selected_option = None
        self.update_button_states()
        self.show_status("已取消", True)

    # UI helper methods
    def show_status(self, message, is_success=True):
        """Show status message with appropriate color"""
        if is_success:
            color = "rgb(100, 200, 100)"  # Green for success
        else:
            color = "rgb(200, 100, 100)"  # Red for error

        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 11px;
                font-style: italic;
            }}
        """)
        self.status_label.setText(message)

        # Auto clear after 3 seconds
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self.status_label.setText(""))

    def apply_button_style(self, button, color, is_selected=False):
        """Apply style to a button"""
        r, g, b = color

        if is_selected:
            # Selected state - keep same color but with white border
            bg_color = f"rgb({r}, {g}, {b})"
            hover_color = f"rgb({min(255, r+30)}, {min(255, g+30)}, {min(255, b+30)})"
            border_color = "rgb(255, 255, 255)"
            border_width = "2px"
        else:
            # Normal colors
            bg_color = f"rgb({r}, {g}, {b})"
            hover_color = f"rgb({min(255, r+30)}, {min(255, g+30)}, {min(255, b+30)})"
            border_color = "rgb(100, 100, 100)"
            border_width = "1px"

        style = f"""
            QPushButton {{
                background-color: {bg_color} !important;
                color: rgb(255, 255, 255);
                border: {border_width} solid {border_color};
                border-radius: 15px;
                font-size: 11px;
                font-weight: semibold;
                font-family: 'Open Sans', sans-serif;
            }}
            QPushButton:hover {{
                background-color: {hover_color} !important;
            }}
            QPushButton:pressed {{
                background-color: {bg_color} !important;
            }}
        """
        button.setStyleSheet(style)

    def add_separator(self, layout):
        """Add a separator line"""
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setLineWidth(1)
        separator.setStyleSheet("background-color: rgb(9, 9, 9); border: none;")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

    def _add_combobox_arrow(self, combobox):
        """Add custom arrow to combobox"""
        from PyQt5.QtWidgets import QLabel
        from PyQt5.QtCore import Qt

        # Create arrow label
        arrow_label = QLabel("⌄", combobox)
        arrow_label.setStyleSheet("""
            QLabel {
                color: rgb(145, 145, 145);
                background: transparent;
                font-size: 10px;
                border: none;
            }
        """)
        arrow_label.setAlignment(Qt.AlignCenter)
        arrow_label.setGeometry(55, 4, 15, 12)
        arrow_label.setAttribute(Qt.WA_TransparentForMouseEvents)

    def setup_styles(self):
        """Setup button styles and colors"""
        # Apply colors to each action button
        for action_type, color in self.button_colors.items():
            if action_type in self.action_buttons:
                btn = self.action_buttons[action_type]
                self.apply_button_style(btn, color, False)


def main():
    """Main function"""
    # Setup application
    import os
    import sys

    # Ensure stdout/stderr are not redirected
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__

    os.environ['QT_LOGGING_RULES'] = '*.debug=false;qt.qpa.*=false'

    app = QApplication(sys.argv)

    # Set application style
    app.setStyle('Fusion')

    # Set dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(40, 40, 46))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(31, 31, 31))
    palette.setColor(QPalette.AlternateBase, QColor(40, 40, 46))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(40, 40, 46))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Link, QColor(100, 200, 255))
    palette.setColor(QPalette.Highlight, QColor(100, 200, 255))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    # Create and show main window
    window = DarkUITemplate()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()