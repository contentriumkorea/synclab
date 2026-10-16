"""Neutral editor surfaces and a single violet accent."""
STYLE = """
QWidget { background: #18181c; color: #eeeef2; font-family: 'Malgun Gothic'; font-size: 12px; }
QLabel { background: transparent; }
QLabel#muted { color: #a5a5b3; }
QLabel#brand { font-size: 20px; font-weight: bold; padding-right: 6px; }
QLabel#brandMark { background: transparent; }
QLabel#landingTitle { font-size: 25px; font-weight: bold; padding-bottom: 7px; }
QLabel#dropTitle { font-size: 18px; font-weight: bold; }
QLabel#section { font-size: 13px; font-weight: bold; }
QLabel#fileTitle { color: #e5e3ee; font-weight: bold; }
QLabel#stepNumber { color: #b69af8; font-size: 12px; font-weight: bold; }
QLabel#xmlMark { color: #c4afff; background: #292238; border: 1px solid #605079; border-radius: 10px; font-weight: bold; font-size: 16px; }
QLabel#timecode { color: #d1bfff; font-family: 'Consolas'; font-size: 14px; }
QLabel#localBadge { color: #a5a5b3; font-size: 11px; padding: 3px 8px; border: 1px solid #3b3b45; border-radius: 4px; }
QFrame#appHeader, QFrame#toolbar { background: #202024; border-bottom: 1px solid #33333d; }
QFrame#fileBar { background: #19191e; border-bottom: 1px solid #303039; }
QFrame#navigation { background: #202024; border-top: 1px solid #33333d; }
QFrame#statusBar { background: #1b1b20; border-top: 1px solid #303039; }
QFrame#dropZone { background: #202025; border: 1px dashed #625478; border-radius: 12px; }
QFrame#inspector { background: #202024; border-left: 1px solid #3b3b45; }
QFrame#inspectorContent { background: #202024; }
QPushButton { background: #2b2b33; border: 1px solid #464650; border-radius: 5px; padding: 8px 13px; font-weight: bold; min-height: 18px; }
QPushButton:hover { background: #373740; border-color: #827393; }
QPushButton:pressed { background: #24242c; }
QPushButton:focus { border: 1px solid #c6afff; }
QPushButton:checked { background: #3a2e51; border-color: #8e72bf; color: #e1d3ff; }
QPushButton:disabled { color: #777782; background: #24242a; border-color: #303038; }
QPushButton#primary { background: #9875ef; color: #141019; border: 1px solid #a98af5; }
QPushButton#primary:hover { background: #b096fa; }
QPushButton#primary:pressed { background: #8561d9; }
QPushButton#primary:disabled { background: #37303f; color: #8b8197; border-color: #433a4e; }
QPushButton#quiet { background: transparent; color: #c3c1ce; border: 1px solid transparent; padding: 7px 10px; }
QPushButton#quiet:hover { background: #303039; border-color: #49434f; }
QPushButton#quiet:checked { background: #3a2e51; border-color: #79608e; color: #e5d6ff; }
QPushButton#quiet:focus { border-color: #c6afff; }
QPushButton#quiet:disabled { color: #6d6c78; }
QPushButton#link { background: transparent; border: none; color: #bba5ed; font-weight: normal; }
QPushButton#link:hover { color: #e1d3ff; text-decoration: underline; }
QComboBox, QDoubleSpinBox { background: #18181e; border: 1px solid #494651; border-radius: 4px; padding: 5px 7px; min-height: 20px; }
QComboBox:focus, QDoubleSpinBox:focus { border-color: #b69af8; }
QComboBox:disabled, QDoubleSpinBox:disabled { color: #777782; border-color: #33333b; }
QComboBox::drop-down { width: 22px; border: none; }
QComboBox QAbstractItemView { background: #29272f; selection-background-color: #524165; selection-color: white; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 19px; }
QTableWidget { background: #1b1b21; gridline-color: #303039; border: 1px solid #35353f; selection-background-color: #3c3051; selection-color: #f0eaff; }
QTableWidget::item { padding: 4px; border-bottom: 1px solid #2b2b34; }
QHeaderView::section { background: #26262e; color: #b2b0c0; padding: 7px 6px; border: none; border-bottom: 1px solid #3b3744; font-size: 11px; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #77717f; border-radius: 3px; background: #1a191f; }
QCheckBox::indicator:checked { background: #9875ef; border-color: #b99bf5; }
QCheckBox:disabled { color: #777782; }
QProgressBar { border: none; background: #2e2938; }
QProgressBar::chunk { background: #ae8af5; }
QScrollArea { border: none; background: #151519; }
QScrollBar:vertical { background: #1e1d25; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #55505e; min-height: 24px; border-radius: 4px; }
QScrollBar:horizontal { background: #1e1d25; height: 9px; margin: 0; }
QScrollBar::handle:horizontal { background: #55505e; min-width: 24px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QSlider::groove:horizontal { height: 3px; background: #48424e; border-radius: 1px; }
QSlider::handle:horizontal { width: 12px; background: #bba0f3; margin: -5px 0; border-radius: 6px; }
QSplitter::handle { background: #36323e; width: 1px; height: 3px; }
QToolTip { background: #302938; border: 1px solid #766087; color: #f1eaff; padding: 6px; }
"""
