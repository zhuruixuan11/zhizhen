"""Celery 应用（Redis broker + result backend）。"""
import logging
import sys
import time

from celery import Celery

from app.core.config import settings

logger = logging.getLogger("app.celery")

# 测试环境无 Redis：改用内存 broker，避免 .delay() 触发 20 次连接重试把用例拖慢到分钟级
_TESTING = "unittest" in sys.modules or "pytest" in sys.modules

celery_app = Celery(
    "tcm",
    broker="memory://" if _TESTING else settings.celery_broker_url,
    backend="cache+memory://" if _TESTING else settings.celery_result_backend,
    include=["app.tasks.jobs"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=86400,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    # ── 生产者侧快速失败 ──
    # Redis 不可达时 kombu 默认会长时间重试，把 HTTP 请求线程卡住 20~30 秒。
    # 这里把连接/读写超时压到 2 秒，并限制发布重试次数。
    broker_connection_timeout=2,
    broker_connection_max_retries=1,
    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    },
    broker_transport_options={
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "retry_on_timeout": False,
        "max_connections": 20,
    },
)


#: Redis 探测失败后的冷却截止时间（monotonic），避免每个请求都白等一次连接超时
_broker_down_until = 0.0
_BROKER_DOWN_COOLDOWN = 30.0


def _broker_reachable() -> bool:
    """用 2 秒超时的 redis 客户端探测 broker 是否可达。

    kombu 在发布时内部仍会做长时间连接重试（实测约 70 秒），仅靠
    broker_transport_options 无法约束。这里先做一次快速探测，
    不可达就直接放弃投递，把最坏耗时压到 2 秒；失败结果缓存 30 秒。
    """
    global _broker_down_until
    now = time.monotonic()
    if now < _broker_down_until:
        return False
    from app.core.redis_client import get_redis
    try:
        get_redis().ping()
        return True
    except Exception as e:  # noqa: BLE001
        _broker_down_until = now + _BROKER_DOWN_COOLDOWN
        logger.warning("broker_unreachable error=%s", type(e).__name__)
        return False


def dispatch(task, *args, **kwargs) -> bool:
    """投递异步任务，Redis 不可用时不阻塞请求。

    测试环境（内存 broker）直接投递；生产环境先做 2 秒探测，
    不可达则立即返回 False，由调用方降级（503 / 静默跳过）。
    """
    if not _TESTING and not _broker_reachable():
        logger.warning("task_dispatch_skipped task=%s", getattr(task, "name", task))
        return False
    try:
        task.apply_async(args=args, kwargs=kwargs, retry=False)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "task_dispatch_failed task=%s error=%s",
            getattr(task, "name", task), type(e).__name__,
        )
        return False

# Producer instrumentation propagates W3C context into broker messages.
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from celery.signals import worker_process_init, worker_process_shutdown
CeleryInstrumentor().instrument()


@worker_process_init.connect
def init_worker_telemetry(**kwargs):
    from app.core.logging import setup_logging
    from app.core.tracing import init_tracing
    setup_logging()
    init_tracing("tcm-worker")


@worker_process_shutdown.connect
def stop_worker_telemetry(**kwargs):
    from app.core.tracing import shutdown_tracing
    shutdown_tracing()


celery_app.conf.beat_schedule = {
    "expire-agent-memory": {"task": "tasks.expire_memory", "schedule": 3600.0},
    "close-stale-sessions": {"task": "tasks.close_stale_sessions", "schedule": 1800.0},  # 每 30 分钟
}
