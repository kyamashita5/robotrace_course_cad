from __future__ import annotations

import unittest

from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.model.course_model import CourseModel, StartGoalHint
from robotrace_course_cad.model.course_solution import CourseSolution, TangentSegment
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.render.qt_renderer import start_goal_area_points
from robotrace_course_cad.solver.course_solver import solve_course
from robotrace_course_cad.solver.markers import generate_corner_markers, generate_start_goal_segment_and_markers


class MarkerGenerationTest(unittest.TestCase):
    def test_generates_marker_for_each_line_boundary(self) -> None:
        solution = CourseSolution(
            tangents=[
                line(0, 1, Vec2(0.0, 0.0), Vec2(20.0, 0.0)),
                line(1, 2, Vec2(20.0, 0.0), Vec2(20.0, 20.0)),
                line(2, 3, Vec2(20.0, 20.0), Vec2(0.0, 20.0)),
                line(3, 0, Vec2(0.0, 20.0), Vec2(0.0, 0.0)),
            ],
            arcs=[],
            issues=[],
        )

        markers = generate_corner_markers(solution)

        self.assertEqual(len(markers), 4)
        self.assertAlmostEqual(markers[0].point.x, 20.0)
        self.assertAlmostEqual(markers[0].point.y, 0.0)
        self.assertAlmostEqual(markers[0].point.distance_to(markers[0].center), 7.0)

    def test_synthetic_touching_arcs_do_not_create_duplicate_markers(self) -> None:
        solution = solve_course(load_course_model("examples/synthetic/2019kansai.json"))
        marker_points = [(round(marker.point.x, 2), round(marker.point.y, 2)) for marker in solution.corner_markers]

        self.assertEqual(len(marker_points), len(set(marker_points)))
        self.assertLessEqual(len(solution.corner_markers), 2 * len(solution.arcs))

    def test_start_goal_markers_are_generated_on_right_side(self) -> None:
        tangent = line(3, 0, Vec2(-60.0, 0.0), Vec2(60.0, 0.0))
        model = CourseModel(start_goal_hint=StartGoalHint(10.0, 20.0, 100.0))

        segment, markers = generate_start_goal_segment_and_markers(model, [tangent])

        self.assertIsNotNone(segment)
        assert segment is not None
        self.assertAlmostEqual(segment.center.x, 10.0)
        self.assertAlmostEqual(segment.center.y, 0.0)
        self.assertAlmostEqual(segment.p_start.x, -40.0)
        self.assertAlmostEqual(segment.p_end.x, 60.0)
        self.assertEqual(len(markers), 2)
        self.assertAlmostEqual(markers[0].center.x, -40.0)
        self.assertAlmostEqual(markers[0].center.y, -7.0)
        self.assertAlmostEqual(markers[1].center.x, 60.0)
        self.assertAlmostEqual(markers[1].center.y, -7.0)

    def test_start_goal_area_is_40_cm_wide_and_extensible(self) -> None:
        tangent = line(3, 0, Vec2(-60.0, 0.0), Vec2(60.0, 0.0))
        model = CourseModel(start_goal_hint=StartGoalHint(10.0, 20.0, 100.0))
        segment, _markers = generate_start_goal_segment_and_markers(model, [tangent])

        assert segment is not None
        points = start_goal_area_points(segment)
        extended_points = start_goal_area_points(segment, extension_cm=10.0)

        self.assertEqual([(point.x, point.y) for point in points], [(-40.0, 20.0), (60.0, 20.0), (60.0, -20.0), (-40.0, -20.0)])
        self.assertEqual(
            [(point.x, point.y) for point in extended_points],
            [(-50.0, 20.0), (70.0, 20.0), (70.0, -20.0), (-50.0, -20.0)],
        )


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
