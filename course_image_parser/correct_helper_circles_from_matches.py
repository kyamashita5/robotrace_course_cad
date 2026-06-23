#!/usr/bin/env python3
"""Correct a fitted helper-circle sequence with matched image-analysis circles."""

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


OUT_DIR = Path("tmp/helper_circle_correction")
TOUCH_SLACK_CM = 1e-10
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
)


@dataclass
class CircleMeta:
    source_fitted_ids: list[str]
    source_fitted_indices: list[int]
    matched_candidate_id: str | None
    match_score: float | None
    replaced_from_match: bool
    approx_radius: bool
    approx_center: bool
    candidate_source: str | None
    evidence: str | None
    actions: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("fitted_json", help="Course CAD JSON produced by line_arc_path_fitting.py")
    parser.add_argument("match_json", help="helper_circle_matches.json produced by match_helper_circles.py")
    parser.add_argument("--name")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--min-match-score", type=float, default=0.4)
    parser.add_argument("--touch-tangent-threshold-cm", type=float, default=5.0)
    parser.add_argument("--trace-report", help="trace_centerline_points.py report.json for exact START-GOAL line")
    parser.add_argument("--start-cm", help="START point as x,y; overrides --trace-report")
    parser.add_argument("--goal-cm", help="GOAL point as x,y; overrides --trace-report")
    parser.add_argument("--image-path", help="optional normalized board image for visualization background")
    parser.add_argument("--px-per-cm", type=float, default=4.0)
    parser.add_argument("--no-fit-approx-centers", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_point(raw: str) -> tuple[float, float]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2:
        raise ValueError(f"invalid point: {raw}")
    return float(parts[0]), float(parts[1])


def read_start_goal(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray] | None:
    if args.start_cm and args.goal_cm:
        return np.asarray(parse_point(args.start_cm), dtype=np.float64), np.asarray(parse_point(args.goal_cm), dtype=np.float64)
    if not args.trace_report:
        return None
    data = load_json(Path(args.trace_report))
    start = data.get("start_cm")
    goal = data.get("goal_cm")
    if isinstance(start, list) and len(start) >= 2 and isinstance(goal, list) and len(goal) >= 2:
        return np.asarray([float(start[0]), float(start[1])], dtype=np.float64), np.asarray([float(goal[0]), float(goal[1])], dtype=np.float64)
    return None


def circle_center(circle: dict[str, Any]) -> np.ndarray:
    return np.asarray([float(circle["x"]), float(circle["y"])], dtype=np.float64)


def set_circle_center(circle: dict[str, Any], center: np.ndarray) -> None:
    circle["x"] = round(float(center[0]), 12)
    circle["y"] = round(float(center[1]), 12)


def set_circle_radius(circle: dict[str, Any], radius: float) -> None:
    circle["r"] = round(float(radius), 6)


def helper_touch_distance(anchor: dict[str, Any], moving: dict[str, Any]) -> float:
    anchor_radius = float(anchor["r"])
    moving_radius = float(moving["r"])
    if anchor.get("turn") == moving.get("turn"):
        return abs(anchor_radius - moving_radius) + TOUCH_SLACK_CM
    return anchor_radius + moving_radius + TOUCH_SLACK_CM


def tangent_length_between(a: dict[str, Any], b: dict[str, Any]) -> float:
    distance = float(np.linalg.norm(circle_center(a) - circle_center(b)))
    touch_distance = helper_touch_distance(a, b)
    if distance <= touch_distance:
        return 0.0
    return math.sqrt(max(0.0, distance * distance - touch_distance * touch_distance))


def circle_intersection_centers(c0: np.ndarray, r0: float, c1: np.ndarray, r1: float) -> list[np.ndarray]:
    delta = c1 - c0
    distance = float(np.linalg.norm(delta))
    eps = 1e-6
    if distance <= eps:
        return []
    if distance > r0 + r1 + eps:
        return []
    if distance < abs(r0 - r1) - eps:
        return []
    a = (r0 * r0 - r1 * r1 + distance * distance) / (2.0 * distance)
    h2 = r0 * r0 - a * a
    if h2 < -eps:
        return []
    base = c0 + delta * (a / distance)
    if abs(h2) <= eps:
        return [base]
    h = math.sqrt(max(0.0, h2))
    offset = np.asarray([-delta[1] / distance * h, delta[0] / distance * h], dtype=np.float64)
    return [base + offset, base - offset]


def adjusted_center_touching_neighbors(circles: list[dict[str, Any]], index: int) -> np.ndarray | None:
    if not 0 < index < len(circles) - 1:
        return None
    previous = circles[index - 1]
    selected = circles[index]
    next_circle = circles[index + 1]
    distance_to_previous = helper_touch_distance(previous, selected)
    distance_to_next = helper_touch_distance(next_circle, selected)
    if distance_to_previous <= 1e-6 or distance_to_next <= 1e-6:
        return None
    candidates = circle_intersection_centers(
        circle_center(previous),
        distance_to_previous,
        circle_center(next_circle),
        distance_to_next,
    )
    if not candidates:
        return None
    current = circle_center(selected)
    return min(candidates, key=lambda point: float(np.linalg.norm(point - current)))


def adjusted_center_touching_anchor(
    circles: list[dict[str, Any]],
    index: int,
    anchor_index: int,
) -> np.ndarray | None:
    moving = circles[index]
    anchor = circles[anchor_index]
    moving_center = circle_center(moving)
    anchor_center = circle_center(anchor)
    direction_to_anchor = anchor_center - moving_center
    current_distance = float(np.linalg.norm(direction_to_anchor))
    target_distance = helper_touch_distance(anchor, moving)
    if current_distance <= 1e-9 or target_distance <= 1e-6:
        return None
    t_candidates = [
        1.0 - target_distance / current_distance,
        1.0 + target_distance / current_distance,
    ]
    best_t = min(t_candidates, key=lambda t: t * t)
    return moving_center + direction_to_anchor * best_t


def adjusted_center_touching_neighbor_and_line(
    circles: list[dict[str, Any]],
    index: int,
    neighbor_index: int,
    start_goal: tuple[np.ndarray, np.ndarray],
) -> np.ndarray | None:
    start, goal = start_goal
    line = goal - start
    line_length = float(np.linalg.norm(line))
    if line_length <= 1e-9:
        return None
    unit = line / line_length
    normal = np.asarray([-unit[1], unit[0]], dtype=np.float64)
    moving = circles[index]
    neighbor = circles[neighbor_index]
    neighbor_center = circle_center(neighbor)
    current_center = circle_center(moving)
    touch_distance = helper_touch_distance(neighbor, moving)
    line_offset = float(moving["r"]) + TOUCH_SLACK_CM

    candidates: list[np.ndarray] = []
    for side in (-1.0, 1.0):
        offset_origin = start + normal * (side * line_offset)
        neighbor_along = float(np.dot(neighbor_center - offset_origin, unit))
        neighbor_perp_vector = neighbor_center - (offset_origin + unit * neighbor_along)
        neighbor_perp_sq = float(np.dot(neighbor_perp_vector, neighbor_perp_vector))
        along_sq = touch_distance * touch_distance - neighbor_perp_sq
        if along_sq < -1e-8:
            continue
        along = math.sqrt(max(0.0, along_sq))
        candidates.append(offset_origin + unit * (neighbor_along + along))
        candidates.append(offset_origin + unit * (neighbor_along - along))
    if not candidates:
        return None
    return min(candidates, key=lambda point: float(np.linalg.norm(point - current_center)))


def read_board_size(course_data: dict[str, Any], match_data: dict[str, Any]) -> tuple[float, float]:
    board = course_data.get("board")
    if isinstance(board, dict) and "width_cm" in board and "height_cm" in board:
        return float(board["width_cm"]), float(board["height_cm"])
    board_cm = match_data.get("board_cm")
    if isinstance(board_cm, list) and len(board_cm) >= 2:
        return float(board_cm[0]), float(board_cm[1])
    raise ValueError("board size is missing from fitted or match JSON")


def best_match(row: dict[str, Any], min_score: float) -> dict[str, Any] | None:
    matches = row.get("matched_candidates")
    if not isinstance(matches, list) or not matches:
        return None
    match = matches[0]
    if not isinstance(match, dict):
        return None
    score = float(match.get("score", 0.0))
    if score < min_score:
        return None
    return match


def merge_or_append_circle(
    corrected: list[dict[str, Any]],
    metas: list[CircleMeta],
    circle: dict[str, Any],
    meta: CircleMeta,
) -> None:
    if (
        corrected
        and meta.matched_candidate_id is not None
        and metas[-1].matched_candidate_id == meta.matched_candidate_id
        and metas[-1].replaced_from_match
        and meta.replaced_from_match
    ):
        metas[-1].source_fitted_ids.extend(meta.source_fitted_ids)
        metas[-1].source_fitted_indices.extend(meta.source_fitted_indices)
        metas[-1].match_score = max(float(metas[-1].match_score or 0.0), float(meta.match_score or 0.0))
        metas[-1].approx_radius = metas[-1].approx_radius or meta.approx_radius
        metas[-1].approx_center = metas[-1].approx_center or meta.approx_center
        metas[-1].actions.append("merged_consecutive_same_candidate")
        return
    corrected.append(circle)
    metas.append(meta)


def build_corrected_sequence(
    course_data: dict[str, Any],
    match_data: dict[str, Any],
    min_match_score: float,
) -> tuple[list[dict[str, Any]], list[CircleMeta]]:
    source_circles = course_data.get("circles")
    if not isinstance(source_circles, list):
        raise ValueError("fitted JSON must contain circles")
    rows = match_data.get("matches")
    if not isinstance(rows, list):
        raise ValueError("match JSON must contain matches")
    rows_by_index = {int(row["fitted_index"]): row for row in rows if isinstance(row, dict) and "fitted_index" in row}

    corrected: list[dict[str, Any]] = []
    metas: list[CircleMeta] = []
    for index, raw_circle in enumerate(source_circles):
        if not isinstance(raw_circle, dict):
            continue
        circle = dict(raw_circle)
        fitted_id = str(raw_circle.get("id", index))
        row = rows_by_index.get(index)
        match = best_match(row, min_match_score) if row is not None else None
        actions: list[str] = []
        if match is not None:
            center = match.get("candidate_center_cm")
            if not isinstance(center, list) or len(center) < 2:
                raise ValueError(f"match for fitted index {index} lacks candidate_center_cm")
            set_circle_center(circle, np.asarray([float(center[0]), float(center[1])], dtype=np.float64))
            set_circle_radius(circle, float(match["candidate_radius_cm"]))
            if match.get("candidate_turn") is not None:
                circle["turn"] = str(match["candidate_turn"])
            actions.append("replaced_with_matched_candidate")
            meta = CircleMeta(
                source_fitted_ids=[fitted_id],
                source_fitted_indices=[index],
                matched_candidate_id=str(match.get("candidate_id")),
                match_score=float(match.get("score", 0.0)),
                replaced_from_match=True,
                approx_radius=bool(match.get("candidate_approx_radius", False)),
                approx_center=bool(match.get("candidate_approx_center", False)),
                candidate_source=str(match.get("candidate_source")) if match.get("candidate_source") is not None else None,
                evidence=str(match.get("evidence")) if match.get("evidence") is not None else None,
                actions=actions,
            )
        else:
            actions.append("kept_original_unmatched")
            meta = CircleMeta(
                source_fitted_ids=[fitted_id],
                source_fitted_indices=[index],
                matched_candidate_id=None,
                match_score=None,
                replaced_from_match=False,
                approx_radius=False,
                approx_center=False,
                candidate_source=None,
                evidence=None,
                actions=actions,
            )
        merge_or_append_circle(corrected, metas, circle, meta)

    for new_id, circle in enumerate(corrected):
        circle["id"] = new_id
    return corrected, metas


def fit_approx_centers(
    circles: list[dict[str, Any]],
    metas: list[CircleMeta],
    touch_tangent_threshold_cm: float,
    start_goal: tuple[np.ndarray, np.ndarray] | None,
) -> None:
    def dimensions_are_confirmed(index: int) -> bool:
        return not metas[index].approx_radius and not metas[index].approx_center

    for index, meta in enumerate(metas):
        if not meta.approx_center:
            continue
        before = circle_center(circles[index])
        touches_prev = index > 0 and tangent_length_between(circles[index - 1], circles[index]) <= touch_tangent_threshold_cm
        touches_next = index < len(circles) - 1 and tangent_length_between(circles[index], circles[index + 1]) <= touch_tangent_threshold_cm
        prev_confirmed = index > 0 and dimensions_are_confirmed(index - 1)
        next_confirmed = index < len(circles) - 1 and dimensions_are_confirmed(index + 1)
        new_center: np.ndarray | None = None
        action = None
        if touches_prev and touches_next and not (prev_confirmed and next_confirmed):
            meta.actions.append("approx_center_not_fit_touch_neighbors_unconfirmed")
            continue
        if touches_prev and not touches_next and not prev_confirmed:
            meta.actions.append("approx_center_not_fit_prev_unconfirmed")
            continue
        if touches_next and not touches_prev and not next_confirmed:
            meta.actions.append("approx_center_not_fit_next_unconfirmed")
            continue
        if index == 0 and touches_next and next_confirmed and start_goal is not None:
            new_center = adjusted_center_touching_neighbor_and_line(circles, index, index + 1, start_goal)
            action = "fit_next_and_start_goal_line"
        elif index == len(circles) - 1 and touches_prev and prev_confirmed and start_goal is not None:
            new_center = adjusted_center_touching_neighbor_and_line(circles, index, index - 1, start_goal)
            action = "fit_prev_and_start_goal_line"
        if new_center is None and touches_prev and touches_next and prev_confirmed and next_confirmed:
            new_center = adjusted_center_touching_neighbors(circles, index)
            action = "fit_touch_prev_next"
        if new_center is None and touches_prev and not touches_next and prev_confirmed:
            new_center = adjusted_center_touching_anchor(circles, index, index - 1)
            action = "fit_prev"
        if new_center is None and touches_next and not touches_prev and next_confirmed:
            new_center = adjusted_center_touching_anchor(circles, index, index + 1)
            action = "fit_next"
        if new_center is None:
            meta.actions.append("approx_center_not_fit_no_touch_context")
            continue
        set_circle_center(circles[index], new_center)
        after = circle_center(circles[index])
        meta.actions.append(str(action))
        meta.actions.append(f"fit_moved_cm={float(np.linalg.norm(after - before)):.6f}")


def update_radius_presets(course_data: dict[str, Any], circles: list[dict[str, Any]]) -> None:
    existing = course_data.get("radius_presets_cm")
    values = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]
    if isinstance(existing, list):
        values.extend(float(value) for value in existing)
    values.extend(round(float(circle["r"]), 6) for circle in circles)
    course_data["radius_presets_cm"] = sorted(set(round(value, 6) for value in values))


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


def draw_visualization(
    path: Path,
    original_circles: list[dict[str, Any]],
    corrected_circles: list[dict[str, Any]],
    metas: list[CircleMeta],
    board_width_cm: float,
    board_height_cm: float,
    px_per_cm: float,
    image_path: str | None,
) -> None:
    canvas = load_background(image_path, board_width_cm, board_height_cm, px_per_cm)
    original_color = (160, 160, 160)
    for circle in original_circles:
        center = cm_to_px(float(circle["x"]), float(circle["y"]), board_height_cm, px_per_cm)
        radius_px = max(1, int(round(float(circle["r"]) * px_per_cm)))
        draw_dashed_circle(canvas, center, radius_px, original_color, 1)
    for index, (circle, meta) in enumerate(zip(corrected_circles, metas)):
        color = PALETTE[index % len(PALETTE)]
        center = cm_to_px(float(circle["x"]), float(circle["y"]), board_height_cm, px_per_cm)
        radius_px = max(1, int(round(float(circle["r"]) * px_per_cm)))
        cv2.circle(canvas, center, radius_px, color, 2, cv2.LINE_AA)
        cv2.circle(canvas, center, 3, color, -1, cv2.LINE_AA)
        flags = ""
        if meta.approx_radius:
            flags += " r~"
        if meta.approx_center:
            flags += " c~"
        label = f"H{index} R{float(circle['r']):g}{flags}"
        cv2.putText(canvas, label, (center[0] + 4, center[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    cv2.putText(canvas, "solid=corrected helper circles, dashed gray=original fitted circles", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), canvas)


def write_tsv(path: Path, circles: list[dict[str, Any]], metas: list[CircleMeta]) -> None:
    fieldnames = [
        "id",
        "x_cm",
        "y_cm",
        "radius_cm",
        "turn",
        "source_fitted_indices",
        "matched_candidate_id",
        "match_score",
        "approx_radius",
        "approx_center",
        "actions",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for circle, meta in zip(circles, metas):
            writer.writerow(
                {
                    "id": circle["id"],
                    "x_cm": f"{float(circle['x']):.6f}",
                    "y_cm": f"{float(circle['y']):.6f}",
                    "radius_cm": f"{float(circle['r']):.6f}",
                    "turn": circle.get("turn"),
                    "source_fitted_indices": ",".join(str(value) for value in meta.source_fitted_indices),
                    "matched_candidate_id": meta.matched_candidate_id or "",
                    "match_score": "" if meta.match_score is None else f"{meta.match_score:.6f}",
                    "approx_radius": str(meta.approx_radius),
                    "approx_center": str(meta.approx_center),
                    "actions": ";".join(meta.actions),
                }
            )


def meta_to_dict(meta: CircleMeta) -> dict[str, Any]:
    return {
        "source_fitted_ids": meta.source_fitted_ids,
        "source_fitted_indices": meta.source_fitted_indices,
        "matched_candidate_id": meta.matched_candidate_id,
        "match_score": meta.match_score,
        "replaced_from_match": meta.replaced_from_match,
        "approx_radius": meta.approx_radius,
        "approx_center": meta.approx_center,
        "candidate_source": meta.candidate_source,
        "evidence": meta.evidence,
        "actions": meta.actions,
    }


def main() -> None:
    args = parse_args()
    fitted_path = Path(args.fitted_json)
    match_path = Path(args.match_json)
    name = args.name or fitted_path.stem
    target = Path(args.out_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    course_data = load_json(fitted_path)
    match_data = load_json(match_path)
    board_width_cm, board_height_cm = read_board_size(course_data, match_data)
    original_circles = [dict(circle) for circle in course_data.get("circles", []) if isinstance(circle, dict)]
    corrected_circles, metas = build_corrected_sequence(course_data, match_data, args.min_match_score)
    start_goal = read_start_goal(args)
    if not args.no_fit_approx_centers:
        fit_approx_centers(corrected_circles, metas, args.touch_tangent_threshold_cm, start_goal)

    corrected_data = dict(course_data)
    corrected_data["circles"] = corrected_circles
    update_radius_presets(corrected_data, corrected_circles)
    corrected_data["metadata"] = {
        **(corrected_data.get("metadata") if isinstance(corrected_data.get("metadata"), dict) else {}),
        "helper_circle_correction": {
            "fitted_json": str(fitted_path),
            "match_json": str(match_path),
            "min_match_score": args.min_match_score,
            "touch_tangent_threshold_cm": args.touch_tangent_threshold_cm,
            "fit_approx_centers": not args.no_fit_approx_centers,
        },
    }

    summary = {
        "input_circle_count": len(original_circles),
        "output_circle_count": len(corrected_circles),
        "replaced_count": sum(1 for meta in metas if meta.replaced_from_match),
        "approx_radius_count": sum(1 for meta in metas if meta.approx_radius),
        "approx_center_count": sum(1 for meta in metas if meta.approx_center),
        "merged_output_count": sum(1 for meta in metas if len(meta.source_fitted_indices) >= 2),
    }
    report = {
        "summary": summary,
        "board_cm": [board_width_cm, board_height_cm],
        "start_goal_cm": None
        if start_goal is None
        else [[round(float(start_goal[0][0]), 6), round(float(start_goal[0][1]), 6)], [round(float(start_goal[1][0]), 6), round(float(start_goal[1][1]), 6)]],
        "circles": [
            {
                "circle": circle,
                "meta": meta_to_dict(meta),
            }
            for circle, meta in zip(corrected_circles, metas)
        ],
    }

    (target / "corrected_course_cad_model.json").write_text(json.dumps(corrected_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "helper_circle_corrections.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_tsv(target / "corrected_helper_circles.tsv", corrected_circles, metas)
    draw_visualization(
        target / "corrected_helper_circles.png",
        original_circles,
        corrected_circles,
        metas,
        board_width_cm,
        board_height_cm,
        args.px_per_cm,
        args.image_path,
    )
    print(f"wrote corrected helper-circle model to {target / 'corrected_course_cad_model.json'}")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
