---
name: robotrace-official-documents-reference
description: Use when checking, explaining, comparing, or applying official Japanese Robotrace competition rules, course requirements, event operations, judging criteria, awards, or rule revisions published by the New Technology Foundation.
---

# Robotrace Official Documents Reference

Use this skill when the user asks about Japanese Robotrace competition rules, course or robot requirements, race operation, judging, awards, eligibility, or the intent behind a rule revision. It is also relevant when a design or implementation must be checked against official competition requirements.

This skill provides a navigation summary, not a frozen copy of the rules. The New Technology Foundation (NTF) pages are the source of truth and may change after this file is written.

## Official Sources

### Competition Rules

URL: https://www.ntf.or.jp/?page_id=68

Primary source for generally applicable Robotrace rules. It covers:

- autonomous robot operation and restrictions on changes during competition
- robot footprint, height, and excessive tire adhesion
- black course surface and 1.9 cm white centerline, with total line length at most 60 m
- straight/arc course construction, minimum 10 cm arc radius, and at least 10 cm between curvature changes
- crossings at 90 degrees plus or minus 5 degrees, with 10 cm straight sections before and after
- start and goal placement, markers, area, gates, and required straight sections
- corner markers, possible course slope, and minimum distance from the course edge
- course-out, run count, time allowance, timing, stopping, touching, and course-information restrictions
- practical notes about the course surface, line material, small floor steps, and timing sensors

### All Japan Event Operations

URL: https://www.ntf.or.jp/?page_id=137

Applies specifically to operation of the Robotrace event at the All Japan Micromouse Contest. It covers:

- qualification through an eligible regional or recognized competition
- one registered robot per maker
- who may operate the robot
- prohibition of battery replacement during competition
- three minutes and up to five runs
- lighting and photography conditions
- tie-breaking using the next-best run records

### All Japan Evaluation And Awards

URL: https://www.ntf.or.jp/?page_id=140

Applies specifically to evaluation and awards at the All Japan Micromouse Contest. It describes:

- Smart Trace Award for work improving intelligence or autonomy
- places first through sixth based on shortest lap time
- Autonomy Award for the fastest qualifying no-touch sequence through completion and return
- New Technology, Best Junior, Special, and possible sponsor awards
- possible restriction to the highest-ranked robot among technically similar robots from one group
- award contents and the warning that other events use their own criteria

### Supplement To The Rule Revision

URL: https://www.ntf.or.jp/?page_id=856

Explains the intent behind the 2023 revision:

- Robotrace values both speed and intelligent, autonomous behavior
- course understanding, path planning, and control are part of that intelligence
- external-force mechanisms that increase normal force, including suction concepts, are not categorically prohibited
- excessive adhesive treatment of tires and other course-damaging behavior remains prohibited

Use this page to understand revision intent, but use the current competition-rules page for the current numbering and wording.

### Competition Overview

URL: https://www.ntf.or.jp/?page_id=27

An introductory explanation rather than a normative rule source. It describes:

- racing around a white-line loop on a black surface
- using corner markers and an initial run to learn straights and curves
- later speed control and advanced path optimization such as smoothing left-right sequences
- the educational value of sensing, mechanics, control, and autonomous planning

Use it for context and user-friendly explanations. Do not use it to resolve exact dimensions, run counts, eligibility, or other normative questions. Its prose may lag behind the dedicated rules pages.

## Source Priority

When sources differ, use this order:

1. Rules and notices published for the specific event and year being discussed
2. Current Robotrace competition rules at `page_id=68`
3. All Japan operations at `page_id=137`, for All Japan operational questions
4. All Japan evaluation criteria at `page_id=140`, for All Japan judging and awards
5. Revision supplement at `page_id=856`, for rationale and historical context
6. Competition overview at `page_id=27`, for non-normative explanation only

Do not silently combine requirements from different scopes. State whether a conclusion is a general competition rule, an All Japan operating rule, an evaluation criterion, or explanatory background.

## Required Fetch Workflow

The summaries above are only an index. Fetch the original page whenever the answer depends on the current wording, a number, a dimension, an allowed/prohibited action, eligibility, event operation, judging, or an apparent conflict.

1. Identify the scope of the question: general rules, a named event/year, All Japan operation, awards, revision intent, or overview.
2. Fetch the most relevant URL above with `webfetch` in Markdown format.
3. For normative questions, also fetch `page_id=68` unless it is already the selected source.
4. If the question names a year or event, follow the official page's links to that event's current notices and rules where available.
5. Read the article body and revision date. Ignore navigation menus, social links, recent-post lists, and duplicated sidebar content.
6. Compare relevant pages when scope overlaps. Do not infer that a newer page date automatically makes an overview page more authoritative than a dedicated rule page.
7. Answer with the applicable rule number or section, source title, URL, and the date shown on the page when available.
8. State the access date when currentness matters.

Fetch URLs directly, for example:

```text
https://www.ntf.or.jp/?page_id=68
https://www.ntf.or.jp/?page_id=137
https://www.ntf.or.jp/?page_id=140
https://www.ntf.or.jp/?page_id=856
https://www.ntf.or.jp/?page_id=27
```

If fetching fails, do not present the summary in this skill as verified current text. Say which source could not be checked and distinguish remembered or summarized information from confirmed official wording.

## Interpretation Rules

- Quote or closely paraphrase the relevant numbered clause before interpreting it.
- Preserve units, tolerances, directions, reference points, and scope qualifiers.
- Distinguish the line center from line edges and the competition-table edge from the course line.
- Distinguish robot requirements, course-construction requirements, race procedure, and award criteria.
- Treat figures as part of the rule when a clause refers to marker placement, start/goal geometry, intersections, or sensors. Inspect the linked image or document if the text alone is insufficient.
- Treat the All Japan operations and evaluation pages as event-specific; do not generalize them to every regional competition.
- When a supplement describes an older clause number, map it to the current rules by meaning and verify the current wording before answering.
- Report contradictions or stale wording explicitly rather than selecting the most convenient statement.

## Known Consistency Check

At the time this skill was drafted, the dedicated rules and All Japan operations pages stated a three-minute allowance and up to five runs. The overview page contained prose mentioning both five runs and a fastest time among three runs. Treat that overview wording as non-normative and verify the current dedicated rules before answering run-count questions.

## Response Format

For a rule lookup, provide:

- a direct answer
- the applicable scope
- the clause or section identifier
- a concise explanation preserving the important numbers and conditions
- the official source URL and page date, when shown
- any conflict, ambiguity, or fetch limitation

Do not reproduce unrelated portions of the pages. If the user asks for design guidance rather than a legalistic lookup, translate the confirmed rules into actionable constraints while retaining links to the original text.
