"""Ten FastAPI endpoints implementing the frozen Smart Watchdog contract."""

import json
import logging
import re
import time
import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from starlette.exceptions import HTTPException

from backend.chat import BedrockClients, ChatService
from backend.config import Settings
from backend.schemas import (
    Brief,
    ChatRequest,
    ChatResponse,
    Curve,
    Districts,
    ErrorResponse,
    FeatureCollection,
    MediaPage,
    Meta,
    ParkDetail,
    ParkPage,
    RiskTop,
    Worklist,
)
from backend.services import brief_for, current_week, worklist_for
from backend.store import DataNotReady, ServingStore, records

logger = logging.getLogger("watchdog.api")
logger.setLevel(logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


def create_app(
    settings: Settings | None = None,
    store: ServingStore | None = None,
    chat_clients=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or ServingStore(settings)
    application = FastAPI(
        title="小小守護員 Smart Watchdog",
        version="1.0.0",
        description="新北市教保機構風險預警 API。分數為離線產生，僅供稽查排序參考。",
        default_response_class=UTF8JSONResponse,
        redirect_slashes=False,
    )
    application.state.store = store
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["x-request-id", "x-data-version"],
    )

    def error(request: Request, status: int, code: str, message: str):
        return UTF8JSONResponse(
            {"error": {"code": code, "message": message, "request_id": request.state.request_id}},
            status_code=status,
        )

    @application.middleware("http")
    async def trace(request: Request, call_next):
        started = time.perf_counter()
        request.state.request_id = str(uuid.uuid4())
        try:
            response = await call_next(request)
        except DataNotReady:
            response = error(request, 503, "DATA_NOT_READY", "serving 資料尚未產生")
        except Exception as exc:  # noqa: BLE001 - the public error boundary must sanitize failures
            # Do not log exception strings/validation inputs, which may contain PII or S3 names.
            logger.error(
                json.dumps(
                    {
                        "request_id": request.state.request_id,
                        "error_type": type(exc).__name__,
                    }
                )
            )
            response = error(request, 500, "INTERNAL_ERROR", "伺服器錯誤")
        if response.status_code >= 400 and not response.headers.get("content-type", "").startswith(
            "application/json"
        ):
            response = error(request, response.status_code, "INVALID_PARAM", "參數格式錯誤")
        response.headers["x-request-id"] = request.state.request_id
        response.headers["x-data-version"] = store.version
        # Signed links must not outlive their fifteen-minute expiry in shared caches.
        signed_detail = getattr(request.state, "signed_detail", False)
        response.headers["Cache-Control"] = (
            "public, max-age=60"
            if 200 <= response.status_code < 300 and not signed_detail and request.method == "GET"
            else "no-store"
        )
        # Also expose headers on errors generated outside CORSMiddleware.
        origin = request.headers.get("origin")
        if origin and origin in settings.cors_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = "x-request-id, x-data-version"
            response.headers.add_vary_header("Origin")
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "request_id": request.state.request_id,
                    "aws_request_id": getattr(
                        request.scope.get("aws.context"), "aws_request_id", None
                    ),
                    "method": request.method,
                    "route": getattr(route, "path", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    # 助手只記回答來源，不記問題原文（可能含個資）。
                    "chat_source": getattr(request.state, "chat_source", None),
                }
            )
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_parameter(request: Request, exc: RequestValidationError):
        return error(request, 400, "INVALID_PARAM", "參數格式錯誤")

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        messages = {
            400: ("INVALID_PARAM", "參數格式錯誤"),
            404: ("PARK_NOT_FOUND", "查無此園所或資源"),
            405: ("METHOD_NOT_ALLOWED", "此資源僅支援 GET"),
        }
        code, message = messages.get(exc.status_code, ("INTERNAL_ERROR", "伺服器錯誤"))
        response = error(request, exc.status_code, code, message)
        response.headers.update(exc.headers or {})
        return response

    def ensure_meta():
        store.meta()

    router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(ensure_meta)],
        responses={code: {"model": ErrorResponse} for code in (400, 404, 500, 503)},
    )

    def park_or_404(park_id: str):
        park = store.parks().get(park_id)
        if park is None:
            raise HTTPException(404)
        return park

    def choices(values: list[str] | None, allowed: set[str] | None = None):
        result = {piece.strip() for value in values or [] for piece in value.split(",")}
        result.discard("")
        if allowed and not result <= allowed:
            raise HTTPException(400)
        return result

    @application.get("/", include_in_schema=False)
    def root():
        return {"service": "Smart Watchdog", "docs": "/docs", "api": "/api/v1"}

    @router.get("/meta", response_model=Meta, response_model_exclude_unset=True)
    def meta():
        return store.meta()

    @router.get("/parks", response_model=ParkPage, response_model_exclude_unset=True)
    def parks(
        q: str = "",
        town: Annotated[list[str] | None, Query()] = None,
        type_: Annotated[list[str] | None, Query(alias="type")] = None,
        tier: Annotated[list[str] | None, Query()] = None,
        has_finance_flag: bool = False,
        # 有無裁罰紀錄。省略＝不篩。true 與 false 都要能選：稽查人員問的是
        # 「這一區有紀錄的有哪些」，也問「零紀錄的為什麼分數還這麼高」。
        punished: bool | None = None,
        sort: Literal["risk", "name", "pun_count"] = "risk",
        direction: Annotated[Literal["asc", "desc"] | None, Query(alias="dir")] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        size: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        towns = choices(town)
        types = choices(type_, {"公立", "私立", "非營利"})
        tiers = choices(tier, {"高", "中", "低"})
        query = q.strip().casefold()
        rows = [
            p
            for p in store.ranked()
            if (not query or query in p.name.casefold())
            and (not towns or p.town in towns)
            and (not types or p.institution_type in types)
            and (not tiers or p.risk.tier in tiers)
            and (not has_finance_flag or p.finance_flags)
            and (punished is None or bool(p.timeline) is punished)
        ]
        key = {
            "risk": lambda p: p.risk.rank,
            "name": lambda p: p.name,
            "pun_count": lambda p: len(p.timeline),
        }[sort]
        rows.sort(
            key=key, reverse=(direction == "desc" or (direction is None and sort == "pun_count"))
        )
        start = (page - 1) * size
        return {
            "total": len(rows),
            "page": page,
            "size": size,
            "items": [
                {
                    "park_id": p.park_id,
                    "name": p.name,
                    "town": p.town,
                    "type": p.institution_type,
                    "institution_type": p.institution_type,
                    "lon": p.lon,
                    "lat": p.lat,
                    "is_active": p.is_active,
                    "risk": p.risk,
                    "pun_count": len(p.timeline),
                    "has_finance_flag": bool(p.finance_flags),
                    "has_media_signal": p.media.has_signal,
                    # SPEC 9.2 rule 3: a score is never shown without its
                    # reasons. Sending them with the list saves the frontend
                    # one detail request per row - 50 per page, which
                    # exhausted the function's reserved concurrency.
                    "reasons": p.reasons,
                }
                for p in rows[start : start + size]
            ],
        }

    @router.get("/parks/{park_id}", response_model=ParkDetail, response_model_exclude_unset=True)
    def detail(park_id: str, request: Request):
        park = park_or_404(park_id)
        data = park.model_dump(exclude_unset=True)
        for key in ("fees", "finance", "evaluations"):
            embedded = data.get(key) or []
            if isinstance(embedded, dict):
                embedded = [embedded]
            data[key] = (
                store.finance(park_id, embedded)
                if key == "finance"
                else (store.related(key, park_id) or embedded)
            )
        # 輿情明細獨立於上面三份：它刻意含切點之後的報導，所以不走同一個迴圈，
        # 也沒有 embedded 退路——沒有這份 serving 檔就是沒有，不編造。
        data["media_coverage"] = store.related("media_coverage", park_id)
        request.state.signed_detail = any(row.get("pdf_url") for row in data["finance"])
        return data

    @router.get("/parks/{park_id}/brief", response_model=Brief, response_model_exclude_unset=True)
    def brief(park_id: str):
        return brief_for(store, park_or_404(park_id))

    @router.get("/risk/top", response_model=RiskTop, response_model_exclude_unset=True)
    def top(k: Annotated[int, Query(ge=1, le=200)] = 50):
        return {"k": k, "items": store.ranked()[:k]}

    @router.get("/media", response_model=MediaPage, response_model_exclude_unset=True)
    def media(months: Annotated[int, Query(ge=1, le=120)] = 12):
        """觀察窗內有明文點名報導的園所，依報導數由多到少。

        觀察窗錨在資料集最後一則報導的日期，不是今天：錨在今天的話，
        資料一週沒更新，「近 12 個月」就會悄悄少掉一週的報導，同一份
        demo 在不同日子跑出不同名單。錨在資料上，結果可重現，`as_of`
        也照實把資料截止日寫給使用者看。
        """
        rows = records(store.load("media_coverage", optional=True) or {})
        if not rows:
            return {"months": months, "as_of": "", "since": "", "items": []}
        as_of = max(r["date"] for r in rows)
        since = (date.fromisoformat(as_of) - timedelta(days=months * 30)).isoformat()
        parks = store.parks()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            if row["date"] >= since and row["park_id"] in parks:
                grouped.setdefault(row["park_id"], []).append(row)
        items = []
        for park_id, group in grouped.items():
            park = parks[park_id]
            severities = [r["severity"] for r in group if r.get("severity")]
            kinds = Counter(r["event_type"] for r in group if r.get("event_type"))
            items.append(
                {
                    "park_id": park_id,
                    "name": park.name,
                    "town": park.town,
                    "tier": park.risk.tier,
                    "sri": park.media.sri,
                    "article_count": len(group),
                    "latest_date": max(r["date"] for r in group),
                    "max_severity": max(severities) if severities else None,
                    # most_common 在平手時看插入順序，也就是看 media_coverage
                    # 的列序——重跑 ETL 換個排序，同一園的「主要事件類型」就會
                    # 變。平手時用類型名決勝，讓它是資料的函數而不是檔案的。
                    # mock 端（api/mock.ts）用同一條規則。
                    "top_event_type": (
                        min(kinds.items(), key=lambda kv: (-kv[1], kv[0]))[0] if kinds else None
                    ),
                    "after_cutoff_count": sum(1 for r in group if r["is_after_cutoff"]),
                }
            )
        # 報導數相同時用最新日期再用 park_id 決勝，排序才是全序、每次都一樣。
        items.sort(key=lambda i: (-i["article_count"], i["latest_date"], i["park_id"]))
        return {"months": months, "as_of": as_of, "since": since, "items": items}

    @router.get("/districts", response_model=Districts, response_model_exclude_unset=True)
    def districts():
        return store.validated("districts", Districts)

    @router.get("/map", response_model=FeatureCollection, response_model_exclude_unset=True)
    def map_points(
        town: Annotated[list[str] | None, Query()] = None,
        tier: Annotated[list[str] | None, Query()] = None,
        punished: bool | None = None,
    ):
        towns, tiers = choices(town), choices(tier, {"高", "中", "低"})
        parks = store.parks()
        features = []
        for feature in store.validated("map", FeatureCollection).features:
            park = parks.get(feature.properties.park_id)
            if park is None:
                raise ValueError("Map references an unknown park")
            if not park.is_active:
                continue
            if towns and park.town not in towns:
                continue
            if tiers and feature.properties.tier not in tiers:
                continue
            if punished is not None and bool(park.timeline) is not punished:
                continue
            features.append(
                feature.model_copy(
                    update={
                        "properties": feature.properties.model_copy(update={"town": park.town}),
                    }
                )
            )
        return {"type": "FeatureCollection", "features": features}

    @router.get("/curve", response_model=Curve, response_model_exclude_unset=True)
    def curve():
        return store.validated("curve", Curve)

    chat_service: ChatService | None = None

    @router.post("/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, request: Request):
        nonlocal chat_service
        if chat_service is None:
            if chat_clients is None and not (settings.chat_enabled or settings.kb_id):
                return error(request, 503, "ASSISTANT_DISABLED", "稽查助手尚未啟用")
            chat_service = ChatService(
                store,
                chat_clients
                or BedrockClients(settings.kb_id, settings.chat_model, settings.aws_region),
            )
        if body.park_id:
            park_or_404(body.park_id)
        reply = chat_service.reply(body)
        request.state.chat_source = reply.source
        return reply

    @router.get("/worklist", response_model=Worklist, response_model_exclude_unset=True)
    def worklist(
        week: str | None = None,
        k: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        if week is not None:
            if not re.fullmatch(r"\d{4}-W\d{2}", week):
                raise HTTPException(400)
            try:
                date.fromisocalendar(int(week[:4]), int(week[-2:]), 1)
            except ValueError:
                raise HTTPException(400) from None
        return worklist_for(store, week or current_week(), k)

    application.include_router(router)
    # Our contract uses 400 for input validation, replacing FastAPI's default 422 docs.
    original_openapi = application.openapi

    def contract_openapi():
        schema = original_openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                if isinstance(operation, dict):
                    operation.get("responses", {}).pop("422", None)
        return schema

    application.openapi = contract_openapi
    return application


app = create_app()
handler = Mangum(app, lifespan="off")
