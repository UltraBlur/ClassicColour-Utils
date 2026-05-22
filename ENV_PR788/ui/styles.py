APP_STYLE = """
QWidget[surface="true"] {
    background: rgb(40, 40, 46);
}

QWidget {
    background: rgb(40, 40, 46);
    color: rgb(235, 235, 235);
    font-family: "Open Sans", "Microsoft YaHei UI";
    font-size: 15px;
}

QMainWindow {
    background: rgb(40, 40, 46);
}

QFrame[card="true"] {
    background: rgb(40, 40, 46);
    border: 1px solid rgb(60, 60, 66);
    border-radius: 14px;
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
    border-radius: 12px;
}

QFrame[metric="true"] {
    background: rgb(33, 33, 38);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 12px;
}

QFrame[plot="true"] {
    background: rgb(33, 33, 38);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 12px;
}

QLabel[title="true"] {
    font-size: 22px;
    font-weight: 500;
    color: rgb(255, 255, 255);
}

QLabel[section="true"] {
    font-size: 14px;
    font-weight: 600;
    color: rgb(232, 232, 232);
}

QLabel[fieldLabel="true"] {
    font-size: 12px;
    font-weight: 700;
    color: rgb(228, 228, 228);
}

QLabel[muted="true"] {
    color: rgb(210, 210, 210);
}

QLabel[chip="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 999px;
    padding: 4px 10px;
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
    font-size: 11px;
    font-weight: 500;
}

QLabel[swatchLabel="true"] {
    color: rgb(225, 225, 225);
    font-size: 10px;
    font-weight: 400;
    background: transparent;
    border: none;
    padding: 0px;
}

QLabel[metricValue="true"] {
    color: rgb(255, 255, 255);
    font-size: 22px;
    font-weight: 400;
}

QLabel[previewName="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(67, 71, 77);
    border-radius: 10px;
    padding: 12px 14px;
    color: rgb(255, 255, 255);
    font-size: 18px;
    font-weight: 700;
}

QLabel[savedName="true"] {
    color: rgb(255, 255, 255);
    font-size: 20px;
    font-weight: 700;
}

QPushButton {
    background-color: rgb(40, 40, 46);
    color: rgb(240, 240, 240);
    border: 1px solid rgb(100, 100, 100);
    border-radius: 12px;
    padding: 10px 18px;
    min-height: 28px;
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
    font-size: 16px;
    padding: 12px 18px;
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
    border-radius: 12px;
    padding: 8px 12px;
}

QPushButton[token="true"]:hover {
    background-color: rgb(45, 45, 50);
}

QLineEdit, QComboBox, QTextEdit, QSpinBox {
    background-color: rgb(31, 31, 31);
    color: rgb(240, 240, 240);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 6px;
    padding: 10px 12px;
    min-height: 28px;
    selection-background-color: rgb(100, 200, 255);
}

QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus {
    border: 1px solid rgb(100, 200, 255);
    background-color: rgb(31, 31, 31);
}

QComboBox::drop-down {
    border: none;
    width: 28px;
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
    spacing: 8px;
    font-size: 15px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid rgb(100, 100, 100);
    background: rgb(31, 31, 31);
}

QCheckBox::indicator:checked {
    background: rgb(100, 200, 255);
}

QTextEdit[console="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 10px;
    padding: 12px;
    color: rgb(235, 235, 235);
}

QListWidget[historyList="true"] {
    background: rgb(31, 31, 31);
    border: 1px solid rgb(7, 7, 7);
    border-radius: 10px;
    padding: 6px;
    color: rgb(235, 235, 235);
    outline: none;
}

QListWidget[historyList="true"]::item {
    padding: 5px 10px;
    margin: 0px;
    border-radius: 6px;
}

QListWidget[historyList="true"]::item:selected {
    background: rgb(100, 150, 200);
    color: rgb(255, 255, 255);
}

QListWidget[historyList="true"]::item:hover {
    background: rgb(45, 45, 50);
}
"""
