"""医生端/管理员端实时通知：Redis pub/sub + 内存缓冲降级。

频道命名：
- 新病例：notify:case:new         患者提交辨证报告草稿后发给医生
- 报告确认：notify:report:confirm  医生审核确认后发给患者（预留）

所有 payload 均为纯 JSON，订阅方直接解析即可。
"""
import json
import logging
import time
from datetime import datetime
from typing import Optional

from app.core.redis_client import get_redis

logger = logging.getLogger("app.notify")

CHANNEL_CASE_NEW = "notify:case:new"
CHANNEL_REPORT_CONFIRM = "notify:report:confirm"


def publish_case_new(analysis_id: int, session_id: int, user_id: int, syndrome: Optional[str]) -> None:
    """患者提交辨证报告草稿 → 通知所有医生/管理员。

    try/except 降级：Redis 挂了不影响主业务，日志记录即可。
    """
    payload = {
        "type": "case_new",
        "analysis_id": analysis_id,
        "session_id": session_id,
        "patient_user_id": user_id,
        "syndrome": syndrome,
        "ts": int(time.time()),
        "ts_iso": datetime.now().isoformat(),
    }
    try:
        get_redis().publish(CHANNEL_CASE_NEW, json.dumps(payload, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        logger.warning("notify.publish_case_new failed: %s", e)


def publish_report_confirmed(analysis_id: int, session_id: int, patient_user_id: int) -> None:
    """医生审核确认报告 → 通知对应患者（预留）。"""
    payload = {
        "type": "report_confirmed",
        "analysis_id": analysis_id,
        "session_id": session_id,
        "patient_user_id": patient_user_id,
        "ts": int(time.time()),
    }
    try:
        get_redis().publish(CHANNEL_REPORT_CONFIRM, json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        logger.warning("notify.publish_report_confirmed failed: %s", e)
