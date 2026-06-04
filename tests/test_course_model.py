from __future__ import annotations

import unittest

from robotrace_course_cad.model.course_model import CourseModel, HelperCircle, Turn


class CourseModelTest(unittest.TestCase):
    def test_renumber_circle_ids_follows_list_order(self) -> None:
        model = CourseModel(
            circles=[
                HelperCircle(20, 0.0, 0.0, 10.0, Turn.CCW),
                HelperCircle(5, 10.0, 0.0, 10.0, Turn.CW),
                HelperCircle(99, 20.0, 0.0, 10.0, Turn.CCW),
            ]
        )

        model.renumber_circle_ids()

        self.assertEqual([circle.id for circle in model.circles], [0, 1, 2])

    def test_next_circle_id_is_list_length(self) -> None:
        model = CourseModel(
            circles=[
                HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW),
                HelperCircle(1, 10.0, 0.0, 10.0, Turn.CW),
            ]
        )

        self.assertEqual(model.next_circle_id(), 2)


if __name__ == "__main__":
    unittest.main()
