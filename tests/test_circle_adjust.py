from __future__ import annotations

import unittest

from robotrace_course_cad.model.course_model import HelperCircle, Turn
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.solver.circle_adjust import (
    adjusted_center_touching_anchor,
    adjusted_center_touching_neighbors,
    adjusted_center_touching_next,
    adjusted_center_touching_previous,
    circle_intersection_points,
    helper_circle_touch_distance,
    projected_center_for_degenerate_neighbor_touch,
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

    def test_adjusted_center_projects_degenerate_same_center_neighbors(self) -> None:
        circles = [
            HelperCircle(0, 410.0, 430.0, 400.0, Turn.CCW),
            HelperCircle(1, 585.0, 87.0, 15.0, Turn.CCW),
            HelperCircle(2, 410.0, 430.0, 370.0, Turn.CW),
        ]

        center = adjusted_center_touching_neighbors(circles, 1)

        self.assertIsNotNone(center)
        assert center is not None
        anchor = circles[0].center
        original_direction = (circles[1].center - anchor).normalized()
        adjusted_direction = (center - anchor).normalized()
        self.assertAlmostEqual(center.distance_to(anchor), 385.0)
        self.assertAlmostEqual(adjusted_direction.x, original_direction.x)
        self.assertAlmostEqual(adjusted_direction.y, original_direction.y)
        self.assertAlmostEqual(center.distance_to(circles[2].center), 385.0)

    def test_degenerate_projection_requires_same_touch_distance(self) -> None:
        center = projected_center_for_degenerate_neighbor_touch(
            current=Vec2(10.0, 0.0),
            previous_center=Vec2(0.0, 0.0),
            distance_to_previous=10.0,
            next_center=Vec2(0.0, 0.0),
            distance_to_next=12.0,
        )

        self.assertIsNone(center)

    def test_adjusted_center_touching_anchor_uses_smallest_t_squared_solution(self) -> None:
        moving = HelperCircle(1, 10.0, 0.0, 10.0, Turn.CW)
        anchor = HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW)

        center = adjusted_center_touching_anchor(moving, anchor)

        self.assertIsNotNone(center)
        assert center is not None
        self.assertAlmostEqual(center.x, 20.0)
        self.assertAlmostEqual(center.y, 0.0)

    def test_adjusted_center_touching_previous_and_next(self) -> None:
        circles = [
            HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW),
            HelperCircle(1, 10.0, 0.0, 10.0, Turn.CW),
            HelperCircle(2, 40.0, 0.0, 10.0, Turn.CCW),
        ]

        prev_center = adjusted_center_touching_previous(circles, 1)
        next_center = adjusted_center_touching_next(circles, 1)

        self.assertIsNotNone(prev_center)
        self.assertIsNotNone(next_center)
        assert prev_center is not None
        assert next_center is not None
        self.assertAlmostEqual(prev_center.x, 20.0)
        self.assertAlmostEqual(next_center.x, 20.0)

    def test_adjusted_center_touching_anchor_returns_none_when_centers_match(self) -> None:
        moving = HelperCircle(1, 0.0, 0.0, 10.0, Turn.CW)
        anchor = HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW)

        self.assertIsNone(adjusted_center_touching_anchor(moving, anchor))


if __name__ == "__main__":
    unittest.main()
