"""
运行时配置模块。

统一管理服务启动所需的环境变量和目录设置。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """LLM 配置。"""

    api_key: str = Field(..., description="API 密钥")
    base_url: str = Field(default="https://api.openai.com/v1", description="API 基础地址")
    model: str = Field(default="gpt-4o-mini", description="模型名称")
    temperature: float = Field(default=0.2, ge=0, le=2, description="生成温度")
    timeout: int = Field(default=60, ge=10, description="请求超时时间")


class DockerConfig(BaseModel):
    """Docker 配置。"""

    host: str = Field(default="unix:///var/run/docker.sock", description="Docker 守护进程地址")


class RuntimeConfig(BaseSettings):
    """运行时配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="opsMind", description="应用名称")
    app_version: str = Field(default="0.1.0", description="应用版本")
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8000, description="监听端口")
    debug: bool = Field(default=False, description="调试模式")

    llm_api_key: Optional[str] = Field(default=None, description="LLM API 密钥")
    llm_base_url: str = Field(default="https://api.openai.com/v1", description="LLM API 地址")
    llm_model: str = Field(default="gpt-4o-mini", description="LLM 模型名称")
    llm_temperature: float = Field(default=0.2, description="LLM 生成温度")
    llm_timeout: int = Field(default=60, description="LLM 请求超时")

    docker_host: str = Field(default="unix:///var/run/docker.sock", description="Docker 守护进程地址")
    prometheus_url: Optional[str] = Field(default=None, description="Prometheus 地址")
    prometheus_api_key: Optional[str] = Field(default=None, description="Prometheus 鉴权信息")
    data_sources: str = Field(default="docker", description="启用的数据源列表，使用逗号分隔")
    access_log_paths: str = Field(default="", description="访问日志文件列表，使用逗号分隔")
    sqlite_path: Optional[Path] = Field(default=None, description="SQLite 文件路径")

    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent)
    config_dir: Optional[Path] = None
    data_dir: Optional[Path] = None
    log_dir: Optional[Path] = None
    raw_log_dir: Optional[Path] = None
    tasks_dir: Optional[Path] = None

    @property
    def llm(self) -> Optional[LLMConfig]:
        """返回 LLM 配置对象。"""
        if not self.llm_api_key:
            return None
        return LLMConfig(
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            model=self.llm_model,
            temperature=self.llm_temperature,
            timeout=self.llm_timeout,
        )

    @property
    def docker(self) -> DockerConfig:
        """返回 Docker 配置对象。"""
        return DockerConfig(host=self.docker_host)

    @property
    def enabled_data_sources(self) -> List[str]:
        """返回启用的数据源列表。"""
        return [item.strip() for item in self.data_sources.split(",") if item.strip()]

    @property
    def access_log_path_list(self) -> List[str]:
        """返回访问日志路径列表。"""
        return [item.strip() for item in self.access_log_paths.split(",") if item.strip()]

    def validate(self) -> List[str]:
        """校验关键配置。"""
        errors: List[str] = []
        if not (1 <= self.port <= 65535):
            errors.append(f"PORT 必须在 1-65535 范围内，当前值：{self.port}")
        if not (0 <= self.llm_temperature <= 2):
            errors.append(f"LLM_TEMPERATURE 必须在 0-2 范围内，当前值：{self.llm_temperature}")
        return errors

    def ensure_directories(self) -> None:
        """确保运行所需目录存在。"""
        self.config_dir = self.base_dir / "config"
        self.data_dir = self.base_dir / "data"
        self.log_dir = self.base_dir / "logs"
        self.raw_log_dir = self.data_dir / "raw_logs"
        self.tasks_dir = self.data_dir / "tasks"
        if self.sqlite_path is None:
            self.sqlite_path = self.data_dir / "opsmind.db"

        for path in [self.config_dir, self.data_dir, self.log_dir, self.raw_log_dir, self.tasks_dir, self.sqlite_path.parent]:
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load_from_env(cls) -> "RuntimeConfig":
        """从环境变量加载配置。"""
        return cls()
