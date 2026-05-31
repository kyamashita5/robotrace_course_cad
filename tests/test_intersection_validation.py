from __future__ import annotations

import math
import unittest

from robotrace_course_cad.model.course_model import Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CourseSolution, TangentSegment
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.solver.course_solver import solve_course
from robotrace_course_cad.solver.intersections import validate_intersections
from robotrace_course_cad.io.json_io import load_course_model


class IntersectionValidationTest(unittest.TestCase):
    def test_perpendicular_line_crossing_with_clearance_is_valid(self) -> None:
        solution = CourseSolution(
            tangents=[
                line(0, 1, Vec2(-20.0, 0.0), Vec2(20.0, 0.0)),
                line(1, 2, Vec2(100.0, 0.0), Vec2(120.0, 0.0)),
                line(2, 3, Vec2(0.0, -20.0), Vec2(0.0, 20.0)),
                line(3, 0, Vec2(100.0, 50.0), Vec2(120.0, 50.0)),
            ],
            arcs=[],
            issues=[],
        )

        issues = validate_intersections(solution)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "info")
        self.assertIn("Valid line-line crossing: angle=90.0 deg, nearest endpoint=20.0 cm", issues[0].message)

    def test_non_perpendicular_line_crossing_is_invalid(self) -> None:
        solution = CourseSolution(
            tangents=[
                line(0, 1, Vec2(-20.0, 0.0), Vec2(20.0, 0.0)),
                line(1, 2, Vec2(100.0, 0.0), Vec2(120.0, 0.0)),
                line(2, 3, Vec2(-20.0, -20.0), Vec2(20.0, 20.0)),
                line(3, 0, Vec2(100.0, 50.0), Vec2(120.0, 50.0)),
            ],
            arcs=[],
            issues=[],
        )

        issues = validate_intersections(solution)

        self.assertTrue(any("Invalid line-line crossing" in issue.message for issue in issues))

    def test_line_crossing_too_close_to_endpoint_is_invalid(self) -> None:
        solution = CourseSolution(
            tangents=[
                line(0, 1, Vec2(-20.0, 0.0), Vec2(20.0, 0.0)),
                line(1, 2, Vec2(100.0, 0.0), Vec2(120.0, 0.0)),
                line(2, 3, Vec2(15.0, -20.0), Vec2(15.0, 20.0)),
                line(3, 0, Vec2(100.0, 50.0), Vec2(120.0, 50.0)),
            ],
            arcs=[],
            issues=[],
        )

        issues = validate_intersections(solution)

        self.assertTrue(any("nearest endpoint=5.0 cm" in issue.message for issue in issues))

    def test_line_crossing_at_just_under_ten_cm_is_valid(self) -> None:
        solution = CourseSolution(
            tangents=[
                line(0, 1, Vec2(-20.0, 0.0), Vec2(20.0, 0.0)),
                line(1, 2, Vec2(100.0, 0.0), Vec2(120.0, 0.0)),
                line(2, 3, Vec2(10.0, -20.0), Vec2(10.0, 20.0)),
                line(3, 0, Vec2(100.0, 50.0), Vec2(120.0, 50.0)),
            ],
            arcs=[],
            issues=[],
        )

        issues = validate_intersections(solution)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "info")
        self.assertIn("nearest endpoint=10.0 cm", issues[0].message)

    def test_line_arc_crossing_is_invalid(self) -> None:
        arc = ArcSegment(
            circle_id=2,
            center=Vec2(0.0, 0.0),
            radius=20.0,
            p_start=Vec2(20.0, 0.0),
            p_end=Vec2(-20.0, 0.0),
            turn=Turn.CCW,
            angle_rad=math.pi,
            length=20.0 * math.pi,
        )
        solution = CourseSolution(
            tangents=[
                line(0, 1, Vec2(-30.0, 10.0), Vec2(30.0, 10.0)),
                line(1, 2, Vec2(100.0, 0.0), Vec2(120.0, 0.0)),
                line(2, 3, Vec2(100.0, 50.0), Vec2(120.0, 50.0)),
                line(3, 0, Vec2(100.0, 80.0), Vec2(120.0, 80.0)),
            ],
            arcs=[None, None, arc],
            issues=[],
        )

        issues = validate_intersections(solution)

        self.assertTrue(any("intersects an arc" in issue.message for issue in issues))

    def test_zero_length_tangent_between_touching_arcs_is_not_warned(self) -> None:
        solution = solve_course(load_course_model("examples/synthetic/2019kansai.json"))

        zero_length_warnings = [
            issue.message
            for issue in solution.issues
            if issue.severity == "warning" and "Tangent" in issue.message and "0.0 cm" in issue.message
        ]

        self.assertEqual(zero_length_warnings, [])


def line(from_id: int, to_id: int, start: Vec2, end: Vec2) -> TangentSegment:
    return TangentSegment(
        from_circle_id=from_id,
        to_circle_id=to_id,
        p_from=start,
        p_to=end,
        kind="outer",
        choice=0,
    )


if __name__ == "__main__":
    unittest.main()
