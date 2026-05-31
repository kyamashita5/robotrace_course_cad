from __future__ import annotations

from robotrace_course_cad.model.course_model import CourseModel, HelperCircle
from robotrace_course_cad.model.course_solution import CourseSolution, TangentSegment, ValidationIssue
from robotrace_course_cad.solver.arcs import MIN_SEGMENT_LENGTH_CM, arc_angle_for_turn, generate_arcs
from robotrace_course_cad.solver.intersections import validate_intersections
from robotrace_course_cad.solver.markers import generate_corner_markers, generate_start_goal_segment_and_markers
from robotrace_course_cad.solver.tangents import choose_tangent_closest_to_point, oriented_tangent_candidates_by_turn

ZERO_LENGTH_TANGENT_EPSILON_CM = 1e-3


def solve_course(model: CourseModel) -> CourseSolution:
    circles = model.circles
    n = len(circles)
    issues: list[ValidationIssue] = []
    tangents: list[TangentSegment | None] = [None] * n

    if n < 2:
        issues.append(
            ValidationIssue(
                severity="error",
                message="At least two helper circles are required",
            )
        )
        return CourseSolution(tangents=tangents, arcs=[], issues=issues)

    c_last = circles[-1]
    c0 = circles[0]
    sg_candidates = oriented_tangent_candidates_by_turn(c_last, c0)
    if not sg_candidates:
        issues.append(
            ValidationIssue(
                severity="error",
                message="No tangent candidate for start-goal segment",
                related_circle_ids=[c_last.id, c0.id],
                related_connection_ids=[n - 1],
            )
        )
        return CourseSolution(tangents=tangents, arcs=[None] * n, issues=issues)

    sg_tangent = choose_tangent_closest_to_point(sg_candidates, model.start_goal_hint.center)
    tangents[n - 1] = sg_tangent
    prev_tangent = sg_tangent

    for i in range(n - 1):
        circle = circles[i]
        next_circle = circles[i + 1]
        candidates = oriented_tangent_candidates_by_turn(circle, next_circle)
        if not candidates:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"No tangent candidate between circle {circle.id} and {next_circle.id}",
                    related_circle_ids=[circle.id, next_circle.id],
                    related_connection_ids=[i],
                )
            )
            continue

        selected = choose_candidate_consistent_with_previous(circle, prev_tangent, candidates)
        tangents[i] = selected
        prev_tangent = selected

    for i, tangent in enumerate(tangents):
        if tangent is not None and ZERO_LENGTH_TANGENT_EPSILON_CM < tangent.length <= MIN_SEGMENT_LENGTH_CM:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message=f"Tangent {i} is short ({tangent.length:.1f} cm)",
                    related_circle_ids=[tangent.from_circle_id, tangent.to_circle_id],
                    related_connection_ids=[i],
                )
            )

    arcs, arc_issues = generate_arcs(circles, tangents)
    issues.extend(arc_issues)
    solution = CourseSolution(tangents=tangents, arcs=arcs, issues=issues)
    issues.extend(validate_intersections(solution))
    start_goal_segment, start_goal_markers = generate_start_goal_segment_and_markers(model, tangents)
    return CourseSolution(
        tangents=tangents,
        arcs=arcs,
        issues=issues,
        corner_markers=generate_corner_markers(solution),
        start_goal_segment=start_goal_segment,
        start_goal_markers=start_goal_markers,
    )


def choose_candidate_consistent_with_previous(
    circle: HelperCircle,
    prev_tangent: TangentSegment,
    candidates: list[TangentSegment],
) -> TangentSegment:
    def score(candidate: TangentSegment) -> tuple[int, float]:
        angle_rad = arc_angle_for_turn(circle, prev_tangent.p_to, candidate.p_from)
        length = circle.r * angle_rad
        penalty = 0
        if length <= 1e-6:
            penalty += 100
        if length <= MIN_SEGMENT_LENGTH_CM:
            penalty += 10
        return penalty, length

    return min(candidates, key=score)
