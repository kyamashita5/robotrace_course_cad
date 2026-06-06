from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.model.course_model import default_course_model
from robotrace_course_cad.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    app = QApplication(sys.argv[:1] + args)
    apply_light_theme(app)
    model_path = args[0] if args else None
    model = load_course_model(model_path) if model_path else default_course_model()

    window = MainWindow(model, model_path=model_path)
    window.resize(1200, 760)
    window.show()

    return app.exec()


def apply_light_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f7f7"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#0057b8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#308cc6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
