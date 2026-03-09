"""
运行时配置模块

从环境变量加载配置。

注意：敏感信息（API Key 等）应通过环境变量传递，
不要提交到版本控制系统！
"""
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """
    LLM 配置类

    Attributes:
        api_key: API 密钥
        base_url: API 基础 URL
        model: 模型名称
        temperature: 生成温度
        timeout: 请求超时（秒）
    """
    api_key: str = Field(..., description="API 密钥")
    base_url: str = Field(default="https://api.openai.com/v1", description="API 基础 URL")
    model: str = Field(default="gpt-4o-mini", description="模型名称")
    temperature: float = Field(default=0.2, ge=0, le=2, description="生成温度")
    timeout: int = Field(default=60, ge=10, description="请求超时（秒）")


class DockerConfig(BaseModel):
    """
    Docker 配置类

    Attributes:
        host: Docker 守护进程地址
    """
    host: str = Field(default="unix:///var/run/docker.sock", description="Docker 守护进程地址")


class RuntimeConfig(BaseSettings):
    """
    运行时配置类

    从环境变量加载所有配置。

    使用示例:
        >>> config = RuntimeConfig()
        >>> print(config.llm.model)
        >>> print(config.port)

    环境变量列表:
        - LLM_API_KEY: LLM API 密钥
        - LLM_BASE_URL: LLM API 基础 URL
        - LLM_MODEL: 模型名称
        - PORT: 服务端口
        - DEBUG: 调试模式
        - DOCKER_HOST: Docker 守护进程地址
        - DATA_SOURCES: 启用的数据源列表
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # 应用配置
    app_name: str = Field(default="opsMind", description="应用名称")
    app_version: str = Field(default="0.1.0", description="应用版本")
    host: str = Field(default="0.0.0.0", description="服务监听地址")
    port: int = Field(default=8000, description="服务端口")
    debug: bool = Field(default=False, description="调试模式")

    # LLM 配置
    llm_api_key: Optional[str] = Field(default=None, description="LLM API 密钥")
    llm_base_url: str = Field(default="https://api.openai.com/v1", description="LLM API 基础 URL")
    llm_model: str = Field(default="gpt-4o-mini", description="LLM 模型名称")
    llm_temperature: float = Field(default=0.2, description="LLM 生成温度")
    llm_timeout: int = Field(default=60, description="LLM 请求超时")

    # Docker 配置
    docker_host: str = Field(default="unix:///var/run/docker.sock", description="Docker 守护进程地址")

    # 数据源配置
    data_sources: str = Field(default="docker", description="启用的数据源列表（逗号分隔）")

    # 目录配置
    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent)
    data_dir: Optional[Path] = None
    log_dir: Optional[Path] = None

    @property
    def llm(self) -> Optional[LLMConfig]:
        """
        获取 LLM 配置

        Returns:
            LLMConfig 或 None（如果 API Key 未设置）
        """
        if not self.llm_api_key:
            return None
        return LLMConfig(
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            model=self.llm_model,
            temperature=self.llm_temperature,
            timeout=self.llm_timeout
        )

    @property
    def docker(self) -> DockerConfig:
        """
        获取 Docker 配置

        Returns:
            DockerConfig
        """
        return DockerConfig(host=self.docker_host)

    @property
    def enabled_data_sources(self) -> List[str]:
        """
        获取启用的数据源列表

        Returns:
            数据源列表
        """
        return [s.strip() for s in self.data_sources.split(",") if s.strip()]

    def validate(self) -> List[str]:
        """
        验证配置

        Returns:
            错误信息列表，空列表表示配置有效
        """
        errors = []

        # LLM API Key 验证
        if not self.llm_api_key:
            errors.append("LLM_API_KEY 环境变量未设置")

        # 端口范围验证
        if not (1 <= self.port <= 65535):
            errors.append(f"PORT 必须在 1-65535 范围内，当前值：{self.port}")

        # 温度值验证
        if not (0 <= self.llm_temperature <= 2):
            errors.append(f"LLM_TEMPERATURE 必须在 0-2 范围内，当前值：{self.llm_temperature}")

        return errors

    def ensure_directories(self) -> None:
        """
        确保必要的目录存在

        创建数据目录和日志目录。
        """
        self.data_dir = self.base_dir / "data"
        self.log_dir = self.base_dir / "logs"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load_from_env(cls) -> "RuntimeConfig":
        """
        从环境变量加载配置

        Returns:
            RuntimeConfig 实例
        """
        return cls()
