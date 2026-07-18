from __future__ import annotations

import unittest

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QGraphicsScene

from robotrace_course_cad.main import apply_light_theme
from robotrace_course_cad.model.course_model import CourseModel, HelperCircle, Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CourseSolution, IssueHighlight, IssueSegment, ValidationIssue
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.render.qt_renderer import render_course
from robotrace_course_cad.solver.course_solver import solve_course
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

    def test_validation_overlay_renders_warning_highlights(self) -> None:
        model = CourseModel(
            circles=[
                HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW),
                HelperCircle(1, 9.9, 0.0, 10.0, Turn.CCW),
            ]
        )
        solution = solve_course(model)
        scene = QGraphicsScene()

        render_course(scene, model, solution, lambda _circle: None)

        self.assertTrue(any(item.zValue() == 60 for item in scene.items()))

    def test_validation_overlay_renders_issue_segments(self) -> None:
        model = CourseModel()
        solution = CourseSolution(
            tangents=[],
            arcs=[],
            issues=[
                ValidationIssue(
                    "warning",
                    "start/goal clearance",
                    segments=[IssueSegment(Vec2(0.0, 0.0), Vec2(5.0, 0.0), "start_goal_clearance")],
                )
            ],
        )
        scene = QGraphicsScene()

        render_course(scene, model, solution, lambda _circle: None)

        self.assertTrue(any(item.zValue() == 62 for item in scene.items()))

    def test_validation_overlay_renders_circle_highlights(self) -> None:
        model = CourseModel()
        solution = CourseSolution(
            tangents=[],
            arcs=[
                ArcSegment(
                    circle_id=0,
                    center=Vec2(0.0, 0.0),
                    radius=10.0,
                    p_start=Vec2(10.0, 0.0),
                    p_end=Vec2(10.0, 0.0),
                    turn=Turn.CCW,
                    angle_rad=0.0,
                    length=0.0,
                )
            ],
            issues=[ValidationIssue("warning", "zero arc", highlights=[IssueHighlight("circle", 0)])],
        )
        scene = QGraphicsScene()

        render_course(scene, model, solution, lambda _circle: None)

        self.assertTrue(any(item.zValue() == 59 for item in scene.items()))


if __name__ == "__main__":
    unittest.main()
