---
name: line-design-info-extractor
description: "Extract red course-design text annotations from robotrace course diagram images into JSON. Use when Codex needs AI-assisted reading of red printed design information such as helper-circle radius/center labels and standalone coordinate labels from normalized board images or original course drawings."
---

# Line Design Info Extractor

Use this skill when the task is limited to reading red printed design information from a robotrace course diagram and writing the read values as structured JSON.

This skill is intentionally narrower than the full course-image-parser workflow. It does not decide course order, validate slalom geometry, match helper circles to traced arcs, or infer geometry from the black line. It only extracts red text annotations and groups nearby lines of red text into the records below.

## Inputs

Preferred input:

- a normalized board image produced by `extract_course_board.py`

Acceptable fallback:

- the original course diagram image, when the normalized board image is unavailable or the red text is clearer in the original

If both images are available, inspect both, but treat the normalized board image as the primary coordinate reference.

## Output

Write a JSON file containing an `items` array. Use the output path requested by the user. If no output path is provided and a course name can be inferred, write:

```text
tmp/<name>/line_design_info_extraction/line_design_info.json
```

Each item must include:

```json
{
  "type": "circle",
  "xy": [[[155.0, 183.0], 0.98]],
  "info_xy": [155.0, 183.0],
  "radius": [[15.0, 0.98]]
}
```

Fields:

- `type`: either `"circle"` or `"coordinate"`
- `xy`: coordinate hypotheses read from the red text as `[[[x_cm, y_cm], confidence], ...]`; use `null` when the coordinate was not detected
- `info_xy`: the center position of the printed red information block in centimeters when the input is a normalized board image
- `info_xy_px`: the center position of the printed red information block in pixels when the input is not normalized
- `radius`: radius hypotheses for `"circle"` items as `[[radius_cm, confidence], ...]`; set `null` for `"coordinate"` items

Each confidence must be a number in `[0.0, 1.0]`. When a value is not unique, include multiple hypotheses rather than using a separate confidence field.

Optional fields such as `text`, `evidence`, or `bbox_note` may be added when they help audit an ambiguous read, but do not omit the required fields above. Do not add separate `confidence_radius`, `confidence_xy`, or generic `confidence` fields.

Use exactly one of `info_xy` or `info_xy_px` for each item, depending on the coordinate system of the input image. This position is especially important for radius-only circle labels, because `xy` is `null` while the printed label position still indicates which nearby support circle or course feature the radius belongs to.

Return valid JSON. Do not include comments or trailing commas.

## Extraction Targets

Extract helper-circle information from these red text patterns.

Case 1: centered two-line helper circle label:

```text
R15
155,183
```

Output:

```json
{"type": "circle", "xy": [[[155.0, 183.0], 0.98]], "info_xy": [155.0, 183.0], "radius": [[15.0, 0.98]]}
```

Case 2: centered three-line helper circle label where the coordinate is split:

```text
R10
150,
113
```

Output:

```json
{"type": "circle", "xy": [[[150.0, 113.0], 0.95]], "info_xy": [150.0, 113.0], "radius": [[10.0, 0.98]]}
```

Case 3: radius-only helper circle label:

```text
R30
```

Output:

```json
{"type": "circle", "xy": null, "info_xy": [100.0, 80.0], "radius": [[30.0, 0.85], [80.0, 0.15]]}
```

Extract standalone red coordinate labels used for start, goal, slalom endpoints, or similar design points:

```text
40, 210
```

Output:

```json
{"type": "coordinate", "xy": [[[40.0, 210.0], 0.98]], "info_xy": [40.0, 210.0], "radius": null}
```

## Grouping Rules

Group red text lines spatially before creating items.

- Treat an `R<number>` line followed immediately below by a coordinate line as one `"circle"` item.
- Treat an `R<number>` line followed by `<x>,` and then `<y>` on the next line as one `"circle"` item.
- Treat an isolated `R<number>` line as a `"circle"` item with `xy: null`.
- Treat an isolated `<x>,<y>` line as a `"coordinate"` item.
- Do not create a separate `"coordinate"` item for a coordinate line that was already consumed as a circle center.
- Preserve duplicate-looking labels when they are visibly separate annotations in the drawing.
- Record the center of the grouped printed text block as `info_xy` or `info_xy_px`; for multi-line labels, use the center of the whole label block, not just one line.

## Reading Rules

Read only red printed design text. Red/magenta circle outlines, guide lines, dashed frames, black course lines, markers, and grid lines may help locate nearby labels, but they are not themselves text reads.

Use numeric values exactly as printed when readable, wrapped as one or more hypotheses:

- a clear `R15` means `radius: [[15.0, 0.98]]`
- an ambiguous `R30` vs `R80` means `radius: [[30.0, 0.8], [80.0, 0.2]]`
- a clear `155,183` means `xy: [[[155.0, 183.0], 0.98]]`
- an ambiguous coordinate means `xy: [[[380.0, 50.0], 0.7], [[380.0, 30.0], 0.3]]`
- `150,` followed by `113` means `xy: [[[150.0, 113.0], confidence]]`

Do not infer missing coordinates from nearby geometry. If a coordinate is not readable, use `xy: null`.

Do not infer a circle radius from a support-circle outline or slalom template. If the red text does not contain an `R<number>` label, do not create a `"circle"` item from that geometry in this skill.

Do not fill `xy` from the printed location. For radius-only labels, keep `xy: null` and record only `info_xy` or `info_xy_px` for where the radius text was printed.

If a digit is ambiguous, include the plausible readings as multiple hypotheses and add an `evidence` field describing the ambiguity. Keep the hypotheses ordered from most likely to least likely.

Set confidence values conservatively:

- use `0.95` to `1.0` only when the red text is clear and unobstructed
- use `0.7` to `0.9` when the value is readable but overlapped by lines, nearby labels, or other drawing elements
- use `0.4` to `0.7` when a value is plausible but one or more digits are ambiguous
- do not add confidence hypotheses for a value that was not detected; use `xy: null` or `radius: null`
- keep radius and coordinate uncertainty independent; for example, a clear `R20` with unreadable coordinates should have `radius: [[20.0, high_confidence]]` and `xy: null`

## Quality Check

Before finalizing the JSON:

- verify that every clear red `R<number>` label appears as one `"circle"` item
- verify that every clear standalone red coordinate label appears as one `"coordinate"` item unless it was consumed as a circle center
- verify that radius-only circle labels have `xy: null`
- verify that every item has either `info_xy` for normalized images or `info_xy_px` for original/non-normalized images
- verify that radius-only circle labels include the printed label position in `info_xy` or `info_xy_px`
- verify that no item contains `confidence_radius`, `confidence_xy`, or generic `confidence`
- verify that every circle has a nonempty `radius` hypothesis list and every detected coordinate is represented as an `xy` hypothesis list
- verify that all hypothesis confidence values are numbers in `[0.0, 1.0]`
- verify that split coordinates such as `150,` / `113` are merged into one `[150.0, 113.0]`
- verify that the file is valid JSON and can be parsed
