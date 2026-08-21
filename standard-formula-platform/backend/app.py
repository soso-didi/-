from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database
from .engine import CalculationError, evaluate_rule
from .security import verify_password
from .seed import seed

ROOT = Path(__file__).resolve().parent.parent
sessions: dict[str, dict[str, Any]] = {}


class Login(BaseModel): username: str; password: str
class FormulaPayload(BaseModel):
    standard_id: int; chapter_id: int | None = None; code: str; name: str; citation: str; page_number: int | None = None
    latex: str; rule: dict[str, Any]; variables: list[dict[str, Any]]; dependencies: list[str] = []; example: dict[str, Any]
class CalculationRequest(BaseModel): formula_ids: list[int] = Field(min_length=1); inputs: dict[str, float]
class ProjectPayload(BaseModel): name: str; client: str = ""; project_number: str = ""; design_basis: dict[str, Any] = {}
class ReviewPayload(BaseModel): note: str = ""
class CalculationChainPayload(BaseModel): predecessor_codes: list[str] = Field(default_factory=list)
class CasePayload(BaseModel): name: str; formula_ids: list[int] = Field(min_length=1); inputs: dict[str, float]
class DebugNotePayload(BaseModel): inputs: dict[str, float]; note: str = Field(min_length=1)


def current_user(token: str | None = None) -> dict[str, Any]:
    if not token or token not in sessions:
        raise HTTPException(401, "请先登录")
    return sessions[token]


def user_from_header(authorization: str | None = None):
    from fastapi import Header


def auth(authorization: str | None = Depends(lambda: None)):
    # Header dependency is assigned below to keep endpoint signatures compact.
    pass


from fastapi import Header
def require_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = authorization.removeprefix("Bearer ") if authorization else None
    return current_user(token)
def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if user["role"] != "admin": raise HTTPException(403, "需要管理员权限")
    return user


app = FastAPI(title="规范公式计算平台", version="1.0.0")

@app.on_event("startup")
def startup(): seed()

@app.post("/api/login")
def login(body: Login):
    user = database.get_user(body.username)
    if not user or not verify_password(body.password, user["password_hash"]): raise HTTPException(401, "用户名或密码错误")
    token = secrets.token_urlsafe(32); sessions[token] = {"id": user["id"], "username": user["username"], "role": user["role"]}
    return {"token": token, "user": sessions[token]}

@app.get("/api/me")
def me(user=Depends(require_user)): return user

@app.get("/api/catalog")
def get_catalog(user=Depends(require_user)): return {"items": database.catalog(True)}

@app.get("/api/admin/catalog")
def admin_catalog(user=Depends(require_admin)): return {"items": database.catalog(False)}

@app.get("/api/dashboard")
def get_dashboard(user=Depends(require_user)): return database.dashboard()

@app.get("/api/standards")
def get_standards(user=Depends(require_user)): return {"items": database.standards_tree()}

@app.get("/api/ocr-assets")
def get_ocr_assets(user=Depends(require_admin)): return {"items": database.ocr_assets()}

@app.get("/api/ocr-assets/{page_number}")
def get_ocr_page(page_number: int, user=Depends(require_admin)): return database.ocr_page(page_number)

@app.get("/api/admin/ocr-formula-drafts")
def get_ocr_formula_drafts(user=Depends(require_admin)):
    """Review-only OCR candidates; this endpoint never creates executable rules."""
    return {"items": database.ocr_formula_drafts()}

@app.get("/api/admin/formulas/{formula_id}/versions")
def get_versions(formula_id: int, user=Depends(require_admin)): return {"items": database.list_versions(formula_id)}

@app.get("/api/admin/formulas/{formula_id}/versions/{version_id}")
def get_formula_version(formula_id: int, version_id: int, user=Depends(require_admin)):
    detail = database.formula_detail(formula_id, version_id)
    if not detail: raise HTTPException(404, "公式版本不存在")
    return detail

@app.get("/api/admin/formulas/{formula_id}/related")
def get_related_formulas(formula_id: int, version_id: int | None = None, user=Depends(require_admin)):
    return {"items": database.related_formulas(formula_id, version_id)}

@app.post("/api/admin/formulas/{formula_id}/calculation-chain")
def save_calculation_chain(formula_id: int, body: CalculationChainPayload, user=Depends(require_admin)):
    """Save a reviewable ordered predecessor list without changing math dependencies."""
    try:
        version_id = database.save_calculation_chain(formula_id, body.predecessor_codes, user["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"version_id": version_id, "status": "draft"}

@app.post("/api/admin/formulas/{formula_id}/versions/{version_id}/submit")
def submit_review(formula_id: int, version_id: int, body: ReviewPayload, user=Depends(require_admin)):
    database.submit_for_review(formula_id, version_id, user["id"], body.note); return {"status": "review"}

@app.get("/api/projects")
def get_projects(user=Depends(require_user)): return {"items": database.projects(user["id"], user["role"])}

@app.post("/api/projects")
def new_project(body: ProjectPayload, user=Depends(require_user)): return {"id": database.create_project(body.model_dump(), user["id"])}

def resolve(formula_id: int, inputs: dict[str, float], result_values: dict[str, float], versions: dict[str, int], trace: list[dict[str, Any]], visiting: set[int]) -> dict[str, Any]:
    if formula_id in visiting: raise CalculationError("发现公式依赖循环")
    detail = database.formula_detail(formula_id)
    if not detail or detail["status"] != "published": raise CalculationError("所选公式没有可用发布版本")
    visiting.add(formula_id)
    for dep_code in detail["dependencies"]:
        catalog = next((item for item in database.catalog(True) if item["code"] == dep_code), None)
        if not catalog: raise CalculationError(f"依赖公式未发布：{dep_code}")
        dependency_key = catalog["rule"].get("result_key", dep_code)
        if dependency_key in inputs:
            result_values[dependency_key] = inputs[dependency_key]
            continue
        dep = resolve(catalog["id"], inputs, result_values, versions, trace, visiting)
        result_values[dep["rule"].get("result_key", dep["code"])] = dep["value"]
    context = {**inputs, **result_values}
    required = [item["code"] for item in detail["variables"] if item.get("required", True)]
    missing = [name for name in required if name not in context]
    if missing: raise CalculationError("缺少必要参数：" + "、".join(missing))
    evaluation = evaluate_rule(detail["rule"], context)
    detail["value"] = evaluation.value; versions[str(formula_id)] = detail["id"]
    trace.append({"formula": detail["code"], "version": detail["version"], "citation": detail["citation"], "value": detail["value"], "steps": evaluation.trace})
    visiting.remove(formula_id)
    return detail

@app.post("/api/calculate")
def calculate(body: CalculationRequest, user=Depends(require_user)):
    values: dict[str, float] = {}; versions: dict[str, int] = {}; trace: list[dict[str, Any]] = []; outputs: dict[str, Any] = {}
    try:
        for formula_id in body.formula_ids:
            detail = resolve(formula_id, body.inputs, values, versions, trace, set())
            key = detail["rule"].get("result_key", detail["code"]); values[key] = detail["value"]
            outputs[detail["code"]] = {"name": detail["name"], "value": detail["value"], "unit": detail["rule"].get("unit", "kN"), "citation": detail["citation"], "version": detail["version"]}
    except CalculationError as exc: raise HTTPException(422, str(exc)) from exc
    # A selected formula may resolve a published dependency first.  Returning
    # that chain lets the user review and reuse the intermediate values.
    published = {item["code"]: item for item in database.catalog(True)}
    for item in trace:
        formula = published.get(item["formula"])
        if formula:
            outputs[item["formula"]] = {"name": formula["name"], "value": item["value"], "unit": formula["rule"].get("unit", "kN"), "citation": formula["citation"], "version": item["version"]}
    record_id = database.save_record(user["id"], 1, body.formula_ids, versions, body.inputs, outputs, trace)
    return {"record_id": record_id, "outputs": outputs, "trace": trace}

@app.get("/api/records")
def get_records(user=Depends(require_user)): return {"items": database.records(user["id"], user["role"])}

@app.delete("/api/records")
def clear_records(user=Depends(require_user)): return {"deleted": database.clear_records(user["id"])}

@app.get("/api/calculation-cases")
def get_cases(user=Depends(require_user)): return {"items": database.cases(user["id"], user["role"])}

@app.post("/api/calculation-cases")
def create_case(body: CasePayload, user=Depends(require_user)):
    return {"id": database.save_case(user["id"], body.name, body.formula_ids, body.inputs)}

@app.get("/api/admin/formulas/{formula_id}/debug-notes")
def get_debug_notes(formula_id: int, user=Depends(require_admin)): return {"items": database.debug_notes(formula_id)}

@app.post("/api/admin/formulas/{formula_id}/debug-notes")
def create_debug_note(formula_id: int, body: DebugNotePayload, user=Depends(require_admin)):
    return {"id": database.add_debug_note(formula_id, user["id"], body.inputs, body.note)}

@app.post("/api/admin/formulas")
def new_formula(body: FormulaPayload, user=Depends(require_admin)): return {"id": database.create_formula(body.model_dump(), user["id"])}

@app.put("/api/admin/formulas/{formula_id}")
def edit_formula(formula_id: int, body: FormulaPayload, user=Depends(require_admin)): return {"version_id": database.update_draft(formula_id, body.model_dump(), user["id"])}

@app.post("/api/admin/formulas/{formula_id}/versions/{version_id}/validate")
def validate_formula(formula_id: int, version_id: int, user=Depends(require_admin)):
    detail = database.formula_detail(formula_id, version_id)
    if not detail: raise HTTPException(404, "公式版本不存在")
    example = detail["example"]
    chain_codes = detail["rule"].get("calculation_chain", [])
    published_codes = {item["code"] for item in database.catalog(True)}
    unpublished_chain = [code for code in chain_codes if code not in published_codes]
    if unpublished_chain:
        raise HTTPException(422, "计算链中的前置公式尚未发布：" + "、".join(unpublished_chain))
    dependency_values: dict[str, float] = {}; versions: dict[str, int] = {}; trace: list[dict[str, Any]] = []
    try:
        for dependency in detail["dependencies"]:
            published = next((item for item in database.catalog(True) if item["code"] == dependency), None)
            if not published: raise CalculationError(f"依赖公式未发布：{dependency}")
            resolved = resolve(published["id"], example["inputs"], dependency_values, versions, trace, set())
            dependency_values[resolved["rule"].get("result_key", resolved["code"])] = resolved["value"]
        result = evaluate_rule(detail["rule"], {**example["inputs"], **dependency_values}).value
    except CalculationError as exc:
        raise HTTPException(422, f"验算无法完成：{exc}") from exc
    expected, tolerance = float(example["expected"]), float(example.get("tolerance", 0.0001))
    return {"passed": abs(result - expected) <= tolerance, "actual": result, "expected": expected, "tolerance": tolerance}

@app.post("/api/admin/formulas/{formula_id}/versions/{version_id}/publish")
def publish_formula(formula_id: int, version_id: int, user=Depends(require_admin)):
    detail = database.formula_detail(formula_id, version_id)
    if not detail: raise HTTPException(404, "公式版本不存在")
    if detail["status"] != "review": raise HTTPException(422, "请先提交审核，再执行发布确认")
    validation = validate_formula(formula_id, version_id, user)
    if not validation["passed"]: raise HTTPException(422, "验算样例未通过，不能发布")
    try:
        database.publish(formula_id, version_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": "published"}

@app.get("/api/health")
def health(): return {"status": "ok"}

FRONTEND_DIST = ROOT / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
app.mount("/pdfjs", StaticFiles(directory=FRONTEND_DIST / "pdfjs"), name="pdfjs")
app.mount("/ocr-files", StaticFiles(directory=ROOT / "data" / "ocr"), name="ocr-files")
app.mount("/source-files", StaticFiles(directory=ROOT / "data" / "sources"), name="source-files")
@app.get("/")
def home(): return FileResponse(FRONTEND_DIST / "index.html")

@app.get("/{path:path}", include_in_schema=False)
def frontend_route(path: str): return FileResponse(FRONTEND_DIST / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8010, reload=False)
