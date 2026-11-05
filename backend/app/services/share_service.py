"""报告分享链接服务：HMAC 签名 URL + 时效控制。

安全设计：
- 用 JWT_SECRET_KEY（已有强密钥）作为 HMAC key
- token 内包含 analysis_id + 过期时间戳 + HMAC 签名
- 验证时重新计算 HMAC 对比，防篡改
"""
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import SyndromeAnalysis, ReportReview
from app.services.consultation_service import analysis_to_report


DEFAULT_TTL_HOURS = 24 * 7  # 7 天


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (4 - len(s) % 4) if len(s) % 4 else ""
    return base64.urlsafe_b64decode((s + padding).encode("ascii"))


def _sign(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(settings.jwt_secret_key.encode(), body, hashlib.sha256).digest()
    return _b64url_encode(mac)


def create_share_token(
    analysis_id: int,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> str:
    """生成带时效的分享 token。"""
    exp = int(time.time()) + ttl_hours * 3600
    payload = {"a": analysis_id, "e": exp}
    sig = _sign(payload)
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{sig}"


def parse_share_token(token: str) -> Optional[int]:
    """验证 token 签名与时效，返回 analysis_id；无效返回 None。"""
    try:
        body_b64, sig = token.rsplit(".", 1)
        payload = json.loads(_b64url_decode(body_b64))
        if payload["e"] < int(time.time()):
            return None
        expected = _sign({"a": payload["a"], "e": payload["e"]})
        if not hmac.compare_digest(expected, sig):
            return None
        return int(payload["a"])
    except Exception:
        return None


def resolve_shared_report(db: Session, analysis_id: int) -> Optional[dict]:
    """查 analysis 并返回可直接给未登录用户看的只读报告 payload。"""
    analysis = db.get(SyndromeAnalysis, analysis_id)
    if not analysis:
        return None
    review = db.get(ReportReview, analysis_id)
    report = analysis_to_report(analysis)
    return {
        "analysis_id": analysis_id,
        "syndrome": report["syndrome"],
        "report": report,
        "review_status": review.status if review else "pending",
        "confidence": analysis.confidence,
        "risk_level": analysis.risk_level,
        "create_time": analysis.create_time.isoformat() if analysis.create_time else None,
        "disclaimer": analysis.disclaimer or "本报告由 AI 辅助生成，仅供参考，不能替代专业医师诊断。",
    }


def describe_token(token: str) -> Optional[dict]:
    """仅用于 owner 查看 token 剩余时长，不需要查 DB。"""
    try:
        body_b64, _ = token.rsplit(".", 1)
        payload = json.loads(_b64url_decode(body_b64))
        exp = payload["e"]
        now = int(time.time())
        return {
            "analysis_id": int(payload["a"]),
            "expires_at": datetime.fromtimestamp(exp).isoformat(),
            "remaining_seconds": max(0, exp - now),
            "expired": exp < now,
        }
    except Exception:
        return None
