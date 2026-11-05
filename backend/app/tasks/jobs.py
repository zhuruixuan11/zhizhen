"""Celery 异步任务：图片识别、图谱导入、向量重建、批量导出（幂等、可观测）。"""
import json
import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.entities import AsyncJob, TcmImage
from app.services import image_analysis_service
from app.tasks.celery_app import celery_app

logger = logging.getLogger("app.tasks")


def _set_job(job_id: str, status: str, progress: int, result=None, error=None) -> None:
    db = SessionLocal()
    try:
        job = db.get(AsyncJob, job_id)
        if job:
            job.status = status
            job.progress = progress
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            if status in ("success", "failed"):
                job.finish_time = datetime.now()
            db.commit()
    finally:
        db.close()


@celery_app.task(bind=True, name="tasks.analyze_image", max_retries=2)
def analyze_image_task(self, job_id: str, image_id: int, image_path: str, image_type: str, session_id: int) -> dict:
    _set_job(job_id, "running", 20)
    db = SessionLocal()
    try:
        result = image_analysis_service.analyze(image_path, image_type)
        img = db.get(TcmImage, image_id)
        if img:
            img.analysis_result = result
            img.quality_pass = True
            db.commit()
        _set_job(job_id, "success", 100, result=result)
        return {"image_id": image_id, "result": result}
    except Exception as e:  # noqa: BLE001
        logger.error("analyze_image failed job=%s err=%s", job_id, e)
        _set_job(job_id, "failed", 100, error=str(e))
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="tasks.graph_import", max_retries=1)
def graph_import_task(self, job_id: str) -> dict:
    _set_job(job_id, "running", 30)
    try:
        from app.scripts.init_knowledge import run_all

        result = run_all()
        _set_job(job_id, "success", 100, result=result)
        return result
    except Exception as e:  # noqa: BLE001
        logger.error("graph_import failed job=%s err=%s", job_id, e)
        _set_job(job_id, "failed", 100, error=str(e))
        raise


@celery_app.task(bind=True, name="tasks.vector_rebuild", max_retries=1)
def vector_rebuild_task(self, job_id: str) -> dict:
    _set_job(job_id, "running", 30)
    try:
        from app.scripts.init_knowledge import build_vectors

        count = build_vectors()
        _set_job(job_id, "success", 100, result={"vectors": count})
        return {"vectors": count}
    except Exception as e:  # noqa: BLE001
        logger.error("vector_rebuild failed job=%s err=%s", job_id, e)
        _set_job(job_id, "failed", 100, error=str(e))
        raise


@celery_app.task(bind=True, name="tasks.export_data", max_retries=1)
def export_task(self, job_id: str, user_id: int) -> dict:
    """导出用户个人数据（数据导出权），结果落 async_job.result。"""
    _set_job(job_id, "running", 30)
    db = SessionLocal()
    try:
        from app.models.entities import ConsultationSession, SyndromeAnalysis
        from app.core.security import decrypt_plaintext

        sessions = (
            db.query(ConsultationSession)
            .filter(ConsultationSession.user_id == user_id)
            .order_by(ConsultationSession.start_time.asc())
            .all()
        )
        data = {
            "user_id": user_id,
            "sessions": [],
        }
        for s in sessions:
            analysis = (
                db.query(SyndromeAnalysis)
                .filter(SyndromeAnalysis.session_id == s.session_id)
                .first()
            )
            data["sessions"].append({
                "session_id": s.session_id,
                "complaint": decrypt_plaintext(s.complaint) or s.complaint,
                "risk_level": s.risk_level,
                "status": s.status,
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "analysis": {
                    "syndrome": analysis.syndrome,
                    "evidence": analysis.evidence,
                    "treatment_principle": analysis.treatment_principle,
                    "formula_suggestions": analysis.formula_suggestions,
                } if analysis else None,
            })
        _set_job(job_id, "success", 100, result={"type": "export", "data": data, "format": "json"})
        return {"exported_sessions": len(data["sessions"])}
    except Exception as e:  # noqa: BLE001
        logger.error("export failed job=%s err=%s", job_id, e)
        _set_job(job_id, "failed", 100, error=str(e))
        raise
    finally:
        db.close()

@celery_app.task(name="tasks.expire_memory")
def expire_memory():
    from sqlalchemy import text
    from app.core.memory import memory_engine
    # Bounded batches avoid long locks; expired rows are already invisible to reads.
    with memory_engine().begin() as conn:
        result = conn.execute(text("""DELETE FROM agent_memory WHERE ctid IN
            (SELECT ctid FROM agent_memory WHERE expires_at <= CURRENT_TIMESTAMP
             LIMIT 10000 FOR UPDATE SKIP LOCKED)"""))
        return {"deleted": result.rowcount}


@celery_app.task(name="tasks.close_stale_sessions")
def close_stale_sessions():
    """将超过 24h 无消息的 ongoing 会话标记为 aborted，释放 session_lock 可能残留的占用。

    幂等：只更新 status='ongoing' 且最后一条消息距今超过 threshold 的行。
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func, update
    from app.core.database import SessionLocal
    from app.models.entities import ConsultationRecord, ConsultationSession

    db = SessionLocal()
    threshold = datetime.now() - timedelta(hours=24)
    try:
        subq = (
            db.query(func.max(ConsultationRecord.create_time))
            .filter(ConsultationRecord.session_id == ConsultationSession.session_id)
            .correlate(ConsultationSession)
            .scalar_subquery()
        )
        stmt = (
            update(ConsultationSession)
            .where(ConsultationSession.status == "ongoing")
            .where(func.coalesce(subq, ConsultationSession.start_time) < threshold)
            .values(status="aborted", end_time=datetime.now())
            .execution_options(synchronize_session=False)
        )
        result = db.execute(stmt)
        db.commit()
        logger.info("close_stale_sessions aborted=%s", result.rowcount)
        return {"aborted": result.rowcount}
    finally:
        db.close()


@celery_app.task(name="tasks.rebuild_user_profile")
def rebuild_user_profile(user_id: int):
    """异步重算用户画像：扫全部历史辨证报告，生成常见证型、高频症状趋势。

    每完成一次问诊后被触发，结果写入 user_profile_summary 字段供下一次问诊参考。
    仅基于统计，不调 LLM。
    """
    from collections import Counter
    from datetime import datetime
    from app.core.database import SessionLocal
    from app.models.entities import SyndromeAnalysis, User

    db = SessionLocal()
    try:
        analyses = (
            db.query(SyndromeAnalysis)
            .join(ConsultationSession := __import__("app.models.entities", fromlist=["ConsultationSession"]).ConsultationSession,
                  SyndromeAnalysis.session_id == ConsultationSession.session_id)
            .filter(ConsultationSession.user_id == user_id)
            .order_by(SyndromeAnalysis.analysis_id.asc())
            .all()
        )
        if len(analyses) < 1:
            return {"user_id": user_id, "profiles": 0, "skipped": True}

        syndromes = [a.syndrome for a in analyses if a.syndrome]
        symptom_counts: Counter = Counter()
        for a in analyses:
            for e in (a.evidence or []):
                desc = e.get("description", "") if isinstance(e, dict) else ""
                symptom_counts[desc[:12]] += 1
            for slot in (a.model_extra or {}).values() if hasattr(a, "model_extra") else []:
                pass

        summary = {
            "rebuilt_at": datetime.now().isoformat(),
            "total_reports": len(analyses),
            "top_syndromes": Counter(syndromes).most_common(5),
            "seasonal_pattern": _seasonal_analysis(analyses),
        }

        from app.core.memory import MemoryStore
        memory = MemoryStore(0, user_id)
        memory.write("long", "profile_summary", "summary", summary)

        logger.info("rebuild_user_profile user_id=%s reports=%d", user_id, len(analyses))
        return {"user_id": user_id, "profiles": len(analyses), "summary": summary}
    finally:
        db.close()


def _seasonal_analysis(analyses: list) -> dict:
    """按月份聚合，看用户症状/证型是否有季节性。"""
    from collections import defaultdict
    by_month: dict[str, list[str]] = defaultdict(list)
    for a in analyses:
        if a.create_time:
            key = a.create_time.strftime("%Y-%m")
            by_month[key].append(a.syndrome or "unknown")
    monthly = {k: {"count": len(v), "top": __import__("collections", fromlist=["Counter"]).Counter(v).most_common(3)}
               for k, v in sorted(by_month.items())}
    return monthly
