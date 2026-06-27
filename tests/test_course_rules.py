from __future__ import annotations

import math
import unittest

from robotrace_course_cad.model.course_model import CourseModel, HelperCircle, Turn
from robotrace_course_cad.model.course_solution import ArcSegment, StartGoalSegment, TangentSegment, ValidationIssue
from robotrace_course_cad.model.geometry import Vec2
from robotrace_course_cad.solver.course_rules import validate_course_rules


class CourseRuleValidationTest(unittest.TestCase):
    def test_line_width_must_be_1_9_cm(self) -> None:
        issues = validate_course_rules(
            CourseModel(line_width_cm=2.0),
            tangents=[],
            arcs=[],
            start_goal_segment=normal_start_goal_segment(),
        )

        issue = find_issue(issues, "Line width must be 1.9 cm")
        self.assertEqual(issue.severity, "error")

    def test_course_length_must_not_exceed_60_m(self) -> None:
        issues = validate_course_rules(
            CourseModel(),
            tangents=[line(Vec2(0.0, 0.0), Vec2(6001.0, 0.0))],
            arcs=[],
            start_goal_segment=normal_start_goal_segment(),
        )

        issue = find_issue(issues, "Course centerline length must be 60.00 m or less")
        self.assertEqual(issue.severity, "error")

    def test_arc_radius_must_be_at_least_10_cm(self) -> None:
        model = CourseModel(circles=[HelperCircle(7, 0.0, 0.0, 9.9, Turn.CCW)])

        issues = validate_course_rules(
            model,
            tangents=[],
            arcs=[],
            start_goal_segment=normal_start_goal_segment(),
        )

        issue = find_issue(issues, "Arc radius on circle 7 is below 10 cm")
        self.assertEqual(issue.severity, "error")
        self.assertEqual(issue.related_circle_ids, [7])

    def test_start_goal_spacing_other_than_100_cm_is_warning(self) -> None:
        issues = validate_course_rules(
            CourseModel(),
            tangents=[line(Vec2(-70.0, 0.0), Vec2(70.0, 0.0))],
            arcs=[],
            start_goal_segment=StartGoalSegment(
                center=Vec2(0.0, 0.0),
                p_start=Vec2(-45.0, 0.0),
                p_end=Vec2(45.0, 0.0),
                tangent_angle_deg=0.0,
                length=90.0,
            ),
        )

        issue = find_issue(issues, "Start/goal line spacing should be 100 cm")
        self.assertEqual(issue.severity, "warning")

    def test_start_goal_lines_need_10_cm_straight_clearance_warning(self) -> None:
        issues = validate_course_rules(
            CourseModel(),
            tangents=[line(Vec2(-50.0, 0.0), Vec2(55.0, 0.0))],
            arcs=[],
            start_goal_segment=normal_start_goal_segment(),
        )

        issue = find_issue(issues, "Start/goal lines should have 10 cm straight clearance")
        self.assertEqual(issue.severity, "warning")

    def test_normal_start_goal_segment_has_no_start_goal_warning(self) -> None:
        issues = validate_course_rules(
            CourseModel(),
            tangents=[line(Vec2(-70.0, 0.0), Vec2(70.0, 0.0))],
            arcs=[],
            start_goal_segment=normal_start_goal_segment(),
        )

        start_goal_messages = [issue.message for issue in issues if issue.message.startswith("Start/goal")]
        self.assertEqual(start_goal_messages, [])

    def test_arc_length_counts_toward_60_m_limit(self) -> None:
        long_arc = ArcSegment(
            circle_id=0,
            center=Vec2(0.0, 0.0),
            radius=1000.0,
            p_start=Vec2(1000.0, 0.0),
            p_end=Vec2(-1000.0, 0.0),
            turn=Turn.CCW,
            angle_rad=2.0 * math.pi,
            length=1000.0 * 2.0 * math.pi,
        )

        issues = validate_course_rules(
            CourseModel(),
            tangents=[],
            arcs=[long_arc],
            start_goal_segment=normal_start_goal_segment(),
        )

        issue = find_issue(issues, "Course centerline length must be 60.00 m or less")
        self.assertEqual(issue.severity, "error")


def line(start: Vec2, end: Vec2) -> TangentSegment:
    return TangentSegment(
        from_circle_id=0,
        to_circle_id=1,
        p_from=start,
        p_to=end,
        kind="outer",
        choice=0,
    )


def normal_start_goal_segment() -> StartGoalSegment:
    return StartGoalSegment(
        center=Vec2(0.0, 0.0),
        p_start=Vec2(-50.0, 0.0),
        p_end=Vec2(50.0, 0.0),
        tangent_angle_deg=0.0,
        length=100.0,
    )


def find_issue(issues: list[ValidationIssue], message_part: str) -> ValidationIssue:
    for issue in issues:
        if message_part in issue.message:
            return issue
    raise AssertionError(f"No issue contained {message_part!r}. Issues: {[issue.message for issue in issues]}")


if __name__ == "__main__":
    unittest.main()
