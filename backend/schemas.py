"""Validated response contracts for SPEC §8; additive fields remain compatible."""

from collections import Counter
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Ratio = Annotated[float, Field(ge=0, le=1)]
Score = Annotated[float, Field(ge=0, le=100)]
Count = Annotated[int, Field(ge=0)]
Tier = Literal["高", "中", "低"]
Institution = Literal["公立", "私立", "非營利"]
DimensionName = Literal["violation", "evaluation", "sentiment", "operation"]
REASON_DIMENSIONS = {
    **dict.fromkeys(
        [
            "VIO_PUNISH_COUNT",
            "VIO_RECENT",
            "VIO_ABUSE",
            "VIO_OWNER_PRIOR",
            "VIO_CHAIN_REPEAT",
            "VIO_SIBLING",
            "VIO_CAT_CONCENTRATED",
            "VIO_CHAIN_SIZE",
        ],
        "violation",
    ),
    **dict.fromkeys(["EVAL_FAIL", "EVAL_ADMIN", "EVAL_FOLLOWUP", "EVAL_MISSING"], "evaluation"),
    **dict.fromkeys(["MEDIA_PARK", "MEDIA_BURST", "MEDIA_TOWN_HEAT"], "sentiment"),
    **dict.fromkeys(
        [
            "OPER_PERSONNEL_EXEC",
            "OPER_SUBSTITUTE_EXEC",
            "OPER_AUDIT_MAJOR",
            "OPER_ENROLL_LOW",
            "OPER_OVER_ENROLL",
            "OPER_FEE_DEVIATION",
        ],
        "operation",
    ),
}


class Contract(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)


class ModelMetrics(Contract):
    name: str
    precision_at_50: Ratio
    baseline: Ratio
    lift: float | None = None


class Weights(Contract):
    violation: Ratio
    evaluation: Ratio
    # None = 該維度沒進分數。兩種原因，形狀相同：
    #   sentiment：ADR-0001 量測後移出計分（L2 區級熱度 lift 0.74x，低於隨機）
    #   operation：私立與非營利-無財報沒有財報來源
    # 原本只有 operation 允許 None，mock 的 sentiment 是 0.15 所以一直驗證過，
    # 直到上傳真實 serving 資料才全面 500。mock fixture 已跟進改成 null。
    sentiment: Ratio | None
    operation: Ratio | None

    @model_validator(mode="after")
    def check_sum(self):
        total = sum(
            w for w in (self.violation, self.evaluation, self.sentiment, self.operation)
            if w is not None
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"有效維度權重總和需為 1.0，實為 {total}")
        return self


class PeerGroup(Contract):
    n: Count
    operation: str | None = None


class Meta(Contract):
    version: str
    generated_at: str
    # cutoff 是「這批分數吃到哪一天為止的事實」，上線時等於資料日。
    # validation_cutoff 是「model 那組成效用哪個時間切分量出來的」，永遠
    # 2025-01-01。兩者分開，畫面上的 26% 才不會被讀成用這批資料量到的。
    cutoff: str
    validation_cutoff: str | None = None
    model_basis: str | None = None
    population: Count
    weights: dict[Institution, Weights]
    peer_groups: dict[str, PeerGroup]
    score_basis: str
    rank_basis: str
    unvalidated_dimensions: list[DimensionName]
    tiers: dict[str, tuple[int, int]]
    data_freshness: dict[str, str]
    model: ModelMetrics


class Risk(Contract):
    # SPEC §2：is_active == 0 的 37 園（已停辦）保留供查詢，但不進排名、
    # 不進分級。它們的 score/rank/tier 三個都是 null；排名分母是 1,178 而非 1,215。
    # 在營園所必須有分數，由 Park.check_park 跟 ParkSummary 分別強制。
    # score 是四維度加權總分（R_raw 取一位小數），不是百分位——2026-09-12 改。
    # rank 仍是全市合併名次；tier 改由各設立別自己的分佈切（scoring.assign_tiers）。
    score: Score | None
    rank: Annotated[int, Field(ge=1)] | None
    tier: Tier | None
    # 設立別內名次，取代舊版那個會被誤讀成「總分」的百分位。
    peer_rank: Annotated[int, Field(ge=1)] | None = None
    peer_n: Annotated[int, Field(ge=1)] | None = None


class Dimension(Contract):
    applicable: bool
    score: Score | None
    coverage: Ratio
    weight: Ratio | None
    validated: bool
    note: str | None = None

    @model_validator(mode="after")
    def check_applicability(self):
        if not self.applicable and (self.score is not None or self.weight is not None):
            raise ValueError("Inapplicable dimensions must have null score and weight")
        return self


class Dimensions(Contract):
    violation: Dimension
    evaluation: Dimension
    sentiment: Dimension
    operation: Dimension

    @model_validator(mode="after")
    def check_operation(self):
        if self.operation.validated:
            raise ValueError("Operation is not a validated dimension")
        return self


class Reason(Contract):
    code: str
    label: str
    weight: Annotated[float, Field(ge=0)]
    dimension: DimensionName
    validated: bool

    @model_validator(mode="after")
    def check_reason(self):
        if REASON_DIMENSIONS.get(self.code) != self.dimension:
            raise ValueError("Unknown or mismatched reason code")
        if self.dimension == "operation" and self.validated:
            raise ValueError("Operation reasons cannot be validated")
        if "{" in self.label or "}" in self.label:
            raise ValueError("Unfilled reason template")
        return self


class FinanceFlag(Contract):
    code: str
    label: str
    severity: Annotated[int, Field(ge=1, le=3)]
    year: int
    # 查核表的項次（OPER_AUDIT_ITEM 專用）。稽查人員要能照這個號碼
    # 去翻原始查核表，所以它是契約的一部分，不是不該出現的額外欄位。
    no: int | None = None
    validated: Literal[False]


class Media(Contract):
    sri: float
    has_signal: bool
    town_heat_per_park: float
    last_negative_at: str | None


class Punishment(Contract):
    date: str
    category: str
    law: str
    fine: float | None
    penalty_raw: str
    is_after_cutoff: bool


class Park(Contract):
    park_id: str
    name: str
    institution_type: Institution
    type: Institution
    peer_group: str
    town: str
    address: str
    tel: str
    lon: Annotated[float, Field(ge=-180, le=180)] | None
    lat: Annotated[float, Field(ge=-90, le=90)] | None
    is_active: Literal[0, 1]
    count_approved: Count | None
    owner_key: str | None = None
    as_of_date: str | None = None
    risk: Risk
    dimensions: Dimensions
    reasons: list[Reason] = Field(max_length=3)
    finance_flags: list[FinanceFlag]
    media: Media
    timeline: list[Punishment]

    @model_validator(mode="after")
    def check_park(self):
        if self.type != self.institution_type:
            raise ValueError("Institution aliases disagree")
        if self.is_active and (
            self.risk.score is None or self.risk.rank is None or self.risk.tier is None
        ):
            raise ValueError("Active parks require score, rank and tier")
        if not self.is_active and self.risk.score is not None:
            raise ValueError("Closed parks are excluded from ranking and carry no score")
        if self.institution_type == "私立" and self.dimensions.operation.applicable:
            raise ValueError("Operation cannot apply to private parks")
        if max(Counter(r.dimension for r in self.reasons).values(), default=0) > 2:
            raise ValueError("At most two reasons per dimension")
        if [r.weight for r in self.reasons] != sorted(
            (r.weight for r in self.reasons), reverse=True
        ):
            raise ValueError("Reasons must be sorted by weight")
        return self


class MediaCoverage(Contract):
    """一則點名本園的報導。**唯一允許帶切點之後日期的契約物件。**

    風險分數的輿情維度必須守著切點（否則是用 2026 年的新聞預測 2025 年的
    裁罰），但稽查人員要看的恰恰是最近發生的事。兩者走不同資料路徑：
    這份不經 features，不進任何分數，`is_after_cutoff` 讓前端把它標示出來。
    """

    date: str
    outlet: str | None = None
    title: str
    url: str | None = None
    event_type: str | None = None
    severity: Annotated[int, Field(ge=1, le=5)] | None = None
    stance: str | None = None
    is_after_cutoff: bool


class ParkDetail(Park):
    fees: list[dict[str, Any]]
    finance: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    media_coverage: list[MediaCoverage] = []


class ParkSummary(Contract):
    park_id: str
    name: str
    type: Institution
    institution_type: Institution
    town: str
    lon: float | None
    lat: float | None
    is_active: Literal[1]
    risk: Risk
    pun_count: Count
    has_finance_flag: bool
    reasons: list[Reason] = []
    has_media_signal: bool

    @model_validator(mode="after")
    def check_scored(self):
        # 列表只收在營園所（is_active Literal[1]），所以 Risk.score 改成可空之後，
        # 這裡要把它收緊回來，否則前端排序會碰到 None。
        if self.risk.score is None or self.risk.rank is None:
            raise ValueError("Listed parks are always scored and ranked")
        return self


class ParkPage(Contract):
    total: Count
    page: int
    size: int
    items: list[ParkSummary]


class RiskTop(Contract):
    k: int
    items: list[Park]


class MediaPark(Contract):
    """輿情分頁的一列：一家園所在觀察窗內的報導聚合。

    排序依 `article_count` 由多到少——同一起事件被十幾家媒體轉載，
    報導數本身就是外界關注度的直接量測。分數不參與排序：
    SRI 守著切點，這裡刻意含切點之後的報導（見 MediaCoverage）。
    """

    park_id: str
    name: str
    town: str
    # 停辦園所 score / rank / tier 三個都是 null（SPEC §2）。停辦不代表
    # 沒被報導過，所以這裡照收，只是沒有分級可標。
    tier: Tier | None = None
    sri: float
    article_count: Count
    latest_date: str
    max_severity: Annotated[int, Field(ge=1, le=5)] | None = None
    top_event_type: str | None = None
    after_cutoff_count: Count


class MediaPage(Contract):
    months: int
    as_of: str
    since: str
    items: list[MediaPark]


class District(Contract):
    town: str
    park_count: Count
    high_risk_count: Count
    high_risk_ratio: Ratio
    media_heat: float
    media_heat_per_park: float
    pun_count_before_cutoff: Count


class Districts(Contract):
    items: list[District]


class Point(Contract):
    type: Literal["Point"]
    coordinates: tuple[
        Annotated[float, Field(ge=-180, le=180)],
        Annotated[float, Field(ge=-90, le=90)],
    ]


class MapProperties(Contract):
    park_id: str
    name: str
    tier: Tier
    risk_score: Score
    pun_count: Count
    has_abuse: bool
    town: str | None = None


class Feature(Contract):
    type: Literal["Feature"]
    geometry: Point
    properties: MapProperties


class FeatureCollection(Contract):
    type: Literal["FeatureCollection"]
    features: list[Feature]


class CurvePoint(Contract):
    k: Count
    model: float
    eval: float
    punish: float
    random: float
    perfect: float


class CurveSummary(Contract):
    precision_at_50: dict[str, Ratio]
    stratified: dict[str, dict[str, float | None]]

    @model_validator(mode="after")
    def check_baselines(self):
        # 成效驗證頁的整個論述是「模型 vs 隨機抽查」。少了 random 就只剩
        # 一個孤零零的 26%，讀的人沒有尺。實測失踪過一次，所以寫成必填。
        missing = {"model", "random"} - set(self.precision_at_50)
        if missing:
            raise ValueError(f"curve summary 缺少 {sorted(missing)}")
        return self


class Curve(Contract):
    population: Count
    positives: Count
    baseline: Ratio
    points: list[CurvePoint]
    summary: CurveSummary


class Action(Contract):
    focus: str
    why: str


class Brief(Contract):
    park_id: str
    source: Literal["template", "llm"]
    summary: str = Field(min_length=1)
    reasons: list[str] = Field(min_length=1, max_length=3)
    actions: list[Action] = Field(max_length=3)
    generated_at: str


class Attachments(Contract):
    punishment_count: Count
    evaluation_count: Count | None


class WorkItem(BaseModel):
    # An allowlist prevents unrelated serving fields being copied into dispatch sheets.
    model_config = ConfigDict(extra="forbid")
    seq: int
    park_id: str
    name: str
    town: str
    type: Institution
    institution_type: Institution
    count_approved: Count | None
    address: str
    tel: str
    risk: Risk
    # 至多 3 條，至少 1 條。原本寫恆為 3，但前 50 名裡有 4 園是純靠評鑑
    # 排上來的（零裁罰），真實只給得出 2 條。湊第三條就是編理由，
    # 而派工單上的每一句話都會被稽查人員當成事實拿去問園方。
    reasons: list[str] = Field(min_length=1, max_length=3)
    actions: list[Action] = Field(max_length=3)
    attachments: Attachments


class Worklist(Contract):
    week: str
    generated_at: str
    model: ModelMetrics
    items: list[WorkItem]


class Error(Contract):
    code: str
    message: str
    request_id: str


class ErrorResponse(Contract):
    error: Error
