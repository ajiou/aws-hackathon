"""Lambda handler。SPEC §8。

單一函式內部路由，9 支 API 共用。serving/*.json 在冷啟時載入模組層
全域變數，之後的 invocation 直接命中記憶體——母體 1,178 筆、約 3 MB，
不需要資料庫（SPEC §8.0）。
"""
import json
import os
import uuid

SERVING_DIR = os.environ.get("SERVING_DIR")      # 本機開發用
BUCKET = os.environ.get("DATA_BUCKET")           # Lambda 用
_CACHE: dict[str, dict] = {}

CORS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "public, max-age=60",
}


def _load(key: str) -> dict:
    """serving/<key>.json。冷啟載入一次，之後走記憶體。"""
    if key in _CACHE:
        return _CACHE[key]
    if SERVING_DIR:
        path = os.path.join(SERVING_DIR, f"{key}.json")
        with open(path, encoding="utf-8") as fh:
            _CACHE[key] = json.load(fh)
    else:
        import boto3
        obj = boto3.client("s3").get_object(Bucket=BUCKET, Key=f"serving/{key}.json")
        _CACHE[key] = json.loads(obj["Body"].read())
    return _CACHE[key]


def _ok(body, request_id):
    return {"statusCode": 200,
            "headers": CORS | {"x-request-id": request_id,
                               "x-data-version": _load("meta").get("version", "")},
            "body": json.dumps(body, ensure_ascii=False)}


def _err(status, code, message, request_id):
    return {"statusCode": status,
            "headers": CORS | {"x-request-id": request_id},
            "body": json.dumps({"error": {"code": code, "message": message,
                                          "request_id": request_id}}, ensure_ascii=False)}


def _multi(qs, key):
    """API Gateway 的重複 query string 以逗號串接。"""
    v = qs.get(key)
    return [x for x in v.split(",") if x] if v else []


def _list_parks(qs):
    items = [r for r in _load("scores")["items"] if r["is_active"] == 1]
    q = (qs.get("q") or "").strip()
    if q:
        items = [r for r in items if q in r["name"]]
    for key, field in (("town", "town"), ("type", "institution_type")):
        vals = _multi(qs, key)
        if vals:
            items = [r for r in items if r[field] in vals]
    tiers = _multi(qs, "tier")
    if tiers:
        items = [r for r in items if r["risk"]["tier"] in tiers]
    if qs.get("has_finance_flag") == "true":
        items = [r for r in items if r["finance_flags"]]

    sort = qs.get("sort", "risk")
    keyfn = {"risk": lambda r: r["risk"]["rank"],
             "name": lambda r: r["name"],
             "pun_count": lambda r: -len(r["timeline"])}.get(sort)
    if keyfn is None:
        raise ValueError(f"sort={sort}")
    items.sort(key=keyfn, reverse=qs.get("dir") == "desc" and sort != "risk")

    page = max(1, int(qs.get("page", 1)))
    size = min(200, max(1, int(qs.get("size", 50))))
    start = (page - 1) * size
    return {"total": len(items), "page": page, "size": size,
            "items": [{"park_id": r["park_id"], "name": r["name"],
                       "institution_type": r["institution_type"], "town": r["town"],
                       "lon": r["lon"], "lat": r["lat"], "is_active": r["is_active"],
                       "risk": r["risk"], "pun_count": len(r["timeline"]),
                       "has_finance_flag": bool(r["finance_flags"]),
                       "has_media_signal": r["media"]["has_signal"]}
                      for r in items[start:start + size]]}


def handler(event, context=None):
    rid = str(uuid.uuid4())
    path = (event.get("rawPath") or event.get("path") or "").rstrip("/")
    qs = event.get("queryStringParameters") or {}
    path = path.removeprefix("/api/v1")

    try:
        if path in ("", "/meta"):
            return _ok(_load("meta"), rid)
        if path == "/parks":
            return _ok(_list_parks(qs), rid)
        if path.startswith("/parks/"):
            rest = path[len("/parks/"):]
            pid, _, sub = rest.partition("/")
            byid = {r["park_id"]: r for r in _load("scores")["items"]}
            if pid not in byid:
                return _err(404, "PARK_NOT_FOUND", "查無此園所", rid)
            if sub == "brief":
                return _ok(_load("briefs").get(pid, {"park_id": pid, "source": "template",
                                                     "summary": "", "reasons": [], "actions": []}), rid)
            if sub:
                return _err(404, "PARK_NOT_FOUND", "查無此資源", rid)
            return _ok(byid[pid], rid)
        if path == "/risk/top":
            k = min(200, max(1, int(qs.get("k", 50))))
            items = sorted((r for r in _load("scores")["items"] if r["is_active"] == 1),
                           key=lambda r: r["risk"]["rank"])[:k]
            return _ok({"k": k, "items": items}, rid)
        if path == "/districts":
            return _ok(_load("districts"), rid)
        if path == "/map":
            fc = _load("map")
            tiers, towns = _multi(qs, "tier"), _multi(qs, "town")
            feats = fc["features"]
            if tiers:
                feats = [f for f in feats if f["properties"]["tier"] in tiers]
            if towns:
                feats = [f for f in feats if f["properties"].get("town") in towns]
            return _ok({"type": "FeatureCollection", "features": feats}, rid)
        if path == "/curve":
            return _ok(_load("curve"), rid)
        if path == "/worklist":
            return _ok(_load("worklist"), rid)
        return _err(404, "PARK_NOT_FOUND", f"無此路徑 {path}", rid)
    except (ValueError, TypeError) as exc:
        return _err(400, "INVALID_PARAM", str(exc), rid)
    except FileNotFoundError:
        return _err(503, "DATA_NOT_READY", "serving 資料尚未產生", rid)
    except Exception:                                  # noqa: BLE001
        # 不回傳 stack trace 或 bucket 名稱（SPEC §8.0）
        return _err(500, "INTERNAL_ERROR", "伺服器錯誤", rid)
