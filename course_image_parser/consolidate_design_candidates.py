#!/usr/bin/env python3
"""Consolidate design text, support-circle detections, and slalom detections."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


OUT_DIR = Path("tmp/consolidated_design_candidates")
SLALOM_RADIUS_CM = 50.0
SLALOM_SPAN_CM = 60.0
SLALOM_TOUCH_SLACK_CM = 1e-10
PALETTE = (
    (230, 25, 75),
    (60, 180, 75),
    (255, 225, 25),
    (0, 130, 200),
    (245, 130, 48),
    (145, 30, 180),
    (70, 240, 240),
    (240, 50, 230),
    (210, 245, 60),
    (250, 190, 190),
    (0, 128, 128),
    (230, 190, 255),
    (170, 110, 40),
    (255, 250, 200),
)


@dataclass(frozen=True)
class Hypothesis:
    value: float | tuple[float, float]
    confidence: float


@dataclass(frozen=True)
class DesignItem:
    index: int
    text: str
    info_xy: tuple[float, float] | None
    radii: tuple[Hypothesis, ...]
    xys: tuple[Hypothesis, ...]
    evidence: str


@dataclass(frozen=True)
class CoordinateItem:
    index: int
    text: str
    info_xy: tuple[float, float] | None
    xys: tuple[Hypothesis, ...]
    evidence: str


@dataclass(frozen=True)
class DetectionCircle:
    rank: int
    x: float
    y: float
    r: float
    score: float
    magenta_support_count: int
    line_support_count: int
    arc_span_deg: float
    mean_abs_radius_error_cm: float


@dataclass(frozen=True)
class MatchResult:
    design_item: DesignItem
    detection: DetectionCircle
    radius_hypothesis: Hypothesis
    xy_hypothesis: Hypothesis | None
    mode: str
    center_distance_cm: float
    radius_delta_cm: float
    match_cost: float
    line_support_length_cm: float
    line_support_ok: bool


@dataclass(frozen=True)
class SlalomCandidate:
    rank: int
    score: float
    kind: str
    turns: tuple[str, str, str]
    angle_deg: float
    start_cm: tuple[float, float]
    end_cm: tuple[float, float]
    arc_centers_cm: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class CoordinateMatch:
    coordinate_item: CoordinateItem
    hypothesis: Hypothesis
    distance_cm: float


@dataclass(frozen=True)
class SlalomMergeResult:
    candidate: SlalomCandidate
    start_cm: tuple[float, float]
    end_cm: tuple[float, float]
    centers_cm: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    approx_center: bool
    mode: str
    start_match: CoordinateMatch | None
    end_match: CoordinateMatch | None
    direction: tuple[float, float] | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("design_info_json", help="line_design_info.json from line-design-info-extractor")
    parser.add_argument("support_circle_report_json", help="report.json from detect_support_circles.py")
    parser.add_argument("--name")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--image-path", help="normalized board image for visualization background")
    parser.add_argument("--px-per-cm", type=float)
    parser.add_argument("--board-width-cm", type=float)
    parser.add_argument("--board-height-cm", type=float)
    parser.add_argument("--unique-center-threshold-cm", type=float, default=6.0)
    parser.add_argument("--unique-radius-threshold-cm", type=float, default=2.6)
    parser.add_argument("--ambiguous-center-threshold-cm", type=float, default=8.0)
    parser.add_argument("--ambiguous-radius-threshold-cm", type=float, default=2.6)
    parser.add_argument("--radius-only-center-threshold-cm", type=float, default=32.0)
    parser.add_argument("--radius-only-radius-threshold-cm", type=float, default=2.6)
    parser.add_argument("--center-cost-scale-cm", type=float, default=6.0)
    parser.add_argument("--radius-cost-scale-cm", type=float, default=2.5)
    parser.add_argument("--max-detections-per-hypothesis", type=int, default=1)
    parser.add_argument("--trace-points-tsv", help="trace_centerline_points.py trace_points.tsv for line support scoring")
    parser.add_argument("--line-support-tolerance-cm", type=float, default=1.0)
    parser.add_argument("--min-line-support-length-cm", type=float, default=8.0)
    parser.add_argument("--line-support-penalty", type=float, default=12.0)
    parser.add_argument("--line-support-reward", type=float, default=8.0)
    parser.add_argument("--line-support-reward-cap-cm", type=float, default=80.0)
    parser.add_argument("--slalom-template-report-json", help="report.json from detect_slalom_template.py")
    parser.add_argument("--slalom-coordinate-threshold-cm", type=float, default=3.0)
    parser.add_argument("--slalom-cardinal-angle-tolerance-deg", type=float, default=3.0)
    parser.add_argument("--max-slalom-candidates", type=int, default=0, help="0 means use all slalom candidates in the report")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_xy_hypotheses(raw: object) -> tuple[Hypothesis, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"xy hypotheses must be a list or null: {raw!r}")
    hypotheses: list[Hypothesis] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"bad xy hypothesis: {item!r}")
        xy, confidence = item
        if not isinstance(xy, list) or len(xy) != 2:
            raise ValueError(f"bad xy value: {xy!r}")
        hypotheses.append(Hypothesis((float(xy[0]), float(xy[1])), float(confidence)))
    return tuple(hypotheses)


def parse_radius_hypotheses(raw: object) -> tuple[Hypothesis, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"radius hypotheses must be a list or null: {raw!r}")
    hypotheses: list[Hypothesis] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"bad radius hypothesis: {item!r}")
        radius, confidence = item
        hypotheses.append(Hypothesis(float(radius), float(confidence)))
    return tuple(hypotheses)


def load_design_items(data: dict[str, Any]) -> list[DesignItem]:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("design info JSON must contain an items list")
    items: list[DesignItem] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict) or raw.get("type") != "circle":
            continue
        radii = parse_radius_hypotheses(raw.get("radius"))
        if not radii:
            continue
        info_xy_raw = raw.get("info_xy")
        info_xy: tuple[float, float] | None = None
        if isinstance(info_xy_raw, list) and len(info_xy_raw) >= 2:
            info_xy = (float(info_xy_raw[0]), float(info_xy_raw[1]))
        items.append(
            DesignItem(
                index=index,
                text=str(raw.get("text", "")),
                info_xy=info_xy,
                radii=radii,
                xys=parse_xy_hypotheses(raw.get("xy")),
                evidence=str(raw.get("evidence", "")),
            )
        )
    return items


def load_coordinate_items(data: dict[str, Any]) -> list[CoordinateItem]:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("design info JSON must contain an items list")
    items: list[CoordinateItem] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict) or raw.get("type") != "coordinate":
            continue
        xys = parse_xy_hypotheses(raw.get("xy"))
        if not xys:
            continue
        info_xy_raw = raw.get("info_xy")
        info_xy: tuple[float, float] | None = None
        if isinstance(info_xy_raw, list) and len(info_xy_raw) >= 2:
            info_xy = (float(info_xy_raw[0]), float(info_xy_raw[1]))
        items.append(
            CoordinateItem(
                index=index,
                text=str(raw.get("text", "")),
                info_xy=info_xy,
                xys=xys,
                evidence=str(raw.get("evidence", "")),
            )
        )
    return items


def load_detection_circles(data: dict[str, Any]) -> list[DetectionCircle]:
    raw_candidates = data.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("support circle report JSON must contain a candidates list")
    detections: list[DetectionCircle] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        center = raw.get("center_cm")
        if not isinstance(center, list) or len(center) < 2:
            continue
        detections.append(
            DetectionCircle(
                rank=int(raw.get("rank", len(detections))),
                x=float(center[0]),
                y=float(center[1]),
                r=float(raw["radius_cm"]),
                score=float(raw.get("score", 0.0)),
                magenta_support_count=int(raw.get("magenta_support_count", 0)),
                line_support_count=int(raw.get("line_support_count", 0)),
                arc_span_deg=float(raw.get("arc_span_deg", 0.0)),
                mean_abs_radius_error_cm=float(raw.get("mean_abs_radius_error_cm", 0.0)),
            )
        )
    return detections


def load_slalom_candidates(data: dict[str, Any], max_count: int = 0) -> list[SlalomCandidate]:
    raw_candidates = data.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("slalom template report JSON must contain a candidates list")
    candidates: list[SlalomCandidate] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        start = raw.get("start_cm")
        end = raw.get("end_cm")
        centers = raw.get("arc_centers_cm")
        turns = raw.get("turns")
        if not isinstance(start, list) or len(start) < 2:
            continue
        if not isinstance(end, list) or len(end) < 2:
            continue
        if not isinstance(centers, list) or len(centers) != 3:
            continue
        if not isinstance(turns, list) or len(turns) != 3:
            turns = str(raw.get("kind", "")).split("-")
        if len(turns) != 3:
            continue
        candidates.append(
            SlalomCandidate(
                rank=int(raw.get("rank", len(candidates))),
                score=float(raw.get("score", 0.0)),
                kind=str(raw.get("kind", "")),
                turns=(str(turns[0]), str(turns[1]), str(turns[2])),
                angle_deg=float(raw.get("angle_deg", 0.0)),
                start_cm=(float(start[0]), float(start[1])),
                end_cm=(float(end[0]), float(end[1])),
                arc_centers_cm=(
                    (float(centers[0][0]), float(centers[0][1])),
                    (float(centers[1][0]), float(centers[1][1])),
                    (float(centers[2][0]), float(centers[2][1])),
                ),
            )
        )
        if max_count > 0 and len(candidates) >= max_count:
            break
    return candidates


def read_board_size(report: dict[str, Any], args: argparse.Namespace) -> tuple[float, float]:
    if args.board_width_cm is not None and args.board_height_cm is not None:
        return float(args.board_width_cm), float(args.board_height_cm)
    board_cm = report.get("board_cm")
    if isinstance(board_cm, list) and len(board_cm) >= 2:
        return float(board_cm[0]), float(board_cm[1])
    raise ValueError("board size missing; pass --board-width-cm and --board-height-cm")


def read_px_per_cm(report: dict[str, Any], args: argparse.Namespace) -> float:
    if args.px_per_cm is not None:
        return float(args.px_per_cm)
    return float(report.get("px_per_cm", 4.0))


def load_trace_points(path: Path | None) -> np.ndarray | None:
    if path is None:
        return None
    points: list[tuple[float, float]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            try:
                points.append((float(row["x_cm"]), float(row["y_cm"])))
            except (KeyError, TypeError, ValueError):
                continue
    if len(points) < 2:
        return None
    return np.asarray(points, dtype=np.float64)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def line_support_length_cm(
    trace_points: np.ndarray | None,
    center: tuple[float, float],
    radius: float,
    tolerance_cm: float,
) -> float:
    if trace_points is None or trace_points.shape[0] < 2:
        return 0.0
    center_array = np.asarray(center, dtype=np.float64)
    distances = np.linalg.norm(trace_points - center_array[None, :], axis=1)
    on_circle = np.abs(distances - radius) <= tolerance_cm
    segment_lengths = np.linalg.norm(np.diff(trace_points, axis=0), axis=1)
    if segment_lengths.size == 0:
        return 0.0
    # Count only trace segments whose both endpoints lie near the circle. This
    # avoids giving a large credit to a short crossing that merely touches the
    # tolerance band at one endpoint.
    segment_on_circle = on_circle[:-1] & on_circle[1:]
    return float(np.sum(segment_lengths[segment_on_circle]))


def slalom_local_centers(kind: str) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    touch_distance = 2.0 * SLALOM_RADIUS_CM + SLALOM_TOUCH_SLACK_CM
    lateral = math.sqrt(touch_distance * touch_distance - (SLALOM_SPAN_CM / 2.0) ** 2)
    if kind == "cw-ccw-cw":
        return ((0.0, -SLALOM_RADIUS_CM), (SLALOM_SPAN_CM / 2.0, lateral - SLALOM_RADIUS_CM), (SLALOM_SPAN_CM, -SLALOM_RADIUS_CM))
    if kind == "ccw-cw-ccw":
        return ((0.0, SLALOM_RADIUS_CM), (SLALOM_SPAN_CM / 2.0, SLALOM_RADIUS_CM - lateral), (SLALOM_SPAN_CM, SLALOM_RADIUS_CM))
    raise ValueError(f"unsupported slalom kind: {kind}")


def transform_slalom_centers(
    kind: str,
    start_cm: tuple[float, float],
    direction: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    ux, uy = direction
    # The template's local positive-y axis points downward in image space, so
    # convert to board coordinates with the negative left-normal.
    nx, ny = -uy, ux
    centers: list[tuple[float, float]] = []
    for local_x, local_y in slalom_local_centers(kind):
        centers.append((start_cm[0] + ux * local_x - nx * local_y, start_cm[1] + uy * local_x - ny * local_y))
    return (centers[0], centers[1], centers[2])


def unit_direction(start_cm: tuple[float, float], end_cm: tuple[float, float]) -> tuple[float, float] | None:
    dx = end_cm[0] - start_cm[0]
    dy = end_cm[1] - start_cm[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    return dx / length, dy / length


def is_cardinal_angle(angle_deg: float, tolerance_deg: float) -> bool:
    nearest = round(angle_deg / 90.0) * 90.0
    return abs((angle_deg - nearest + 180.0) % 360.0 - 180.0) <= tolerance_deg


def snapped_cardinal_direction(start_cm: tuple[float, float], end_cm: tuple[float, float]) -> tuple[float, float] | None:
    dx = end_cm[0] - start_cm[0]
    dy = end_cm[1] - start_cm[1]
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return None
    if abs(dx) >= abs(dy):
        return (1.0 if dx >= 0.0 else -1.0), 0.0
    return 0.0, (1.0 if dy >= 0.0 else -1.0)


def start_from_end(end_cm: tuple[float, float], direction: tuple[float, float]) -> tuple[float, float]:
    return end_cm[0] - direction[0] * 60.0, end_cm[1] - direction[1] * 60.0


def best_coordinate_match(
    point: tuple[float, float],
    coordinate_items: list[CoordinateItem],
    threshold_cm: float,
) -> CoordinateMatch | None:
    best: CoordinateMatch | None = None
    for item in coordinate_items:
        for hypothesis in item.xys:
            xy = hypothesis.value
            if not isinstance(xy, tuple):
                continue
            current_distance = distance(point, xy)
            if current_distance > threshold_cm:
                continue
            match = CoordinateMatch(item, hypothesis, current_distance)
            if best is None or match.distance_cm < best.distance_cm:
                best = match
    return best


def merge_slalom_candidate(
    candidate: SlalomCandidate,
    coordinate_items: list[CoordinateItem],
    args: argparse.Namespace,
) -> SlalomMergeResult:
    start_match = best_coordinate_match(candidate.start_cm, coordinate_items, args.slalom_coordinate_threshold_cm)
    end_match = best_coordinate_match(candidate.end_cm, coordinate_items, args.slalom_coordinate_threshold_cm)

    if start_match is not None and end_match is not None:
        start_xy = start_match.hypothesis.value
        end_xy = end_match.hypothesis.value
        assert isinstance(start_xy, tuple) and isinstance(end_xy, tuple)
        direction = unit_direction(start_xy, end_xy)
        if direction is not None:
            return SlalomMergeResult(
                candidate=candidate,
                start_cm=start_xy,
                end_cm=end_xy,
                centers_cm=transform_slalom_centers(candidate.kind, start_xy, direction),
                approx_center=False,
                mode="slalom_text_start_end",
                start_match=start_match,
                end_match=end_match,
                direction=direction,
            )

    if is_cardinal_angle(candidate.angle_deg, args.slalom_cardinal_angle_tolerance_deg):
        direction = snapped_cardinal_direction(candidate.start_cm, candidate.end_cm)
        if direction is not None and start_match is not None:
            start_xy = start_match.hypothesis.value
            assert isinstance(start_xy, tuple)
            return SlalomMergeResult(
                candidate=candidate,
                start_cm=start_xy,
                end_cm=(start_xy[0] + direction[0] * 60.0, start_xy[1] + direction[1] * 60.0),
                centers_cm=transform_slalom_centers(candidate.kind, start_xy, direction),
                approx_center=False,
                mode="slalom_text_start_cardinal_angle",
                start_match=start_match,
                end_match=end_match,
                direction=direction,
            )
        if direction is not None and end_match is not None:
            end_xy = end_match.hypothesis.value
            assert isinstance(end_xy, tuple)
            start_xy = start_from_end(end_xy, direction)
            return SlalomMergeResult(
                candidate=candidate,
                start_cm=start_xy,
                end_cm=end_xy,
                centers_cm=transform_slalom_centers(candidate.kind, start_xy, direction),
                approx_center=False,
                mode="slalom_text_end_cardinal_angle",
                start_match=start_match,
                end_match=end_match,
                direction=direction,
            )

    return SlalomMergeResult(
        candidate=candidate,
        start_cm=candidate.start_cm,
        end_cm=candidate.end_cm,
        centers_cm=candidate.arc_centers_cm,
        approx_center=True,
        mode="slalom_template_approx",
        start_match=start_match,
        end_match=end_match,
        direction=unit_direction(candidate.start_cm, candidate.end_cm),
    )


def best_matches(
    detections: list[DetectionCircle],
    center: tuple[float, float],
    radius: float,
    max_center_distance_cm: float,
    max_radius_delta_cm: float,
    center_cost_scale_cm: float,
    radius_cost_scale_cm: float,
    max_count: int,
    trace_points: np.ndarray | None,
    line_support_tolerance_cm: float,
    min_line_support_length_cm: float,
    line_support_penalty: float,
    line_support_reward: float,
    line_support_reward_cap_cm: float,
) -> list[tuple[DetectionCircle, float, float, float, float, bool]]:
    candidates: list[tuple[DetectionCircle, float, float, float, float, bool]] = []
    for detection in detections:
        center_distance = distance(center, (detection.x, detection.y))
        radius_delta = abs(radius - detection.r)
        if center_distance > max_center_distance_cm or radius_delta > max_radius_delta_cm:
            continue
        support_length = line_support_length_cm(trace_points, (detection.x, detection.y), detection.r, line_support_tolerance_cm)
        support_ok = support_length >= min_line_support_length_cm if trace_points is not None else True
        cost = (center_distance / max(center_cost_scale_cm, 1e-9)) ** 2 + (radius_delta / max(radius_cost_scale_cm, 1e-9)) ** 2
        if not support_ok:
            shortfall = max(0.0, min_line_support_length_cm - support_length)
            cost += line_support_penalty * (shortfall / max(min_line_support_length_cm, 1e-9)) ** 2
        elif trace_points is not None:
            reward_ratio = min(support_length, max(line_support_reward_cap_cm, 1e-9)) / max(line_support_reward_cap_cm, 1e-9)
            cost -= line_support_reward * reward_ratio
        cost -= min(detection.score, 1000.0) / 100000.0
        candidates.append((detection, center_distance, radius_delta, cost, support_length, support_ok))
    candidates.sort(key=lambda item: item[3])
    return candidates[: max(1, max_count)]


def match_design_item(
    item: DesignItem,
    detections: list[DetectionCircle],
    args: argparse.Namespace,
    trace_points: np.ndarray | None,
) -> tuple[MatchResult | None, str]:
    matches: list[MatchResult] = []
    if not item.xys:
        if item.info_xy is None:
            return None, "xy is null and info_xy is missing"
        for radius_hypothesis in item.radii:
            radius = float(radius_hypothesis.value)
            for detection, center_distance, radius_delta, cost, support_length, support_ok in best_matches(
                detections,
                item.info_xy,
                radius,
                args.radius_only_center_threshold_cm,
                args.radius_only_radius_threshold_cm,
                args.center_cost_scale_cm,
                args.radius_cost_scale_cm,
                args.max_detections_per_hypothesis,
                trace_points,
                args.line_support_tolerance_cm,
                args.min_line_support_length_cm,
                args.line_support_penalty,
                args.line_support_reward,
                args.line_support_reward_cap_cm,
            ):
                matches.append(
                    MatchResult(
                        design_item=item,
                        detection=detection,
                        radius_hypothesis=radius_hypothesis,
                        xy_hypothesis=None,
                        mode="radius_only",
                        center_distance_cm=center_distance,
                        radius_delta_cm=radius_delta,
                        match_cost=cost,
                        line_support_length_cm=support_length,
                        line_support_ok=support_ok,
                    )
                )
        if matches:
            return min(matches, key=lambda match: match.match_cost), ""
        return None, "no support-circle detection matched any radius hypothesis near info_xy"

    unique = len(item.xys) == 1 and len(item.radii) == 1
    center_threshold = args.unique_center_threshold_cm if unique else args.ambiguous_center_threshold_cm
    radius_threshold = args.unique_radius_threshold_cm if unique else args.ambiguous_radius_threshold_cm
    mode = "unique_text" if unique else "ambiguous_text"
    for xy_hypothesis in item.xys:
        xy = xy_hypothesis.value
        if not isinstance(xy, tuple):
            continue
        for radius_hypothesis in item.radii:
            radius = float(radius_hypothesis.value)
            for detection, center_distance, radius_delta, cost, support_length, support_ok in best_matches(
                detections,
                xy,
                radius,
                center_threshold,
                radius_threshold,
                args.center_cost_scale_cm,
                args.radius_cost_scale_cm,
                args.max_detections_per_hypothesis,
                trace_points,
                args.line_support_tolerance_cm,
                args.min_line_support_length_cm,
                args.line_support_penalty,
                args.line_support_reward,
                args.line_support_reward_cap_cm,
            ):
                matches.append(
                    MatchResult(
                        design_item=item,
                        detection=detection,
                        radius_hypothesis=radius_hypothesis,
                        xy_hypothesis=xy_hypothesis,
                        mode=mode,
                        center_distance_cm=center_distance,
                        radius_delta_cm=radius_delta,
                        match_cost=cost,
                        line_support_length_cm=support_length,
                        line_support_ok=support_ok,
                    )
                )
    if matches:
        return min(matches, key=lambda match: match.match_cost), ""
    return None, "no support-circle detection matched text xy/radius hypotheses"


def final_candidate(match: MatchResult, output_index: int) -> dict[str, Any]:
    radius = float(match.radius_hypothesis.value)
    if match.xy_hypothesis is None:
        center = [round(match.detection.x, 6), round(match.detection.y, 6)]
        approx_center = True
    else:
        xy = match.xy_hypothesis.value
        assert isinstance(xy, tuple)
        center = [round(float(xy[0]), 6), round(float(xy[1]), 6)]
        approx_center = False
    return {
        "id": f"support_text_{output_index}",
        "radius_cm": round(radius, 6),
        "center_cm": center,
        "approx_radius": False,
        "approx_center": approx_center,
        "source": "line_design_text_support_circle_match",
        "text": match.design_item.text,
        "text_item_index": match.design_item.index,
        "mode": match.mode,
        "radius_hypothesis_confidence": round(float(match.radius_hypothesis.confidence), 6),
        "xy_hypothesis_confidence": None if match.xy_hypothesis is None else round(float(match.xy_hypothesis.confidence), 6),
        "matched_detection": {
            "rank": match.detection.rank,
            "radius_cm": round(match.detection.r, 6),
            "center_cm": [round(match.detection.x, 6), round(match.detection.y, 6)],
            "score": round(match.detection.score, 6),
            "magenta_support_count": match.detection.magenta_support_count,
            "line_support_count": match.detection.line_support_count,
        },
        "match_metrics": {
            "center_distance_cm": round(match.center_distance_cm, 6),
            "radius_delta_cm": round(match.radius_delta_cm, 6),
            "match_cost": round(match.match_cost, 6),
            "line_support_length_cm": round(match.line_support_length_cm, 6),
            "line_support_ok": match.line_support_ok,
        },
        "evidence": match.design_item.evidence,
    }


def coordinate_match_payload(match: CoordinateMatch | None) -> dict[str, Any] | None:
    if match is None:
        return None
    xy = match.hypothesis.value
    assert isinstance(xy, tuple)
    return {
        "text_item_index": match.coordinate_item.index,
        "text": match.coordinate_item.text,
        "xy": [round(float(xy[0]), 6), round(float(xy[1]), 6)],
        "confidence": round(float(match.hypothesis.confidence), 6),
        "distance_cm": round(match.distance_cm, 6),
        "evidence": match.coordinate_item.evidence,
    }


def slalom_final_candidates(result: SlalomMergeResult, start_index: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for local_index, center in enumerate(result.centers_cm):
        candidates.append(
            {
                "id": f"slalom_{result.candidate.rank}_{local_index}",
                "radius_cm": 50.0,
                "center_cm": [round(center[0], 6), round(center[1], 6)],
                "approx_radius": False,
                "approx_center": result.approx_center,
                "source": "slalom_text_geometry" if not result.approx_center else "slalom_template",
                "mode": result.mode,
                "slalom_candidate_rank": result.candidate.rank,
                "slalom_circle_index": local_index,
                "turn": result.candidate.turns[local_index],
                "text_item_index": None,
                "text": "",
                "radius_hypothesis_confidence": 1.0,
                "xy_hypothesis_confidence": None,
                "matched_detection": {
                    "rank": result.candidate.rank,
                    "score": round(result.candidate.score, 6),
                    "kind": result.candidate.kind,
                    "angle_deg": result.candidate.angle_deg,
                    "start_cm": [round(result.candidate.start_cm[0], 6), round(result.candidate.start_cm[1], 6)],
                    "end_cm": [round(result.candidate.end_cm[0], 6), round(result.candidate.end_cm[1], 6)],
                    "arc_center_cm": [
                        round(result.candidate.arc_centers_cm[local_index][0], 6),
                        round(result.candidate.arc_centers_cm[local_index][1], 6),
                    ],
                },
                "match_metrics": {
                    "start_coordinate_match": coordinate_match_payload(result.start_match),
                    "end_coordinate_match": coordinate_match_payload(result.end_match),
                    "direction": None if result.direction is None else [round(result.direction[0], 6), round(result.direction[1], 6)],
                },
                "evidence": (
                    f"slalom candidate rank {result.candidate.rank}; "
                    f"{'text-derived exact center' if not result.approx_center else 'template-derived approximate center'}"
                ),
                "output_index_hint": start_index + local_index,
            }
        )
    return candidates


def slalom_record(result: SlalomMergeResult) -> dict[str, Any]:
    source = "slalom_text_geometry" if not result.approx_center else "slalom_template"
    return {
        "id": f"slalom_{result.candidate.rank}",
        "source": source,
        "mode": result.mode,
        "radius_cm": SLALOM_RADIUS_CM,
        "approx_radius": False,
        "approx_center": result.approx_center,
        "start_cm": rounded_point(result.start_cm),
        "end_cm": rounded_point(result.end_cm),
        "turns": list(result.candidate.turns),
        "helper_circles": [
            {
                "radius_cm": SLALOM_RADIUS_CM,
                "center_cm": rounded_point(center),
                "turn": result.candidate.turns[index],
                "arc_index": index,
                "approx_radius": False,
                "approx_center": result.approx_center,
            }
            for index, center in enumerate(result.centers_cm)
        ],
        "text_matches": {
            "start": coordinate_match_payload(result.start_match),
            "end": coordinate_match_payload(result.end_match),
        },
        "detected_template": {
            "rank": result.candidate.rank,
            "score": round(result.candidate.score, 6),
            "kind": result.candidate.kind,
            "angle_deg": result.candidate.angle_deg,
            "start_cm": rounded_point(result.candidate.start_cm),
            "end_cm": rounded_point(result.candidate.end_cm),
            "arc_centers_cm": [rounded_point([x, y]) for x, y in result.candidate.arc_centers_cm],
        },
        "evidence": (
            f"slalom candidate rank {result.candidate.rank}; "
            f"{'text-derived exact center' if not result.approx_center else 'template-derived approximate center'}"
        ),
    }


def failure_record(item: DesignItem, reason: str) -> dict[str, Any]:
    return {
        "text_item_index": item.index,
        "text": item.text,
        "info_xy": list(item.info_xy) if item.info_xy is not None else None,
        "radius": [[float(h.value), float(h.confidence)] for h in item.radii],
        "xy": [[list(h.value), float(h.confidence)] for h in item.xys if isinstance(h.value, tuple)] if item.xys else None,
        "reason": reason,
        "evidence": item.evidence,
    }


def cm_to_px(point: tuple[float, float] | list[float], board_height_cm: float, px_per_cm: float) -> tuple[int, int]:
    return int(round(float(point[0]) * px_per_cm)), int(round((board_height_cm - float(point[1])) * px_per_cm))


def draw_dashed_circle(
    canvas: np.ndarray,
    center: tuple[int, int],
    radius_px: int,
    color: tuple[int, int, int],
    thickness: int = 2,
) -> None:
    if radius_px <= 0:
        return
    dash_deg = 8
    gap_deg = 8
    for start_deg in range(0, 360, dash_deg + gap_deg):
        cv2.ellipse(canvas, center, (radius_px, radius_px), 0.0, start_deg, start_deg + dash_deg, color, thickness, cv2.LINE_AA)


def render_overlay(
    image_path: Path | None,
    board_width_cm: float,
    board_height_cm: float,
    px_per_cm: float,
    matches: list[MatchResult],
    slalom_results: list[SlalomMergeResult],
    failures: list[dict[str, Any]],
    path: Path,
) -> None:
    if image_path is not None and image_path.exists():
        canvas = cv2.imread(str(image_path))
        if canvas is None:
            raise ValueError(f"failed to read image: {image_path}")
        expected_size = (int(round(board_width_cm * px_per_cm)), int(round(board_height_cm * px_per_cm)))
        if canvas.shape[1] != expected_size[0] or canvas.shape[0] != expected_size[1]:
            canvas = cv2.resize(canvas, expected_size, interpolation=cv2.INTER_AREA)
    else:
        canvas = np.full((int(round(board_height_cm * px_per_cm)), int(round(board_width_cm * px_per_cm)), 3), 255, dtype=np.uint8)

    for index, match in enumerate(matches):
        color = PALETTE[index % len(PALETTE)]
        final = final_candidate(match, index)
        final_center_px = cm_to_px(final["center_cm"], board_height_cm, px_per_cm)
        detection_center_px = cm_to_px((match.detection.x, match.detection.y), board_height_cm, px_per_cm)
        detection_radius_px = int(round(match.detection.r * px_per_cm))
        final_radius_px = int(round(float(final["radius_cm"]) * px_per_cm))
        draw_dashed_circle(canvas, detection_center_px, detection_radius_px, color, 2)
        cv2.circle(canvas, final_center_px, final_radius_px, color, 2, cv2.LINE_AA)
        cv2.circle(canvas, final_center_px, 4, color, -1, cv2.LINE_AA)
        if tuple(final_center_px) != tuple(detection_center_px):
            cv2.line(canvas, final_center_px, detection_center_px, color, 1, cv2.LINE_AA)
        label = f"{index}:R{final['radius_cm']:g} {match.mode}"
        cv2.putText(canvas, label, (final_center_px[0] + 5, final_center_px[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)

    support_count = len(matches)
    for result_index, result in enumerate(slalom_results):
        color = PALETTE[(support_count + result_index) % len(PALETTE)]
        for circle_index, center in enumerate(result.centers_cm):
            center_px = cm_to_px(center, board_height_cm, px_per_cm)
            radius_px = int(round(50.0 * px_per_cm))
            cv2.circle(canvas, center_px, radius_px, color, 2, cv2.LINE_AA)
            cv2.circle(canvas, center_px, 4, color, -1, cv2.LINE_AA)
            label = f"S{result.candidate.rank}.{circle_index} {result.mode}"
            cv2.putText(canvas, label, (center_px[0] + 5, center_px[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
        start_px = cm_to_px(result.candidate.start_cm, board_height_cm, px_per_cm)
        end_px = cm_to_px(result.candidate.end_cm, board_height_cm, px_per_cm)
        cv2.line(canvas, start_px, end_px, color, 1, cv2.LINE_AA)

    for failure in failures:
        info_xy = failure.get("info_xy")
        if not isinstance(info_xy, list) or len(info_xy) < 2:
            continue
        point_px = cm_to_px(info_xy, board_height_cm, px_per_cm)
        cv2.drawMarker(canvas, point_px, (0, 0, 255), markerType=cv2.MARKER_TILTED_CROSS, markerSize=18, thickness=2, line_type=cv2.LINE_AA)

    cv2.putText(
        canvas,
        "solid=merged final, dashed=detection, red cross=unmatched text label",
        (8, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.56,
        (20, 20, 20),
        1,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(path), canvas)


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summary_value(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "-"
    return f"{value}{suffix}"


def rounded_point(point: tuple[float, float] | list[float], ndigits: int = 12) -> list[float]:
    return [round(float(point[0]), ndigits), round(float(point[1]), ndigits)]


def write_outputs(
    target: Path,
    matches: list[MatchResult],
    slalom_results: list[SlalomMergeResult],
    failures: list[dict[str, Any]],
    detections: list[DetectionCircle],
    args: argparse.Namespace,
    board_width_cm: float,
    board_height_cm: float,
    px_per_cm: float,
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    helper_circles = [final_candidate(match, index) for index, match in enumerate(matches)]
    r50_60_slaloms = [slalom_record(result) for result in slalom_results]
    output = {
        "helper_circles": helper_circles,
        "r50_60_slaloms": r50_60_slaloms,
        "detection_failures": failures,
        "summary": {
            "final_count": len(helper_circles) + len(r50_60_slaloms) * 3,
            "support_final_count": len(matches),
            "slalom_final_count": len(slalom_results) * 3,
            "slalom_candidate_count": len(slalom_results),
            "failure_count": len(failures),
            "support_detection_count": len(detections),
        },
        "parameters": {
            "unique_center_threshold_cm": args.unique_center_threshold_cm,
            "unique_radius_threshold_cm": args.unique_radius_threshold_cm,
            "ambiguous_center_threshold_cm": args.ambiguous_center_threshold_cm,
            "ambiguous_radius_threshold_cm": args.ambiguous_radius_threshold_cm,
            "radius_only_center_threshold_cm": args.radius_only_center_threshold_cm,
            "radius_only_radius_threshold_cm": args.radius_only_radius_threshold_cm,
            "line_support_tolerance_cm": args.line_support_tolerance_cm,
            "min_line_support_length_cm": args.min_line_support_length_cm,
            "line_support_penalty": args.line_support_penalty,
            "line_support_reward": args.line_support_reward,
            "line_support_reward_cap_cm": args.line_support_reward_cap_cm,
            "slalom_template_report_json": args.slalom_template_report_json,
            "slalom_coordinate_threshold_cm": args.slalom_coordinate_threshold_cm,
            "slalom_cardinal_angle_tolerance_deg": args.slalom_cardinal_angle_tolerance_deg,
            "max_slalom_candidates": args.max_slalom_candidates,
        },
    }
    (target / "consolidated_design_candidates.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    match_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(helper_circles):
        matched_detection = candidate.get("matched_detection", {})
        match_metrics = candidate.get("match_metrics", {})
        match_rows.append(
            {
                "index": index,
                "mode": candidate["mode"],
                "radius_cm": candidate["radius_cm"],
                "center_x_cm": candidate["center_cm"][0],
                "center_y_cm": candidate["center_cm"][1],
                "approx_radius": candidate["approx_radius"],
                "approx_center": candidate["approx_center"],
                "source": candidate.get("source", ""),
                "text": candidate.get("text", ""),
                "text_item_index": candidate.get("text_item_index"),
                "radius_conf": candidate.get("radius_hypothesis_confidence"),
                "xy_conf": candidate.get("xy_hypothesis_confidence"),
                "detection_rank": matched_detection.get("rank"),
                "detection_radius_cm": matched_detection.get("radius_cm"),
                "detection_center_x_cm": matched_detection.get("center_cm", [None, None])[0],
                "detection_center_y_cm": matched_detection.get("center_cm", [None, None])[1],
                "slalom_rank": candidate.get("slalom_candidate_rank"),
                "slalom_circle_index": candidate.get("slalom_circle_index"),
                "turn": candidate.get("turn"),
                "center_distance_cm": match_metrics.get("center_distance_cm"),
                "radius_delta_cm": match_metrics.get("radius_delta_cm"),
                "line_support_length_cm": match_metrics.get("line_support_length_cm"),
                "line_support_ok": match_metrics.get("line_support_ok"),
                "match_cost": match_metrics.get("match_cost"),
            }
        )
    for slalom in r50_60_slaloms:
        for circle in slalom["helper_circles"]:
            index = len(match_rows)
            match_rows.append(
                {
                    "index": index,
                    "mode": slalom["mode"],
                    "radius_cm": circle["radius_cm"],
                    "center_x_cm": circle["center_cm"][0],
                    "center_y_cm": circle["center_cm"][1],
                    "approx_radius": circle["approx_radius"],
                    "approx_center": circle["approx_center"],
                    "source": slalom["source"],
                    "text": "",
                    "text_item_index": None,
                    "radius_conf": 1.0,
                    "xy_conf": None,
                    "detection_rank": slalom["detected_template"]["rank"],
                    "detection_radius_cm": None,
                    "detection_center_x_cm": None,
                    "detection_center_y_cm": None,
                    "slalom_rank": slalom["detected_template"]["rank"],
                    "slalom_circle_index": circle["arc_index"],
                    "turn": circle["turn"],
                    "center_distance_cm": None,
                    "radius_delta_cm": None,
                    "line_support_length_cm": None,
                    "line_support_ok": None,
                    "match_cost": None,
                }
            )
    write_tsv(
        target / "consolidated_design_candidates.tsv",
        match_rows,
        [
            "index",
            "mode",
            "radius_cm",
            "center_x_cm",
            "center_y_cm",
            "approx_radius",
            "approx_center",
            "source",
            "text",
            "text_item_index",
            "radius_conf",
            "xy_conf",
            "detection_rank",
            "detection_radius_cm",
            "detection_center_x_cm",
            "detection_center_y_cm",
            "slalom_rank",
            "slalom_circle_index",
            "turn",
            "center_distance_cm",
            "radius_delta_cm",
            "line_support_length_cm",
            "line_support_ok",
            "match_cost",
        ],
    )
    slalom_rows: list[dict[str, Any]] = []
    for slalom in r50_60_slaloms:
        slalom_rows.append(
            {
                "id": slalom["id"],
                "mode": slalom["mode"],
                "source": slalom["source"],
                "start_x_cm": slalom["start_cm"][0],
                "start_y_cm": slalom["start_cm"][1],
                "end_x_cm": slalom["end_cm"][0],
                "end_y_cm": slalom["end_cm"][1],
                "approx_center": slalom["approx_center"],
                "turns": ",".join(slalom["turns"]),
                "detected_rank": slalom["detected_template"]["rank"],
                "detected_score": slalom["detected_template"]["score"],
            }
        )
    write_tsv(
        target / "r50_60_slaloms.tsv",
        slalom_rows,
        [
            "id",
            "mode",
            "source",
            "start_x_cm",
            "start_y_cm",
            "end_x_cm",
            "end_y_cm",
            "approx_center",
            "turns",
            "detected_rank",
            "detected_score",
        ],
    )
    write_tsv(
        target / "detection_failures.tsv",
        failures,
        ["text_item_index", "text", "info_xy", "radius", "xy", "reason", "evidence"],
    )

    summary_lines = [
        f"final helper circles: {len(helper_circles) + len(slalom_results) * 3}",
        f"support helper circles: {len(matches)}",
        f"slalom helper circles: {len(slalom_results) * 3}",
        f"detection failures: {len(failures)}",
        "",
        "Final helper circles:",
    ]
    for row in match_rows:
        summary_lines.append(
            f"- #{row['index']:02d} {row['mode']} R{row['radius_cm']} "
            f"({row['center_x_cm']}, {row['center_y_cm']}) "
            f"source={row['source']} text={row['text']!r} detection_rank={row['detection_rank']} "
            f"slalom_rank={row['slalom_rank']} d_center={summary_value(row['center_distance_cm'], 'cm')} "
            f"d_radius={summary_value(row['radius_delta_cm'], 'cm')} line_support={summary_value(row['line_support_length_cm'], 'cm')}"
        )
    summary_lines.append("")
    summary_lines.append("Detection failures:")
    for failure in failures:
        summary_lines.append(f"- item {failure['text_item_index']} text={failure['text']!r}: {failure['reason']}")
    (target / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    image_path = Path(args.image_path) if args.image_path else None
    render_overlay(image_path, board_width_cm, board_height_cm, px_per_cm, matches, slalom_results, failures, target / "consolidated_design_candidates.png")


def main() -> None:
    args = parse_args()
    design_path = Path(args.design_info_json)
    report_path = Path(args.support_circle_report_json)
    design_data = load_json(design_path)
    support_report = load_json(report_path)
    board_width_cm, board_height_cm = read_board_size(support_report, args)
    px_per_cm = read_px_per_cm(support_report, args)
    design_items = load_design_items(design_data)
    coordinate_items = load_coordinate_items(design_data)
    detections = load_detection_circles(support_report)
    slalom_candidates: list[SlalomCandidate] = []
    if args.slalom_template_report_json:
        slalom_report = load_json(Path(args.slalom_template_report_json))
        slalom_candidates = load_slalom_candidates(slalom_report, args.max_slalom_candidates)
    trace_points = load_trace_points(Path(args.trace_points_tsv)) if args.trace_points_tsv else None

    matches: list[MatchResult] = []
    failures: list[dict[str, Any]] = []
    for item in design_items:
        item_match, reason = match_design_item(item, detections, args, trace_points)
        if item_match is not None:
            matches.append(item_match)
        else:
            failures.append(failure_record(item, reason))
    slalom_results = [merge_slalom_candidate(candidate, coordinate_items, args) for candidate in slalom_candidates]

    name = args.name or design_path.stem
    target = Path(args.out_dir) / name
    write_outputs(target, matches, slalom_results, failures, detections, args, board_width_cm, board_height_cm, px_per_cm)
    print(f"final helper circles: {len(matches) + len(slalom_results) * 3}")
    print(f"support helper circles: {len(matches)}")
    print(f"slalom helper circles: {len(slalom_results) * 3}")
    print(f"detection failures: {len(failures)}")
    print(f"wrote: {target}")


if __name__ == "__main__":
    main()
