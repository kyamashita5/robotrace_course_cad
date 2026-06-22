#!/usr/bin/env python3
"""Detect magenta/helper-circle candidates from a normalized course image."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from detect_start_goal_area import BOARD_OUT_DIR, normalize_board_image, to_board_cm
from trace_centerline_points import clean_mask, extract_black_mask, zhang_suen_thinning


OUT_DIR = Path("tmp/support_circle_detection")


@dataclass(frozen=True)
class CircleCandidate:
    rank: int
    radius_cm: float
    center_px: tuple[float, float]
    center_cm: tuple[float, float]
    vote_count: int
    support_count: int
    magenta_support_count: int
    line_support_count: int
    arc_span_deg: float
    mean_abs_radius_error_cm: float
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--name")
    parser.add_argument("--json-path")
    parser.add_argument("--width-cm", type=float)
    parser.add_argument("--height-cm", type=float)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--board-out-dir", default=str(BOARD_OUT_DIR))
    parser.add_argument("--px-per-cm", type=int, default=4)
    parser.add_argument("--board-color", default="cyan")
    parser.add_argument("--candidate-cell-sizes", default="135x90,180x90,90x135,90x180")
    parser.add_argument("--black-threshold", type=int, default=120)
    parser.add_argument("--normalized-input", action="store_true")

    parser.add_argument("--line-threshold", type=int, default=150)
    parser.add_argument("--open-erode-size", type=int, default=5)
    parser.add_argument("--open-dilate-size", type=int, default=5)
    parser.add_argument("--close-dilate-size", type=int, default=5)
    parser.add_argument("--close-erode-size", type=int, default=5)

    parser.add_argument("--magenta-hue-min", type=int, default=135)
    parser.add_argument("--magenta-hue-max", type=int, default=175)
    parser.add_argument("--magenta-saturation-min", type=int, default=45)
    parser.add_argument("--magenta-value-min", type=int, default=50)
    parser.add_argument("--magenta-open-size", type=int, default=1)
    parser.add_argument("--magenta-close-size", type=int, default=1)

    parser.add_argument("--min-radius-cm", type=float, default=10.0)
    parser.add_argument("--max-radius-cm", type=float)
    parser.add_argument("--radius-step-cm", type=float, default=5.0)
    parser.add_argument("--local-window-cm", type=float, default=2.0)
    parser.add_argument("--vote-bin-cm", type=float, default=1.0)
    parser.add_argument("--support-tolerance-cm", type=float, default=0.9)
    parser.add_argument("--min-votes", type=int, default=8)
    parser.add_argument("--min-support-points", type=int, default=18)
    parser.add_argument("--min-arc-span-deg", type=float, default=8.0)
    parser.add_argument("--top-bins-per-radius", type=int, default=160)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--nms-center-distance-cm", type=float, default=4.0)
    parser.add_argument("--nms-radius-distance-cm", type=float, default=2.5)
    parser.add_argument("--score-radius-reference-cm", type=float, default=10.0)
    parser.add_argument("--score-vote-radius-power", type=float, default=0.5)
    parser.add_argument("--score-support-radius-power", type=float, default=1.0)
    return parser.parse_args()


def odd_size(size: int) -> int:
    return size if size % 2 == 1 else size + 1


def extract_magenta_mask(
    image: np.ndarray,
    hue_min: int,
    hue_max: int,
    saturation_min: int,
    value_min: int,
    open_size: int,
    close_size: int,
) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue, green, red = cv2.split(image)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    if hue_min <= hue_max:
        magenta_hue_mask = (hue >= hue_min) & (hue <= hue_max)
    else:
        magenta_hue_mask = (hue >= hue_min) | (hue <= hue_max)

    # The support circles in the scanned diagrams often look red rather than
    # pure magenta. In OpenCV HSV that lives around H=0/179, while the blue
    # construction lines live far away in hue and do not have red dominance.
    red_hue_mask = (hue <= 12) | (hue >= 170)
    red_dominant = red.astype(np.int16) >= green.astype(np.int16) + 15
    mask_bool = (
        ((magenta_hue_mask & (saturation >= saturation_min)) | (red_hue_mask & (saturation >= max(25, saturation_min - 10))))
        & (value >= value_min)
        & red_dominant
    )
    mask = mask_bool.astype(np.uint8) * 255

    if open_size > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (odd_size(open_size), odd_size(open_size)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    if close_size > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (odd_size(close_size), odd_size(close_size)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def candidate_radii(min_radius_cm: float, max_radius_cm: float, radius_step_cm: float) -> list[float]:
    if min_radius_cm <= 0.0:
        raise ValueError("--min-radius-cm must be positive")
    if max_radius_cm < min_radius_cm:
        raise ValueError("--max-radius-cm must be greater than or equal to --min-radius-cm")
    if radius_step_cm <= 0.0:
        raise ValueError("--radius-step-cm must be positive")
    radii: list[float] = []
    value = min_radius_cm
    while value <= max_radius_cm + 1e-9:
        radii.append(round(value, 6))
        value += radius_step_cm
    return radii


def local_tangent(point_xy: np.ndarray, skeleton: np.ndarray, window_px: int) -> np.ndarray | None:
    x = int(round(float(point_xy[0])))
    y = int(round(float(point_xy[1])))
    y0 = max(0, y - window_px)
    y1 = min(skeleton.shape[0], y + window_px + 1)
    x0 = max(0, x - window_px)
    x1 = min(skeleton.shape[1], x + window_px + 1)
    coords = np.argwhere(skeleton[y0:y1, x0:x1] > 0)
    if coords.shape[0] < 4:
        return None
    xy = coords[:, ::-1].astype(np.float64)
    xy[:, 0] += x0
    xy[:, 1] += y0
    centered = xy - xy.mean(axis=0, keepdims=True)
    covariance = centered.T @ centered
    values, vectors = np.linalg.eigh(covariance)
    if float(values[-1]) <= 1e-9:
        return None
    tangent = vectors[:, int(np.argmax(values))]
    norm = float(np.linalg.norm(tangent))
    if norm <= 1e-9:
        return None
    return tangent / norm


def angular_span_deg(points_xy: np.ndarray, center_xy: np.ndarray) -> float:
    if points_xy.shape[0] < 2:
        return 0.0
    angles = np.mod(np.arctan2(points_xy[:, 1] - center_xy[1], points_xy[:, 0] - center_xy[0]), math.tau)
    angles.sort()
    gaps = np.diff(np.concatenate([angles, angles[:1] + math.tau]))
    max_gap = float(gaps.max()) if gaps.size else math.tau
    return math.degrees(max(0.0, math.tau - max_gap))


def vote_circle_centers(
    skeleton: np.ndarray,
    magenta_skeleton: np.ndarray,
    line_skeleton: np.ndarray,
    board_height_cm: float,
    px_per_cm: int,
    radii_cm: list[float],
    local_window_cm: float,
    vote_bin_cm: float,
    support_tolerance_cm: float,
    min_votes: int,
    min_support_points: int,
    min_arc_span_deg: float,
    top_bins_per_radius: int,
    score_radius_reference_cm: float,
    score_vote_radius_power: float,
    score_support_radius_power: float,
) -> list[CircleCandidate]:
    coords_xy = np.argwhere(skeleton > 0)[:, ::-1].astype(np.float64)
    if coords_xy.size == 0:
        return []
    magenta_coords_xy = np.argwhere(magenta_skeleton > 0)[:, ::-1].astype(np.float64)
    line_coords_xy = np.argwhere(line_skeleton > 0)[:, ::-1].astype(np.float64)

    window_px = max(2, int(round(local_window_cm * px_per_cm)))
    vote_bin_px = max(1.0, vote_bin_cm * px_per_cm)
    support_tolerance_px = max(1.0, support_tolerance_cm * px_per_cm)
    tangents: list[tuple[np.ndarray, np.ndarray]] = []
    for point_xy in coords_xy:
        tangent = local_tangent(point_xy, skeleton, window_px)
        if tangent is None:
            continue
        tangents.append((point_xy, tangent))

    candidates: list[CircleCandidate] = []
    for radius_cm in radii_cm:
        radius_px = radius_cm * px_per_cm
        bins: dict[tuple[int, int], list[float]] = {}
        for point_xy, tangent in tangents:
            normal = np.array([-tangent[1], tangent[0]], dtype=np.float64)
            for sign in (-1.0, 1.0):
                center_xy = point_xy + sign * normal * radius_px
                key = (int(round(center_xy[0] / vote_bin_px)), int(round(center_xy[1] / vote_bin_px)))
                bucket = bins.setdefault(key, [0.0, 0.0, 0.0])
                bucket[0] += 1.0
                bucket[1] += float(center_xy[0])
                bucket[2] += float(center_xy[1])

        top_bins = sorted(bins.values(), key=lambda item: item[0], reverse=True)[:top_bins_per_radius]
        for vote_sum, sum_x, sum_y in top_bins:
            vote_count = int(round(vote_sum))
            if vote_count < min_votes:
                continue
            center_xy = np.array([sum_x / vote_sum, sum_y / vote_sum], dtype=np.float64)
            distances = np.linalg.norm(coords_xy - center_xy[None, :], axis=1)
            inliers = np.abs(distances - radius_px) <= support_tolerance_px
            support_count = int(np.count_nonzero(inliers))
            if support_count < min_support_points:
                continue
            inlier_points = coords_xy[inliers]
            arc_span = angular_span_deg(inlier_points, center_xy)
            if arc_span < min_arc_span_deg:
                continue
            magenta_support_count = 0
            if magenta_coords_xy.size:
                magenta_distances = np.linalg.norm(magenta_coords_xy - center_xy[None, :], axis=1)
                magenta_support_count = int(np.count_nonzero(np.abs(magenta_distances - radius_px) <= support_tolerance_px))
            line_support_count = 0
            if line_coords_xy.size:
                line_distances = np.linalg.norm(line_coords_xy - center_xy[None, :], axis=1)
                line_support_count = int(np.count_nonzero(np.abs(line_distances - radius_px) <= support_tolerance_px))
            mean_error_cm = float(np.mean(np.abs(distances[inliers] - radius_px)) / float(px_per_cm))
            density_scale = max(1.0, arc_span / 20.0)
            source_bonus = min(magenta_support_count, line_support_count) * 0.03
            radius_norm = max(radius_cm / max(score_radius_reference_cm, 1e-9), 1.0)
            vote_norm = radius_norm ** score_vote_radius_power
            support_norm = radius_norm ** score_support_radius_power
            score = float(
                vote_count / max(vote_norm, 1e-9)
                + support_count * 0.15 / max(support_norm, 1e-9)
                + source_bonus
                + density_scale * 2.0
                - mean_error_cm * 5.0
            )
            center_cm = to_board_cm((float(center_xy[0]), float(center_xy[1])), board_height_cm, px_per_cm)
            candidates.append(
                CircleCandidate(
                    rank=-1,
                    radius_cm=radius_cm,
                    center_px=(float(center_xy[0]), float(center_xy[1])),
                    center_cm=(float(center_cm[0]), float(center_cm[1])),
                    vote_count=vote_count,
                    support_count=support_count,
                    magenta_support_count=magenta_support_count,
                    line_support_count=line_support_count,
                    arc_span_deg=arc_span,
                    mean_abs_radius_error_cm=mean_error_cm,
                    score=score,
                )
            )
    return candidates


def suppress_candidates(
    candidates: list[CircleCandidate],
    max_candidates: int,
    center_distance_cm: float,
    radius_distance_cm: float,
    px_per_cm: int,
) -> list[CircleCandidate]:
    kept: list[CircleCandidate] = []
    center_distance_px = center_distance_cm * px_per_cm
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        center = np.array(candidate.center_px, dtype=np.float64)
        duplicate = False
        for other in kept:
            other_center = np.array(other.center_px, dtype=np.float64)
            if (
                abs(candidate.radius_cm - other.radius_cm) <= radius_distance_cm
                and float(np.linalg.norm(center - other_center)) <= center_distance_px
            ):
                duplicate = True
                break
        if duplicate:
            continue
        kept.append(candidate)
        if len(kept) >= max_candidates:
            break
    return [
        CircleCandidate(
            rank=index,
            radius_cm=candidate.radius_cm,
            center_px=candidate.center_px,
            center_cm=candidate.center_cm,
            vote_count=candidate.vote_count,
            support_count=candidate.support_count,
            magenta_support_count=candidate.magenta_support_count,
            line_support_count=candidate.line_support_count,
            arc_span_deg=candidate.arc_span_deg,
            mean_abs_radius_error_cm=candidate.mean_abs_radius_error_cm,
            score=candidate.score,
        )
        for index, candidate in enumerate(kept)
    ]


def render_overlay(image: np.ndarray, candidates: list[CircleCandidate], px_per_cm: int, top_n: int = 32) -> np.ndarray:
    overlay = image.copy()
    colors = [(255, 0, 255), (0, 128, 255), (0, 180, 0), (255, 0, 0), (0, 0, 255)]
    for candidate in candidates[:top_n]:
        color = colors[candidate.rank % len(colors)]
        center = (int(round(candidate.center_px[0])), int(round(candidate.center_px[1])))
        radius_px = int(round(candidate.radius_cm * px_per_cm))
        cv2.circle(overlay, center, radius_px, color, 2, cv2.LINE_AA)
        cv2.circle(overlay, center, 4, color, -1, cv2.LINE_AA)
        cv2.putText(
            overlay,
            f"{candidate.rank}:R{candidate.radius_cm:g}",
            (center[0] + 6, center[1] - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    return overlay


def render_mask_overlay(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    overlay = image.copy()
    color = np.zeros_like(image)
    color[:, :, 2] = 255
    mask_bool = mask > 0
    overlay[mask_bool] = cv2.addWeighted(image[mask_bool], 0.35, color[mask_bool], 0.65, 0.0)
    return overlay


def save_report(
    path: Path,
    image_path: Path,
    board_width_cm: float,
    board_height_cm: float,
    px_per_cm: int,
    radii_cm: list[float],
    candidates: list[CircleCandidate],
    score_radius_reference_cm: float,
    score_vote_radius_power: float,
    score_support_radius_power: float,
) -> None:
    payload = {
        "image": str(image_path),
        "board_cm": [board_width_cm, board_height_cm],
        "px_per_cm": px_per_cm,
        "candidate_radii_cm": radii_cm,
        "candidate_count": len(candidates),
        "score_parameters": {
            "radius_reference_cm": score_radius_reference_cm,
            "vote_radius_power": score_vote_radius_power,
            "support_radius_power": score_support_radius_power,
        },
        "candidates": [
            {
                "rank": candidate.rank,
                "radius_cm": candidate.radius_cm,
                "center_px": [round(candidate.center_px[0], 3), round(candidate.center_px[1], 3)],
                "center_cm": [round(candidate.center_cm[0], 3), round(candidate.center_cm[1], 3)],
                "vote_count": candidate.vote_count,
                "support_count": candidate.support_count,
                "magenta_support_count": candidate.magenta_support_count,
                "line_support_count": candidate.line_support_count,
                "arc_span_deg": round(candidate.arc_span_deg, 3),
                "mean_abs_radius_error_cm": round(candidate.mean_abs_radius_error_cm, 4),
                "score": round(candidate.score, 4),
            }
            for candidate in candidates
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_tsv(path: Path, candidates: list[CircleCandidate]) -> None:
    lines = [
        "rank\tradius_cm\tcenter_x_cm\tcenter_y_cm\tvote_count\tsupport_count\tmagenta_support_count\tline_support_count\tarc_span_deg\tmean_abs_radius_error_cm\tscore"
    ]
    for candidate in candidates:
        lines.append(
            "\t".join(
                [
                    str(candidate.rank),
                    f"{candidate.radius_cm:.3f}",
                    f"{candidate.center_cm[0]:.3f}",
                    f"{candidate.center_cm[1]:.3f}",
                    str(candidate.vote_count),
                    str(candidate.support_count),
                    str(candidate.magenta_support_count),
                    str(candidate.line_support_count),
                    f"{candidate.arc_span_deg:.3f}",
                    f"{candidate.mean_abs_radius_error_cm:.4f}",
                    f"{candidate.score:.4f}",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    image_path = Path(args.image_path)
    name = args.name or image_path.stem
    target = Path(args.out_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    normalized, board_width_cm, board_height_cm, px_per_cm, _board_color = normalize_board_image(args)
    max_radius_cm = args.max_radius_cm
    if max_radius_cm is None:
        max_radius_cm = max(board_width_cm, board_height_cm)
    radii_cm = candidate_radii(args.min_radius_cm, float(max_radius_cm), args.radius_step_cm)

    magenta_mask = extract_magenta_mask(
        normalized,
        hue_min=args.magenta_hue_min,
        hue_max=args.magenta_hue_max,
        saturation_min=args.magenta_saturation_min,
        value_min=args.magenta_value_min,
        open_size=args.magenta_open_size,
        close_size=args.magenta_close_size,
    )
    line_mask = extract_black_mask(normalized, args.line_threshold)
    line_mask_cleaned = clean_mask(
        line_mask,
        open_erode_size=args.open_erode_size,
        open_dilate_size=args.open_dilate_size,
        close_dilate_size=args.close_dilate_size,
        close_erode_size=args.close_erode_size,
    )
    line_skeleton = zhang_suen_thinning(line_mask_cleaned)
    magenta_skeleton = zhang_suen_thinning(magenta_mask)
    combined_mask = cv2.bitwise_or(magenta_mask, line_skeleton)
    combined_skeleton = zhang_suen_thinning(combined_mask)

    raw_candidates = vote_circle_centers(
        skeleton=combined_skeleton,
        magenta_skeleton=magenta_skeleton,
        line_skeleton=line_skeleton,
        board_height_cm=board_height_cm,
        px_per_cm=px_per_cm,
        radii_cm=radii_cm,
        local_window_cm=args.local_window_cm,
        vote_bin_cm=args.vote_bin_cm,
        support_tolerance_cm=args.support_tolerance_cm,
        min_votes=args.min_votes,
        min_support_points=args.min_support_points,
        min_arc_span_deg=args.min_arc_span_deg,
        top_bins_per_radius=args.top_bins_per_radius,
        score_radius_reference_cm=args.score_radius_reference_cm,
        score_vote_radius_power=args.score_vote_radius_power,
        score_support_radius_power=args.score_support_radius_power,
    )
    candidates = suppress_candidates(
        raw_candidates,
        max_candidates=args.max_candidates,
        center_distance_cm=args.nms_center_distance_cm,
        radius_distance_cm=args.nms_radius_distance_cm,
        px_per_cm=px_per_cm,
    )

    cv2.imwrite(str(target / "normalized.png"), normalized)
    cv2.imwrite(str(target / "magenta_mask.png"), magenta_mask)
    cv2.imwrite(str(target / "magenta_overlay.png"), render_mask_overlay(normalized, magenta_mask))
    cv2.imwrite(str(target / "line_mask.png"), line_mask)
    cv2.imwrite(str(target / "line_mask_cleaned.png"), line_mask_cleaned)
    cv2.imwrite(str(target / "line_skeleton.png"), line_skeleton)
    cv2.imwrite(str(target / "magenta_skeleton.png"), magenta_skeleton)
    cv2.imwrite(str(target / "combined_mask.png"), combined_mask)
    cv2.imwrite(str(target / "combined_skeleton.png"), combined_skeleton)
    cv2.imwrite(str(target / "circle_candidates.png"), render_overlay(normalized, candidates, px_per_cm))
    save_report(
        target / "report.json",
        image_path,
        board_width_cm,
        board_height_cm,
        px_per_cm,
        radii_cm,
        candidates,
        args.score_radius_reference_cm,
        args.score_vote_radius_power,
        args.score_support_radius_power,
    )
    save_tsv(target / "circle_candidates.tsv", candidates)

    print(f"wrote {len(candidates)} support-circle candidates to {target}")


if __name__ == "__main__":
    main()
