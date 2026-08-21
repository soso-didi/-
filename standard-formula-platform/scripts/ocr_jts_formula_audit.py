"""Run Pix2Tex on the four published JTS 144-1-2010 §10.2.1 source formulas.

This is a review artifact: model output is retained verbatim and never used by
the calculation engine.  The reviewer reference is the already-published,
human-audited formula, not a model correction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from pix2tex.cli import LatexOCR

ROOT = Path(__file__).resolve().parents[1]
POPPLER = ROOT.parent / "MooringForceDemo-Complete" / "runtime" / "poppler" / "pdftoppm.exe"
FORMULAS = [
    ("10.2.1-1", (440, 990, 970, 1075), r"N=\frac{K}{n}\left[\frac{\sum F_x}{\sin\alpha\cos\beta}+\frac{\sum F_y}{\cos\alpha\cos\beta}\right]"),
    ("10.2.1-2", (450, 1070, 900, 1120), r"N_x=N\sin\alpha\cos\beta"),
    ("10.2.1-3", (450, 1120, 900, 1168), r"N_y=N\cos\alpha\cos\beta"),
    ("10.2.1-4", (450, 1170, 900, 1215), r"N_z=N\sin\beta"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ocr-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    document = json.loads(args.ocr_json.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="jts-formula-") as directory:
        prefix = Path(directory) / "page"
        subprocess.run(
            [str(POPPLER), "-f", "30", "-l", "30", "-r", "150", "-png", str(source), str(prefix)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        image = Image.open(Path(directory) / "page-030.png").convert("RGB")
        model = LatexOCR()
        results = [
            {
                "code": code,
                "page_number": 30,
                "bbox": {"x": box[0], "y": box[1], "width": box[2] - box[0], "height": box[3] - box[1]},
                "engine": "pix2tex-0.1.4",
                "recognized_latex": str(model(image.crop(box))).strip(),
                "reviewer_reference_latex": reference,
                "review_status": "needs_human_review",
            }
            for code, box, reference in FORMULAS
        ]

    with source.open("rb") as stream:
        source_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    document["formula_ocr"] = {
        "engine": "pix2tex-0.1.4",
        "scope": "JTS 144-1-2010 §10.2.1 published-formula source crops",
        "source_sha256": source_sha256,
        "warning": "Pix2Tex output is review material only and must not be executed as a calculation rule.",
        "items": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(results)} Pix2Tex formula review items to {args.output}")


if __name__ == "__main__":
    main()
