"""
任务、资产、信号、事件和建议等核心对象。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .time_utils import utc_now


class TaskType(str, Enum):
    DASHBOARD_REFRESH = "dashboard_refresh"
    INCIDENT_ANALYSIS = "incident_analysis"
    RECOMMENDATION_GENERATION = "recommendation_generation"
    REPORT_GENERATION = "report_generation"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    COLLECTING = "COLLECTING"
    ANALYZING = "ANALYZING"
    WAITING_CONFIRM = "WAITING_CONFIRM"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AssetType(str, Enum):
    HOST = "host"
    CONTAINER = "container"
    POD = "pod"
    SERVICE = "service"
    INGRESS = "ingress"


class SignalType(str, Enum):
    METRIC = "metric"
    LOG = "log"
    ALERT = "alert"
    EVENT = "event"


class IncidentStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class RecommendationKind(str, Enum):
    SCALE = "scale"
    RATE_LIMIT = "rate_limit"
    RESOURCE_TUNING = "resource_tuning"
    MANIFEST_DRAFT = "manifest_draft"


class ObservationKind(str, Enum):
    INLINE = "inline"
    REF = "ref"


class ArtifactKind(str, Enum):
    LOG_SNIPPET = "log_snippet"
    TRACE = "trace"
    REPORT = "report"
    MANIFEST = "manifest"
    JSON = "json"
    TEXT = "text"
    DIFF = "diff"


class ArtifactRef(BaseModel):
    artifact_id: str
    task_id: str
    kind: str
    path: str
    preview: str = ""
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=utc_now)


class Observation(BaseModel):
    kind: ObservationKind
    summary: str
    data: Optional[Dict[str, Any]] = None
    artifact_ref: Optional[ArtifactRef] = None


class TraceRecord(BaseModel):
    trace_id: str
    task_id: str
    step: str
    action: str
    stage: TaskStatus
    observation: Observation
    created_at: datetime = Field(default_factory=utc_now)


class TaskError(BaseModel):
    error_code: str
    error_message: str
    failed_stage: Optional[TaskStatus] = None


class TaskApproval(BaseModel):
    approved_by: str
    approval_note: str = ""
    approved_at: datetime = Field(default_factory=utc_now)


class TaskRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{uuid4().hex[:12]}")
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    current_stage: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    progress_message: str = ""
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid4().hex[:12]}")
    payload: Dict[str, Any] = Field(default_factory=dict)
    result_ref: Optional[Dict[str, Any]] = None
    error: Optional[TaskError] = None
    approval: Optional[TaskApproval] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = None


class AICallLogStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class AIProviderConfigRecord(BaseModel):
    provider_id: str = Field(default_factory=lambda: f"provider_{uuid4().hex[:12]}")
    name: str
    provider_type: str
    model: str
    base_url: Optional[str] = None
    api_key: str = ""
    enabled: bool = True
    is_default: bool = False
    timeout: int = 30
    max_retries: int = 2
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AICallLog(BaseModel):
    call_id: str = Field(default_factory=lambda: f"llm_call_{uuid4().hex[:12]}")
    provider_name: str
    model: str
    source: str = "unknown"
    endpoint: str = "chat"
    task_id: Optional[str] = None
    prompt_preview: str = ""
    response_preview: str = ""
    status: AICallLogStatus = AICallLogStatus.SUCCESS
    error_code: str = ""
    error_message: str = ""
    latency_ms: int = 0
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    created_at: datetime = Field(default_factory=utc_now)


class UsageMetricsDailyRecord(BaseModel):
    metric_date: str
    service_key: str = "all"
    model: str = "all"
    provider_name: str = "all"
    ai_call_total: int = 0
    ai_error_count: int = 0
    ai_success_count: int = 0
    ai_avg_latency_ms: float = 0.0
    ai_total_tokens: int = 0
    ai_total_cost: float = 0.0
    ai_timeout_count: int = 0
    guardrail_fallback_count: int = 0
    guardrail_retried_count: int = 0
    guardrail_schema_error_count: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


class ExecutorPluginKey(str, Enum):
    LINUX = "linux"
    K8S = "k8s"
    DOCKER = "docker"


class ExecutorHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class ExecutorRunStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    REJECTED = "rejected"
    CIRCUIT_OPEN = "circuit_open"


class ExecutorPluginRecord(BaseModel):
    plugin_key: str
    display_name: str
    description: str = ""
    enabled: bool = True
    readonly_only: bool = True
    write_enabled: bool = False
    failure_count: int = 0
    circuit_open_until: Optional[datetime] = None
    last_error: str = ""
    updated_at: datetime = Field(default_factory=utc_now)


class ExecutorAuditRecord(BaseModel):
    execution_id: str = Field(default_factory=lambda: f"exec_{uuid4().hex[:12]}")
    task_id: Optional[str] = None
    plugin_key: str
    command: str
    readonly: bool = True
    status: ExecutorRunStatus = ExecutorRunStatus.SUCCESS
    exit_code: Optional[int] = None
    stdout_preview: str = ""
    stderr_preview: str = ""
    duration_ms: int = 0
    error_code: str = ""
    error_message: str = ""
    operator: str = "system"
    approval_ticket: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class Asset(BaseModel):
    asset_id: str = Field(default_factory=lambda: f"asset_{uuid4().hex[:12]}")
    asset_type: AssetType
    name: str
    namespace: Optional[str] = None
    service_key: str
    labels: Dict[str, Any] = Field(default_factory=dict)
    source_refs: Dict[str, Any] = Field(default_factory=dict)
    health_status: str = "unknown"
    unmapped: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Signal(BaseModel):
    signal_id: str = Field(default_factory=lambda: f"signal_{uuid4().hex[:12]}")
    signal_type: SignalType
    timestamp: datetime = Field(default_factory=utc_now)
    asset_id: Optional[str] = None
    service_key: str
    severity: str = "info"
    payload: Dict[str, Any] = Field(default_factory=dict)
    source: str = "unknown"
    created_at: datetime = Field(default_factory=utc_now)


class Incident(BaseModel):
    incident_id: str = Field(default_factory=lambda: f"incident_{uuid4().hex[:12]}")
    title: str
    severity: str = "warning"
    status: IncidentStatus = IncidentStatus.OPEN
    time_window_start: datetime
    time_window_end: datetime
    service_key: str
    related_asset_ids: List[str] = Field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    recommended_actions: List[str] = Field(default_factory=list)
    reasoning_tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Recommendation(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: f"rec_{uuid4().hex[:12]}")
    incident_id: str
    target_asset_id: Optional[str] = None
    kind: RecommendationKind
    confidence: float = 0.0
    observation: str
    recommendation: str
    risk_note: str = ""
    artifact_refs: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RecommendationFeedbackAction(str, Enum):
    ADOPT = "adopt"
    REJECT = "reject"
    REWRITE = "rewrite"


class RecommendationFeedback(BaseModel):
    feedback_id: str = Field(default_factory=lambda: f"feedback_{uuid4().hex[:12]}")
    recommendation_id: str
    incident_id: str
    task_id: Optional[str] = None
    action: RecommendationFeedbackAction
    reason_code: str = ""
    comment: str = ""
    operator: str = "anonymous"
    created_at: datetime = Field(default_factory=utc_now)


class TimeSeriesPoint(BaseModel):
    timestamp: str
    value: float


class OverviewCard(BaseModel):
    key: str
    label: str
    value: float | int | str
    unit: str = ""
    status: Literal["normal", "warning", "critical", "info"] = "info"


class ServiceHotspot(BaseModel):
    service_key: str
    score: float
    reason: str
    metric_value: float = 0.0


class DashboardOverview(BaseModel):
    cards: List[OverviewCard]
    traffic_trend: List[TimeSeriesPoint]
    recent_incidents: List[Incident]
    hot_services: List[ServiceHotspot]
    data_health: Dict[str, Any] = Field(default_factory=dict)
    data_sources: Dict[str, Any]
