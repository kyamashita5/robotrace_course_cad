#!/usr/bin/env python3
"""Match fitted helper circles against detected/AI-reviewed helper-circle candidates."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


OUT_DIR = Path("tmp/helper_circle_matching")
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
    (128, 0, 0),
    (170, 255, 195),
    (128, 128, 0),
    (255, 215, 180),
    (0, 0, 128),
    (128, 128, 128),
)


@dataclass(frozen=True)
class Circle:
    id: str
    source_index: int
    x: float
    y: float
    r: float
    turn: str | None = None
    source: str | None = None
    approx_radius: bool | None = None
    approx_center: bool | None = None
    evidence: str | None = None
    arc_points: tuple[tuple[float, float], ...] = ()
    arc_length_cm: float | None = None
    arc_angle_deg: float | None = None
    segment_index: int | None = None
    slalom_group_id: str | None = None
    slalom_arc_index: int | None = None


@dataclass(frozen=True)
class Match:
    fitted: Circle
    candidate: Circle
    score: float
    center_distance_cm: float
    radius_delta_cm: float
    normalized_center_error: float
    normalized_radius_error: float
    arc_rms_error_cm: float | None = None
    arc_max_error_cm: float | None = None
    normalized_arc_error: float | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("fitted_json", help="Course CAD JSON produced by line_arc_path_fitting.py")
    parser.add_argument("candidate_json", help="AI review JSON or detect_support_circles report JSON")
    parser.add_argument("--name")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--image-path", help="optional normalized board image for visualization background")
    parser.add_argument("--px-per-cm", type=float, default=4.0)
    parser.add_argument("--board-width-cm", type=float)
    parser.add_argument("--board-height-cm", type=float)
    parser.add_argument("--max-center-distance-cm", type=float, default=18.0)
    parser.add_argument("--max-radius-delta-cm", type=float, default=25.0)
    parser.add_argument("--center-scale-cm", type=float, default=6.0)
    parser.add_argument("--radius-scale-cm", type=float, default=5.0)
    parser.add_argument("--radius-relative-scale", type=float, default=0.03)
    parser.add_argument("--arc-radius-relative-scale", type=float, default=0.20)
    parser.add_argument("--arc-radius-weight", type=float, default=0.08)
    parser.add_argument("--arc-residual-scale-cm", type=float, default=2.0)
    parser.add_argument("--max-arc-rms-error-cm", type=float, default=8.0)
    parser.add_argument("--slalom-arc-residual-scale-cm", type=float, default=8.0)
    parser.add_argument("--max-slalom-arc-rms-error-cm", type=float, default=16.0)
    parser.add_argument("--slalom-trajectory-scale-cm", type=float, default=8.0)
    parser.add_argument("--max-slalom-trajectory-rms-error-cm", type=float, default=16.0)
    parser.add_argument("--arc-sample-spacing-cm", type=float, default=2.0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--score-threshold", type=float, default=0.08)
    parser.add_argument("--allow-radius-mismatch-for-large-r", type=float, default=0.12)
    parser.add_argument("--draw-top-k", type=int, default=1)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_board_size(fitted_data: dict[str, object], candidate_data: dict[str, object], args: argparse.Namespace) -> tuple[float, float]:
    if args.board_width_cm is not None and args.board_height_cm is not None:
        return float(args.board_width_cm), float(args.board_height_cm)
    board = fitted_data.get("board")
    if isinstance(board, dict) and "width_cm" in board and "height_cm" in board:
        return float(board["width_cm"]), float(board["height_cm"])
    config = fitted_data.get("config")
    if isinstance(config, dict) and "board_width_cm" in config and "board_height_cm" in config:
        return float(config["board_width_cm"]), float(config["board_height_cm"])
    board_cm = candidate_data.get("board_cm")
    if isinstance(board_cm, list) and len(board_cm) >= 2:
        return float(board_cm[0]), float(board_cm[1])
    raise ValueError("board size is missing; pass --board-width-cm and --board-height-cm")


def load_fitted_circles(data: dict[str, object], sample_spacing_cm: float = 2.0) -> list[Circle]:
    if isinstance(data.get("segments"), list):
        return load_fitted_arc_segments(data["segments"], sample_spacing_cm)  # type: ignore[arg-type]
    raw_circles = data.get("circles")
    if not isinstance(raw_circles, list):
        raise ValueError("fitted JSON must contain a circles list")
    circles: list[Circle] = []
    for index, item in enumerate(raw_circles):
        if not isinstance(item, dict):
            continue
        circle_id = str(item.get("id", index))
        circles.append(
            Circle(
                id=circle_id,
                source_index=index,
                x=float(item["x"]),
                y=float(item["y"]),
                r=float(item["r"]),
                turn=str(item["turn"]) if item.get("turn") is not None else None,
                source="line_arc_path_fitting",
            )
        )
    return circles


def sample_arc_points(segment: dict[str, object], spacing_cm: float) -> tuple[tuple[float, float], ...]:
    center = segment.get("center")
    if not isinstance(center, list) or len(center) < 2:
        return ()
    radius = float(segment["radius"])
    theta0 = float(segment["theta0"])
    delta_theta = float(segment["delta_theta"])
    arc_length = abs(radius * delta_theta)
    sample_count = max(3, int(math.ceil(arc_length / max(spacing_cm, 0.1))) + 1)
    points: list[tuple[float, float]] = []
    for index in range(sample_count):
        ratio = index / max(sample_count - 1, 1)
        theta = theta0 + delta_theta * ratio
        points.append((float(center[0]) + radius * math.cos(theta), float(center[1]) + radius * math.sin(theta)))
    return tuple(points)


def load_fitted_arc_segments(raw_segments: list[object], sample_spacing_cm: float = 2.0) -> list[Circle]:
    circles: list[Circle] = []
    arc_index = 0
    for segment_index, item in enumerate(raw_segments):
        if not isinstance(item, dict) or item.get("kind") != "arc":
            continue
        center = item.get("center")
        if not isinstance(center, list) or len(center) < 2:
            continue
        clockwise = bool(item.get("clockwise", False))
        radius = float(item["radius"])
        delta_theta = float(item.get("delta_theta", 0.0))
        circles.append(
            Circle(
                id=str(arc_index),
                source_index=arc_index,
                x=float(center[0]),
                y=float(center[1]),
                r=radius,
                turn="cw" if clockwise else "ccw",
                source="line_arc_segments",
                arc_points=sample_arc_points(item, sample_spacing_cm),
                arc_length_cm=float(item.get("arc_length", abs(radius * delta_theta))),
                arc_angle_deg=math.degrees(abs(delta_theta)),
                segment_index=segment_index,
            )
        )
        arc_index += 1
    return circles


def load_candidate_circles(data: dict[str, object]) -> list[Circle]:
    if isinstance(data.get("helper_circles"), list):
        circles = load_ai_review_candidates(data["helper_circles"])  # type: ignore[arg-type]
        if isinstance(data.get("r50_60_slaloms"), list):
            circles.extend(load_r50_60_slalom_candidates(data["r50_60_slaloms"]))  # type: ignore[arg-type]
        return circles
    if isinstance(data.get("r50_60_slaloms"), list):
        return load_r50_60_slalom_candidates(data["r50_60_slaloms"])  # type: ignore[arg-type]
    if isinstance(data.get("candidates"), list):
        return load_detection_candidates(data["candidates"])  # type: ignore[arg-type]
    if isinstance(data.get("circles"), list):
        return load_cad_candidates(data["circles"])  # type: ignore[arg-type]
    raise ValueError("candidate JSON must contain helper_circles, candidates, or circles")


def load_ai_review_candidates(raw: list[object]) -> list[Circle]:
    circles: list[Circle] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        center = item.get("center_cm")
        if not isinstance(center, list) or len(center) < 2:
            continue
        circles.append(
            Circle(
                id=str(item.get("id", index)),
                source_index=index,
                x=float(center[0]),
                y=float(center[1]),
                r=float(item["radius_cm"]),
                turn=str(item["turn"]) if item.get("turn") is not None else None,
                source=str(item.get("source", "ai_review")),
                approx_radius=bool(item.get("approx_radius", False)),
                approx_center=bool(item.get("approx_center", False)),
                evidence=str(item.get("evidence", "")) if item.get("evidence") is not None else None,
                arc_points=load_arc_points_cm(item.get("arc_points_cm")),
                slalom_group_id=slalom_group_id(item),
                slalom_arc_index=slalom_arc_index(item),
            )
        )
    return circles


def angle_ccw(a0: float, a1: float) -> float:
    return (a1 - a0) % math.tau


def angle_cw(a0: float, a1: float) -> float:
    return (a0 - a1) % math.tau


def sample_candidate_arc_points(
    center: tuple[float, float],
    radius: float,
    start: tuple[float, float],
    end: tuple[float, float],
    turn: str,
    spacing_cm: float = 2.0,
) -> tuple[tuple[float, float], ...]:
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    delta = angle_cw(a0, a1) if turn == "cw" else angle_ccw(a0, a1)
    count = max(3, int(math.ceil(abs(radius * delta) / max(spacing_cm, 0.1))) + 1)
    points: list[tuple[float, float]] = []
    for index in range(count):
        ratio = index / max(count - 1, 1)
        theta = a0 - delta * ratio if turn == "cw" else a0 + delta * ratio
        points.append((center[0] + radius * math.cos(theta), center[1] + radius * math.sin(theta)))
    return tuple(points)


def load_r50_60_slalom_candidates(raw: list[object]) -> list[Circle]:
    circles: list[Circle] = []
    for slalom_index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("id", f"slalom_{slalom_index}"))
        start = item.get("start_cm")
        end = item.get("end_cm")
        raw_circles = item.get("helper_circles")
        if not isinstance(start, list) or len(start) < 2:
            continue
        if not isinstance(end, list) or len(end) < 2:
            continue
        if not isinstance(raw_circles, list) or len(raw_circles) != 3:
            continue
        centers: list[tuple[float, float]] = []
        turns: list[str] = []
        radii: list[float] = []
        approx_radius = bool(item.get("approx_radius", False))
        approx_center = bool(item.get("approx_center", False))
        for circle in raw_circles:
            if not isinstance(circle, dict):
                break
            center = circle.get("center_cm")
            if not isinstance(center, list) or len(center) < 2:
                break
            centers.append((float(center[0]), float(center[1])))
            turns.append(str(circle.get("turn", "")))
            radii.append(float(circle.get("radius_cm", item.get("radius_cm", 50.0))))
        if len(centers) != 3 or len(turns) != 3 or len(radii) != 3:
            continue
        boundaries = [
            (float(start[0]), float(start[1])),
            ((centers[0][0] + centers[1][0]) / 2.0, (centers[0][1] + centers[1][1]) / 2.0),
            ((centers[1][0] + centers[2][0]) / 2.0, (centers[1][1] + centers[2][1]) / 2.0),
            (float(end[0]), float(end[1])),
        ]
        for arc_index, center in enumerate(centers):
            circles.append(
                Circle(
                    id=f"{group_id}_{arc_index}",
                    source_index=len(circles),
                    x=center[0],
                    y=center[1],
                    r=radii[arc_index],
                    turn=turns[arc_index],
                    source="slalom_template",
                    approx_radius=approx_radius or bool(raw_circles[arc_index].get("approx_radius", False)),  # type: ignore[index,union-attr]
                    approx_center=approx_center or bool(raw_circles[arc_index].get("approx_center", False)),  # type: ignore[index,union-attr]
                    evidence=str(item.get("evidence", "")) if item.get("evidence") is not None else None,
                    arc_points=sample_candidate_arc_points(center, radii[arc_index], boundaries[arc_index], boundaries[arc_index + 1], turns[arc_index]),
                    slalom_group_id=group_id,
                    slalom_arc_index=arc_index,
                )
            )
    return circles


def slalom_group_id(item: dict[str, object]) -> str | None:
    raw = item.get("slalom_group_id")
    if raw is not None:
        return str(raw)
    raw_id = item.get("id")
    if not isinstance(raw_id, str) or not raw_id.startswith("slalom_"):
        return None
    parts = raw_id.split("_")
    if len(parts) < 3:
        return None
    return "_".join(parts[:2])


def slalom_arc_index(item: dict[str, object]) -> int | None:
    raw = item.get("slalom_arc_index")
    if raw is not None:
        return int(raw)
    raw_id = item.get("id")
    if not isinstance(raw_id, str) or not raw_id.startswith("slalom_"):
        return None
    parts = raw_id.split("_")
    if len(parts) < 3:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def load_arc_points_cm(raw: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(raw, list):
        return ()
    points: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) < 2:
            continue
        points.append((float(item[0]), float(item[1])))
    return tuple(points)


def load_detection_candidates(raw: list[object]) -> list[Circle]:
    circles: list[Circle] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        center = item.get("center_cm")
        if not isinstance(center, list) or len(center) < 2:
            continue
        rank = item.get("rank", index)
        circles.append(
            Circle(
                id=str(rank),
                source_index=index,
                x=float(center[0]),
                y=float(center[1]),
                r=float(item["radius_cm"]),
                source="support_circle_detection",
                approx_radius=True,
                approx_center=True,
                evidence=f"support candidate rank {rank}",
            )
        )
    return circles


def load_cad_candidates(raw: list[object]) -> list[Circle]:
    circles: list[Circle] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        circles.append(
            Circle(
                id=str(item.get("id", index)),
                source_index=index,
                x=float(item["x"]),
                y=float(item["y"]),
                r=float(item["r"]),
                turn=str(item["turn"]) if item.get("turn") is not None else None,
                source="cad_json",
            )
        )
    return circles


def arc_radial_errors(fitted: Circle, candidate: Circle) -> tuple[float, float] | None:
    if not fitted.arc_points:
        return None
    errors = [
        abs(math.hypot(point[0] - candidate.x, point[1] - candidate.y) - candidate.r)
        for point in fitted.arc_points
    ]
    if not errors:
        return None
    rms = math.sqrt(sum(error * error for error in errors) / len(errors))
    return rms, max(errors)


def interpolate_line_points(
    start: tuple[float, float],
    end: tuple[float, float],
    spacing_cm: float,
) -> list[tuple[float, float]]:
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    if distance <= 1e-9:
        return []
    count = max(1, int(math.ceil(distance / max(spacing_cm, 0.1))))
    return [
        (
            start[0] + (end[0] - start[0]) * index / count,
            start[1] + (end[1] - start[1]) * index / count,
        )
        for index in range(1, count)
    ]


def join_paths(
    paths: list[tuple[tuple[float, float], ...]],
    spacing_cm: float,
) -> tuple[tuple[float, float], ...]:
    joined: list[tuple[float, float]] = []
    for path in paths:
        if not path:
            continue
        if joined:
            joined.extend(interpolate_line_points(joined[-1], path[0], spacing_cm))
            joined.extend(path[1:] if math.hypot(joined[-1][0] - path[0][0], joined[-1][1] - path[0][1]) <= 1e-9 else path)
        else:
            joined.extend(path)
    return tuple(joined)


def nearest_path_errors(
    source: tuple[tuple[float, float], ...],
    target: tuple[tuple[float, float], ...],
) -> list[float]:
    if not source or not target:
        return []
    return [
        min(math.hypot(point[0] - sample[0], point[1] - sample[1]) for sample in target)
        for point in source
    ]


def path_rms_and_max(
    first: tuple[tuple[float, float], ...],
    second: tuple[tuple[float, float], ...],
) -> tuple[float, float] | None:
    errors = nearest_path_errors(first, second) + nearest_path_errors(second, first)
    if not errors:
        return None
    rms = math.sqrt(sum(error * error for error in errors) / len(errors))
    return rms, max(errors)


def arc_path_errors(fitted: Circle, candidate: Circle) -> tuple[float, float] | None:
    if not fitted.arc_points or not candidate.arc_points:
        return None
    errors: list[float] = []
    for point in fitted.arc_points:
        nearest = min(math.hypot(point[0] - sample[0], point[1] - sample[1]) for sample in candidate.arc_points)
        errors.append(nearest)
    if not errors:
        return None
    rms = math.sqrt(sum(error * error for error in errors) / len(errors))
    return rms, max(errors)


def compute_match(
    fitted: Circle,
    candidate: Circle,
    center_scale_cm: float,
    radius_scale_cm: float,
    radius_relative_scale: float,
    arc_radius_relative_scale: float,
    arc_radius_weight: float,
    arc_residual_scale_cm: float,
    slalom_arc_residual_scale_cm: float,
) -> Match:
    center_distance = math.hypot(fitted.x - candidate.x, fitted.y - candidate.y)
    radius_delta = abs(fitted.r - candidate.r)
    normalized_center = center_distance / max(center_scale_cm, min(fitted.r, candidate.r) * 0.08, 1e-6)
    arc_errors = arc_path_errors(fitted, candidate) if candidate.source == "slalom_template" else arc_radial_errors(fitted, candidate)
    if arc_errors is None:
        normalized_radius = radius_delta / max(radius_scale_cm, min(fitted.r, candidate.r) * radius_relative_scale, 1e-6)
        normalized_arc = None
        arc_rms = None
        arc_max = None
        score = math.exp(-(normalized_center * normalized_center + normalized_radius * normalized_radius) * 0.5)
    else:
        normalized_radius = radius_delta / max(radius_scale_cm, min(fitted.r, candidate.r) * arc_radius_relative_scale, 1e-6)
        arc_rms, arc_max = arc_errors
        if candidate.source == "slalom_template":
            normalized_arc = arc_rms / max(slalom_arc_residual_scale_cm, 1e-6)
            normalized_center = 0.0
            normalized_radius = 0.0
            # R50/60 templates are path-shape evidence. If the fitted arc interval and turn align,
            # do not penalize fitted center/radius drift from the template helper circle.
            score = math.exp(-(normalized_arc * normalized_arc) * 0.5)
        else:
            normalized_arc = arc_rms / max(arc_residual_scale_cm, 1e-6)
            # The arc residual already accounts for candidate center and radius on the actually used path.
            # Keep a light radius term so same-arc accidental large-radius matches are still disfavored.
            score = math.exp(-(normalized_arc * normalized_arc + arc_radius_weight * normalized_radius * normalized_radius) * 0.5)
    return Match(
        fitted=fitted,
        candidate=candidate,
        score=score,
        center_distance_cm=center_distance,
        radius_delta_cm=radius_delta,
        normalized_center_error=normalized_center,
        normalized_radius_error=normalized_radius,
        arc_rms_error_cm=arc_rms,
        arc_max_error_cm=arc_max,
        normalized_arc_error=normalized_arc,
    )


def radius_gate(fitted: Circle, candidate: Circle, max_radius_delta_cm: float, large_r_ratio: float) -> bool:
    if candidate.source == "slalom_template":
        return True
    delta = abs(fitted.r - candidate.r)
    if delta <= max_radius_delta_cm:
        return True
    large_scale = max(fitted.r, candidate.r)
    return large_scale >= 100.0 and delta / large_scale <= large_r_ratio


def collect_matches(
    fitted_circles: list[Circle],
    candidate_circles: list[Circle],
    args: argparse.Namespace,
) -> tuple[list[dict[str, object]], list[Match]]:
    rows: list[dict[str, object]] = []
    adopted: list[Match] = []
    slalom_overrides = collect_slalom_trajectory_matches(fitted_circles, candidate_circles, args)
    for fitted in fitted_circles:
        override = slalom_overrides.get(fitted.id)
        if override is not None:
            adopted.append(override)
            rows.append(
                {
                    "fitted_id": fitted.id,
                    "fitted_index": fitted.source_index,
                    "fitted_radius_cm": fitted.r,
                    "fitted_center_cm": [round(fitted.x, 6), round(fitted.y, 6)],
                    "fitted_turn": fitted.turn,
                    "fitted_arc_length_cm": round(fitted.arc_length_cm, 6) if fitted.arc_length_cm is not None else None,
                    "fitted_arc_angle_deg": round(fitted.arc_angle_deg, 6) if fitted.arc_angle_deg is not None else None,
                    "fitted_arc_sample_count": len(fitted.arc_points),
                    "best_candidate_id": override.candidate.id,
                    "best_score": round(override.score, 6),
                    "matched_candidates": [match_to_dict(override)],
                }
            )
            continue
        all_matches: list[Match] = []
        for candidate in candidate_circles:
            if candidate.source == "slalom_template" and fitted.turn and candidate.turn and fitted.turn != candidate.turn:
                continue
            if not radius_gate(fitted, candidate, args.max_radius_delta_cm, args.allow_radius_mismatch_for_large_r):
                continue
            match = compute_match(
                fitted,
                candidate,
                args.center_scale_cm,
                args.radius_scale_cm,
                args.radius_relative_scale,
                args.arc_radius_relative_scale,
                args.arc_radius_weight,
                args.arc_residual_scale_cm,
                args.slalom_arc_residual_scale_cm,
            )
            if fitted.arc_points:
                max_arc_rms = args.max_slalom_arc_rms_error_cm if candidate.source == "slalom_template" else args.max_arc_rms_error_cm
                if match.arc_rms_error_cm is None or match.arc_rms_error_cm > max_arc_rms:
                    continue
            elif math.hypot(fitted.x - candidate.x, fitted.y - candidate.y) > args.max_center_distance_cm:
                continue
            if match.score >= args.score_threshold:
                all_matches.append(match)
        all_matches.sort(key=lambda item: item.score, reverse=True)
        top_matches = all_matches[: max(1, args.top_k)]
        if top_matches:
            adopted.append(top_matches[0])
        rows.append(
            {
                "fitted_id": fitted.id,
                "fitted_index": fitted.source_index,
                "fitted_radius_cm": fitted.r,
                "fitted_center_cm": [round(fitted.x, 6), round(fitted.y, 6)],
                "fitted_turn": fitted.turn,
                "fitted_arc_length_cm": round(fitted.arc_length_cm, 6) if fitted.arc_length_cm is not None else None,
                "fitted_arc_angle_deg": round(fitted.arc_angle_deg, 6) if fitted.arc_angle_deg is not None else None,
                "fitted_arc_sample_count": len(fitted.arc_points),
                "best_candidate_id": top_matches[0].candidate.id if top_matches else None,
                "best_score": round(top_matches[0].score, 6) if top_matches else 0.0,
                "matched_candidates": [match_to_dict(match) for match in top_matches],
            }
        )
    return rows, adopted


def collect_slalom_trajectory_matches(
    fitted_circles: list[Circle],
    candidate_circles: list[Circle],
    args: argparse.Namespace,
) -> dict[str, Match]:
    groups: dict[str, list[Circle]] = {}
    for candidate in candidate_circles:
        if candidate.source != "slalom_template" or candidate.slalom_group_id is None:
            continue
        groups.setdefault(candidate.slalom_group_id, []).append(candidate)

    used_fitted_ids: set[str] = set()
    overrides: dict[str, Match] = {}
    for _group_id, raw_group in sorted(groups.items()):
        group = sorted(raw_group, key=lambda item: -1 if item.slalom_arc_index is None else item.slalom_arc_index)
        if len(group) != 3 or any(not circle.arc_points for circle in group):
            continue
        oriented_groups: list[tuple[list[Circle], tuple[tuple[float, float], ...]]] = [
            (group, join_paths([circle.arc_points for circle in group], args.arc_sample_spacing_cm)),
            (
                list(reversed(group)),
                join_paths([tuple(reversed(circle.arc_points)) for circle in reversed(group)], args.arc_sample_spacing_cm),
            ),
        ]
        best: tuple[float, float, float, list[Circle], list[Circle]] | None = None
        for start_index in range(0, len(fitted_circles) - 2):
            window = fitted_circles[start_index : start_index + 3]
            if any(circle.id in used_fitted_ids for circle in window):
                continue
            fitted_path = join_paths([circle.arc_points for circle in window], args.arc_sample_spacing_cm)
            for oriented_group, candidate_path in oriented_groups:
                if [circle.turn for circle in window] != [circle.turn for circle in oriented_group]:
                    continue
                errors = path_rms_and_max(fitted_path, candidate_path)
                if errors is None:
                    continue
                rms, max_error = errors
                if rms > args.max_slalom_trajectory_rms_error_cm:
                    continue
                score = math.exp(-((rms / max(args.slalom_trajectory_scale_cm, 1e-6)) ** 2) * 0.5)
                center_sum = sum(
                    math.hypot(fitted.x - candidate.x, fitted.y - candidate.y)
                    for fitted, candidate in zip(window, oriented_group)
                )
                if best is None or score > best[0] + 1e-9 or (abs(score - best[0]) <= 1e-9 and center_sum < best[2]):
                    best = (score, rms, center_sum, window, oriented_group)
        if best is None:
            continue
        score, rms, _center_sum, window, adopted_group = best
        for fitted, candidate in zip(window, adopted_group):
            center_distance = math.hypot(fitted.x - candidate.x, fitted.y - candidate.y)
            radius_delta = abs(fitted.r - candidate.r)
            overrides[fitted.id] = Match(
                fitted=fitted,
                candidate=candidate,
                score=score,
                center_distance_cm=center_distance,
                radius_delta_cm=radius_delta,
                normalized_center_error=0.0,
                normalized_radius_error=0.0,
                arc_rms_error_cm=rms,
                arc_max_error_cm=None,
                normalized_arc_error=rms / max(args.slalom_trajectory_scale_cm, 1e-6),
            )
            used_fitted_ids.add(fitted.id)
    return overrides


def match_to_dict(match: Match) -> dict[str, object]:
    candidate = match.candidate
    return {
        "candidate_id": candidate.id,
        "candidate_index": candidate.source_index,
        "candidate_radius_cm": candidate.r,
        "candidate_center_cm": [round(candidate.x, 12), round(candidate.y, 12)],
        "candidate_turn": candidate.turn,
        "candidate_source": candidate.source,
        "candidate_approx_radius": candidate.approx_radius,
        "candidate_approx_center": candidate.approx_center,
        "score": round(match.score, 6),
        "center_distance_cm": round(match.center_distance_cm, 6),
        "radius_delta_cm": round(match.radius_delta_cm, 6),
        "normalized_center_error": round(match.normalized_center_error, 6),
        "normalized_radius_error": round(match.normalized_radius_error, 6),
        "arc_rms_error_cm": None if match.arc_rms_error_cm is None else round(match.arc_rms_error_cm, 6),
        "arc_max_error_cm": None if match.arc_max_error_cm is None else round(match.arc_max_error_cm, 6),
        "normalized_arc_error": None if match.normalized_arc_error is None else round(match.normalized_arc_error, 6),
        "evidence": candidate.evidence,
    }


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [
        "fitted_index\tfitted_id\tfitted_radius_cm\tfitted_x_cm\tfitted_y_cm\tfitted_arc_length_cm\tfitted_arc_angle_deg\tbest_candidate_id\tbest_score\tcandidate_radius_cm\tcandidate_x_cm\tcandidate_y_cm\tcenter_distance_cm\tradius_delta_cm\tarc_rms_error_cm\tarc_max_error_cm\tcandidate_source\tcandidate_approx_radius\tcandidate_approx_center"
    ]
    for row in rows:
        matches = row["matched_candidates"]
        if not isinstance(matches, list) or not matches:
            lines.append(
                "\t".join(
                    [
                        str(row["fitted_index"]),
                        str(row["fitted_id"]),
                        f"{float(row['fitted_radius_cm']):.6f}",
                        f"{float(row['fitted_center_cm'][0]):.6f}",
                        f"{float(row['fitted_center_cm'][1]):.6f}",
                        "" if row.get("fitted_arc_length_cm") is None else f"{float(row['fitted_arc_length_cm']):.6f}",
                        "" if row.get("fitted_arc_angle_deg") is None else f"{float(row['fitted_arc_angle_deg']):.6f}",
                        "",
                        "0.000000",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
            )
            continue
        for index, match in enumerate(matches):
            lines.append(
                "\t".join(
                    [
                        str(row["fitted_index"]),
                        str(row["fitted_id"]),
                        f"{float(row['fitted_radius_cm']):.6f}",
                        f"{float(row['fitted_center_cm'][0]):.6f}",
                        f"{float(row['fitted_center_cm'][1]):.6f}",
                        "" if row.get("fitted_arc_length_cm") is None else f"{float(row['fitted_arc_length_cm']):.6f}",
                        "" if row.get("fitted_arc_angle_deg") is None else f"{float(row['fitted_arc_angle_deg']):.6f}",
                        str(match["candidate_id"]) if index == 0 else str(match["candidate_id"]),
                        f"{float(match['score']):.6f}",
                        f"{float(match['candidate_radius_cm']):.6f}",
                        f"{float(match['candidate_center_cm'][0]):.6f}",
                        f"{float(match['candidate_center_cm'][1]):.6f}",
                        f"{float(match['center_distance_cm']):.6f}",
                        f"{float(match['radius_delta_cm']):.6f}",
                        "" if match.get("arc_rms_error_cm") is None else f"{float(match['arc_rms_error_cm']):.6f}",
                        "" if match.get("arc_max_error_cm") is None else f"{float(match['arc_max_error_cm']):.6f}",
                        str(match["candidate_source"]),
                        str(match["candidate_approx_radius"]),
                        str(match["candidate_approx_center"]),
                    ]
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cm_to_px(x: float, y: float, board_height_cm: float, px_per_cm: float) -> tuple[int, int]:
    return int(round(x * px_per_cm)), int(round((board_height_cm - y) * px_per_cm))


def load_background(path: str | None, board_width_cm: float, board_height_cm: float, px_per_cm: float) -> np.ndarray:
    width = int(round(board_width_cm * px_per_cm))
    height = int(round(board_height_cm * px_per_cm))
    if path:
        image = cv2.imread(path)
        if image is None:
            raise FileNotFoundError(path)
        if image.shape[1] != width or image.shape[0] != height:
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        return image
    return np.full((height, width, 3), 255, dtype=np.uint8)


def draw_dashed_circle(
    image: np.ndarray,
    center: tuple[int, int],
    radius_px: int,
    color: tuple[int, int, int],
    thickness: int,
    dash_deg: int = 10,
) -> None:
    for start_deg in range(0, 360, dash_deg * 2):
        cv2.ellipse(image, center, (radius_px, radius_px), 0.0, start_deg, start_deg + dash_deg, color, thickness, cv2.LINE_AA)


def draw_dashed_line(
    image: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    thickness: int,
    dash_px: float = 10.0,
    gap_px: float = 7.0,
) -> None:
    start_array = np.array(start, dtype=np.float64)
    end_array = np.array(end, dtype=np.float64)
    vector = end_array - start_array
    length = float(np.linalg.norm(vector))
    if length <= 1e-6:
        cv2.circle(image, start, max(1, thickness), color, -1, cv2.LINE_AA)
        return
    direction = vector / length
    position = 0.0
    while position < length:
        segment_end = min(position + dash_px, length)
        p0 = start_array + direction * position
        p1 = start_array + direction * segment_end
        cv2.line(
            image,
            (int(round(p0[0])), int(round(p0[1]))),
            (int(round(p1[0])), int(round(p1[1]))),
            color,
            thickness,
            cv2.LINE_AA,
        )
        position += dash_px + gap_px


def draw_visualization(
    path: Path,
    fitted_circles: list[Circle],
    candidate_circles: list[Circle],
    adopted: list[Match],
    board_width_cm: float,
    board_height_cm: float,
    px_per_cm: float,
    image_path: str | None,
    draw_top_k: int,
) -> None:
    canvas = load_background(image_path, board_width_cm, board_height_cm, px_per_cm)
    match_by_fitted = {match.fitted.id: match for match in adopted}
    color_by_candidate: dict[str, tuple[int, int, int]] = {}
    for index, match in enumerate(adopted):
        color_by_candidate.setdefault(match.candidate.id, PALETTE[index % len(PALETTE)])

    unmatched_color = (170, 170, 170)
    for candidate in candidate_circles:
        color = color_by_candidate.get(candidate.id, unmatched_color)
        center = cm_to_px(candidate.x, candidate.y, board_height_cm, px_per_cm)
        radius_px = max(1, int(round(candidate.r * px_per_cm)))
        draw_dashed_circle(canvas, center, radius_px, color, 2)

    for fitted in fitted_circles:
        match = match_by_fitted.get(fitted.id)
        color = color_by_candidate.get(match.candidate.id, unmatched_color) if match else unmatched_color
        center = cm_to_px(fitted.x, fitted.y, board_height_cm, px_per_cm)
        radius_px = max(1, int(round(fitted.r * px_per_cm)))
        cv2.circle(canvas, center, radius_px, color, 2, cv2.LINE_AA)
        cv2.circle(canvas, center, 3, color, -1, cv2.LINE_AA)
        label = f"F{fitted.source_index}"
        if match:
            label += f" C{match.candidate.id} {match.score:.2f}"
            candidate_center = cm_to_px(match.candidate.x, match.candidate.y, board_height_cm, px_per_cm)
            draw_dashed_line(canvas, center, candidate_center, color, 1)
        cv2.putText(canvas, label, (center[0] + 4, center[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)

    legend_y = 24
    cv2.putText(canvas, "solid circle=fitted, dashed circle=candidate, dashed line=center link", (8, legend_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), canvas)


def summarize(rows: list[dict[str, object]], candidate_circles: list[Circle]) -> dict[str, object]:
    matched_candidate_ids: dict[str, list[str]] = {}
    unmatched_fitted_ids: list[str] = []
    matched_count = 0
    for row in rows:
        cid = row.get("best_candidate_id")
        if cid is None:
            unmatched_fitted_ids.append(str(row["fitted_id"]))
            continue
        matched_count += 1
        matched_candidate_ids.setdefault(str(cid), []).append(str(row["fitted_id"]))
    candidate_ids = {circle.id for circle in candidate_circles}
    unmatched_candidate_ids = sorted(candidate_ids - set(matched_candidate_ids))
    multi_matched = {key: value for key, value in matched_candidate_ids.items() if len(value) >= 2}
    return {
        "fitted_count": len(rows),
        "candidate_count": len(candidate_circles),
        "matched_fitted_count": matched_count,
        "unmatched_fitted_count": len(rows) - matched_count,
        "matched_candidate_count": len(matched_candidate_ids),
        "unmatched_candidate_count": len(candidate_circles) - len(matched_candidate_ids),
        "unmatched_fitted_ids": unmatched_fitted_ids,
        "unmatched_candidate_ids": unmatched_candidate_ids,
        "matched_candidate_to_fitted_ids": matched_candidate_ids,
        "multi_matched_candidate_to_fitted_ids": multi_matched,
    }


def main() -> None:
    args = parse_args()
    fitted_path = Path(args.fitted_json)
    candidate_path = Path(args.candidate_json)
    name = args.name or f"{fitted_path.stem}_to_{candidate_path.stem}"
    target = Path(args.out_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    fitted_data = load_json(fitted_path)
    candidate_data = load_json(candidate_path)
    board_width_cm, board_height_cm = read_board_size(fitted_data, candidate_data, args)
    fitted_circles = load_fitted_circles(fitted_data, args.arc_sample_spacing_cm)
    candidate_circles = load_candidate_circles(candidate_data)
    rows, adopted = collect_matches(fitted_circles, candidate_circles, args)
    summary = summarize(rows, candidate_circles)

    report = {
        "fitted_json": str(fitted_path),
        "candidate_json": str(candidate_path),
        "board_cm": [board_width_cm, board_height_cm],
        "parameters": {
            "max_center_distance_cm": args.max_center_distance_cm,
            "max_radius_delta_cm": args.max_radius_delta_cm,
            "center_scale_cm": args.center_scale_cm,
            "radius_scale_cm": args.radius_scale_cm,
            "radius_relative_scale": args.radius_relative_scale,
            "arc_radius_relative_scale": args.arc_radius_relative_scale,
            "arc_radius_weight": args.arc_radius_weight,
            "arc_residual_scale_cm": args.arc_residual_scale_cm,
            "max_arc_rms_error_cm": args.max_arc_rms_error_cm,
            "slalom_arc_residual_scale_cm": args.slalom_arc_residual_scale_cm,
            "max_slalom_arc_rms_error_cm": args.max_slalom_arc_rms_error_cm,
            "slalom_trajectory_scale_cm": args.slalom_trajectory_scale_cm,
            "max_slalom_trajectory_rms_error_cm": args.max_slalom_trajectory_rms_error_cm,
            "arc_sample_spacing_cm": args.arc_sample_spacing_cm,
            "top_k": args.top_k,
            "score_threshold": args.score_threshold,
            "allow_radius_mismatch_for_large_r": args.allow_radius_mismatch_for_large_r,
        },
        "summary": summary,
        "matches": rows,
    }
    (target / "helper_circle_matches.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_tsv(target / "helper_circle_matches.tsv", rows)
    draw_visualization(
        target / "helper_circle_matches.png",
        fitted_circles,
        candidate_circles,
        adopted,
        board_width_cm,
        board_height_cm,
        args.px_per_cm,
        args.image_path,
        args.draw_top_k,
    )
    print(f"wrote helper-circle matching report to {target}")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
