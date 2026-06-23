#!/usr/bin/env python3
"""Fit a traced course centerline with tangent-continuous line and arc segments."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np


OUT_DIR = Path("tmp/line_arc_path_fitting")
SegmentKind = Literal["line", "arc"]


@dataclass(frozen=True)
class FitConfig:
    # The traced point TSV uses board coordinates in centimeters.
    resample_spacing: float = 2.0
    remove_duplicate_eps: float = 1e-9
    rdp_epsilon: float = 0.5
    fit_tolerance: float = 1.0
    curvature_threshold: float = 0.02
    curvature_change_threshold: float = 0.02
    candidate_neighbor_count: int = 2
    max_candidate_spacing_straight: float = 100.0
    max_candidate_spacing_curve: float = 30.0
    max_candidate_spacing_sharp: float = 10.0
    min_segment_points: int = 3
    max_segment_length: float = 400.0
    min_segment_length: float = 0.0
    min_arc_points: int = 4
    min_arc_angle_deg: float = 3.0
    max_arc_angle_deg: float = 270.0
    min_radius: float = 10.0
    max_radius: float = 100000.0
    quantize_arc_radius: bool = True
    arc_radius_step: float = 5.0
    arc_radius_neighbor_steps: int = 1
    line_cost_bias: float = 0.0
    arc_cost_bias: float = 0.05
    short_segment_penalty: float = 8.0
    min_preferred_segment_length: float = 8.0
    fit_error_weight: float = 3.0
    tangent_tolerance_deg: float = 3.0
    tangent_soft_limit_deg: float = 5.0
    max_tangent_angle_error_deg: float = 10.0
    tangent_weight: float = 5.0
    tangent_soft_penalty: float = 50.0
    type_switch_penalty: float = 0.0
    same_radius_same_turn_arc_penalty: float = 2.0
    same_radius_tolerance: float = 1e-6
    start_cm: tuple[float, float] | None = None
    goal_cm: tuple[float, float] | None = None
    board_width_cm: float | None = None
    board_height_cm: float | None = None
    grid_cell_width_cm: float = 90.0
    grid_cell_height_cm: float = 90.0
    debug_keep_rejected_transitions: bool = False

    @property
    def min_arc_angle(self) -> float:
        return math.radians(self.min_arc_angle_deg)

    @property
    def max_arc_angle(self) -> float:
        return math.radians(self.max_arc_angle_deg)

    @property
    def tangent_tolerance(self) -> float:
        return math.radians(self.tangent_tolerance_deg)

    @property
    def tangent_soft_limit(self) -> float:
        return math.radians(self.tangent_soft_limit_deg)

    @property
    def max_tangent_angle_error(self) -> float:
        return math.radians(self.max_tangent_angle_error_deg)


@dataclass(frozen=True)
class LineSegment:
    kind: SegmentKind
    start_idx: int
    end_idx: int
    p0: tuple[float, float]
    p1: tuple[float, float]
    length: float
    max_error: float
    start_tangent: tuple[float, float]
    end_tangent: tuple[float, float]


@dataclass(frozen=True)
class ArcSegment:
    kind: SegmentKind
    start_idx: int
    end_idx: int
    p0: tuple[float, float]
    p1: tuple[float, float]
    center: tuple[float, float]
    radius: float
    clockwise: bool
    theta0: float
    theta1: float
    delta_theta: float
    arc_length: float
    max_error: float
    start_tangent: tuple[float, float]
    end_tangent: tuple[float, float]


Segment = LineSegment | ArcSegment


@dataclass(frozen=True)
class SegmentHypothesis:
    id: int
    segment: Segment
    start_idx: int
    end_idx: int
    start_tangent: tuple[float, float]
    end_tangent: tuple[float, float]
    base_cost: float


@dataclass
class DagDebugStats:
    candidate_count: int = 0
    hypothesis_count: int = 0
    start_hypothesis_count: int = 0
    final_hypothesis_count: int = 0
    interval_count: int = 0
    interval_without_fit_count: int = 0
    short_hypothesis_rejected_count: int = 0
    line_hypothesis_count: int = 0
    arc_hypothesis_count: int = 0
    transition_count: int = 0
    rejected_transition_count: int = 0
    reachable_hypothesis_count: int = 0
    rejected_transitions: list[dict[str, int | float | str]] | None = None


@dataclass(frozen=True)
class FitResult:
    source_point_count: int
    fit_point_count: int
    candidate_count: int
    segment_count: int
    max_segment_error: float
    max_tangent_error_deg: float
    tangent_warnings: list[dict[str, int | float]]
    connection_report: list[dict[str, int | float | str]]
    debug_stats: DagDebugStats
    segments: list[Segment]
    fit_points: np.ndarray
    candidate_indices: list[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace_points_tsv", help="trace_centerline_points.py output TSV")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--name")
    parser.add_argument("--resample-spacing", type=float, default=FitConfig.resample_spacing)
    parser.add_argument("--rdp-epsilon", type=float, default=FitConfig.rdp_epsilon)
    parser.add_argument("--fit-tolerance", type=float, default=FitConfig.fit_tolerance)
    parser.add_argument("--curvature-threshold", type=float, default=FitConfig.curvature_threshold)
    parser.add_argument("--curvature-change-threshold", type=float, default=FitConfig.curvature_change_threshold)
    parser.add_argument("--candidate-neighbor-count", type=int, default=FitConfig.candidate_neighbor_count)
    parser.add_argument("--max-segment-length", type=float, default=FitConfig.max_segment_length)
    parser.add_argument(
        "--min-segment-length",
        type=float,
        default=FitConfig.min_segment_length,
        help="discard segment hypotheses with length less than or equal to this many centimeters; 0 disables hard rejection",
    )
    parser.add_argument("--min-preferred-segment-length", type=float, default=FitConfig.min_preferred_segment_length)
    parser.add_argument("--short-segment-penalty", type=float, default=FitConfig.short_segment_penalty)
    parser.add_argument("--fit-error-weight", type=float, default=FitConfig.fit_error_weight)
    parser.add_argument("--min-radius", type=float, default=FitConfig.min_radius)
    parser.add_argument("--max-radius", type=float, default=FitConfig.max_radius)
    parser.add_argument("--arc-radius-step", type=float, default=FitConfig.arc_radius_step)
    parser.add_argument("--arc-radius-neighbor-steps", type=int, default=FitConfig.arc_radius_neighbor_steps)
    parser.add_argument("--no-quantize-arc-radius", action="store_true")
    parser.add_argument("--arc-cost-bias", type=float, default=FitConfig.arc_cost_bias)
    parser.add_argument("--tangent-tolerance-deg", type=float, default=FitConfig.tangent_tolerance_deg)
    parser.add_argument("--tangent-soft-limit-deg", type=float, default=FitConfig.tangent_soft_limit_deg)
    parser.add_argument("--max-tangent-angle-error-deg", type=float, default=FitConfig.max_tangent_angle_error_deg)
    parser.add_argument("--tangent-weight", type=float, default=FitConfig.tangent_weight)
    parser.add_argument("--tangent-soft-penalty", type=float, default=FitConfig.tangent_soft_penalty)
    parser.add_argument("--type-switch-penalty", type=float, default=FitConfig.type_switch_penalty)
    parser.add_argument("--same-radius-same-turn-arc-penalty", type=float, default=FitConfig.same_radius_same_turn_arc_penalty)
    parser.add_argument("--start-cm", help="confirmed START point as x,y in board cm; defaults to sibling report.json")
    parser.add_argument("--goal-cm", help="confirmed GOAL point as x,y in board cm; defaults to sibling report.json")
    parser.add_argument("--board-width-cm", type=float, help="board width for the additional course CAD JSON")
    parser.add_argument("--board-height-cm", type=float, help="board height for the additional course CAD JSON")
    parser.add_argument("--grid-cell-width-cm", type=float, default=FitConfig.grid_cell_width_cm)
    parser.add_argument("--grid-cell-height-cm", type=float, default=FitConfig.grid_cell_height_cm)
    parser.add_argument("--debug-keep-rejected-transitions", action="store_true")
    parser.add_argument("--write-svg", action="store_true", help="write a simple debug SVG next to the JSON")
    return parser.parse_args()


def point_tuple(point: np.ndarray) -> tuple[float, float]:
    return (round(float(point[0]), 6), round(float(point[1]), 6))


def vector_tuple(vector: np.ndarray) -> tuple[float, float]:
    return (round(float(vector[0]), 9), round(float(vector[1]), 9))


def cross2(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError("zero-length vector")
    return vector / norm


def normalize_ccw(angle: float) -> float:
    value = math.fmod(angle, 2.0 * math.pi)
    if value < 0.0:
        value += 2.0 * math.pi
    return value


def parse_point_cm(raw_value: str) -> tuple[float, float]:
    values = [token.strip() for token in raw_value.split(",")]
    if len(values) != 2:
        raise ValueError(f"invalid point format: {raw_value}")
    return float(values[0]), float(values[1])


def load_trace_points(path: Path) -> np.ndarray:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or "x_cm" not in reader.fieldnames or "y_cm" not in reader.fieldnames:
            raise ValueError("trace TSV must contain x_cm and y_cm columns")
        points = [(float(row["x_cm"]), float(row["y_cm"])) for row in reader]
    if len(points) < 2:
        raise ValueError("at least two points are required")
    return np.asarray(points, dtype=np.float64)


def load_metadata_from_report(
    trace_points_path: Path,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None, float | None, float | None]:
    report_path = trace_points_path.with_name("report.json")
    if not report_path.exists():
        return None, None, None, None
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    start = payload.get("start_cm")
    goal = payload.get("goal_cm")
    board = payload.get("board", {})
    board_width_cm = board.get("width_cm") if isinstance(board, dict) else None
    board_height_cm = board.get("height_cm") if isinstance(board, dict) else None
    if not isinstance(start, list) or not isinstance(goal, list) or len(start) != 2 or len(goal) != 2:
        return None, None, float(board_width_cm) if board_width_cm is not None else None, float(board_height_cm) if board_height_cm is not None else None
    return (
        (float(start[0]), float(start[1])),
        (float(goal[0]), float(goal[1])),
        float(board_width_cm) if board_width_cm is not None else None,
        float(board_height_cm) if board_height_cm is not None else None,
    )


def remove_duplicate_points(points: np.ndarray, eps: float) -> np.ndarray:
    keep = [0]
    for index in range(1, len(points)):
        if float(np.linalg.norm(points[index] - points[keep[-1]])) >= eps:
            keep.append(index)
    return points[keep]


def cumulative_lengths(points: np.ndarray) -> np.ndarray:
    if len(points) == 0:
        return np.zeros(0, dtype=np.float64)
    distances = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return np.concatenate(([0.0], np.cumsum(distances)))


def resample_polyline(points: np.ndarray, spacing: float) -> np.ndarray:
    if len(points) < 2 or spacing <= 0.0:
        return points.copy()
    lengths = cumulative_lengths(points)
    total = float(lengths[-1])
    if total <= spacing:
        return points.copy()

    sample_distances = list(np.arange(0.0, total, spacing))
    if not math.isclose(sample_distances[-1], total):
        sample_distances.append(total)

    result: list[np.ndarray] = []
    segment_index = 0
    for distance in sample_distances:
        while segment_index < len(lengths) - 2 and lengths[segment_index + 1] < distance:
            segment_index += 1
        span = lengths[segment_index + 1] - lengths[segment_index]
        if span <= 1e-12:
            result.append(points[segment_index].copy())
            continue
        t = (distance - lengths[segment_index]) / span
        result.append(points[segment_index] * (1.0 - t) + points[segment_index + 1] * t)
    return np.stack(result, axis=0)


def preprocess_points(points: np.ndarray, config: FitConfig) -> np.ndarray:
    cleaned = remove_duplicate_points(points, config.remove_duplicate_eps)
    return resample_polyline(cleaned, config.resample_spacing)


def point_to_segment_distances(points: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
    segment = p1 - p0
    denom = float(np.dot(segment, segment))
    if denom <= 1e-12:
        return np.linalg.norm(points - p0[None, :], axis=1)
    t = ((points - p0[None, :]) @ segment) / denom
    t = np.clip(t, 0.0, 1.0)
    projections = p0[None, :] + t[:, None] * segment[None, :]
    return np.linalg.norm(points - projections, axis=1)


def rdp_indices(points: np.ndarray, epsilon: float) -> list[int]:
    if len(points) <= 2:
        return list(range(len(points)))

    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end - start <= 1:
            continue
        interior = points[start + 1 : end]
        distances = point_to_segment_distances(interior, points[start], points[end])
        local_index = int(np.argmax(distances))
        if float(distances[local_index]) > epsilon:
            index = start + 1 + local_index
            keep.add(index)
            stack.append((start, index))
            stack.append((index, end))
    return sorted(keep)


def compute_curvature(points: np.ndarray) -> np.ndarray:
    curvature = np.zeros(len(points), dtype=np.float64)
    for index in range(1, len(points) - 1):
        v_prev = points[index] - points[index - 1]
        v_next = points[index + 1] - points[index]
        norm_prev = float(np.linalg.norm(v_prev))
        norm_next = float(np.linalg.norm(v_next))
        ds = 0.5 * (norm_prev + norm_next)
        if ds <= 1e-12 or norm_prev <= 1e-12 or norm_next <= 1e-12:
            continue
        theta = math.atan2(cross2(v_prev, v_next), float(np.dot(v_prev, v_next)))
        curvature[index] = theta / ds
    if len(curvature) >= 5:
        padded = np.pad(curvature, (2, 2), mode="edge")
        curvature = np.convolve(padded, np.ones(5, dtype=np.float64) / 5.0, mode="valid")
    return curvature


def curvature_candidate_indices(curvature: np.ndarray, config: FitConfig) -> set[int]:
    candidates: set[int] = set()
    for index in range(1, len(curvature) - 1):
        current = curvature[index]
        previous = curvature[index - 1]
        if abs(current) > config.curvature_threshold:
            candidates.add(index)
        if abs(current - previous) > config.curvature_change_threshold:
            candidates.add(index)
        if current * previous < 0.0:
            candidates.add(index)
        if (abs(current) > config.curvature_threshold) != (abs(previous) > config.curvature_threshold):
            candidates.add(index)
    return candidates


def add_spacing_candidates(
    candidates: set[int],
    arc_lengths: np.ndarray,
    curvature: np.ndarray,
    config: FitConfig,
) -> None:
    ordered = sorted(candidates)
    for start, end in zip(ordered[:-1], ordered[1:]):
        distance = float(arc_lengths[end] - arc_lengths[start])
        if distance <= 0.0:
            continue
        local_abs_curvature = float(np.max(np.abs(curvature[start : end + 1]))) if end > start else 0.0
        if local_abs_curvature < config.curvature_threshold * 0.5:
            max_spacing = config.max_candidate_spacing_straight
        elif local_abs_curvature < config.curvature_threshold * 2.0:
            max_spacing = config.max_candidate_spacing_curve
        else:
            max_spacing = config.max_candidate_spacing_sharp
        if distance <= max_spacing:
            continue
        pieces = int(math.ceil(distance / max_spacing))
        for piece in range(1, pieces):
            target_distance = arc_lengths[start] + distance * piece / pieces
            candidates.add(int(np.searchsorted(arc_lengths, target_distance)))


def add_neighbor_candidates(candidates: set[int], point_count: int, neighbor_count: int) -> set[int]:
    expanded: set[int] = set()
    for index in candidates:
        for offset in range(-neighbor_count, neighbor_count + 1):
            candidate = index + offset
            if 0 <= candidate < point_count:
                expanded.add(candidate)
    return expanded


def build_candidate_indices(points: np.ndarray, config: FitConfig) -> list[int]:
    curvature = compute_curvature(points)
    candidates = {0, len(points) - 1}
    candidates.update(rdp_indices(points, config.rdp_epsilon))
    candidates.update(curvature_candidate_indices(curvature, config))
    add_spacing_candidates(candidates, cumulative_lengths(points), curvature, config)
    candidates = add_neighbor_candidates(candidates, len(points), config.candidate_neighbor_count)
    return sorted(candidates)


def line_tangent(p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
    return normalize_vector(p1 - p0)


def start_goal_line_points(config: FitConfig) -> tuple[np.ndarray, np.ndarray] | None:
    if config.start_cm is None or config.goal_cm is None:
        return None
    start = np.asarray(config.start_cm, dtype=np.float64)
    goal = np.asarray(config.goal_cm, dtype=np.float64)
    if float(np.linalg.norm(start - goal)) <= 1e-9:
        return None
    return start, goal


def project_to_line(point: np.ndarray, line_p0: np.ndarray, line_p1: np.ndarray) -> np.ndarray:
    vector = line_p1 - line_p0
    t = float(np.dot(point - line_p0, vector) / np.dot(vector, vector))
    return line_p0 + t * vector


def arc_tangent_at(point: np.ndarray, center: np.ndarray, clockwise: bool) -> np.ndarray:
    radial = normalize_vector(point - center)
    if clockwise:
        return np.asarray([radial[1], -radial[0]], dtype=np.float64)
    return np.asarray([-radial[1], radial[0]], dtype=np.float64)


def fit_line(points: np.ndarray, start_idx: int, end_idx: int, config: FitConfig) -> LineSegment | None:
    if end_idx - start_idx + 1 < config.min_segment_points:
        return None
    p0 = points[start_idx]
    p1 = points[end_idx]
    length = float(np.linalg.norm(p1 - p0))
    if length <= 1e-12:
        return None
    interval = points[start_idx : end_idx + 1]
    max_error = float(np.max(point_to_segment_distances(interval, p0, p1)))
    if max_error > config.fit_tolerance:
        return None
    tangent = line_tangent(p0, p1)
    return LineSegment(
        kind="line",
        start_idx=start_idx,
        end_idx=end_idx,
        p0=point_tuple(p0),
        p1=point_tuple(p1),
        length=round(length, 6),
        max_error=round(max_error, 6),
        start_tangent=vector_tuple(tangent),
        end_tangent=vector_tuple(tangent),
    )


def fit_start_goal_line_segment(points: np.ndarray, start_idx: int, end_idx: int, config: FitConfig) -> LineSegment | None:
    line_points = start_goal_line_points(config)
    if line_points is None:
        return None
    if start_idx != 0 and end_idx != len(points) - 1:
        return None

    start_cm, goal_cm = line_points
    interval = points[start_idx : end_idx + 1]
    if len(interval) < 2:
        return None

    if start_idx == 0:
        p0 = start_cm
    else:
        p0 = project_to_line(points[start_idx], start_cm, goal_cm)
    if end_idx == len(points) - 1:
        p1 = goal_cm
    else:
        p1 = project_to_line(points[end_idx], start_cm, goal_cm)

    length = float(np.linalg.norm(p1 - p0))
    if length <= 1e-12:
        return None
    max_error = float(np.max(point_to_segment_distances(interval, p0, p1)))
    if max_error > config.fit_tolerance:
        return None
    tangent = line_tangent(p0, p1)
    return LineSegment(
        kind="line",
        start_idx=start_idx,
        end_idx=end_idx,
        p0=point_tuple(p0),
        p1=point_tuple(p1),
        length=round(length, 6),
        max_error=round(max_error, 6),
        start_tangent=vector_tuple(tangent),
        end_tangent=vector_tuple(tangent),
    )


def fit_circle_kasa(interval: np.ndarray) -> tuple[np.ndarray, float] | None:
    x = interval[:, 0]
    y = interval[:, 1]
    matrix = np.column_stack((x, y, np.ones_like(x)))
    rhs = -(x * x + y * y)
    try:
        a, b, c = np.linalg.lstsq(matrix, rhs, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    radius_squared = (a * a + b * b) / 4.0 - c
    if radius_squared <= 0.0 or not np.isfinite(radius_squared):
        return None
    return np.asarray([-a / 2.0, -b / 2.0], dtype=np.float64), math.sqrt(float(radius_squared))


def quantized_radius_candidates(initial_radius: float, config: FitConfig) -> list[float]:
    if not config.quantize_arc_radius:
        return [initial_radius]
    step = config.arc_radius_step
    if step <= 0.0:
        raise ValueError("arc_radius_step must be positive")
    min_radius = max(config.min_radius, step * math.ceil(config.min_radius / step))
    nearest = int(round(initial_radius / step))
    candidates: set[float] = set()
    for offset in range(-config.arc_radius_neighbor_steps, config.arc_radius_neighbor_steps + 1):
        radius = (nearest + offset) * step
        if min_radius <= radius <= config.max_radius:
            candidates.add(round(radius, 9))
    if not candidates:
        radius = step * round(initial_radius / step)
        radius = min(max(radius, min_radius), config.max_radius)
        candidates.add(round(radius, 9))
    return sorted(candidates)


def endpoint_circle_centers(p0: np.ndarray, p1: np.ndarray, radius: float) -> list[np.ndarray]:
    chord = p1 - p0
    chord_length = float(np.linalg.norm(chord))
    if chord_length <= 1e-12 or chord_length > 2.0 * radius + 1e-9:
        return []
    midpoint = (p0 + p1) * 0.5
    half_chord = chord_length * 0.5
    height_sq = radius * radius - half_chord * half_chord
    height = math.sqrt(max(0.0, height_sq))
    normal = np.asarray([-chord[1], chord[0]], dtype=np.float64) / chord_length
    return [midpoint + normal * height, midpoint - normal * height]


def score_fixed_radius_center(interval: np.ndarray, radius: float, center: np.ndarray) -> tuple[float, float]:
    distances = np.linalg.norm(interval - center[None, :], axis=1)
    residuals = distances - radius
    max_error = float(np.max(np.abs(residuals)))
    rms_error = float(math.sqrt(np.mean(residuals * residuals)))
    return max_error, rms_error


def fit_quantized_circle(interval: np.ndarray, initial_center: np.ndarray, initial_radius: float, config: FitConfig) -> tuple[np.ndarray, float, float] | None:
    if not config.quantize_arc_radius:
        max_error, _rms_error = score_fixed_radius_center(interval, initial_radius, initial_center)
        return initial_center, initial_radius, max_error

    best: tuple[np.ndarray, float, float, float] | None = None
    p0 = interval[0]
    p1 = interval[-1]
    for radius in quantized_radius_candidates(initial_radius, config):
        if radius < config.min_radius or radius > config.max_radius:
            continue
        for center in endpoint_circle_centers(p0, p1, radius):
            max_error, rms_error = score_fixed_radius_center(interval, radius, center)
            score = rms_error
            if best is None or (score, max_error) < (best[3], best[2]):
                best = (center, radius, max_error, score)
    if best is None:
        return None
    return best[0], best[1], best[2]


def arc_progress(theta: float, theta0: float, clockwise: bool) -> float:
    if clockwise:
        return normalize_ccw(theta0 - theta)
    return normalize_ccw(theta - theta0)


def fit_arc(points: np.ndarray, start_idx: int, end_idx: int, config: FitConfig) -> ArcSegment | None:
    if end_idx - start_idx + 1 < config.min_arc_points:
        return None
    interval = points[start_idx : end_idx + 1]
    circle = fit_circle_kasa(interval)
    if circle is None:
        return None
    initial_center, initial_radius = circle
    if initial_radius < config.min_radius or initial_radius > config.max_radius:
        return None
    initial_radial_distances = np.linalg.norm(interval - initial_center[None, :], axis=1)
    initial_max_error = float(np.max(np.abs(initial_radial_distances - initial_radius)))
    if initial_max_error > config.fit_tolerance:
        return None

    fitted_circle = fit_quantized_circle(interval, initial_center, initial_radius, config)
    if fitted_circle is None:
        return None
    center, radius, max_error = fitted_circle
    if radius < config.min_radius or radius > config.max_radius:
        return None

    if max_error > config.fit_tolerance:
        return None

    p0 = points[start_idx]
    p1 = points[end_idx]
    theta0 = math.atan2(float(p0[1] - center[1]), float(p0[0] - center[0]))
    theta1 = math.atan2(float(p1[1] - center[1]), float(p1[0] - center[0]))
    radial = interval - center[None, :]
    signed_area = sum(cross2(previous, current) for previous, current in zip(radial[:-1], radial[1:]))
    if abs(signed_area) <= 1e-9:
        return None
    clockwise = signed_area < 0.0
    if clockwise:
        delta_theta = -normalize_ccw(theta0 - theta1)
        arc_span = -delta_theta
    else:
        delta_theta = normalize_ccw(theta1 - theta0)
        arc_span = delta_theta
    if abs(delta_theta) < config.min_arc_angle or abs(delta_theta) > config.max_arc_angle:
        return None

    angles = np.arctan2(interval[:, 1] - center[1], interval[:, 0] - center[0])
    progresses = np.asarray([arc_progress(float(angle), theta0, clockwise) for angle in angles])
    angle_slop = max(config.fit_tolerance / max(radius, 1e-9), math.radians(2.0))
    if np.any(progresses > arc_span + angle_slop):
        return None
    if float(np.max(np.diff(progresses))) > math.pi:
        return None

    start_tangent = arc_tangent_at(p0, center, clockwise)
    end_tangent = arc_tangent_at(p1, center, clockwise)
    return ArcSegment(
        kind="arc",
        start_idx=start_idx,
        end_idx=end_idx,
        p0=point_tuple(p0),
        p1=point_tuple(p1),
        center=point_tuple(center),
        radius=round(radius, 6),
        clockwise=clockwise,
        theta0=round(theta0, 9),
        theta1=round(theta1, 9),
        delta_theta=round(delta_theta, 9),
        arc_length=round(radius * abs(delta_theta), 6),
        max_error=round(max_error, 6),
        start_tangent=vector_tuple(start_tangent),
        end_tangent=vector_tuple(end_tangent),
    )


def evaluate_interval(points: np.ndarray, start_idx: int, end_idx: int, config: FitConfig) -> list[Segment]:
    if (start_idx == 0 or end_idx == len(points) - 1) and start_goal_line_points(config) is not None:
        forced_line = fit_start_goal_line_segment(points, start_idx, end_idx, config)
        return [forced_line] if forced_line is not None else []

    segments: list[Segment] = []
    line = fit_line(points, start_idx, end_idx, config)
    if line is not None:
        segments.append(line)
    arc = fit_arc(points, start_idx, end_idx, config)
    if arc is not None:
        segments.append(arc)
    return segments


def segment_length(segment: Segment) -> float:
    return segment.length if isinstance(segment, LineSegment) else segment.arc_length


def base_segment_cost(segment: Segment, config: FitConfig) -> float:
    cost = 1.0 + (config.line_cost_bias if segment.kind == "line" else config.arc_cost_bias)
    length = segment_length(segment)
    if length <= config.min_preferred_segment_length:
        short_ratio = (config.min_preferred_segment_length - length) / max(config.min_preferred_segment_length, 1e-9)
        cost += config.short_segment_penalty * (1.0 + short_ratio * short_ratio)
    if config.fit_error_weight > 0.0 and config.fit_tolerance > 0.0:
        error_ratio = segment.max_error / config.fit_tolerance
        cost += config.fit_error_weight * error_ratio * error_ratio
    return cost


def is_short_hypothesis(segment: Segment, config: FitConfig) -> bool:
    return config.min_segment_length > 0.0 and segment_length(segment) <= config.min_segment_length


def angle_between_tangents(t0: tuple[float, float] | np.ndarray, t1: tuple[float, float] | np.ndarray) -> float:
    v0 = normalize_vector(np.asarray(t0, dtype=np.float64))
    v1 = normalize_vector(np.asarray(t1, dtype=np.float64))
    dot_value = float(np.clip(np.dot(v0, v1), -1.0, 1.0))
    return float(math.acos(dot_value))


def tangent_angle_penalty(angle: float, config: FitConfig) -> float:
    penalty = config.tangent_weight * max(0.0, angle - config.tangent_tolerance) ** 2
    if angle > config.tangent_soft_limit:
        soft_scale = max(config.tangent_soft_limit, 1e-9)
        soft_ratio = (angle - config.tangent_soft_limit) / soft_scale
        penalty += config.tangent_soft_penalty * soft_ratio**4
    return penalty


def same_radius_same_turn_arc_pair(left: Segment, right: Segment, config: FitConfig) -> bool:
    if not isinstance(left, ArcSegment) or not isinstance(right, ArcSegment):
        return False
    if left.clockwise != right.clockwise:
        return False
    return abs(left.radius - right.radius) <= config.same_radius_tolerance


def segment_transition_penalty(left: Segment, right: Segment, angle: float, config: FitConfig) -> float:
    penalty = tangent_angle_penalty(angle, config)
    if left.kind != right.kind:
        penalty += config.type_switch_penalty
    if same_radius_same_turn_arc_pair(left, right, config):
        penalty += config.same_radius_same_turn_arc_penalty
    return penalty


def transition_cost(prev: SegmentHypothesis, curr: SegmentHypothesis, config: FitConfig) -> tuple[float, float] | None:
    if prev.end_idx != curr.start_idx:
        return None
    angle = angle_between_tangents(prev.end_tangent, curr.start_tangent)
    if angle >= config.max_tangent_angle_error:
        return None
    penalty = segment_transition_penalty(prev.segment, curr.segment, angle, config)
    return penalty, angle


def build_segment_hypotheses(
    points: np.ndarray,
    candidate_indices: list[int],
    config: FitConfig,
) -> tuple[list[SegmentHypothesis], dict[int, list[SegmentHypothesis]], dict[int, list[SegmentHypothesis]], DagDebugStats]:
    arc_lengths = cumulative_lengths(points)
    hypotheses: list[SegmentHypothesis] = []
    by_start: dict[int, list[SegmentHypothesis]] = defaultdict(list)
    by_end: dict[int, list[SegmentHypothesis]] = defaultdict(list)
    stats = DagDebugStats(candidate_count=len(candidate_indices))

    next_id = 0
    for a, start_idx in enumerate(candidate_indices):
        for b in range(a + 1, len(candidate_indices)):
            end_idx = candidate_indices[b]
            if arc_lengths[end_idx] - arc_lengths[start_idx] > config.max_segment_length:
                break
            stats.interval_count += 1
            interval_segments = evaluate_interval(points, start_idx, end_idx, config)
            if not interval_segments:
                stats.interval_without_fit_count += 1
            for segment in interval_segments:
                if is_short_hypothesis(segment, config):
                    stats.short_hypothesis_rejected_count += 1
                    continue
                hyp = SegmentHypothesis(
                    id=next_id,
                    segment=segment,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    start_tangent=segment.start_tangent,
                    end_tangent=segment.end_tangent,
                    base_cost=base_segment_cost(segment, config),
                )
                next_id += 1
                hypotheses.append(hyp)
                by_start[start_idx].append(hyp)
                by_end[end_idx].append(hyp)
                if segment.kind == "line":
                    stats.line_hypothesis_count += 1
                else:
                    stats.arc_hypothesis_count += 1

    stats.hypothesis_count = len(hypotheses)
    stats.start_hypothesis_count = len(by_start.get(0, []))
    stats.final_hypothesis_count = len(by_end.get(len(points) - 1, []))
    if config.debug_keep_rejected_transitions:
        stats.rejected_transitions = []
    return hypotheses, by_start, by_end, stats


def run_segment_dag_dp(
    points: np.ndarray,
    candidate_indices: list[int],
    config: FitConfig,
) -> tuple[list[Segment], DagDebugStats]:
    hypotheses, by_start, by_end, stats = build_segment_hypotheses(points, candidate_indices, config)
    id_to_hypothesis = {hyp.id: hyp for hyp in hypotheses}
    best_cost: dict[int, float] = {}
    best_prev: dict[int, int | None] = {}

    for hyp in by_start.get(0, []):
        best_cost[hyp.id] = hyp.base_cost
        best_prev[hyp.id] = None

    for idx in candidate_indices[1:]:
        prev_segments = by_end.get(idx, [])
        curr_segments = by_start.get(idx, [])
        if not prev_segments or not curr_segments:
            continue

        reachable_prev = [prev for prev in prev_segments if prev.id in best_cost]
        if not reachable_prev:
            continue

        for curr in curr_segments:
            best = best_cost.get(curr.id, math.inf)
            best_p: int | None = best_prev.get(curr.id)
            for prev in reachable_prev:
                stats.transition_count += 1
                trans = transition_cost(prev, curr, config)
                if trans is None:
                    stats.rejected_transition_count += 1
                    if stats.rejected_transitions is not None and len(stats.rejected_transitions) < 200:
                        angle = math.degrees(angle_between_tangents(prev.end_tangent, curr.start_tangent))
                        stats.rejected_transitions.append(
                            {
                                "prev_id": prev.id,
                                "curr_id": curr.id,
                                "idx": idx,
                                "angle_deg": round(angle, 6),
                                "reason": "tangent_angle",
                            }
                        )
                    continue
                penalty, _angle = trans
                cost = best_cost[prev.id] + penalty + curr.base_cost
                if cost < best:
                    best = cost
                    best_p = prev.id
            if best_p is not None:
                best_cost[curr.id] = best
                best_prev[curr.id] = best_p

    stats.reachable_hypothesis_count = len(best_cost)
    final_idx = len(points) - 1
    best_final: SegmentHypothesis | None = None
    best_final_cost = math.inf
    for hyp in by_end.get(final_idx, []):
        cost = best_cost.get(hyp.id, math.inf)
        if cost < best_final_cost:
            best_final = hyp
            best_final_cost = cost

    if best_final is None:
        raise RuntimeError(
            "no tangent-continuous path found; "
            f"candidates={stats.candidate_count}, hypotheses={stats.hypothesis_count}, "
            f"start_hypotheses={stats.start_hypothesis_count}, final_hypotheses={stats.final_hypothesis_count}, "
            f"transitions={stats.transition_count}, rejected_transitions={stats.rejected_transition_count}, "
            f"reachable_hypotheses={stats.reachable_hypothesis_count}"
        )

    path: list[SegmentHypothesis] = []
    cursor: int | None = best_final.id
    while cursor is not None:
        hyp = id_to_hypothesis[cursor]
        path.append(hyp)
        cursor = best_prev[cursor]
    path.reverse()
    return [hyp.segment for hyp in path], stats


def can_connect(left: Segment, right: Segment, config: FitConfig) -> bool:
    angle = angle_between_tangents(left.end_tangent, right.start_tangent)
    return angle < config.max_tangent_angle_error


def try_merge(points: np.ndarray, left: Segment, right: Segment, config: FitConfig) -> Segment | None:
    if (left.start_idx == 0 or right.end_idx == len(points) - 1) and start_goal_line_points(config) is not None:
        return fit_start_goal_line_segment(points, left.start_idx, right.end_idx, config)
    if isinstance(left, LineSegment) and isinstance(right, LineSegment):
        return fit_line(points, left.start_idx, right.end_idx, config)
    if isinstance(left, ArcSegment) and isinstance(right, ArcSegment):
        return fit_arc(points, left.start_idx, right.end_idx, config)
    options = [
        segment
        for segment in (
            fit_line(points, left.start_idx, right.end_idx, config),
            fit_arc(points, left.start_idx, right.end_idx, config),
        )
        if segment is not None
    ]
    if not options:
        return None
    return min(options, key=lambda segment: base_segment_cost(segment, config))


def path_is_tangent_valid(segments: list[Segment], config: FitConfig) -> bool:
    return all(can_connect(left, right, config) for left, right in zip(segments[:-1], segments[1:]))


def postprocess_segments(points: np.ndarray, segments: list[Segment], config: FitConfig) -> list[Segment]:
    changed = True
    current = segments
    while changed:
        changed = False
        merged: list[Segment] = []
        index = 0
        while index < len(current):
            if index + 1 < len(current):
                candidate = try_merge(points, current[index], current[index + 1], config)
                if candidate is not None:
                    trial = merged + [candidate] + current[index + 2 :]
                    if path_is_tangent_valid(trial, config):
                        merged.append(candidate)
                        index += 2
                        changed = True
                        continue
            merged.append(current[index])
            index += 1
        current = merged
    return current


def connection_report(segments: list[Segment], config: FitConfig) -> list[dict[str, int | float | str]]:
    report: list[dict[str, int | float | str]] = []
    for index, (prev, curr) in enumerate(zip(segments[:-1], segments[1:])):
        angle = angle_between_tangents(prev.end_tangent, curr.start_tangent)
        penalty = segment_transition_penalty(prev, curr, angle, config)
        report.append(
            {
                "connection_index": index,
                "prev_kind": prev.kind,
                "curr_kind": curr.kind,
                "joint_idx": prev.end_idx,
                "tangent_angle_error_deg": round(math.degrees(angle), 6),
                "transition_cost": round(penalty, 9),
                "same_radius_same_turn_arc": same_radius_same_turn_arc_pair(prev, curr, config),
            }
        )
    return report


def tangent_warnings(segments: list[Segment], config: FitConfig) -> list[dict[str, int | float]]:
    warnings: list[dict[str, int | float]] = []
    for item in connection_report(segments, config):
        if float(item["tangent_angle_error_deg"]) > config.max_tangent_angle_error_deg:
            warnings.append(
                {
                    "connection_index": int(item["connection_index"]),
                    "angle_deg": float(item["tangent_angle_error_deg"]),
                }
            )
    return warnings


def fit_line_arc_path(points: np.ndarray, config: FitConfig | None = None) -> FitResult:
    config = config or FitConfig()
    fit_points = preprocess_points(points, config)
    candidate_indices = build_candidate_indices(fit_points, config)
    segments, stats = run_segment_dag_dp(fit_points, candidate_indices, config)
    segments = postprocess_segments(fit_points, segments, config)
    connections = connection_report(segments, config)
    max_error = max((segment.max_error for segment in segments), default=0.0)
    max_tangent_error_deg = max((float(item["tangent_angle_error_deg"]) for item in connections), default=0.0)
    return FitResult(
        source_point_count=len(points),
        fit_point_count=len(fit_points),
        candidate_count=len(candidate_indices),
        segment_count=len(segments),
        max_segment_error=round(max_error, 6),
        max_tangent_error_deg=round(max_tangent_error_deg, 6),
        tangent_warnings=tangent_warnings(segments, config),
        connection_report=connections,
        debug_stats=stats,
        segments=segments,
        fit_points=fit_points,
        candidate_indices=candidate_indices,
    )


def result_to_jsonable(result: FitResult, config: FitConfig) -> dict[str, object]:
    return {
        "config": asdict(config),
        "source_point_count": result.source_point_count,
        "fit_point_count": result.fit_point_count,
        "candidate_count": result.candidate_count,
        "segment_count": result.segment_count,
        "max_segment_error": result.max_segment_error,
        "max_tangent_error_deg": result.max_tangent_error_deg,
        "tangent_warnings": result.tangent_warnings,
        "connection_report": result.connection_report,
        "debug_stats": asdict(result.debug_stats),
        "segments": [asdict(segment) for segment in result.segments],
    }


def infer_board_size(points: np.ndarray, config: FitConfig) -> tuple[float, float]:
    if config.board_width_cm is not None and config.board_height_cm is not None:
        return config.board_width_cm, config.board_height_cm
    max_x = float(np.max(points[:, 0])) if len(points) else 360.0
    max_y = float(np.max(points[:, 1])) if len(points) else 180.0
    width = config.board_width_cm if config.board_width_cm is not None else math.ceil(max(max_x, 1.0) / 90.0) * 90.0
    height = config.board_height_cm if config.board_height_cm is not None else math.ceil(max(max_y, 1.0) / 90.0) * 90.0
    return width, height


def unique_radius_presets(segments: list[Segment]) -> list[float]:
    defaults = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]
    radii = [round(segment.radius, 3) for segment in segments if isinstance(segment, ArcSegment)]
    values = sorted(set(defaults + radii))
    return values


def course_cad_model_to_dict(result: FitResult, config: FitConfig) -> dict[str, object]:
    board_width_cm, board_height_cm = infer_board_size(result.fit_points, config)
    if config.start_cm is not None and config.goal_cm is not None:
        start = np.asarray(config.start_cm, dtype=np.float64)
        goal = np.asarray(config.goal_cm, dtype=np.float64)
        hint_center = (start + goal) * 0.5
        hint_length = float(np.linalg.norm(goal - start))
    else:
        hint_center = result.fit_points[0] if len(result.fit_points) else np.asarray([0.0, 0.0], dtype=np.float64)
        hint_length = 100.0

    circles = []
    for circle_id, segment in enumerate(segment for segment in result.segments if isinstance(segment, ArcSegment)):
        circles.append(
            {
                "id": circle_id,
                "x": segment.center[0],
                "y": segment.center[1],
                "r": segment.radius,
                "turn": "cw" if segment.clockwise else "ccw",
                "locked": False,
            }
        )

    return {
        "board": {
            "width_cm": board_width_cm,
            "height_cm": board_height_cm,
        },
        "line_width_cm": 1.9,
        "min_edge_margin_cm": 20.0,
        "grid": {
            "origin_x_cm": 0.0,
            "origin_y_cm": 0.0,
            "cell_width_cm": config.grid_cell_width_cm,
            "cell_height_cm": config.grid_cell_height_cm,
        },
        "radius_presets_cm": unique_radius_presets(result.segments),
        "start_goal_hint": {
            "x": round(float(hint_center[0]), 6),
            "y": round(float(hint_center[1]), 6),
            "length": round(hint_length, 6),
        },
        "circles": circles,
    }


def write_segments_tsv(path: Path, segments: list[Segment]) -> None:
    lines = [
        "index\tkind\tstart_idx\tend_idx\tp0_x\tp0_y\tp1_x\tp1_y\tcenter_x\tcenter_y\t"
        "radius\tclockwise\tmax_error\tstart_tangent_x\tstart_tangent_y\tend_tangent_x\tend_tangent_y"
    ]
    for index, segment in enumerate(segments):
        if isinstance(segment, LineSegment):
            center_x = center_y = radius = clockwise = ""
        else:
            center_x = f"{segment.center[0]:.6f}"
            center_y = f"{segment.center[1]:.6f}"
            radius = f"{segment.radius:.6f}"
            clockwise = str(segment.clockwise).lower()
        lines.append(
            "\t".join(
                [
                    str(index),
                    segment.kind,
                    str(segment.start_idx),
                    str(segment.end_idx),
                    f"{segment.p0[0]:.6f}",
                    f"{segment.p0[1]:.6f}",
                    f"{segment.p1[0]:.6f}",
                    f"{segment.p1[1]:.6f}",
                    center_x,
                    center_y,
                    radius,
                    clockwise,
                    f"{segment.max_error:.6f}",
                    f"{segment.start_tangent[0]:.9f}",
                    f"{segment.start_tangent[1]:.9f}",
                    f"{segment.end_tangent[0]:.9f}",
                    f"{segment.end_tangent[1]:.9f}",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_connections_tsv(path: Path, report: list[dict[str, int | float | str]]) -> None:
    lines = ["connection_index\tjoint_idx\tprev_kind\tcurr_kind\ttangent_angle_error_deg\ttransition_cost\tsame_radius_same_turn_arc"]
    for item in report:
        lines.append(
            "\t".join(
                [
                    str(item["connection_index"]),
                    str(item["joint_idx"]),
                    str(item["prev_kind"]),
                    str(item["curr_kind"]),
                    f"{float(item['tangent_angle_error_deg']):.6f}",
                    f"{float(item['transition_cost']):.9f}",
                    str(item.get("same_radius_same_turn_arc", False)).lower(),
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sample_segment(segment: Segment, sample_count: int = 48) -> np.ndarray:
    if isinstance(segment, LineSegment):
        return np.asarray([segment.p0, segment.p1], dtype=np.float64)
    center = np.asarray(segment.center, dtype=np.float64)
    theta0 = segment.theta0
    delta = segment.delta_theta
    count = max(2, min(sample_count, int(abs(delta) / math.radians(3.0)) + 2))
    angles = theta0 + np.linspace(0.0, delta, count)
    return center[None, :] + segment.radius * np.column_stack((np.cos(angles), np.sin(angles)))


def write_debug_svg(path: Path, points: np.ndarray, result: FitResult) -> None:
    min_xy = np.min(points, axis=0) - 10.0
    max_xy = np.max(points, axis=0) + 10.0
    width = float(max_xy[0] - min_xy[0])
    height = float(max_xy[1] - min_xy[1])

    def svg_xy(point: np.ndarray | tuple[float, float]) -> tuple[float, float]:
        array = np.asarray(point, dtype=np.float64)
        return float(array[0] - min_xy[0]), float(max_xy[1] - array[1])

    raw_poly = " ".join(f"{svg_xy(point)[0]:.2f},{svg_xy(point)[1]:.2f}" for point in points)
    candidate_dots = []
    for index in result.candidate_indices:
        x, y = svg_xy(result.fit_points[index])
        candidate_dots.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.3" fill="#2563eb" />')

    segment_paths = []
    tangent_marks = []
    tangent_scale = 8.0
    for segment_index, segment in enumerate(result.segments):
        sampled = sample_segment(segment)
        points_attr = " ".join(f"{svg_xy(point)[0]:.2f},{svg_xy(point)[1]:.2f}" for point in sampled)
        color = "#16a34a" if isinstance(segment, LineSegment) else "#f97316"
        segment_paths.append(f'<polyline points="{points_attr}" fill="none" stroke="{color}" stroke-width="1.9" />')
        for point, tangent in ((segment.p0, segment.start_tangent), (segment.p1, segment.end_tangent)):
            x0, y0 = svg_xy(point)
            tangent_array = np.asarray(tangent, dtype=np.float64)
            x1 = x0 + tangent_array[0] * tangent_scale
            y1 = y0 - tangent_array[1] * tangent_scale
            tangent_marks.append(
                f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" '
                f'stroke="#111827" stroke-width="0.9"><title>seg {segment_index}</title></line>'
            )

    warning_marks = []
    for item in result.connection_report:
        if float(item["tangent_angle_error_deg"]) > 0.5:
            joint = result.segments[int(item["connection_index"])].p1
            x, y = svg_xy(joint)
            color = "#dc2626" if float(item["tangent_angle_error_deg"]) > 5.0 else "#ca8a04"
            warning_marks.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.0" fill="{color}">'
                f'<title>{float(item["tangent_angle_error_deg"]):.2f} deg</title></circle>'
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width:.1f}" height="{height:.1f}" viewBox="0 0 {width:.1f} {height:.1f}">
<rect width="100%" height="100%" fill="white" />
<polyline points="{raw_poly}" fill="none" stroke="#cbd5e1" stroke-width="1" />
{chr(10).join(candidate_dots)}
{chr(10).join(segment_paths)}
{chr(10).join(tangent_marks)}
{chr(10).join(warning_marks)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def build_config(
    args: argparse.Namespace,
    start_cm: tuple[float, float] | None = None,
    goal_cm: tuple[float, float] | None = None,
    board_width_cm: float | None = None,
    board_height_cm: float | None = None,
) -> FitConfig:
    return FitConfig(
        resample_spacing=args.resample_spacing,
        rdp_epsilon=args.rdp_epsilon,
        fit_tolerance=args.fit_tolerance,
        curvature_threshold=args.curvature_threshold,
        curvature_change_threshold=args.curvature_change_threshold,
        candidate_neighbor_count=args.candidate_neighbor_count,
        max_segment_length=args.max_segment_length,
        min_segment_length=args.min_segment_length,
        min_preferred_segment_length=args.min_preferred_segment_length,
        short_segment_penalty=args.short_segment_penalty,
        fit_error_weight=args.fit_error_weight,
        min_radius=args.min_radius,
        max_radius=args.max_radius,
        quantize_arc_radius=not args.no_quantize_arc_radius,
        arc_radius_step=args.arc_radius_step,
        arc_radius_neighbor_steps=args.arc_radius_neighbor_steps,
        arc_cost_bias=args.arc_cost_bias,
        tangent_tolerance_deg=args.tangent_tolerance_deg,
        tangent_soft_limit_deg=args.tangent_soft_limit_deg,
        max_tangent_angle_error_deg=args.max_tangent_angle_error_deg,
        tangent_weight=args.tangent_weight,
        tangent_soft_penalty=args.tangent_soft_penalty,
        type_switch_penalty=args.type_switch_penalty,
        same_radius_same_turn_arc_penalty=args.same_radius_same_turn_arc_penalty,
        start_cm=start_cm,
        goal_cm=goal_cm,
        board_width_cm=args.board_width_cm if args.board_width_cm is not None else board_width_cm,
        board_height_cm=args.board_height_cm if args.board_height_cm is not None else board_height_cm,
        grid_cell_width_cm=args.grid_cell_width_cm,
        grid_cell_height_cm=args.grid_cell_height_cm,
        debug_keep_rejected_transitions=args.debug_keep_rejected_transitions,
    )


def main() -> None:
    args = parse_args()
    input_path = Path(args.trace_points_tsv)
    name = args.name or input_path.parent.name or input_path.stem
    target = Path(args.out_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    report_start_cm, report_goal_cm, report_board_width_cm, report_board_height_cm = load_metadata_from_report(input_path)
    start_cm = parse_point_cm(args.start_cm) if args.start_cm else report_start_cm
    goal_cm = parse_point_cm(args.goal_cm) if args.goal_cm else report_goal_cm
    config = build_config(
        args,
        start_cm=start_cm,
        goal_cm=goal_cm,
        board_width_cm=report_board_width_cm,
        board_height_cm=report_board_height_cm,
    )
    source_points = load_trace_points(input_path)
    result = fit_line_arc_path(source_points, config)

    (target / "line_arc_segments.json").write_text(
        json.dumps(result_to_jsonable(result, config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_segments_tsv(target / "line_arc_segments.tsv", result.segments)
    write_connections_tsv(target / "line_arc_connections.tsv", result.connection_report)
    (target / "course_cad_model.json").write_text(
        json.dumps(course_cad_model_to_dict(result, config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.write_svg:
        write_debug_svg(target / "line_arc_segments.svg", source_points, result)

    print(
        f"wrote {target / 'line_arc_segments.json'} "
        f"({result.segment_count} segments, {result.candidate_count} candidates, "
        f"max error {result.max_segment_error:.3f} cm, "
        f"max tangent error {result.max_tangent_error_deg:.3f} deg)"
    )


if __name__ == "__main__":
    main()
