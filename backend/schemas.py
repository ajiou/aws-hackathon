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
    sentiment: Ratio
    operation: Ratio | None


class PeerGroup(Contract):
    n: Count
    operation: str | None = None


class Meta(Contract):
    version: str
    generated_at: str
    cutoff: str
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
    score: Score
    rank: Annotated[int, Field(ge=1)] | None
    tier: Tier | None


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
        if self.is_active and (self.risk.rank is None or self.risk.tier is None):
            raise ValueError("Active parks require rank and tier")
        if self.institution_type == "私立" and self.dimensions.operation.applicable:
            raise ValueError("Operation cannot apply to private parks")
        if max(Counter(r.dimension for r in self.reasons).values(), default=0) > 2:
            raise ValueError("At most two reasons per dimension")
        if [r.weight for r in self.reasons] != sorted(
            (r.weight for r in self.reasons), reverse=True
        ):
            raise ValueError("Reasons must be sorted by weight")
        return self


class ParkDetail(Park):
    fees: list[dict[str, Any]]
    finance: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]


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
    has_media_signal: bool


class ParkPage(Contract):
    total: Count
    page: int
    size: int
    items: list[ParkSummary]


class RiskTop(Contract):
    k: int
    items: list[Park]


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
    reasons: list[str] = Field(min_length=3, max_length=3)
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
