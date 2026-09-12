"""全專案共用常數。SPEC §1 的定義在這裡只有一份。"""
from datetime import date

CUTOFF = date(2025, 1, 1)          # SPEC §1.2
CITY = "新北市"

# SPEC §5.0 四維度權重
WEIGHTS = {
    "公立":   {"violation": 0.35, "evaluation": 0.20, "sentiment": 0.15, "operation": 0.30},
    "非營利": {"violation": 0.35, "evaluation": 0.20, "sentiment": 0.15, "operation": 0.30},
    "私立":   {"violation": 0.50, "evaluation": 0.286, "sentiment": 0.214, "operation": None},
}

# SPEC §5.6.0 營運維度的同儕群與公式
PEER_GROUPS = {
    "公立-獨立":     {"operation": {"F": 0.60, "E": 0.25, "C": 0.15}},
    "公立-附設":     {"operation": {"C": 1.00}},
    "非營利-有財報": {"operation": {"F": 0.40, "H": 0.45, "E": 0.15}},
    "非營利-無財報": {"operation": None},
    "私立":          {"operation": None},
}

# SPEC §5.3 裁罰嚴重度。不可用罰鍰金額，40 筆停招/減招的 fine 是 NULL
SEVERITY = {
    "性平事件": 5, "不當管教": 5,
    "食安衛生": 4, "設施安全": 4,
    "交通車": 3, "超收": 3, "師生比": 3, "師資": 3,
    "收費爭議": 2,
    "其他行政": 1,
}
PUNISH_HALFLIFE_DAYS = 540

# SPEC §5.5 輿情半衰期
MEDIA_HALFLIFE = {
    "性平事件": 180, "不當管教": 180,
    "食安衛生": 120, "設施安全": 120, "交通車": 120,
    "超收": 60, "收費爭議": 60, "行政裁罰": 60,
    "師資不足": 30, "財務欠薪": 30,
}
MEDIA_HALFLIFE_DEFAULT = 30
SRI_SATURATION = 3.0

# SPEC §1.4 分級（依全市合併名次）
TIERS = [("高", 1, 50), ("中", 51, 200), ("低", 201, None)]

# SPEC §2.2 / §2.4 必須丟棄的欄位
DROP_COLUMNS = {
    "penalty",    # §2.4 標籤洩漏
    "is_free5",   # 可用率 0%
    "shuttle",    # 全是 tab 字元
}
