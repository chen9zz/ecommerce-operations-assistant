"""Local-only FastAPI boundary for CommerceOps."""

import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .catalog import DEMO_AT, catalog
from .retrieval import from_environment, load_evidence
from .service import DiagnosisService
from .storage import Store


class CartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    price: str
    quantity: Annotated[StrictInt, Field(ge=1, le=1000)]
    collection: str | None = Field(default=None, max_length=80)
    tags: list[Annotated[str, Field(max_length=80)]] | None = Field(default=None, max_length=30)

    @field_validator("price")
    @classmethod
    def check_price(cls, value):
        try:
            price = Decimal(value)
            if (
                not price.is_finite()
                or price < 0
                or price > Decimal("1000000")
                or price.as_tuple().exponent < -2
            ):
                raise ValueError("价格须为非负且至多两位小数，最大为1000000")
        except InvalidOperation as exc:
            raise ValueError("价格格式无效") from exc
        return value


class DiagnosisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=2, max_length=1000)
    is_new_customer: StrictBool | None = None
    at: str = DEMO_AT
    cart: list[CartItem] | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("请输入具体的促销问题")
        return value

    @field_validator("at")
    @classmethod
    def aware_time(cls, value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("业务时间必须包含时区")
        return value


class ContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_new_customer: StrictBool


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["helpful", "incorrect"]
    comment: str = Field(default="", max_length=2000)


def create_app(db_path: Path | None = None, retriever=None):
    data_dir = Path(os.environ.get("COMMERCEOPS_DATA_DIR", "var")).resolve()
    store = Store(db_path or data_dir / "commerceops.sqlite3")
    evidence = load_evidence()
    backend = (
        retriever if retriever is not None else from_environment(data_dir / "lightrag", evidence)
    )
    service = DiagnosisService(backend, store)

    @asynccontextmanager
    async def lifespan(app):
        if hasattr(backend, "initialize"):
            await backend.initialize()
        try:
            yield
        finally:
            if hasattr(backend, "close"):
                await backend.close()

    app = FastAPI(title="商策助手 CommerceOps", version=__version__, lifespan=lifespan)
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_browser_boundary(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get(
                    "host"
                ):
                    return JSONResponse(
                        {"detail": "跨站写入被拒绝，请从本地工作台操作。"}, status_code=403
                    )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "跨站写入被拒绝。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "backend": backend.backend,
            "version": __version__,
            "mode": "local-single-shop-demo",
        }

    @app.get("/api/catalog")
    def get_catalog():
        return catalog()

    @app.get("/api/knowledge")
    def knowledge():
        return {"items": [asdict(e) for e in evidence]}

    @app.post("/api/diagnoses")
    async def diagnose(body: DiagnosisRequest):
        try:
            return await service.diagnose(body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/diagnoses")
    def history():
        return {"items": store.list()}

    @app.get("/api/diagnoses/{diagnosis_id}")
    def get_diagnosis(diagnosis_id: str):
        saved = store.get(diagnosis_id)
        if saved is None:
            raise HTTPException(404, "诊断记录不存在")
        return saved["response"]

    @app.post("/api/diagnoses/{diagnosis_id}/continue")
    async def continue_diagnosis(diagnosis_id: str, body: ContinueRequest):
        saved = store.get(diagnosis_id)
        if saved is None:
            raise HTTPException(404, "诊断记录不存在")
        if "is_new_customer" not in saved["response"]["missing_fields"]:
            raise HTTPException(409, "该记录没有待确认的新客资格")
        return await service.diagnose(
            dict(saved["request"], is_new_customer=body.is_new_customer),
            parent_id=diagnosis_id,
            customer_confirmed=True,
        )

    @app.post("/api/diagnoses/{diagnosis_id}/feedback")
    def feedback(diagnosis_id: str, body: FeedbackRequest):
        try:
            store.feedback(diagnosis_id, body.rating, body.comment)
        except KeyError as exc:
            raise HTTPException(404, "诊断记录不存在") from exc
        return {"saved": True}

    @app.get("/api/evaluation")
    def evaluation():
        path = data_dir / "evaluation.json"
        if not path.exists():
            return {
                "status": "not_run",
                "backend": backend.backend,
                "scope": "尚未运行本地业务回归评测，请执行 python -m commerceops evaluate。",
                "summary": {},
                "cases": [],
            }
        return json.loads(path.read_text())

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    return app
