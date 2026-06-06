from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGraphicsScene

from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.render.final_drawing_exporter import (
    FinalDrawingOptions,
    FINAL_START_GOAL_AREA_WIDTH_CM,
    HELPER_CIRCLE_WIDTH_CM,
    HELPER_LABEL_PIXEL_SIZE,
    START_GOAL_GATE_COORD_PIXEL_SIZE,
    START_GOAL_GATE_LABEL_PIXEL_SIZE,
    _helper_circle_text_item,
    add_right_aligned_text,
    create_final_drawing_scene,
    export_final_drawing,
    fitted_target_rect,
    final_start_goal_outer_area_points,
    helper_circle_label_text,
    occupied_grid_cells,
    start_goal_coordinate_anchor,
    start_goal_coordinate_text,
    start_goal_gate_points,
    svg_pixel_size_for_mm,
)
from robotrace_course_cad.model.course_model import HelperCircle, Turn
from robotrace_course_cad.model.course_solution import StartGoalSegment
from robotrace_course_cad.model.geometry import Vec2
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

    def test_exports_helper_circles_when_option_is_enabled(self) -> None:
        model = load_course_model("examples/sample_course.json")
        solution = solve_course(model)

        with tempfile.TemporaryDirectory() as tmp_dir:
            svg_path = Path(tmp_dir) / "course_helpers.svg"
            export_final_drawing(svg_path, model, solution, FinalDrawingOptions(print_helper_circles=True))

            svg = svg_path.read_text(encoding="utf-8")

        self.assertIn("R20", svg)
        self.assertIn("#ff2a5a", svg.lower())
        self.assertIn('viewBox="0 0 297 210"', svg)

    def test_exports_start_goal_area_by_default(self) -> None:
        model = load_course_model("examples/sample_course.json")
        solution = solve_course(model)

        with tempfile.TemporaryDirectory() as tmp_dir:
            enabled_path = Path(tmp_dir) / "course_sg_area.svg"
            outer_enabled_path = Path(tmp_dir) / "course_sg_outer_area.svg"
            disabled_path = Path(tmp_dir) / "course_no_sg_area.svg"
            export_final_drawing(enabled_path, model, solution)
            export_final_drawing(
                outer_enabled_path,
                model,
                solution,
                FinalDrawingOptions(print_start_goal_outer_area=True),
            )
            export_final_drawing(disabled_path, model, solution, FinalDrawingOptions(print_start_goal_area=False))

            enabled_svg = enabled_path.read_text(encoding="utf-8").lower()
            outer_enabled_svg = outer_enabled_path.read_text(encoding="utf-8").lower()
            disabled_svg = disabled_path.read_text(encoding="utf-8").lower()

        self.assertIn("#f2c400", enabled_svg)
        self.assertNotIn("#8d8d8d", enabled_svg)
        self.assertIn("#8d8d8d", outer_enabled_svg)
        self.assertNotIn("#f2c400", disabled_svg)
        self.assertNotIn("#8d8d8d", disabled_svg)
        self.assertIn("start", enabled_svg)
        self.assertIn("goal", enabled_svg)

    def test_start_goal_gate_geometry_is_40_by_10_cm(self) -> None:
        segment = StartGoalSegment(
            center=Vec2(10.0, 0.0),
            p_start=Vec2(-40.0, 0.0),
            p_end=Vec2(60.0, 0.0),
            tangent_angle_deg=0.0,
            length=100.0,
        )

        points = start_goal_gate_points(segment.p_start, segment)

        self.assertEqual(
            [(point.x, point.y) for point in points],
            [(-45.0, 20.0), (-35.0, 20.0), (-35.0, -20.0), (-45.0, -20.0)],
        )

    def test_start_goal_outer_area_geometry_is_80_cm_wide(self) -> None:
        segment = StartGoalSegment(
            center=Vec2(10.0, 0.0),
            p_start=Vec2(-40.0, 0.0),
            p_end=Vec2(60.0, 0.0),
            tangent_angle_deg=0.0,
            length=100.0,
        )

        points = final_start_goal_outer_area_points(segment)

        self.assertEqual(
            [(point.x, point.y) for point in points],
            [(-50.0, 40.0), (70.0, 40.0), (70.0, -40.0), (-50.0, -40.0)],
        )

    def test_start_goal_coordinate_text_uses_line_coordinates(self) -> None:
        self.assertEqual(start_goal_coordinate_text(Vec2(40.0, 200.0)), "40,200")
        self.assertEqual(start_goal_coordinate_text(Vec2(40.25, 99.94)), "40.2,99.9")

    def test_start_goal_coordinate_text_is_right_aligned_to_area_outline(self) -> None:
        segment = StartGoalSegment(
            center=Vec2(10.0, 0.0),
            p_start=Vec2(-40.0, 0.0),
            p_end=Vec2(60.0, 0.0),
            tangent_angle_deg=0.0,
            length=100.0,
        )
        anchor = start_goal_coordinate_anchor(segment.p_start, segment)
        scene = QGraphicsScene()

        rect = add_right_aligned_text(scene, "40,200", anchor, Qt.GlobalColor.magenta, 39, z=1)

        self.assertEqual((anchor.x, anchor.y), (-40.0, -20.0))
        self.assertAlmostEqual(rect.right(), anchor.x * 10.0)

    def test_a4_svg_size_uses_physical_page_pixels(self) -> None:
        size = svg_pixel_size_for_mm(297.0, 210.0)

        self.assertEqual(size.width(), 842)
        self.assertEqual(size.height(), 595)

    def test_helper_circle_style_matches_clean_drawing_spec(self) -> None:
        self.assertAlmostEqual(HELPER_CIRCLE_WIDTH_CM, 0.48)
        self.assertEqual(HELPER_LABEL_PIXEL_SIZE, 39)
        self.assertEqual(START_GOAL_GATE_LABEL_PIXEL_SIZE, HELPER_LABEL_PIXEL_SIZE)
        self.assertEqual(START_GOAL_GATE_COORD_PIXEL_SIZE, HELPER_LABEL_PIXEL_SIZE)

    def test_start_goal_area_outline_is_heavy_enough_for_clean_drawing(self) -> None:
        self.assertAlmostEqual(FINAL_START_GOAL_AREA_WIDTH_CM, 1.0)

    def test_helper_circle_label_uses_two_lines_for_r20_and_larger(self) -> None:
        r10 = HelperCircle(id=0, x=219.0, y=204.0, r=10.0, turn=Turn.CCW)
        r20 = HelperCircle(id=1, x=310.0, y=50.0, r=20.0, turn=Turn.CCW)

        self.assertEqual(helper_circle_label_text(r10), "R10\n219,\n204")
        self.assertEqual(helper_circle_label_text(r20), "R20\n310, 50")

    def test_helper_circle_label_is_center_aligned(self) -> None:
        circle = HelperCircle(id=0, x=219.0, y=204.0, r=10.0, turn=Turn.CCW)
        item = _helper_circle_text_item(circle)

        self.assertEqual(item.document().defaultTextOption().alignment(), Qt.AlignmentFlag.AlignCenter)
        self.assertTrue(item.font().bold())
        self.assertGreater(item.textWidth(), 0.0)

    def test_board_cells_include_cells_near_line_within_19_cm(self) -> None:
        model = load_course_model("examples/sample_course.json")
        model.board_grid.origin_x = 0.0
        model.board_grid.origin_y = 0.0
        model.board_grid.cell_width = 90.0
        model.board_grid.cell_height = 90.0
        solution = solve_course(model)

        cells = occupied_grid_cells(model, solution)

        self.assertIn((-1, 0), cells)

    def test_final_drawing_options_can_hide_markers(self) -> None:
        model = load_course_model("examples/sample_course.json")
        solution = solve_course(model)
        with_markers = create_final_drawing_scene(model, solution, FinalDrawingOptions())
        without_markers = create_final_drawing_scene(
            model,
            solution,
            FinalDrawingOptions(print_corner_markers=False, print_start_goal_markers=False),
        )

        self.assertEqual(
            len(with_markers.items()) - len(without_markers.items()),
            len(solution.corner_markers) + len(solution.start_goal_markers),
        )

    def test_fitted_target_rect_keeps_source_inside_a4(self) -> None:
        target = fitted_target_rect(source_rect(1000.0, 500.0), 297.0, 210.0, 8.0)

        self.assertLessEqual(target.right(), 297.0)
        self.assertLessEqual(target.bottom(), 210.0)
        self.assertGreaterEqual(target.left(), 0.0)
        self.assertGreaterEqual(target.top(), 0.0)


def source_rect(width: float, height: float):
    from PySide6.QtCore import QRectF

    return QRectF(0, 0, width, height)


if __name__ == "__main__":
    unittest.main()
