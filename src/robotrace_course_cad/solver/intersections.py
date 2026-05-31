from __future__ import annotations

from dataclasses import dataclass
import math

from robotrace_course_cad.model.course_model import Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CourseSolution, TangentSegment, ValidationIssue
from robotrace_course_cad.model.geometry import EPSILON, TAU, Vec2, angle_ccw, angle_cw, point_angle

ANGLE_TOLERANCE_DEG = 5.0
MIN_CROSSING_STRAIGHT_CM = 10.0
MIN_CROSSING_STRAIGHT_TOLERANCE_CM = 9.9
INTERSECTION_EPSILON = 1e-6


@dataclass(frozen=True)
class PathSegment:
    sequence_index: int
    kind: str
    index: int
    tangent: TangentSegment | None = None
    arc: ArcSegment | None = None

    @property
    def p_start(self) -> Vec2:
        if self.tangent is not None:
            return self.tangent.p_from
        assert self.arc is not None
        return self.arc.p_start

    @property
    def p_end(self) -> Vec2:
        if self.tangent is not None:
            return self.tangent.p_to
        assert self.arc is not None
        return self.arc.p_end

    @property
    def related_circle_ids(self) -> list[int]:
        if self.tangent is not None:
            return [self.tangent.from_circle_id, self.tangent.to_circle_id]
        assert self.arc is not None
        return [self.arc.circle_id]

    @property
    def related_connection_ids(self) -> list[int]:
        if self.tangent is not None:
            return [self.index]
        return []


@dataclass(frozen=True)
class LineLineIntersection:
    point: Vec2 | None
    overlapping: bool = False


def validate_intersections(solution: CourseSolution) -> list[ValidationIssue]:
    segments = path_segments(solution)
    issues: list[ValidationIssue] = []

    for i, first in enumerate(segments):
        for second in segments[i + 1 :]:
            if are_adjacent(first, second, len(segments)):
                continue

            if first.kind == "line" and second.kind == "line":
                issue = validate_line_line_intersection(first, second)
            elif first.kind == "line" and second.kind == "arc":
                issue = validate_line_arc_intersection(first, second)
            elif first.kind == "arc" and second.kind == "line":
                issue = validate_line_arc_intersection(second, first)
            else:
                issue = validate_arc_arc_intersection(first, second)

            if issue is not None:
                issues.append(issue)

    return issues


def path_segments(solution: CourseSolution) -> list[PathSegment]:
    n = max(len(solution.arcs), len(solution.tangents))
    segments: list[PathSegment] = []

    for i in range(n):
        if i < len(solution.arcs) and solution.arcs[i] is not None:
            segments.append(PathSegment(len(segments), "arc", i, arc=solution.arcs[i]))
        if i < len(solution.tangents) and solution.tangents[i] is not None:
            segments.append(PathSegment(len(segments), "line", i, tangent=solution.tangents[i]))

    return segments


def are_adjacent(first: PathSegment, second: PathSegment, segment_count: int) -> bool:
    distance = abs(first.sequence_index - second.sequence_index)
    return distance == 1 or distance == segment_count - 1 or segments_share_endpoint(first, second)


def segments_share_endpoint(first: PathSegment, second: PathSegment) -> bool:
    first_points = [first.p_start, first.p_end]
    second_points = [second.p_start, second.p_end]
    return any(a.distance_to(b) < 1e-4 for a in first_points for b in second_points)


def validate_line_line_intersection(first: PathSegment, second: PathSegment) -> ValidationIssue | None:
    intersection = line_line_intersection(first.p_start, first.p_end, second.p_start, second.p_end)
    if intersection is None:
        return None

    if intersection.overlapping or intersection.point is None:
        return intersection_issue("Line segments overlap or touch ambiguously", first, second)

    point = intersection.point
    angle = line_crossing_angle_deg(first.p_start, first.p_end, second.p_start, second.p_end)
    distances = [
        point.distance_to(first.p_start),
        point.distance_to(first.p_end),
        point.distance_to(second.p_start),
        point.distance_to(second.p_end),
    ]
    min_endpoint_distance = min(distances)

    if abs(angle - 90.0) <= ANGLE_TOLERANCE_DEG and min_endpoint_distance >= MIN_CROSSING_STRAIGHT_TOLERANCE_CM:
        return intersection_issue(
            (
                "Valid line-line crossing: "
                f"angle={angle:.1f} deg, nearest endpoint={min_endpoint_distance:.1f} cm"
            ),
            first,
            second,
            severity="info",
        )

    return intersection_issue(
        (
            "Invalid line-line crossing: "
            f"angle={angle:.1f} deg, nearest endpoint={min_endpoint_distance:.1f} cm"
        ),
        first,
        second,
    )


def validate_line_arc_intersection(line: PathSegment, arc_segment: PathSegment) -> ValidationIssue | None:
    assert arc_segment.arc is not None
    intersections = line_arc_intersections(line.p_start, line.p_end, arc_segment.arc)
    if not intersections:
        return None

    return intersection_issue("Line segment intersects an arc segment", line, arc_segment)


def validate_arc_arc_intersection(first: PathSegment, second: PathSegment) -> ValidationIssue | None:
    assert first.arc is not None
    assert second.arc is not None
    intersections = arc_arc_intersections(first.arc, second.arc)
    if not intersections:
        return None

    return intersection_issue("Arc segment intersects another arc segment", first, second)


def intersection_issue(message: str, first: PathSegment, second: PathSegment, severity: str = "error") -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        message=f"{message} ({first.kind} {first.index} vs {second.kind} {second.index})",
        related_circle_ids=unique(first.related_circle_ids + second.related_circle_ids),
        related_connection_ids=unique(first.related_connection_ids + second.related_connection_ids),
    )


def line_line_intersection(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> LineLineIntersection | None:
    r = b - a
    s = d - c
    denom = r.cross(s)
    cma = c - a

    if abs(denom) < INTERSECTION_EPSILON:
        if abs(cma.cross(r)) > INTERSECTION_EPSILON:
            return None
        if collinear_segments_overlap(a, b, c, d):
            return LineLineIntersection(None, overlapping=True)
        return None

    t = cma.cross(s) / denom
    u = cma.cross(r) / denom
    if -INTERSECTION_EPSILON <= t <= 1.0 + INTERSECTION_EPSILON and -INTERSECTION_EPSILON <= u <= 1.0 + INTERSECTION_EPSILON:
        return LineLineIntersection(a + r * clamp01(t))

    return None


def collinear_segments_overlap(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> bool:
    ab = b - a
    denom = ab.dot(ab)
    if denom < EPSILON:
        return a.distance_to(c) < INTERSECTION_EPSILON or a.distance_to(d) < INTERSECTION_EPSILON

    t0 = (c - a).dot(ab) / denom
    t1 = (d - a).dot(ab) / denom
    lo = max(0.0, min(t0, t1))
    hi = min(1.0, max(t0, t1))
    return lo <= hi + INTERSECTION_EPSILON


def line_crossing_angle_deg(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> float:
    u = (b - a).normalized()
    v = (d - c).normalized()
    dot = abs(max(-1.0, min(1.0, u.dot(v))))
    return math.degrees(math.acos(dot))


def line_arc_intersections(a: Vec2, b: Vec2, arc: ArcSegment) -> list[Vec2]:
    ab = b - a
    center_to_a = a - arc.center
    qa = ab.dot(ab)
    qb = 2.0 * center_to_a.dot(ab)
    qc = center_to_a.dot(center_to_a) - arc.radius * arc.radius

    if qa < EPSILON:
        return [a] if arc_contains_point(arc, a) else []

    discriminant = qb * qb - 4.0 * qa * qc
    if discriminant < -INTERSECTION_EPSILON:
        return []

    roots: list[float]
    if abs(discriminant) <= INTERSECTION_EPSILON:
        roots = [-qb / (2.0 * qa)]
    else:
        sqrt_disc = math.sqrt(max(0.0, discriminant))
        roots = [(-qb - sqrt_disc) / (2.0 * qa), (-qb + sqrt_disc) / (2.0 * qa)]

    points: list[Vec2] = []
    for t in roots:
        if -INTERSECTION_EPSILON <= t <= 1.0 + INTERSECTION_EPSILON:
            point = a + ab * clamp01(t)
            if arc_contains_point(arc, point):
                append_unique_point(points, point)
    return points


def arc_arc_intersections(first: ArcSegment, second: ArcSegment) -> list[Vec2]:
    center_delta = second.center - first.center
    distance = center_delta.norm()

    if distance < INTERSECTION_EPSILON:
        if abs(first.radius - second.radius) < INTERSECTION_EPSILON and arcs_share_any_endpoint(first, second):
            return [first.p_start]
        return []

    if distance > first.radius + second.radius + INTERSECTION_EPSILON:
        return []
    if distance < abs(first.radius - second.radius) - INTERSECTION_EPSILON:
        return []

    a = (first.radius * first.radius - second.radius * second.radius + distance * distance) / (2.0 * distance)
    h2 = first.radius * first.radius - a * a
    if h2 < -INTERSECTION_EPSILON:
        return []

    base = first.center + center_delta * (a / distance)
    if abs(h2) <= INTERSECTION_EPSILON:
        points = [base]
    else:
        h = math.sqrt(max(0.0, h2))
        offset = Vec2(-center_delta.y / distance * h, center_delta.x / distance * h)
        points = [base + offset, base - offset]

    return [point for point in points if arc_contains_point(first, point) and arc_contains_point(second, point)]


def arc_contains_point(arc: ArcSegment, point: Vec2) -> bool:
    radial_error = abs(point.distance_to(arc.center) - arc.radius)
    if radial_error > 1e-4:
        return False

    start = point_angle(arc.center, arc.p_start)
    candidate = point_angle(arc.center, point)
    if arc.turn == Turn.CCW:
        delta = angle_ccw(start, candidate)
    else:
        delta = angle_cw(start, candidate)
    return -1e-7 <= delta <= arc.angle_rad + 1e-7 or abs(delta - TAU) < 1e-7


def arcs_share_any_endpoint(first: ArcSegment, second: ArcSegment) -> bool:
    endpoints_first = [first.p_start, first.p_end]
    endpoints_second = [second.p_start, second.p_end]
    return any(a.distance_to(b) < INTERSECTION_EPSILON for a in endpoints_first for b in endpoints_second)


def append_unique_point(points: list[Vec2], point: Vec2) -> None:
    if not any(existing.distance_to(point) < INTERSECTION_EPSILON for existing in points):
        points.append(point)


def unique(values: list[int]) -> list[int]:
    result: list[int] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
