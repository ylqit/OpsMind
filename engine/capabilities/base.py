"""
能力基类模块

定义所有运维能力的统一接口。
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel, Field


class CapabilityMetadata(BaseModel):
    """
    能力元数据类

    描述能力的基本信息。

    Attributes:
        name: 能力名称（英文蛇形命名）
        description: 能力描述（中文）
        version: 版本号
        tags: 标签列表（用于分类）
        requires_confirmation: 是否需要用户确认
    """
    name: str = Field(..., description="能力名称", min_length=1, max_length=64)
    description: str = Field(..., description="能力描述", min_length=1)
    version: str = Field(default="1.0.0", description="版本号")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    requires_confirmation: bool = Field(default=False, description="是否需要确认")


class CapabilitySchema(BaseModel):
    """
    能力参数模式类

    定义能力调用时所需的参数结构。
    """
    type: str = Field(default="object", description="类型")
    properties: Dict[str, Any] = Field(default_factory=dict, description="属性定义")
    required: List[str] = Field(default_factory=list, description="必填字段列表")


class BaseCapability(ABC):
    """
    能力基类

    所有运维能力必须继承此类，实现 dispatch 方法。

    使用示例:
        >>> class ContainerInspector(BaseCapability):
        ...     def _define_metadata(self) -> CapabilityMetadata:
        ...         return CapabilityMetadata(
        ...             name="inspect_container",
        ...             description="检查容器状态"
        ...         )
        ...
        ...     def _define_input_schema(self) -> Type[BaseModel]:
        ...         return ContainerInspectInput
        ...
        ...     async def dispatch(self, **kwargs) -> ActionResult:
        ...         # 实现具体逻辑
        ...         pass

    子类必须实现的方法:
        - _define_metadata: 定义能力元数据
        - _define_input_schema: 定义输入参数模式
        - dispatch: 执行能力逻辑
    """

    def __init__(self):
        """初始化能力"""
        self.metadata = self._define_metadata()
        self.input_schema = self._define_input_schema()

    @abstractmethod
    def _define_metadata(self) -> CapabilityMetadata:
        """
        定义能力元数据

        子类必须实现此方法来描述自身。

        Returns:
            CapabilityMetadata: 能力元数据
        """
        pass

    @abstractmethod
    def _define_input_schema(self) -> Type[BaseModel]:
        """
        定义输入参数模式

        子类必须实现此方法来定义输入参数结构。

        Returns:
            Type[BaseModel]: 输入参数模式类
        """
        pass

    @abstractmethod
    async def dispatch(self, **kwargs) -> "ActionResult":
        """
        分派执行

        子类必须实现此方法来实现具体逻辑。

        Args:
            **kwargs: 调用参数

        Returns:
            ActionResult: 执行结果
        """
        pass

    def to_openai_tool(self) -> Dict[str, Any]:
        """
        转换为 OpenAI Tool 定义格式

        Returns:
            OpenAI Tool 定义字典
        """
        schema_dict = self.input_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.metadata.name,
                "description": self.metadata.description,
                "parameters": schema_dict
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典表示

        Returns:
            能力的字典表示
        """
        return {
            "name": self.metadata.name,
            "description": self.metadata.description,
            "version": self.metadata.version,
            "tags": self.metadata.tags,
            "requires_confirmation": self.metadata.requires_confirmation
        }


class CapabilityRegistry:
    """
    能力注册表

    管理所有已注册的能力，提供注册、查询、获取定义等功能。

    使用示例:
        >>> registry = CapabilityRegistry()
        >>> registry.register(ContainerInspector())
        >>> tool = registry.get("inspect_container")
        >>> definitions = registry.get_all_definitions()
    """

    def __init__(self):
        """初始化注册表"""
        self._capabilities: Dict[str, BaseCapability] = {}

    def register(self, capability: BaseCapability) -> None:
        """
        注册能力

        Args:
            capability: 能力实例

        Raises:
            ValueError: 当能力名称已存在时
        """
        name = capability.metadata.name
        if name in self._capabilities:
            raise ValueError(f"能力 '{name}' 已注册")
        self._capabilities[name] = capability

    def get(self, name: str) -> Optional[BaseCapability]:
        """
        获取能力

        Args:
            name: 能力名称

        Returns:
            能力实例，如果不存在则返回 None
        """
        return self._capabilities.get(name)

    def unregister(self, name: str) -> None:
        """
        注销能力

        Args:
            name: 能力名称
        """
        if name in self._capabilities:
            del self._capabilities[name]

    def get_all_definitions(self) -> List[Dict[str, Any]]:
        """
        获取所有能力的 OpenAI Tool 定义

        Returns:
            OpenAI Tool 定义列表
        """
        return [cap.to_openai_tool() for cap in self._capabilities.values()]

    def list_capabilities(self) -> List[str]:
        """
        列出所有已注册的能力名称

        Returns:
            能力名称列表
        """
        return list(self._capabilities.keys())

    def clear(self) -> None:
        """清空注册表"""
        self._capabilities.clear()
