APP_STYLE = """
QWidget[surface="true"] {
    background: rgb(40, 40, 46);
}

QWidget {
    background: rgb(40, 40, 46);
    color: rgb(235, 235, 235);
    font-family: "Open Sans", "Microsoft YaHei UI";
    font-size: 10px;
}

QMainWindow {
    background: rgb(40, 40, 46);
}

QFrame[card="true"] {
    background: rgb(40, 40, 46);
    border: 1px solid rgb(60, 60, 66);
    border-radius: 6px;
}

QFrame[sidebar="true"] {
    background: rgb(40, 40, 46);
    border: 1px solid rgb(7, 7, 7);
}

QFrame[mainpanel="true"] {
    background: rgb(40, 40, 46);
    border: 1px solid rgb(7, 7, 7);
}

QFrame[hero="true"] {
    background: rgb(33, 33, 38);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 6px;
}

QFrame[metric="true"] {
    background: rgb(33, 33, 38);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 6px;
}

QFrame[plot="true"] {
    background: rgb(33, 33, 38);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 6px;
}

QLabel[title="true"] {
    font-size: 13px;
    font-weight: 500;
    color: rgb(255, 255, 255);
}

QLabel[section="true"] {
    font-size: 10px;
    font-weight: 600;
    color: rgb(232, 232, 232);
}

QLabel[fieldLabel="true"] {
    font-size: 9px;
    font-weight: 700;
    color: rgb(228, 228, 228);
}

QLabel[muted="true"] {
    color: rgb(210, 210, 210);
}

QLabel[attribution="true"] {
    color: rgb(185, 185, 185);
    font-size: 9px;
    font-weight: 500;
}

QLabel[chip="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 999px;
    padding: 2px 6px;
}

QLabel[status="connected"] {
    color: rgb(100, 200, 100);
    font-weight: 700;
}

QLabel[status="disconnected"] {
    color: rgb(200, 120, 120);
    font-weight: 700;
}

QLabel[status="busy"] {
    color: rgb(230, 190, 90);
    font-weight: 700;
}

QLabel[metricTitle="true"] {
    color: rgb(225, 225, 225);
    font-size: 9px;
    font-weight: 500;
}

QLabel[swatchLabel="true"] {
    color: rgb(225, 225, 225);
    font-size: 8px;
    font-weight: 400;
    background: transparent;
    border: none;
    padding: 0px;
}

QLabel[metricValue="true"] {
    color: rgb(255, 255, 255);
    font-size: 13px;
    font-weight: 400;
}

QLabel[previewName="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 6px;
    padding: 6px 8px;
    color: rgb(255, 255, 255);
    font-size: 11px;
    font-weight: 700;
}

QLabel[savedName="true"] {
    color: rgb(255, 255, 255);
    font-size: 11px;
    font-weight: 700;
}

QPushButton {
    background-color: rgb(40, 40, 46);
    color: rgb(240, 240, 240);
    border: 1px solid rgb(100, 100, 100);
    border-radius: 6px;
    padding: 4px 9px;
    min-height: 18px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: rgb(53, 53, 58);
}

QPushButton:pressed {
    background-color: rgb(23, 23, 28);
}

QPushButton[primaryAction="true"] {
    background-color: rgb(100, 150, 200);
    color: rgb(255, 255, 255);
    border: 1px solid rgb(100, 150, 200);
    font-size: 11px;
    padding: 5px 10px;
}

QPushButton[primaryAction="true"]:hover {
    background-color: rgb(130, 180, 230);
}

QPushButton[secondary="true"] {
    background-color: rgb(40, 40, 46);
    color: rgb(240, 240, 240);
    border: 1px solid rgb(100, 100, 100);
}

QPushButton[secondary="true"]:hover {
    background-color: rgb(53, 53, 58);
}

QPushButton[danger="true"] {
    background-color: rgb(150, 50, 50);
    color: rgb(255, 255, 255);
    border: 1px solid rgb(150, 50, 50);
}

QPushButton[danger="true"]:hover {
    background-color: rgb(180, 70, 70);
}

QPushButton[token="true"] {
    background-color: rgb(31, 31, 31);
    color: rgb(238, 238, 238);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 6px;
    padding: 4px 7px;
}

QPushButton[token="true"]:hover {
    background-color: rgb(45, 45, 50);
}

QLineEdit, QComboBox, QTextEdit, QSpinBox {
    background-color: rgb(31, 31, 31);
    color: rgb(240, 240, 240);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 5px;
    padding: 4px 7px;
    min-height: 18px;
    selection-background-color: rgb(100, 200, 255);
}

QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus {
    border: 1px solid rgb(100, 200, 255);
    background-color: rgb(31, 31, 31);
}

QComboBox::drop-down {
    border: none;
    width: 18px;
    background: transparent;
}

QComboBox QAbstractItemView {
    background-color: rgb(31, 31, 31);
    color: rgb(240, 240, 240);
    border: 1px solid rgb(7, 7, 7);
    selection-background-color: rgb(100, 200, 255);
    selection-color: rgb(0, 0, 0);
}

QCheckBox {
    spacing: 5px;
    font-size: 10px;
}

QCheckBox::indicator {
    width: 12px;
    height: 12px;
    border-radius: 3px;
    border: 1px solid rgb(100, 100, 100);
    background: rgb(31, 31, 31);
}

QCheckBox::indicator:checked {
    background: rgb(100, 200, 255);
}

QTextEdit[console="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 6px;
    padding: 8px;
    color: rgb(235, 235, 235);
}

QListWidget[historyList="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 6px;
    padding: 4px;
    color: rgb(235, 235, 235);
    outline: none;
}

QListWidget[historyList="true"]::item {
    padding: 4px 6px;
    margin: 0px;
    border-radius: 4px;
}

QListWidget[historyList="true"]::item:selected {
    background: rgb(100, 150, 200);
    color: rgb(255, 255, 255);
}

QListWidget[historyList="true"]::item:hover {
    background: rgb(45, 45, 50);
}

QTreeWidget[historyList="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 6px;
    padding: 4px;
    color: rgb(235, 235, 235);
    outline: none;
}

QTreeWidget[historyList="true"]::item {
    padding: 4px 6px;
    margin: 0px;
    border-radius: 4px;
}

QTreeWidget[historyList="true"]::item:selected {
    background: rgb(100, 150, 200);
    color: rgb(255, 255, 255);
}

QTreeWidget[historyList="true"]::item:hover {
    background: rgb(45, 45, 50);
}

QFrame[metric="true"][compact="true"] {
    border-radius: 5px;
}

QLabel[metricTitle="true"][compact="true"] {
    font-size: 8px;
}

QLabel[metricValue="true"][compact="true"] {
    font-size: 11px;
}

QComboBox[small="true"] {
    font-size: 10px;
    padding: 2px 6px;
    min-height: 16px;
}

QComboBox[small="true"]::drop-down {
    width: 14px;
}

QSplitter::handle {
    background: rgb(40, 40, 46);
}

QSplitter::handle:horizontal {
    width: 4px;
}

QSplitter::handle:vertical {
    height: 4px;
}

QSplitter::handle:hover {
    background: rgb(100, 150, 200);
}

QDialog {
    background-color: rgb(40, 40, 46);
}

QTableWidget {
    background-color: rgb(31, 31, 31);
    color: rgb(235, 235, 235);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 6px;
    gridline-color: rgb(55, 58, 64);
    alternate-background-color: rgb(35, 35, 40);
}

QHeaderView::section {
    background-color: rgb(38, 38, 44);
    color: rgb(220, 220, 225);
    border: none;
    border-bottom: 1px solid rgb(67, 71, 77);
    padding: 4px 6px;
    font-weight: 600;
}

QTableCornerButton::section {
    background-color: rgb(38, 38, 44);
    border: none;
}

QTableWidget::item {
    padding: 2px 6px;
}

QTableWidget::item:selected {
    background-color: rgb(100, 150, 200);
    color: rgb(255, 255, 255);
}
"""
