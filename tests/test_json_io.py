from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from robotrace_course_cad.io.json_io import load_course_model, save_course_model
from robotrace_course_cad.model.course_model import HelperCircle, StartGoalHint, Turn, default_course_model


class JsonIoTest(unittest.TestCase):
    def test_default_course_model_matches_template_course(self) -> None:
        model = default_course_model()
        template = load_course_model("examples/template_course.json")

        self.assertEqual(model.board_width_cm, template.board_width_cm)
        self.assertEqual(model.board_height_cm, template.board_height_cm)
        self.assertEqual(model.line_width_cm, template.line_width_cm)
        self.assertEqual(model.min_edge_margin_cm, template.min_edge_margin_cm)
        self.assertEqual(model.radius_presets_cm, template.radius_presets_cm)
        self.assertEqual(model.board_grid, template.board_grid)
        self.assertEqual(model.start_goal_hint, template.start_goal_hint)
        self.assertEqual(model.circles, template.circles)

    def test_save_and_load_course_model(self) -> None:
        model = default_course_model()
        model.board_width_cm = 420.0
        model.board_height_cm = 210.0
        model.board_grid.origin_x = -45.0
        model.board_grid.origin_y = -30.0
        model.board_grid.cell_width = 120.0
        model.board_grid.cell_height = 90.0
        model.start_goal_hint = StartGoalHint(12.5, -34.5, 90.0)
        model.circles.append(HelperCircle(99, 1.25, 2.5, 15.0, Turn.CW, locked=True))

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "course.json"
            save_course_model(model, path)
            loaded = load_course_model(path)

        self.assertEqual(loaded.board_width_cm, 420.0)
        self.assertEqual(loaded.board_height_cm, 210.0)
        self.assertEqual(loaded.board_grid.origin_x, -45.0)
        self.assertEqual(loaded.board_grid.origin_y, -30.0)
        self.assertEqual(loaded.board_grid.cell_width, 120.0)
        self.assertEqual(loaded.board_grid.cell_height, 90.0)
        self.assertEqual(loaded.start_goal_hint.x, 12.5)
        self.assertEqual(loaded.start_goal_hint.y, -34.5)
        self.assertEqual(loaded.start_goal_hint.length, 90.0)
        self.assertEqual(len(loaded.circles), len(model.circles))
        self.assertEqual([circle.id for circle in loaded.circles], list(range(len(loaded.circles))))
        self.assertEqual(loaded.circles[-1].turn, Turn.CW)
        self.assertTrue(loaded.circles[-1].locked)


if __name__ == "__main__":
    unittest.main()
