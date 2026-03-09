"""
日志分析能力

提供日志文件读取、错误模式识别、日志聚类等能力。
"""
import os
import re
from typing import Dict, Any, Type, List, Optional
from pathlib import Path
from collections import Counter
from datetime import datetime
from pydantic import BaseModel, Field
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult


class LogAnalyzeInput(BaseModel):
    """
    日志分析输入参数

    Attributes:
        log_path: 日志文件路径
        lines: 读取行数
        pattern: 过滤模式（正则表达式）
        level: 日志级别过滤（ERROR, WARN, INFO, DEBUG）
    """
    log_path: str = Field(..., description="日志文件路径", min_length=1)
    lines: int = Field(default=1000, description="读取行数", ge=1, le=10000)
    pattern: Optional[str] = Field(default=None, description="过滤模式（正则表达式）")
    level: Optional[str] = Field(default=None, description="日志级别过滤", pattern="^(ERROR|WARN|WARNING|INFO|DEBUG)$")


class LogPatternInput(BaseModel):
    """
    日志目录扫描输入参数

    Attributes:
        log_dir: 日志目录路径
        file_pattern: 文件模式（如 *.log）
    """
    log_dir: str = Field(..., description="日志目录路径")
    file_pattern: str = Field(default="*.log", description="文件模式")


class LogAnalyzer(BaseCapability):
    """
    日志分析器

    提供日志文件读取、错误模式识别、日志聚类等能力。

    使用示例:
        >>> analyzer = LogAnalyzer()
        >>> result = await analyzer.dispatch(
        ...     log_path="/var/log/app.log",
        ...     level="ERROR"
        ... )
    """

    # 常见错误模式
    ERROR_PATTERNS = {
        "exception": r"(?i)(exception|error|traceback|stacktrace)",
        "timeout": r"(?i)(timeout|timed out|connection timed out)",
        "memory": r"(?i)(out of memory|oom|memory error|heap space)",
        "connection": r"(?i)(connection refused|connection reset|connection failed)",
        "permission": r"(?i)(permission denied|access denied|unauthorized)",
        "null_pointer": r"(?i)(nullpointer|null pointer|none type)",
        "file_not_found": r"(?i)(file not found|no such file|does not exist)"
    }

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="analyze_logs",
            description="分析日志文件，识别错误模式和异常",
            version="1.0.0",
            tags=["log", "analyze", "debug"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return LogAnalyzeInput

    @with_timeout(timeout_seconds=60)
    @with_error_handling("LOG_ANALYZE_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        执行日志分析

        Args:
            log_path: 日志文件路径
            lines: 读取行数
            pattern: 过滤模式
            level: 日志级别

        Returns:
            ActionResult: 分析结果
        """
        try:
            input_data = LogAnalyzeInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        # 检查文件是否存在
        log_file = Path(input_data.log_path)
        if not log_file.exists():
            return ActionResult.fail(
                f"日志文件不存在：{input_data.log_path}",
                code="FILE_NOT_FOUND"
            )

        # 读取日志
        logs = self._read_logs(log_file, input_data.lines)

        # 过滤日志
        if input_data.level:
            logs = self._filter_by_level(logs, input_data.level)
        if input_data.pattern:
            logs = self._filter_by_pattern(logs, input_data.pattern)

        # 分析错误模式
        error_analysis = self._analyze_errors(logs)

        # 统计信息
        stats = self._compute_stats(logs)

        return ActionResult.ok({
            "log_file": str(log_file),
            "total_lines": len(logs),
            "stats": stats,
            "error_analysis": error_analysis,
            "sample_logs": logs[:50]  # 返回前 50 行作为样本
        })

    def _read_logs(self, file_path: Path, max_lines: int) -> List[str]:
        """
        读取日志文件

        Args:
            file_path: 文件路径
            max_lines: 最大行数

        Returns:
            日志行列表
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    lines.append(line.strip())
                return lines
        except Exception as e:
            return []

    def _filter_by_level(self, logs: List[str], level: str) -> List[str]:
        """
        按日志级别过滤

        Args:
            logs: 日志列表
            level: 日志级别

        Returns:
            过滤后的日志
        """
        level_upper = level.upper()
        if level_upper == "WARNING":
            level_upper = "WARN"

        return [log for log in logs if level_upper in log.upper()]

    def _filter_by_pattern(self, logs: List[str], pattern: str) -> List[str]:
        """
        按正则表达式过滤

        Args:
            logs: 日志列表
            pattern: 正则表达式

        Returns:
            过滤后的日志
        """
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            return [log for log in logs if regex.search(log)]
        except re.error:
            return logs

    def _analyze_errors(self, logs: List[str]) -> Dict[str, Any]:
        """
        分析错误模式

        Args:
            logs: 日志列表

        Returns:
            错误分析结果
        """
        errors = []
        error_counts = Counter()

        for log in logs:
            for error_type, pattern in self.ERROR_PATTERNS.items():
                if re.search(pattern, log, re.IGNORECASE):
                    error_counts[error_type] += 1
                    errors.append({
                        "log": log[:200],  # 限制长度
                        "type": error_type
                    })

        return {
            "total_errors": len(errors),
            "error_types": dict(error_counts),
            "top_errors": error_counts.most_common(5),
            "sample_errors": errors[:20]  # 返回前 20 个错误样本
        }

    def _compute_stats(self, logs: List[str]) -> Dict[str, Any]:
        """
        计算统计信息

        Args:
            logs: 日志列表

        Returns:
            统计信息
        """
        level_counts = Counter()
        for level in ["ERROR", "WARN", "INFO", "DEBUG"]:
            count = sum(1 for log in logs if level in log.upper())
            if count > 0:
                level_counts[level] = count

        return {
            "total_lines": len(logs),
            "level_distribution": dict(level_counts),
            "error_rate": level_counts.get("ERROR", 0) / len(logs) * 100 if logs else 0
        }


class ScanLogDirectory(BaseCapability):
    """
    日志目录扫描器

    扫描目录中的所有日志文件并提供概览。

    使用示例:
        >>> scanner = ScanLogDirectory()
        >>> result = await scanner.dispatch(
        ...     log_dir="/var/log",
        ...     file_pattern="*.log"
        ... )
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="scan_log_directory",
            description="扫描日志目录，列出所有日志文件及其大小",
            version="1.0.0",
            tags=["log", "scan", "directory"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return LogPatternInput

    @with_timeout(timeout_seconds=30)
    @with_error_handling("SCAN_LOG_DIRECTORY_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        扫描日志目录

        Args:
            log_dir: 日志目录路径
            file_pattern: 文件模式

        Returns:
            ActionResult: 扫描结果
        """
        try:
            input_data = LogPatternInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        log_dir = Path(input_data.log_dir)
        if not log_dir.exists() or not log_dir.is_dir():
            return ActionResult.fail(
                f"目录不存在：{input_data.log_dir}",
                code="DIRECTORY_NOT_FOUND"
            )

        # 扫描日志文件
        log_files = []
        for pattern in [input_data.file_pattern, "*.txt", "*.out"]:
            for log_file in log_dir.glob(pattern):
                try:
                    size = log_file.stat().st_size
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    log_files.append({
                        "path": str(log_file),
                        "name": log_file.name,
                        "size_bytes": size,
                        "size_mb": round(size / 1024 / 1024, 2),
                        "modified": mtime.isoformat()
                    })
                except (PermissionError, OSError):
                    continue

        # 按大小排序
        log_files.sort(key=lambda x: x["size_bytes"], reverse=True)

        return ActionResult.ok({
            "directory": str(log_dir),
            "total_files": len(log_files),
            "files": log_files[:100]  # 返回前 100 个文件
        })
