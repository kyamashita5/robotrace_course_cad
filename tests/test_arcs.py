from __future__ import annotations

import math
import unittest

from robotrace_course_cad.model.course_model import HelperCircle, Turn
from robotrace_course_cad.model.course_solution import TangentSegment
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.solver.arcs import generate_arcs


class ArcGenerationTest(unittest.TestCase):
    def test_short_arc_issue_highlights_arc(self) -> None:
        circles = [
            HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW),
            HelperCircle(1, 50.0, 0.0, 10.0, Turn.CCW),
        ]
        short_arc_start = Vec2(10.0, 0.0)
        short_arc_end = Vec2(10.0 * math.cos(0.5), 10.0 * math.sin(0.5))
        tangents = [
            TangentSegment(0, 1, short_arc_end, Vec2(50.0, 10.0), "outer", 0),
            TangentSegment(1, 0, Vec2(50.0, 0.0), short_arc_start, "outer", 0),
        ]

        _arcs, issues = generate_arcs(circles, tangents)

        issue = find_issue(issues, "Arc on circle 0 is short")
        self.assertEqual([(highlight.kind, highlight.index) for highlight in issue.highlights], [("arc", 0)])
        self.assertEqual(issue.markers, [])

    def test_zero_length_short_arc_issue_marks_contact_point_and_circle(self) -> None:
        circles = [
            HelperCircle(0, 0.0, 0.0, 10.0, Turn.CCW),
            HelperCircle(1, 50.0, 0.0, 10.0, Turn.CCW),
        ]
        contact = Vec2(10.0, 0.0)
        tangents = [
            TangentSegment(0, 1, contact, Vec2(50.0, 10.0), "outer", 0),
            TangentSegment(1, 0, Vec2(50.0, 0.0), contact, "outer", 0),
        ]

        _arcs, issues = generate_arcs(circles, tangents)

        issue = find_issue(issues, "Arc on circle 0 is short")
        self.assertEqual([(highlight.kind, highlight.index) for highlight in issue.highlights], [("arc", 0), ("circle", 0)])
        self.assertEqual(len(issue.markers), 1)
        self.assertEqual(issue.markers[0].point, contact)


def find_issue(issues, message_part: str):
    for issue in issues:
        if message_part in issue.message:
            return issue
    raise AssertionError(f"No issue contained {message_part!r}. Issues: {[issue.message for issue in issues]}")


if __name__ == "__main__":
    unittest.main()
