from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from .database import ROOT, connect, initialize, migrate_legacy_ocr, migrate_review_ocr_json


def seed() -> None:
    initialize()
    migrate_legacy_ocr()
    migrate_review_ocr_json()
    with connect() as db:
        if db.execute("SELECT 1 FROM standards").fetchone():
            return
        source = ROOT.parent / "MooringForceDemo-Complete" / "uploads" / "doc_d8fff89756424a3aa78130f6821b985a" / "source.pdf"
        target = ROOT / "data" / "sources" / "JTS-144-1-2010.pdf"
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        standard_id = db.execute("INSERT INTO standards(code,title,source_document_path) VALUES(?,?,?)", ("JTS 144-1-2010", "港口工程荷载规范", target.relative_to(ROOT).as_posix() if target.exists() else None)).lastrowid
        chapter_id = db.execute("INSERT INTO chapters(standard_id,number,title,sort_order) VALUES(?,?,?,?)", (standard_id, "10.2", "系缆力", 1)).lastrowid
        admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        variables = [
            {"code":"K","label":"系数 K","unit":"-","required":True}, {"code":"n","label":"受力系船柱数 n","unit":"个","required":True},
            {"code":"Fx","label":"ΣFx","unit":"kN","required":True}, {"code":"Fy","label":"ΣFy","unit":"kN","required":True},
            {"code":"alpha","label":"α","unit":"°","required":True}, {"code":"beta","label":"β","unit":"°","required":True},
        ]
        formulas = [
            ("10.2.1-1", "系缆力 N", r"N=\\frac{K}{n}[\\frac{ΣF_x}{\\sin α\\cos β}+\\frac{ΣF_y}{\\cos α\\cos β}]", {"kind":"expression", "expression":"K / n * (Fx / (sin(radians(alpha))*cos(radians(beta))) + Fy / (cos(radians(alpha))*cos(radians(beta))))", "conditions":[{"expression":"n > 0", "message":"受力系船柱数必须大于 0"}]}, variables, [], {"inputs":{"K":1.3,"n":4,"Fx":600,"Fy":300,"alpha":30,"beta":15},"expected":520.31,"tolerance":0.02}, "N"),
            ("10.2.1-2", "系缆力纵向分力 Nx", r"N_x=N\\sin α\\cos β", {"kind":"expression", "expression":"N * sin(radians(alpha)) * cos(radians(beta))"}, variables[4:], ["10.2.1-1"], {"inputs":{"K":1.3,"n":4,"Fx":600,"Fy":300,"alpha":30,"beta":15},"expected":251.29,"tolerance":0.02}, "Nx"),
            ("10.2.1-3", "系缆力横向分力 Ny", r"N_y=N\\cos α\\cos β", {"kind":"expression", "expression":"N * cos(radians(alpha)) * cos(radians(beta))"}, variables[4:], ["10.2.1-1"], {"inputs":{"K":1.3,"n":4,"Fx":600,"Fy":300,"alpha":30,"beta":15},"expected":435.25,"tolerance":0.02}, "Ny"),
            ("10.2.1-4", "系缆力竖向分力 Nz", r"N_z=N\\sin β", {"kind":"expression", "expression":"N * sin(radians(beta))"}, variables[5:], ["10.2.1-1"], {"inputs":{"K":1.3,"n":4,"Fx":600,"Fy":300,"alpha":30,"beta":15},"expected":134.67,"tolerance":0.02}, "Nz"),
        ]
        for code, name, latex, rule, vars_, deps, example, result_key in formulas:
            formula_id = db.execute("INSERT INTO formulas(standard_id,chapter_id,code,name,citation,page_number) VALUES(?,?,?,?,?,30)", (standard_id, chapter_id, code, name, "JTS 144-1-2010，第 10.2.1 条",)).lastrowid
            version_id = db.execute("INSERT INTO formula_versions(formula_id,version,status,latex,rule_json,variables_json,dependencies_json,example_json,author_id,published_at) VALUES(?,1,'published',?,?,?,?,?,?,CURRENT_TIMESTAMP)", (formula_id, latex, json.dumps({**rule, "result_key": result_key}, ensure_ascii=False), json.dumps(vars_, ensure_ascii=False), json.dumps(deps), json.dumps(example), admin_id)).lastrowid
            db.execute("UPDATE formulas SET active_version_id=? WHERE id=?", (version_id, formula_id))
        legacy_db = ROOT.parent / "MooringForceDemo-Complete" / "data" / "demo.sqlite"
        if legacy_db.exists():
            legacy = sqlite3.connect(legacy_db)
            doc = legacy.execute("SELECT id FROM documents LIMIT 1").fetchone()
            for page, count in legacy.execute("SELECT page_number,count(*) FROM extraction_blocks GROUP BY page_number"):
                db.execute("INSERT INTO ocr_assets(source_document_id,page_number,block_count,notes) VALUES(?,?,?,?)", (doc[0] if doc else None, page, count, "从旧 Demo 迁移的 OCR 草稿，需人工审核"))
            legacy.close()


if __name__ == "__main__":
    seed()
