"""Create review-only formula drafts from the saved body OCR.

The source PDF is never OCR'd again here.  A candidate must be tied to a
right-side printed formula label and the preceding article heading.  OCR that
damaged punctuation is repaired only when the article context proves the
three-part prefix; every result still requires human review before execution.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "ocr" / "JTS-144-1-2010.review-ocr.json"
OUTPUT = ROOT / "data" / "ocr" / "JTS-144-1-2010.numbered-formula-drafts.json"
NUMBER = re.compile(r"\d+")


def numbers(value: str) -> list[str]:
    return NUMBER.findall(value)


def center_y(item: dict) -> float:
    box = item.get("bbox", {})
    return float(box.get("y", 0)) + float(box.get("height", 0)) / 2


def article_code(item: dict) -> str | None:
    if item.get("block_type") != "article":
        return None
    parts = numbers(item.get("raw_text", ""))
    if len(parts) < 3 or any(not 1 <= len(part) <= 2 or (len(part) > 1 and part.startswith("0")) for part in parts[:3]):
        return None
    return ".".join(parts[:3])


def printed_formula_code(item: dict, page_width: float) -> tuple[str, str] | None:
    box = item.get("bbox", {})
    if float(box.get("x", 0)) < page_width * 0.65:
        return None
    raw = item.get("raw_text", "")
    parts = numbers(raw)
    if len(parts) != 4 or any(not 1 <= len(part) <= 2 for part in parts):
        return None
    return ".".join(parts[:3]) + "-" + parts[3], raw


def preceding_article(blocks: list[dict], y: float) -> str | None:
    current = None
    for item in blocks:
        if center_y(item) >= y:
            break
        code = article_code(item)
        if code:
            current = code
    return current


def contextual_text(blocks: list[dict], y: float, page_width: float) -> tuple[str, list[str]]:
    article = ""
    context: list[str] = []
    for item in blocks:
        item_y = center_y(item)
        if item_y < y:
            if item.get("block_type") == "article":
                article = item.get("corrected_text", "").strip()
            continue
        if item_y > y + 360:
            break
        if float(item.get("bbox", {}).get("x", 0)) < page_width * 0.72 and item.get("block_type") in {"text", "heading", "article"}:
            value = item.get("corrected_text", "").strip()
            if value:
                context.append(value)
    return article, context


def formula_rows(candidates: list[dict]) -> list[dict]:
    """Group OCR fragments on the same baseline into one possible formula row."""
    rows: list[list[dict]] = []
    for item in sorted(candidates, key=center_y):
        if rows and abs(center_y(rows[-1][0]) - center_y(item)) <= 18:
            rows[-1].append(item)
        else:
            rows.append([item])
    result = []
    for row in rows:
        representative = min(row, key=lambda item: float(item.get("bbox", {}).get("x", 0)))
        result.append({
            "y": center_y(representative),
            "bbox": representative.get("bbox", {}),
            "ocr_text": " ".join(item.get("corrected_text", "").strip() for item in row if item.get("corrected_text", "").strip()),
        })
    return result


def make_item(*, sequence: int, page_number: int, code: str, raw_label: str, status: str, row: dict | None, label_y: float, blocks: list[dict], width: float) -> dict:
    y = row["y"] if row else label_y
    article_context, variable_context = contextual_text(blocks, y, width) if row else ("", [])
    return {
        "id": f"saved-body-ocr-{page_number}-{code}",
        "sequence": sequence,
        "suggested_code": code,
        "page_number": page_number,
        "raw_formula_label": raw_label,
        "code_status": status,
        "ocr_text": row["ocr_text"] if row else "",
        "formula_candidate_bbox": row["bbox"] if row else {},
        "article_context": article_context,
        "variable_context": variable_context,
        "latex_suggestion": "",
        "calculation_expression_suggestion": "",
        "review_status": "draft_only",
        "engine_status": "已由正文 OCR 的右侧编号、条文上下文和公式候选关联；LaTeX、受限表达式、表格取值和适用条件均待人工审核确认。",
    }


def build_drafts(review: dict) -> list[dict]:
    candidates_by_page: dict[int, list[dict]] = defaultdict(list)
    for candidate in review.get("formula_candidates", []):
        candidates_by_page[int(candidate.get("page_number", 0))].append(candidate)
    items: list[dict] = []
    seen: set[str] = set()

    for page in review.get("pages", []):
        page_number = int(page.get("page_number", 0))
        blocks = sorted(page.get("blocks", []), key=center_y)
        width = float(page.get("width", 1))
        rows = formula_rows(candidates_by_page.get(page_number, []))
        verified: list[dict] = []

        for block in blocks:
            parsed = printed_formula_code(block, width)
            if not parsed:
                continue
            observed, raw_label = parsed
            y = center_y(block)
            article = preceding_article(blocks, y)
            observed_prefix, ordinal = observed.rsplit("-", 1)
            if article == observed_prefix:
                code, status = observed, "right_side_label_verified_against_article"
            elif article and article.split(".")[1:] == observed_prefix.split(".")[1:]:
                code, status = f"{article}-{ordinal}", "right_side_label_repaired_from_article_context"
            else:
                continue
            row = min(rows, key=lambda item: abs(item["y"] - y), default=None)
            if row and abs(row["y"] - y) > 32:
                row = None
            verified.append({"code": code, "article": article, "ordinal": int(ordinal), "y": y, "row": row, "raw_label": raw_label, "status": status})

        for label in verified:
            if label["code"] in seen:
                continue
            items.append(make_item(sequence=len(items) + 1, page_number=page_number, code=label["code"], raw_label=label["raw_label"], status=label["status"], row=label["row"], label_y=label["y"], blocks=blocks, width=width))
            seen.add(label["code"])

        # Infer only a missing middle sequence: e.g. -1 and -3 on consecutive
        # formula rows prove a single intervening -2 row.  No edge sequence is
        # ever invented.
        labels_by_article: dict[str, list[dict]] = defaultdict(list)
        for label in verified:
            if label["article"]:
                labels_by_article[label["article"]].append(label)
        for article, labels in labels_by_article.items():
            labels.sort(key=lambda item: item["y"])
            article_rows = [row for row in rows if preceding_article(blocks, row["y"]) == article]
            for before, after in zip(labels, labels[1:]):
                gap = after["ordinal"] - before["ordinal"]
                middle = [row for row in article_rows if before["y"] + 18 < row["y"] < after["y"] - 18]
                if gap != 2 or len(middle) != 1:
                    continue
                code = f"{article}-{before['ordinal'] + 1}"
                if code in seen:
                    continue
                items.append(make_item(sequence=len(items) + 1, page_number=page_number, code=code, raw_label="", status="sequence_inferred_between_verified_right_side_labels", row=middle[0], label_y=middle[0]["y"], blocks=blocks, width=width))
                seen.add(code)
    return items


def main() -> None:
    review = json.loads(INPUT.read_text(encoding="utf-8"))
    items = build_drafts(review)
    OUTPUT.write_text(json.dumps({
        "schema_version": "numbered-formula-drafts-v2",
        "source": "saved-body-ocr-only",
        "source_hash": review.get("source_hash", ""),
        "safety": "All entries are draft_only. No OCR text is executable or published.",
        "items": items,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(items)} review-only numbered formula drafts to {OUTPUT}")


if __name__ == "__main__":
    main()
