"""Generate review-only OCR data for a scanned engineering standard.

The generated JSON is intentionally not executable input for the calculation
engine.  Every formula candidate remains a draft until a reviewer transcribes,
tests, and publishes an explicit calculation rule.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from winrt.windows.globalization import Language
from winrt.windows.media.ocr import OcrEngine

ROOT = Path(__file__).resolve().parents[1]
OCR_HELPERS = ROOT.parent / "MooringForceDemo-Complete" / "backend"
POPPLER = ROOT.parent / "MooringForceDemo-Complete" / "runtime" / "poppler" / "pdftoppm.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OCR a scanned standard into review-only JSON")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=150)
    return parser.parse_args()


async def recognize_page(engine: OcrEngine, image_path: Path, page_number: int) -> dict:
    # Reuse the line normalization and conservative candidate classification
    # already used by the earlier local OCR demo.
    import sys

    sys.path.insert(0, str(OCR_HELPERS.parent))
    from backend.ocr_service import _recognize_image, _result_to_blocks  # noqa: PLC0415

    result = await _recognize_image(engine, image_path)
    from PIL import Image  # noqa: PLC0415

    with Image.open(image_path) as image:
        width, height = image.size
    return {
        "page_number": page_number,
        "image_size": {"width": width, "height": height},
        "blocks": _result_to_blocks(result, page_number, width),
    }


async def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    if not source.is_file():
        raise SystemExit(f"Source PDF does not exist: {source}")
    if not POPPLER.is_file():
        raise SystemExit(f"Bundled PDF renderer does not exist: {POPPLER}")

    engine = OcrEngine.try_create_from_language(Language("zh-CN"))
    if engine is None:
        raise SystemExit("Windows Simplified Chinese OCR engine is unavailable")

    from pypdf import PdfReader  # noqa: PLC0415

    page_count = len(PdfReader(str(source)).pages)
    pages: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="jts-ocr-") as temporary:
        temporary_dir = Path(temporary)
        for page_number in range(1, page_count + 1):
            prefix = temporary_dir / "page"
            subprocess.run(
                [str(POPPLER), "-f", str(page_number), "-l", str(page_number), "-r", str(args.dpi), "-png", str(source), str(prefix)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            image_path = temporary_dir / f"page-{page_number:03d}.png"
            pages.append(await recognize_page(engine, image_path, page_number))
            image_path.unlink()

    formula_candidates = [
        {"page_number": page["page_number"], **block}
        for page in pages
        for block in page["blocks"]
        if block["block_type"] == "formula"
    ]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "standard": {"code": "JTS 144-1-2010", "title": "港口工程荷载规范"},
                "source_pdf": source.name,
                "page_count": page_count,
                "dpi": args.dpi,
                "generated_at": datetime.now(UTC).isoformat(),
                "review_status": "draft_only",
                "warning": "OCR text and formula candidates are review material only; never execute them as calculation rules.",
                "pages": pages,
                "formula_candidates": formula_candidates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {page_count} pages and {len(formula_candidates)} formula candidates to {output}")


if __name__ == "__main__":
    asyncio.run(main())
