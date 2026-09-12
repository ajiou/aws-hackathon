"""Deterministic decision support; no online inference or database access."""

from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from backend.privacy import assert_no_pii
from backend.schemas import Action, Brief, Park, WorkItem, Worklist
from backend.store import DataNotReady, ServingStore


def current_week() -> str:
    year, week, _ = datetime.now(ZoneInfo("Asia/Taipei")).isocalendar()
    return f"{year}-W{week:02}"


def template_actions(park: Park) -> list[Action]:
    counts = Counter((p.category, p.law) for p in park.timeline if p.law)
    actions = [
        Action(focus=category, why=f"歷史違規涉及{law}（{count} 次），查核改善情形")
        for (category, law), count in counts.most_common(2)
    ]
    if park.count_approved is not None:
        actions.append(
            Action(
                focus=f"實際招收人數 vs 核定 {park.count_approved} 人",
                why=f"依核定 {park.count_approved} 人比對在園人數與名冊",
            )
        )
    return actions[:3]


def actions_grounded(actions: list[Action], park: Park) -> bool:
    import re

    laws = [p.law for p in park.timeline if p.law]
    for action in actions:
        text = action.focus + action.why
        law_match = any(law in text for law in laws)
        capacity_match = park.count_approved is not None and re.search(
            rf"核定\s*{park.count_approved}\s*人", text
        )
        if not law_match and not capacity_match:
            return False
    return True


def brief_for(store: ServingStore, park: Park) -> Brief:
    offline = store.related("briefs", park.park_id)
    if offline:
        try:
            brief = Brief.model_validate(offline[0])
            if actions_grounded(brief.actions, park):
                return brief
        except ValidationError:
            pass  # The contract explicitly requires template fallback for failed LLM output.
    labels = [r.label for r in park.reasons] or ["目前資料未觸發原因碼，不代表園所安全"]
    return Brief(
        park_id=park.park_id,
        source="template",
        summary=f"{park.name}：" + "；".join(labels) + "。分數供稽查排序參考，並非違規認定。",
        reasons=labels,
        actions=template_actions(park),
        generated_at=store.meta().generated_at,
    )


def dispatch_item(store: ServingStore, park: Park, seq: int) -> WorkItem:
    reasons = [r.label for r in park.reasons]
    # Fill short reason lists with facts, without inventing reason codes or model evidence.
    facts = [
        f"風險排序為全市第 {park.risk.rank} 名，僅供本週稽查優先順序參考",
        f"已公開裁罰紀錄共 {len(park.timeline)} 筆，包含切點前後紀錄",
        f"資料基準日為 {park.as_of_date}",
    ]
    for fact in facts:
        if len(reasons) >= 3:
            break
        if fact not in reasons:
            reasons.append(fact)
    evaluations = store.related("evaluations", park.park_id)
    embedded = (park.model_extra or {}).get("evaluations")
    evaluation_count = (
        len(evaluations) if evaluations else (len(embedded) if isinstance(embedded, list) else None)
    )
    return WorkItem(
        seq=seq,
        park_id=park.park_id,
        name=park.name,
        town=park.town,
        type=park.institution_type,
        institution_type=park.institution_type,
        count_approved=park.count_approved,
        address=park.address,
        tel=park.tel,
        risk=park.risk,
        reasons=reasons,
        actions=template_actions(park),
        attachments={"punishment_count": len(park.timeline), "evaluation_count": evaluation_count},
    )


def worklist_for(store: ServingStore, week: str, k: int) -> Worklist:
    stored = store.load("worklist", optional=True)
    is_current = week == current_week()
    if stored and stored.get("week") == week:
        # Keep the offline sheet's exact order and evidence for the requested week.
        data = {**stored, "items": []}
        for row in stored["items"][:k]:
            row = dict(row)
            kind = row.get("institution_type", row.get("type"))
            row.setdefault("type", kind)
            row.setdefault("institution_type", kind)
            if is_current and len(row["reasons"]) < 3:
                park = store.parks().get(row["park_id"])
                if park is None:
                    raise ValueError("Unknown worklist park")
                row["reasons"] = dispatch_item(store, park, row["seq"]).reasons
            data["items"].append(row)
        result = Worklist.model_validate(data)
        if len(stored["items"]) < k and is_current:
            seen = {item.park_id for item in result.items}
            for park in store.ranked():
                if len(result.items) >= k:
                    break
                if park.park_id not in seen:
                    result.items.append(dispatch_item(store, park, len(result.items) + 1))
        # Legacy mocks include hard-coded laws: replace unsupported actions with evidence.
        parks = store.parks() if is_current else {}
        seen = set()
        for seq, item in enumerate(result.items, 1):
            if item.park_id in seen or (is_current and item.park_id not in parks):
                raise ValueError("Invalid worklist park reference")
            seen.add(item.park_id)
            item.seq = seq
            if is_current:
                park = parks[item.park_id]
                if not park.is_active:
                    raise ValueError("Inactive park in current worklist")
                if not actions_grounded(item.actions, park):
                    item.actions = template_actions(park)
    elif not is_current:
        archive = store.load(f"worklist-{week.lower()}", optional=True)
        if archive is None:
            raise DataNotReady
        if archive.get("week") != week:
            raise ValueError("Worklist archive week mismatch")
        data = {**archive, "items": []}
        for source in archive["items"][:k]:
            row = dict(source)
            kind = row.get("institution_type", row.get("type"))
            row.setdefault("type", kind)
            row.setdefault("institution_type", kind)
            data["items"].append(row)
        result = Worklist.model_validate(data)
    else:
        meta = store.meta()
        result = Worklist(
            week=week,
            generated_at=meta.generated_at,
            model=meta.model,
            items=[dispatch_item(store, park, i) for i, park in enumerate(store.ranked()[:k], 1)],
        )
    assert_no_pii(result.model_dump())
    return result
