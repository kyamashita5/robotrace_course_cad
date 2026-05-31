from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.model.course_model import default_course_model
from robotrace_course_cad.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    app = QApplication(sys.argv[:1] + args)
    model = load_course_model(args[0]) if args else default_course_model()

    window = MainWindow(model)
    window.resize(1200, 760)
    window.show()

    return app.exec()
