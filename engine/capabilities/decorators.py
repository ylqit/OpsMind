"""
装饰器模块

提供超时保护、重试保护、统一错误处理等装饰器。
"""
import asyncio
import functools
from typing import Any, Callable, TypeVar
from ..contracts import ActionResult

F = TypeVar('F', bound=Callable[..., Any])


def with_timeout(timeout_seconds: int = 30):
    """
    超时保护装饰器

    当函数执行时间超过指定秒数时，自动抛出超时异常并返回错误结果。

    Args:
        timeout_seconds: 超时秒数，默认 30 秒

    Returns:
        装饰后的函数

    使用示例:
        >>> @with_timeout(timeout_seconds=30)
        ... async def long_running_task():
        ...     # 长时间运行的任务
        ...     pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> ActionResult:
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                return ActionResult.fail(
                    f"执行超时（{timeout_seconds}秒）",
                    code="TIMEOUT"
                )
        return wrapper  # type: ignore
    return decorator


def with_retry(max_attempts: int = 3, delay_seconds: float = 1.0, backoff: float = 2.0):
    """
    重试保护装饰器

    当函数执行失败时，自动重试指定次数。

    Args:
        max_attempts: 最大重试次数，默认 3 次
        delay_seconds: 初始重试间隔（秒），默认 1 秒
        backoff: 重试间隔倍增系数，默认 2.0

    Returns:
        装饰后的函数

    使用示例:
        >>> @with_retry(max_attempts=3, delay_seconds=1.0)
        ... async def flaky_operation():
        ...     # 可能失败的操作
        ...     pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> ActionResult:
            last_error = None
            current_delay = delay_seconds

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff

            return ActionResult.fail(
                f"执行失败（已重试{max_attempts}次）: {str(last_error)}",
                code="MAX_RETRIES_EXCEEDED"
            )
        return wrapper  # type: ignore
    return decorator


def with_error_handling(default_error_code: str = "EXECUTION_ERROR"):
    """
    统一错误处理装饰器

    捕获并转换常见异常为 ActionResult 错误结果。

    Args:
        default_error_code: 默认错误代码

    Returns:
        装饰后的函数

    使用示例:
        >>> @with_error_handling("CONTAINER_ERROR")
        ... async def container_operation():
        ...     # 容器操作
        ...     pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> ActionResult:
            try:
                return await func(*args, **kwargs)
            except ValueError as e:
                return ActionResult.fail(
                    str(e),
                    code=f"INVALID_INPUT_{default_error_code}"
                )
            except PermissionError as e:
                return ActionResult.fail(
                    "权限不足，无法执行此操作",
                    code="PERMISSION_DENIED"
                )
            except FileNotFoundError as e:
                return ActionResult.fail(
                    f"资源不存在：{str(e)}",
                    code="RESOURCE_NOT_FOUND"
                )
            except KeyError as e:
                return ActionResult.fail(
                    f"缺少必需参数：{str(e)}",
                    code="MISSING_PARAMETER"
                )
            except Exception as e:
                # 记录日志（实际应用中应使用 logging）
                return ActionResult.fail(
                    f"执行异常：{str(e)}",
                    code=default_error_code
                )
        return wrapper  # type: ignore
    return decorator


def with_validation(input_schema: type):
    """
    输入验证装饰器

    在函数执行前验证输入参数是否符合指定模式。

    Args:
        input_schema: Pydantic BaseModel 子类

    Returns:
        装饰后的函数

    使用示例:
        >>> class MyInput(BaseModel):
        ...     name: str
        ...     value: int
        >>> @with_validation(MyInput)
        ... async def my_function(**kwargs):
        ...     # 参数已经过验证
        ...     pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> ActionResult:
            try:
                # 尝试使用输入 schema 验证
                validated = input_schema(**kwargs)
                # 将验证后的数据传递给原函数
                return await func(*args, validated_data=validated.model_dump())
            except ValueError as e:
                return ActionResult.fail(
                    f"参数验证失败：{str(e)}",
                    code="VALIDATION_ERROR"
                )
        return wrapper  # type: ignore
    return decorator
