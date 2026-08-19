from __future__ import annotations

import json
import sqlite3
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .security import hash_password

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "platform.sqlite"


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS standards (id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, title TEXT NOT NULL, source_document_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS chapters (id INTEGER PRIMARY KEY, standard_id INTEGER NOT NULL REFERENCES standards(id), parent_id INTEGER REFERENCES chapters(id), number TEXT NOT NULL, title TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS formulas (id INTEGER PRIMARY KEY, standard_id INTEGER NOT NULL REFERENCES standards(id), chapter_id INTEGER REFERENCES chapters(id), code TEXT NOT NULL, name TEXT NOT NULL, citation TEXT NOT NULL, page_number INTEGER, active_version_id INTEGER, UNIQUE(standard_id, code));
        CREATE TABLE IF NOT EXISTS formula_versions (id INTEGER PRIMARY KEY, formula_id INTEGER NOT NULL REFERENCES formulas(id), version INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','review','published','archived')), latex TEXT NOT NULL, rule_json TEXT NOT NULL, variables_json TEXT NOT NULL, dependencies_json TEXT NOT NULL DEFAULT '[]', example_json TEXT NOT NULL, author_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, published_at TEXT, UNIQUE(formula_id,version));
        CREATE TABLE IF NOT EXISTS calculation_records (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), standard_id INTEGER NOT NULL REFERENCES standards(id), requested_formula_ids_json TEXT NOT NULL, formula_versions_json TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, trace_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS calculation_cases (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), name TEXT NOT NULL, formula_ids_json TEXT NOT NULL, input_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS formula_debug_notes (id INTEGER PRIMARY KEY, formula_id INTEGER NOT NULL REFERENCES formulas(id), author_id INTEGER REFERENCES users(id), input_json TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS ocr_assets (id INTEGER PRIMARY KEY, source_document_id TEXT, page_number INTEGER, block_count INTEGER NOT NULL DEFAULT 0, formula_crop_count INTEGER NOT NULL DEFAULT 0, notes TEXT);
        CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, client TEXT NOT NULL DEFAULT '', project_number TEXT NOT NULL DEFAULT '', design_basis_json TEXT NOT NULL DEFAULT '{}', owner_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS review_events (id INTEGER PRIMARY KEY, formula_version_id INTEGER NOT NULL REFERENCES formula_versions(id), actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS ocr_blocks (id INTEGER PRIMARY KEY, source_document_id TEXT NOT NULL, page_number INTEGER NOT NULL, sequence INTEGER NOT NULL, block_type TEXT NOT NULL, raw_text TEXT NOT NULL, corrected_text TEXT NOT NULL, bbox_json TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0, UNIQUE(source_document_id,page_number,sequence));
        CREATE TABLE IF NOT EXISTS ocr_formulas (id INTEGER PRIMARY KEY, source_document_id TEXT NOT NULL, page_number INTEGER NOT NULL, sequence INTEGER NOT NULL, crop_path TEXT NOT NULL, engine_status TEXT NOT NULL, recognized_latex TEXT NOT NULL, reference_latex TEXT NOT NULL, confirmed_latex TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0, UNIQUE(source_document_id,page_number,sequence));
        """)
        if not db.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)", ("admin", hash_password("admin123"), "admin"))
            db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)", ("user", hash_password("user123"), "user"))


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def get_user(username: str) -> dict[str, Any] | None:
    with connect() as db:
        return row_dict(db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())


def catalog(published_only: bool = True) -> list[dict[str, Any]]:
    query = """
    SELECT f.*, c.number chapter_number, c.title chapter_title, v.id version_id, v.version, v.status, v.latex, v.rule_json, v.variables_json, v.dependencies_json
    FROM formulas f JOIN formula_versions v ON v.id=f.active_version_id LEFT JOIN chapters c ON c.id=f.chapter_id
    WHERE (?=0 OR v.status='published') ORDER BY c.sort_order, f.code
    """
    with connect() as db:
        rows = db.execute(query, (1 if published_only else 0,)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        for key in ("rule_json", "variables_json", "dependencies_json"):
            item[key[:-5]] = json.loads(item.pop(key))
        items.append(item)
    return items


def formula_detail(formula_id: int, version_id: int | None = None) -> dict[str, Any] | None:
    with connect() as db:
        if version_id:
            row = db.execute("SELECT f.*,v.* FROM formulas f JOIN formula_versions v ON v.formula_id=f.id WHERE f.id=? AND v.id=?", (formula_id, version_id)).fetchone()
        else:
            row = db.execute("SELECT f.*,v.* FROM formulas f JOIN formula_versions v ON v.id=f.active_version_id WHERE f.id=?", (formula_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    for key in ("rule_json", "variables_json", "dependencies_json", "example_json"):
        result[key[:-5]] = json.loads(result.pop(key))
    return result


def create_formula(payload: dict[str, Any], author_id: int) -> int:
    with connect() as db:
        formula_id = db.execute("INSERT INTO formulas(standard_id,chapter_id,code,name,citation,page_number) VALUES(?,?,?,?,?,?)", (payload["standard_id"], payload.get("chapter_id"), payload["code"], payload["name"], payload["citation"], payload.get("page_number"))).lastrowid
        version_id = db.execute("INSERT INTO formula_versions(formula_id,version,status,latex,rule_json,variables_json,dependencies_json,example_json,author_id) VALUES(?,1,'draft',?,?,?,?,?,?)", (formula_id, payload["latex"], json.dumps(payload["rule"], ensure_ascii=False), json.dumps(payload["variables"], ensure_ascii=False), json.dumps(payload.get("dependencies", [])), json.dumps(payload["example"], ensure_ascii=False), author_id)).lastrowid
        db.execute("UPDATE formulas SET active_version_id=? WHERE id=?", (version_id, formula_id))
        return formula_id


def update_draft(formula_id: int, payload: dict[str, Any], author_id: int) -> int:
    with connect() as db:
        current = db.execute("SELECT COALESCE(MAX(version),0) version FROM formula_versions WHERE formula_id=?", (formula_id,)).fetchone()["version"]
        version_id = db.execute("INSERT INTO formula_versions(formula_id,version,status,latex,rule_json,variables_json,dependencies_json,example_json,author_id) VALUES(?,?,'draft',?,?,?,?,?,?)", (formula_id, current + 1, payload["latex"], json.dumps(payload["rule"], ensure_ascii=False), json.dumps(payload["variables"], ensure_ascii=False), json.dumps(payload.get("dependencies", [])), json.dumps(payload["example"], ensure_ascii=False), author_id)).lastrowid
        # 草稿不能取代正在使用的已发布版本；发布操作才会切换 active_version_id。
        db.execute("UPDATE formulas SET name=?,citation=?,page_number=? WHERE id=?", (payload["name"], payload["citation"], payload.get("page_number"), formula_id))
        return version_id


def publish(formula_id: int, version_id: int) -> None:
    with connect() as db:
        db.execute("UPDATE formula_versions SET status='archived' WHERE formula_id=? AND status='published'", (formula_id,))
        db.execute("UPDATE formula_versions SET status='published',published_at=CURRENT_TIMESTAMP WHERE id=? AND formula_id=?", (version_id, formula_id))
        db.execute("UPDATE formulas SET active_version_id=? WHERE id=?", (version_id, formula_id))


def save_record(user_id: int, standard_id: int, requested: list[int], versions: dict[str, int], inputs: dict[str, float], outputs: dict[str, Any], trace: list[dict[str, Any]]) -> int:
    with connect() as db:
        return db.execute("INSERT INTO calculation_records(user_id,standard_id,requested_formula_ids_json,formula_versions_json,input_json,output_json,trace_json) VALUES(?,?,?,?,?,?,?)", (user_id, standard_id, json.dumps(requested), json.dumps(versions), json.dumps(inputs), json.dumps(outputs), json.dumps(trace, ensure_ascii=False))).lastrowid


def records(user_id: int, role: str) -> list[dict[str, Any]]:
    with connect() as db:
        sql = "SELECT * FROM calculation_records" + ("" if role == "admin" else " WHERE user_id=?") + " ORDER BY id DESC"
        rows = db.execute(sql, () if role == "admin" else (user_id,)).fetchall()
    return [dict(row) for row in rows]


def clear_records(user_id: int) -> int:
    with connect() as db:
        return db.execute("DELETE FROM calculation_records WHERE user_id=?", (user_id,)).rowcount


def save_case(user_id: int, name: str, formula_ids: list[int], inputs: dict[str, float]) -> int:
    with connect() as db:
        return db.execute("INSERT INTO calculation_cases(user_id,name,formula_ids_json,input_json) VALUES(?,?,?,?)", (user_id, name, json.dumps(formula_ids), json.dumps(inputs, ensure_ascii=False))).lastrowid


def cases(user_id: int, role: str) -> list[dict[str, Any]]:
    with connect() as db:
        sql = "SELECT * FROM calculation_cases" + ("" if role == "admin" else " WHERE user_id=?") + " ORDER BY id DESC"
        rows = db.execute(sql, () if role == "admin" else (user_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row); item["formula_ids"] = json.loads(item.pop("formula_ids_json")); item["inputs"] = json.loads(item.pop("input_json")); result.append(item)
    return result


def add_debug_note(formula_id: int, author_id: int, inputs: dict[str, float], note: str) -> int:
    with connect() as db:
        return db.execute("INSERT INTO formula_debug_notes(formula_id,author_id,input_json,note) VALUES(?,?,?,?)", (formula_id, author_id, json.dumps(inputs, ensure_ascii=False), note)).lastrowid


def debug_notes(formula_id: int) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT n.*,u.username FROM formula_debug_notes n LEFT JOIN users u ON u.id=n.author_id WHERE n.formula_id=? ORDER BY n.id DESC", (formula_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row); item["inputs"] = json.loads(item.pop("input_json")); result.append(item)
    return result


def dashboard() -> dict[str, Any]:
    with connect() as db:
        return {
            "standards": db.execute("SELECT count(*) FROM standards").fetchone()[0],
            "published": db.execute("SELECT count(*) FROM formula_versions WHERE status='published'").fetchone()[0],
            "drafts": db.execute("SELECT count(*) FROM formula_versions WHERE status IN ('draft','review')").fetchone()[0],
            "ocr_pages": db.execute("SELECT count(*) FROM ocr_assets").fetchone()[0],
            "calculations": db.execute("SELECT count(*) FROM calculation_records").fetchone()[0],
        }


def standards_tree() -> list[dict[str, Any]]:
    with connect() as db:
        standards = [dict(row) for row in db.execute("SELECT * FROM standards ORDER BY id")]
        chapters = [dict(row) for row in db.execute("SELECT * FROM chapters ORDER BY standard_id,sort_order,number")]
        counts = {row["chapter_id"]: row["count"] for row in db.execute("SELECT chapter_id,count(*) count FROM formulas GROUP BY chapter_id")}
    for standard in standards:
        standard["chapters"] = [{**chapter, "formula_count": counts.get(chapter["id"], 0)} for chapter in chapters if chapter["standard_id"] == standard["id"]]
    return standards


def ocr_assets() -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM ocr_assets ORDER BY page_number")]


def ocr_page(page_number: int) -> dict[str, Any]:
    with connect() as db:
        blocks = [dict(row) for row in db.execute("SELECT * FROM ocr_blocks WHERE page_number=? ORDER BY sequence", (page_number,))]
        formulas = [dict(row) for row in db.execute("SELECT * FROM ocr_formulas WHERE page_number=? ORDER BY sequence", (page_number,))]
    for block in blocks:
        block["bbox"] = json.loads(block.pop("bbox_json"))
    return {"page_number": page_number, "page_image": f"pages/page_{page_number:03d}.png", "blocks": blocks, "formulas": formulas}


def migrate_legacy_ocr() -> None:
    legacy_root = ROOT.parent / "MooringForceDemo-Complete" / "uploads" / "doc_d8fff89756424a3aa78130f6821b985a"
    legacy_db = ROOT.parent / "MooringForceDemo-Complete" / "data" / "demo.sqlite"
    if not legacy_db.exists():
        return
    target = DATA_DIR / "ocr"
    (target / "pages").mkdir(parents=True, exist_ok=True)
    (target / "formulas").mkdir(parents=True, exist_ok=True)
    for page in (30, 31):
        source = legacy_root / "pages" / f"page_{page:03d}.png"
        destination = target / "pages" / source.name
        if source.exists() and not destination.exists():
            shutil.copy2(source, destination)
    for source in (legacy_root / "formulas").glob("*.png"):
        destination = target / "formulas" / source.name
        if not destination.exists():
            shutil.copy2(source, destination)
    legacy = sqlite3.connect(legacy_db)
    legacy.row_factory = sqlite3.Row
    try:
        document = legacy.execute("SELECT id FROM documents LIMIT 1").fetchone()
        document_id = document["id"] if document else "legacy"
        with connect() as db:
            for row in legacy.execute("SELECT page_number,sequence,block_type,raw_text,corrected_text,bbox_json,confirmed FROM extraction_blocks ORDER BY page_number,sequence"):
                db.execute("INSERT OR IGNORE INTO ocr_blocks(source_document_id,page_number,sequence,block_type,raw_text,corrected_text,bbox_json,confirmed) VALUES(?,?,?,?,?,?,?,?)", (document_id, row["page_number"], row["sequence"], row["block_type"], row["raw_text"], row["corrected_text"], row["bbox_json"], row["confirmed"]))
            for row in legacy.execute("SELECT page_number,sequence,crop_path,engine_status,recognized_latex,reference_latex,confirmed_latex,confirmed FROM formula_candidates ORDER BY page_number,sequence"):
                crop = Path(row["crop_path"]).name
                db.execute("INSERT OR IGNORE INTO ocr_formulas(source_document_id,page_number,sequence,crop_path,engine_status,recognized_latex,reference_latex,confirmed_latex,confirmed) VALUES(?,?,?,?,?,?,?,?,?)", (document_id, row["page_number"], row["sequence"], f"formulas/{crop}", row["engine_status"], row["recognized_latex"], row["reference_latex"], row["confirmed_latex"], row["confirmed"]))
    finally:
        legacy.close()


def migrate_review_ocr_json() -> None:
    """Import the complete review-only JSON; it never creates executable formulas."""
    review_path = DATA_DIR / "ocr" / "JTS-144-1-2010.review-ocr.json"
    legacy_pages = ROOT.parent / "MooringForceDemo-Complete" / "uploads" / "doc_d8fff89756424a3aa78130f6821b985a" / "pages"
    if not review_path.exists():
        return
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    pages = payload.get("pages", [])
    document_id = "doc_d8fff89756424a3aa78130f6821b985a"
    images_dir = DATA_DIR / "ocr" / "pages"
    images_dir.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        for page in pages:
            page_number = int(page["page_number"])
            page_blocks = page.get("blocks", [])
            source_image = legacy_pages / f"page_{page_number:03d}.png"
            target_image = images_dir / source_image.name
            if source_image.exists() and not target_image.exists():
                shutil.copy2(source_image, target_image)
            existing = db.execute("SELECT id FROM ocr_assets WHERE source_document_id=? AND page_number=?", (document_id, page_number)).fetchone()
            if existing:
                db.execute("UPDATE ocr_assets SET block_count=?,notes=? WHERE id=?", (len(page_blocks), "全册 OCR JSON 导入；仅供人工审核", existing["id"]))
            else:
                db.execute("INSERT INTO ocr_assets(source_document_id,page_number,block_count,notes) VALUES(?,?,?,?)", (document_id, page_number, len(page_blocks), "全册 OCR JSON 导入；仅供人工审核"))
            for block in page_blocks:
                db.execute(
                    "INSERT OR REPLACE INTO ocr_blocks(source_document_id,page_number,sequence,block_type,raw_text,corrected_text,bbox_json,confirmed) VALUES(?,?,?,?,?,?,?,?)",
                    (document_id, page_number, int(block["sequence"]), block["block_type"], block.get("raw_text", ""), block.get("corrected_text", ""), json.dumps(block.get("bbox", {}), ensure_ascii=False), int(bool(block.get("confirmed", False)))),
                )
        for candidate in payload.get("formula_candidates", []):
            # Keep these draft candidates separate from the four manually confirmed formula crops.
            db.execute(
                "INSERT OR REPLACE INTO ocr_formulas(source_document_id,page_number,sequence,crop_path,engine_status,recognized_latex,reference_latex,confirmed_latex,confirmed) VALUES(?,?,?,?,?,?,?,?,?)",
                (document_id, int(candidate["page_number"]), 10_000 + int(candidate["sequence"]), "", "全册 OCR 公式候选；待人工转写", candidate.get("corrected_text", ""), "", "", 0),
            )


def list_versions(formula_id: int) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT id,formula_id,version,status,latex,example_json,created_at,published_at FROM formula_versions WHERE formula_id=? ORDER BY version DESC", (formula_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row); item["example"] = json.loads(item.pop("example_json")); result.append(item)
    return result


def submit_for_review(formula_id: int, version_id: int, actor_id: int, note: str) -> None:
    with connect() as db:
        db.execute("UPDATE formula_versions SET status='review' WHERE id=? AND formula_id=? AND status='draft'", (version_id, formula_id))
        db.execute("INSERT INTO review_events(formula_version_id,actor_id,action,note) VALUES(?,?,?,?)", (version_id, actor_id, "submitted", note))


def create_project(payload: dict[str, Any], owner_id: int) -> int:
    with connect() as db:
        return db.execute("INSERT INTO projects(name,client,project_number,design_basis_json,owner_id) VALUES(?,?,?,?,?)", (payload["name"], payload.get("client", ""), payload.get("project_number", ""), json.dumps(payload.get("design_basis", {}), ensure_ascii=False), owner_id)).lastrowid


def projects(owner_id: int, role: str) -> list[dict[str, Any]]:
    with connect() as db:
        sql = "SELECT p.*,count(r.id) result_count FROM projects p LEFT JOIN calculation_records r ON r.user_id=p.owner_id" + ("" if role == "admin" else " WHERE p.owner_id=?") + " GROUP BY p.id ORDER BY p.updated_at DESC,p.id DESC"
        rows = db.execute(sql, () if role == "admin" else (owner_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row); item["design_basis"] = json.loads(item.pop("design_basis_json")); result.append(item)
    return result
