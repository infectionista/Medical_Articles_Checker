# Ground Truth Annotations

Expert-annotated checklist evaluations for benchmarking the automated checker.

## Schema

Each JSON file contains:
- `article_id` — matches filename in `test_input/`
- `checklist` — which checklist was applied (CONSORT, STROBE, etc.)
- `annotator` — who annotated and when
- `items` — dict of item_id → annotation:
  - `verdict`: "present" | "partial" | "absent"
  - `note`: optional expert comment (why this verdict)

## Verdict scale

| Verdict | Meaning |
|---------|---------|
| present | Item is adequately reported — a reader can find the required information |
| partial | Item is mentioned or partially addressed, but key details are missing |
| absent  | Item is not reported at all, or only in a way that doesn't meet the requirement |

## How to contribute

Run `./check.sh test_input/<article>.pdf`, then compare with the ground truth.
New annotations are collected via the interactive annotation pipeline in Cowork.
