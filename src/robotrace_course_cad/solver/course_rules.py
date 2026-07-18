from __future__ import annotations

from robotrace_course_cad.model.course_model import CourseModel
from robotrace_course_cad.model.course_solution import ArcSegment, IssueSegment, StartGoalSegment, TangentSegment, ValidationIssue
from robotrace_course_cad.model.geometry import EPSILON, Vec2

EXPECTED_LINE_WIDTH_CM = 1.9
MAX_COURSE_LENGTH_CM = 6000.0
MIN_ARC_RADIUS_CM = 10.0
EXPECTED_START_GOAL_LENGTH_CM = 100.0
MIN_START_GOAL_STRAIGHT_CM = 10.0
RULE_TOLERANCE_CM = 1e-6


def validate_course_rules(
    model: CourseModel,
    tangents: list[TangentSegment | None],
    arcs: list[ArcSegment | None],
    start_goal_segment: StartGoalSegment | None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_line_width(model))
    issues.extend(validate_course_length(tangents, arcs))
    issues.extend(validate_arc_radii(model))
    issues.extend(validate_start_goal_length(start_goal_segment))
    issues.extend(validate_start_goal_straight_clearance(tangents, start_goal_segment))
    return issues


def validate_line_width(model: CourseModel) -> list[ValidationIssue]:
    if abs(model.line_width_cm - EXPECTED_LINE_WIDTH_CM) <= RULE_TOLERANCE_CM:
        return []
    return [
        ValidationIssue(
            severity="error",
            message=(
                "Line width must be 1.9 cm "
                f"(current: {model.line_width_cm:.2f} cm)"
            ),
        )
    ]


def validate_course_length(
    tangents: list[TangentSegment | None],
    arcs: list[ArcSegment | None],
) -> list[ValidationIssue]:
    length_cm = sum(tangent.length for tangent in tangents if tangent is not None)
    length_cm += sum(arc.length for arc in arcs if arc is not None)
    if length_cm <= MAX_COURSE_LENGTH_CM + RULE_TOLERANCE_CM:
        return []
    return [
        ValidationIssue(
            severity="error",
            message=(
                "Course centerline length must be 60.00 m or less "
                f"(current: {length_cm / 100.0:.2f} m)"
            ),
        )
    ]


def validate_arc_radii(model: CourseModel) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for circle in model.circles:
        if circle.r < MIN_ARC_RADIUS_CM - RULE_TOLERANCE_CM:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"Arc radius on circle {circle.id} is below 10 cm ({circle.r:.2f} cm)",
                    related_circle_ids=[circle.id],
                )
            )
    return issues


def validate_start_goal_length(start_goal_segment: StartGoalSegment | None) -> list[ValidationIssue]:
    if start_goal_segment is None:
        return [
            ValidationIssue(
                severity="warning",
                message="Start/goal segment could not be generated",
            )
        ]
    if abs(start_goal_segment.length - EXPECTED_START_GOAL_LENGTH_CM) <= RULE_TOLERANCE_CM:
        return []
    return [
        ValidationIssue(
            severity="warning",
            message=(
                "Start/goal line spacing should be 100 cm "
                f"(current: {start_goal_segment.length:.1f} cm)"
            ),
        )
    ]


def validate_start_goal_straight_clearance(
    tangents: list[TangentSegment | None],
    start_goal_segment: StartGoalSegment | None,
) -> list[ValidationIssue]:
    if start_goal_segment is None or not tangents:
        return []
    start_goal_tangent = tangents[-1]
    if start_goal_tangent is None:
        return []

    clearances = [
        line_clearance_on_tangent(start_goal_segment.p_start, start_goal_tangent),
        line_clearance_on_tangent(start_goal_segment.p_end, start_goal_tangent),
    ]
    if all(clearance is not None and clearance >= MIN_START_GOAL_STRAIGHT_CM - RULE_TOLERANCE_CM for clearance in clearances):
        return []

    details = ", ".join(format_clearance(clearance) for clearance in clearances)
    return [
        ValidationIssue(
            severity="warning",
            message=(
                "Start/goal lines should have 10 cm straight clearance before and after each line "
                f"(clearances: {details})"
            ),
            segments=start_goal_clearance_issue_segments(start_goal_segment, start_goal_tangent),
        )
    ]


def line_clearance_on_tangent(point: Vec2, tangent: TangentSegment) -> float | None:
    segment = tangent.p_to - tangent.p_from
    length = segment.norm()
    if length < EPSILON:
        return None
    direction = segment.normalized()
    distance_from_start = (point - tangent.p_from).dot(direction)
    closest = tangent.p_from + direction * distance_from_start
    if point.distance_to(closest) > RULE_TOLERANCE_CM:
        return None
    distance_from_end = length - distance_from_start
    if distance_from_start < -RULE_TOLERANCE_CM or distance_from_end < -RULE_TOLERANCE_CM:
        return None
    return min(distance_from_start, distance_from_end)


def start_goal_clearance_issue_segments(
    start_goal_segment: StartGoalSegment,
    tangent: TangentSegment,
) -> list[IssueSegment]:
    tangent_delta = tangent.p_to - tangent.p_from
    if tangent_delta.norm() < EPSILON:
        return []

    direction = tangent_delta.normalized()
    segments: list[IssueSegment] = []
    for point, clearance_direction in (
        (start_goal_segment.p_start, direction * -1.0),
        (start_goal_segment.p_end, direction),
    ):
        segment = start_goal_clearance_issue_segment(point, tangent, clearance_direction)
        if segment is not None:
            segments.append(segment)
    return segments


def start_goal_clearance_issue_segment(
    point: Vec2,
    tangent: TangentSegment,
    clearance_direction: Vec2,
) -> IssueSegment | None:
    tangent_delta = tangent.p_to - tangent.p_from
    tangent_length = tangent_delta.norm()
    if tangent_length < EPSILON:
        return None

    direction = tangent_delta.normalized()
    distance_from_start = (point - tangent.p_from).dot(direction)
    projected = tangent.p_from + direction * distance_from_start
    distance_from_end = tangent_length - distance_from_start

    if point.distance_to(projected) > RULE_TOLERANCE_CM:
        return None

    if distance_from_start < -RULE_TOLERANCE_CM or distance_from_end < -RULE_TOLERANCE_CM:
        available = 0.0
    elif clearance_direction.dot(direction) < 0.0:
        available = distance_from_start
    else:
        available = distance_from_end

    if available >= MIN_START_GOAL_STRAIGHT_CM - RULE_TOLERANCE_CM:
        return None
    return IssueSegment(point, point + clearance_direction * MIN_START_GOAL_STRAIGHT_CM, "start_goal_clearance")


def format_clearance(clearance: float | None) -> str:
    if clearance is None:
        return "outside tangent"
    return f"{clearance:.1f} cm"
