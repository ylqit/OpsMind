"""
运行时合约模块

定义系统核心数据模型和状态枚举。
"""
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime


class RuntimeState(IntEnum):
    """
    运行时状态枚举

    描述任务在其生命周期中的当前位置。

    Attributes:
        Idle: 空闲状态，等待新任务
        Running: 正在执行
        Pending: 等待外部输入（如 HITL 确认）
        Suspended: 已暂停
        Completed: 正常完成
        Error: 执行出错
    """
    Idle = 0
    Running = 1
    Pending = 2
    Suspended = 3
    Completed = 4
    Error = 5


class FlowPhase(IntEnum):
    """
    流程阶段枚举

    ReAct 模式中的各个阶段。

    Attributes:
        Reasoning: 推理阶段
        Planning: 规划阶段
        Acting: 执行阶段
        Observing: 观察阶段
        Reflecting: 反思阶段
    """
    Reasoning = 0
    Planning = 1
    Acting = 2
    Observing = 3
    Reflecting = 4


@dataclass
class ExecutionContext:
    """
    执行上下文数据类

    携带任务执行过程中的所有状态信息。

    Attributes:
        session_uuid: 会话唯一标识
        flow_id: 流程标识
        current_phase: 当前所处阶段
        state: 运行时状态
        history: 历史操作记录
        variables: 上下文变量
        created_at: 创建时间
        updated_at: 更新时间
    """
    session_uuid: UUID
    flow_id: str
    current_phase: FlowPhase
    state: RuntimeState
    history: List[Dict[str, Any]] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None

    @classmethod
    def create(cls, flow_id: str) -> "ExecutionContext":
        """
        创建新的执行上下文

        Args:
            flow_id: 流程标识

        Returns:
            ExecutionContext: 新创建的执行上下文实例
        """
        now = datetime.now()
        return cls(
            session_uuid=uuid4(),
            flow_id=flow_id,
            current_phase=FlowPhase.Reasoning,
            state=RuntimeState.Idle,
            history=[],
            variables={},
            created_at=now
        )

    def transition(self, new_state: RuntimeState, phase: Optional[FlowPhase] = None) -> None:
        """
        状态转换

        Args:
            new_state: 新的运行时状态
            phase: 新的流程阶段（可选）
        """
        self.state = new_state
        if phase is not None:
            self.current_phase = phase
        self.updated_at = datetime.now()

    def record_history(self, entry: Dict[str, Any]) -> None:
        """
        记录历史操作

        Args:
            entry: 历史记录条目
        """
        entry["timestamp"] = datetime.now().isoformat()
        self.history.append(entry)


@dataclass
class ActionResult:
    """
    动作执行结果数据类

    Attributes:
        success: 是否成功
        data: 结果数据
        error_message: 错误信息
        error_code: 错误代码
        requires_confirmation: 是否需要确认
        metadata: 额外元数据
    """
    success: bool
    data: Optional[Any] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    requires_confirmation: bool = False
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def ok(cls, data: Any, metadata: Optional[Dict[str, Any]] = None) -> "ActionResult":
        """
        创建成功结果

        Args:
            data: 结果数据
            metadata: 额外元数据

        Returns:
            ActionResult: 成功结果实例
        """
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, message: str, code: str = "UNKNOWN_ERROR") -> "ActionResult":
        """
        创建失败结果

        Args:
            message: 错误信息
            code: 错误代码

        Returns:
            ActionResult: 失败结果实例
        """
        return cls(success=False, error_message=message, error_code=code)

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典

        Returns:
            字典表示
        """
        return {
            "success": self.success,
            "data": self.data,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "requires_confirmation": self.requires_confirmation,
            "metadata": self.metadata
        }


@dataclass
class TraceStep:
    """
    追踪步骤数据类

    记录执行过程中的每一步。

    Attributes:
        step_id: 步骤 ID
        phase: 所属阶段
        action_type: 动作类型
        content: 内容
        result: 执行结果
        timestamp: 时间戳
    """
    step_id: str
    phase: FlowPhase
    action_type: str
    content: str
    result: Optional[ActionResult] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "step_id": self.step_id,
            "phase": self.phase.name,
            "action_type": self.action_type,
            "content": self.content,
            "result": self.result.to_dict() if self.result else None,
            "timestamp": self.timestamp.isoformat()
        }
