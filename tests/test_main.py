from __future__ import annotations

import unittest

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from robotrace_course_cad.main import apply_light_theme
from robotrace_course_cad.model.course_solution import CourseSolution, ValidationIssue
from robotrace_course_cad.ui.main_window import format_solution_messages


class MainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_apply_light_theme_sets_light_palette(self) -> None:
        apply_light_theme(self.app)
        palette = self.app.palette()

        self.assertEqual(palette.color(QPalette.ColorRole.Window), QColor("#f0f0f0"))
        self.assertEqual(palette.color(QPalette.ColorRole.Base), QColor("#ffffff"))
        self.assertEqual(palette.color(QPalette.ColorRole.Text), QColor("#000000"))
        self.assertEqual(palette.color(QPalette.ColorRole.ButtonText), QColor("#000000"))

    def test_solver_messages_are_grouped_by_severity(self) -> None:
        solution = CourseSolution(
            tangents=[],
            arcs=[],
            issues=[
                ValidationIssue("info", "crossing info"),
                ValidationIssue("warning", "short start/goal"),
                ValidationIssue("error", "line width"),
                ValidationIssue("warning", "clearance"),
                ValidationIssue("info", "length info"),
            ],
        )

        lines = format_solution_messages(solution).splitlines()

        self.assertEqual(
            lines[:5],
            [
                "ERROR: line width",
                "WARNING: short start/goal",
                "WARNING: clearance",
                "INFO: crossing info",
                "INFO: length info",
            ],
        )


if __name__ == "__main__":
    unittest.main()
