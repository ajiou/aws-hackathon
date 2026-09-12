"""Synthetic fixtures independent of the team's serving artifacts."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings


@pytest.fixture
def artifacts():
    # sentiment=None 跟真實 serving 資料一致（ADR-0001 把輿情移出計分）。
    # 舊 fixture 寫 0.214，把 Weights.sentiment 不可為 None 的 bug 蔽了一整輪部署。
    weights = {"violation": 0.38, "evaluation": 0.62, "sentiment": None, "operation": None}
    meta = {
        "version": "test-v1",
        "generated_at": "2026-09-12T06:00:00Z",
        "cutoff": "2025-01-01",
        "population": 3,
        "weights": {"私立": weights},
        "peer_groups": {"私立": {"n": 3}},
        "score_basis": "組內百分位",
        "rank_basis": "全市合併",
        "unvalidated_dimensions": ["operation"],
        "tiers": {"high": [1, 1], "medium": [2, 2], "low": [3, 3]},
        "data_freshness": {"punishments": "2026-08-21"},
        "model": {"name": "test-model", "precision_at_50": 0.28, "baseline": 0.106},
    }
    base = {
        "park_id": "park-1",
        "name": "測試甲幼兒園",
        "institution_type": "私立",
        "peer_group": "私立",
        "town": "板橋區",
        "address": "測試路1號",
        "tel": "02-00000000",
        "lon": 121.4,
        "lat": 25.0,
        "is_active": 1,
        "count_approved": 100,
        "owner_key": "012345abcdef",
        "risk": {"score": 90, "rank": 1, "tier": "高"},
        "dimensions": {
            key: {
                "applicable": True,
                "score": 50,
                "coverage": 1,
                "weight": weight,
                "validated": True,
            }
            for key, weight in weights.items()
            if key != "operation"
        },
        "reasons": [
            {
                "code": "VIO_PUNISH_COUNT",
                "label": "切點前已有 3 次裁罰",
                "weight": 0.4,
                "dimension": "violation",
                "validated": True,
            }
        ],
        "finance_flags": [],
        "media": {
            "sri": 0,
            "has_signal": False,
            "town_heat_per_park": 0.1,
            "last_negative_at": None,
        },
        "timeline": [
            {
                "date": "2023-01-01",
                "category": "師生比",
                "law": "第16條第4項",
                "fine": 6000,
                "penalty_raw": "罰鍰6,000元",
                "is_after_cutoff": False,
            }
        ],
    }
    base["dimensions"]["operation"] = {
        "applicable": False,
        "score": None,
        "coverage": 0,
        "weight": None,
        "validated": False,
    }
    rows = [deepcopy(base) for _ in range(4)]
    for index, row in enumerate(rows, 1):
        row["park_id"] = f"park-{index}"
        row["name"] = f"測試{index}幼兒園"
        row["risk"] = {
            "score": 100 - index * 10,
            "rank": index,
            "tier": ["高", "中", "低", "低"][index - 1],
        }
        row["timeline"] = deepcopy(base["timeline"] * index)
    rows[1]["town"] = "新店區"
    rows[1]["institution_type"] = "公立"
    rows[1]["peer_group"] = "公立-附設"
    rows[1]["finance_flags"] = [
        {
            "code": "OPER_PERSONNEL_EXEC",
            "label": "人事費執行率偏低",
            "severity": 2,
            "year": 113,
            "validated": False,
        }
    ]
    rows[2]["institution_type"] = "非營利"
    rows[2]["type"] = "非營利"
    rows[2]["peer_group"] = "非營利-無財報"
    rows[2]["timeline"] = []
    rows[2]["reasons"] = []
    rows[3]["is_active"] = 0
    # 已停辦的園所 score 是 null，不是 0。score 0 讀起來是「算過，風險最低」，
    # 但實情是「根本沒進排名」。SPEC §2：37 園不進排名、不進分級。
    rows[3]["risk"] = {"score": None, "rank": None, "tier": None}
    return {
        "meta": meta,
        "scores": {"items": rows},
        "districts": {
            "items": [
                {
                    "town": "板橋區",
                    "park_count": 2,
                    "high_risk_count": 1,
                    "high_risk_ratio": 0.5,
                    "media_heat": 0.2,
                    "media_heat_per_park": 0.1,
                    "pun_count_before_cutoff": 1,
                }
            ]
        },
        "map": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "park_id": r["park_id"],
                        "name": r["name"],
                        "tier": r["risk"]["tier"],
                        "risk_score": r["risk"]["score"],
                        "pun_count": len(r["timeline"]),
                        "has_abuse": False,
                    },
                }
                for r in rows[:3]
            ],
        },
        "curve": {
            "population": 3,
            "positives": 1,
            "baseline": 1 / 3,
            "points": [{"k": 1, "model": 1, "eval": 0, "punish": 1, "random": 1 / 3, "perfect": 1}],
            "summary": {
                "precision_at_50": {"model": 0.28, "random": 0.106},
                "stratified": {},
            },
        },
    }


@pytest.fixture
def serving_dir(tmp_path, artifacts):
    for key, data in artifacts.items():
        (tmp_path / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    return tmp_path


@pytest.fixture
def client(serving_dir):
    with TestClient(create_app(Settings(serving_dir=serving_dir))) as test_client:
        yield test_client
