"""聚合 API 路由。"""
from fastapi import APIRouter

from .ai import router as ai_router
from .dashboard import report_router, router as dashboard_router
from .executors import router as executors_router
from .incidents import router as incidents_router
from .llm import router as llm_router
from .metrics import router as metrics_router
from .recommendations import router as recommendations_router
from .resources import router as resources_router
from .tasks import router as tasks_router
from .traffic import router as traffic_router

router = APIRouter()
router.include_router(dashboard_router)
router.include_router(report_router)
router.include_router(ai_router)
router.include_router(llm_router)
router.include_router(traffic_router)
router.include_router(resources_router)
router.include_router(incidents_router)
router.include_router(recommendations_router)
router.include_router(tasks_router)
router.include_router(metrics_router)
router.include_router(executors_router)
