from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.render.final_drawing_exporter import export_final_drawing, occupied_grid_cells
from robotrace_course_cad.solver.course_solver import solve_course


class FinalDrawingExporterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_exports_svg_and_pdf(self) -> None:
        model = load_course_model("examples/sample_course.json")
        solution = solve_course(model)

        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_path = Path(tmp_dir) / "course.svg"
            pdf_path = Path(tmp_dir) / "course.pdf"

            export_final_drawing(svg_path, model, solution)
            export_final_drawing(pdf_path, model, solution)

            self.assertGreater(svg_path.stat().st_size, 100)
            self.assertGreater(pdf_path.stat().st_size, 100)

    def test_detects_occupied_grid_cells(self) -> None:
        model = load_course_model("examples/sample_course.json")
        model.board_grid.origin_x = 0.0
        model.board_grid.origin_y = 0.0
        model.board_grid.cell_width = 90.0
        model.board_grid.cell_height = 90.0
        solution = solve_course(model)

        cells = occupied_grid_cells(model, solution)

        self.assertGreater(len(cells), 0)
        self.assertTrue(all(isinstance(cell[0], int) and isinstance(cell[1], int) for cell in cells))

    def test_rejects_unknown_extension(self) -> None:
        model = load_course_model("examples/sample_course.json")
        solution = solve_course(model)

        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                export_final_drawing(Path(tmp_dir) / "course.png", model, solution)


if __name__ == "__main__":
    unittest.main()
