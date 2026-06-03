from __future__ import annotations

import unittest

from robotrace_course_cad.model.course_model import HelperCircle, Turn
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.solver.circle_adjust import (
    adjusted_center_touching_neighbors,
    circle_intersection_points,
    helper_circle_touch_distance,
)


class CircleAdjustTest(unittest.TestCase):
    def test_touch_distance_uses_turn_combination(self) -> None:
        ccw = HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW)
        cw = HelperCircle(1, 0.0, 0.0, 20.0, Turn.CW)
        ccw_large = HelperCircle(2, 0.0, 0.0, 25.0, Turn.CCW)

        self.assertEqual(helper_circle_touch_distance(ccw, cw), 30.0)
        self.assertEqual(helper_circle_touch_distance(ccw, ccw_large), 15.0)

    def test_circle_intersection_points_returns_two_candidates(self) -> None:
        points = circle_intersection_points(Vec2(0.0, 0.0), 5.0, Vec2(8.0, 0.0), 5.0)

        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(points[0].x, 4.0)
        self.assertAlmostEqual(abs(points[0].y), 3.0)
        self.assertAlmostEqual(points[1].x, 4.0)
        self.assertAlmostEqual(abs(points[1].y), 3.0)

    def test_adjusted_center_chooses_candidate_closest_to_current_position(self) -> None:
        circles = [
            HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW),
            HelperCircle(1, 15.0, 25.0, 10.0, Turn.CW),
            HelperCircle(2, 30.0, 0.0, 10.0, Turn.CCW),
        ]

        center = adjusted_center_touching_neighbors(circles, 1)

        self.assertIsNotNone(center)
        assert center is not None
        self.assertAlmostEqual(center.x, 15.0)
        self.assertAlmostEqual(center.y, 13.228756555, places=6)

    def test_adjusted_center_returns_none_when_no_solution_exists(self) -> None:
        circles = [
            HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW),
            HelperCircle(1, 0.0, 10.0, 10.0, Turn.CW),
            HelperCircle(2, 100.0, 0.0, 10.0, Turn.CCW),
        ]

        self.assertIsNone(adjusted_center_touching_neighbors(circles, 1))


if __name__ == "__main__":
    unittest.main()
