from __future__ import annotations

import unittest

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from robotrace_course_cad.main import apply_light_theme


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


if __name__ == "__main__":
    unittest.main()
