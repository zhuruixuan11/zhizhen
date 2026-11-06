"""实时通知端点：医生端订阅新病例，Redis pub/sub 驱动。"""
import asyncio
import json
import logging
import time
from typing import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.redis_client import get_async_redis
from app.models.entities import User
from app.api.deps import get_current_user
from app.services import notification_service

logger = logging.getLogger("app.notify-api")
router = APIRouter(prefix="/notify", tags=["notification"])

_PING_INTERVAL = 25  # 秒


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/stream")
async def subscribe_notifications(
    last_event_id: str = Header(default="0", alias="Last-Event-ID"),
    user: User = Depends(get_current_user),
):
    """SSE 订阅：医生/管理员实时收新病例通知。

    权限：ROLE_DOCTOR 或 ROLE_ADMIN 才能订阅。
    """
    if user.role not in ("doctor", "admin"):
        raise HTTPException(status_code=403, detail="仅医生和管理员可订阅通知")

    channel = notification_service.CHANNEL_CASE_NEW

    async def _stream():
        async_redis = get_async_redis()
        try:
            pubsub = async_redis.pubsub()
            await pubsub.subscribe(channel)
            yield _sse("connected", {"message": "订阅成功", "channel": channel})

            last_ping = time.time()
            while True:
                try:
                    msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=30)
                except asyncio.TimeoutError:
                    msg = None

                if msg:
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"event: message\ndata: {data}\n\n"
                    last_ping = time.time()

                # 心跳 ping，保持连接活跃
                if time.time() - last_ping > _PING_INTERVAL:
                    yield ": ping\n\n"
                    last_ping = time.time()
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            # Redis 不可达时连接超时已被压到 2 秒，这里给出明确事件再断开，避免前端一直空白
            logger.warning("notify.subscribe_failed error=%s", type(e).__name__)
            yield f"event: error\ndata: {{\"message\": \"通知服务暂不可用\"}}\n\n"
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:  # noqa: BLE001
                pass

    return StreamingResponse(_stream(), media_type="text/event-stream")
