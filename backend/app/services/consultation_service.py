"""问诊服务：会话创建、消息历史、SSE 对话流（追问/辨证/论治 + 急危重症短路）。"""
import json
import logging
from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy.orm import Session

from app.core import llm
from app.core.config import settings
from app.core.logging import session_id_var
from app.core.memory import MemoryStore, session_lock, SessionBusy
from app.core.graph import BoundedToolExecutor
from app.models.entities import (
    ConsultationRecord,
    ConsultationSession,
    SyndromeAnalysis,
    TcmImage,
    ReportReview,
)
from app.schemas.schemas import SyndromeReport
from app.services.inquiry_choices import build_choices
from app.services import knowledge_service, prompt_service, safety_service, syndrome_service

logger = logging.getLogger("app.consultation")

# 触发"生成报告"意图的关键词——去掉"分析"这类宽泛词，避免正常追问被误触发
_REPORT_KEYWORDS = [
    "生成报告", "出报告", "给我结果", "出结果",
    "诊断一下", "看看结果", "辨证结果", "要报告",
]


def create_session(db: Session, user_id: int, complaint: Optional[str], trace_id: str, tenant_id: int = 0) -> ConsultationSession:
    session = ConsultationSession(
        tenant_id=tenant_id, user_id=user_id, complaint=complaint, status="ongoing", trace_id=trace_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: int, user_id: int) -> Optional[ConsultationSession]:
    s = db.get(ConsultationSession, session_id)
    if not s or s.user_id != user_id:
        return None
    return s


def list_sessions(db: Session, user_id: int) -> list[ConsultationSession]:
    return (
        db.query(ConsultationSession)
        .filter(ConsultationSession.user_id == user_id)
        .order_by(ConsultationSession.start_time.desc())
        .limit(100)
        .all()
    )


def list_messages(db: Session, session_id: int) -> list[ConsultationRecord]:
    return (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.session_id == session_id)
        .order_by(ConsultationRecord.create_time.asc())
        .all()
    )


def get_latest_analysis(db: Session, session_id: int) -> Optional[SyndromeAnalysis]:
    return (
        db.query(SyndromeAnalysis)
        .filter(SyndromeAnalysis.session_id == session_id)
        .order_by(SyndromeAnalysis.analysis_id.desc())
        .first()
    )


def analysis_to_report(analysis: SyndromeAnalysis) -> dict:
    return SyndromeReport(
        syndrome=analysis.syndrome,
        confidence=analysis.confidence,
        evidence=analysis.evidence or [],
        differential=analysis.differential or [],
        treatment_principle=analysis.treatment_principle,
        formula_suggestions=analysis.formula_suggestions or [],
        diet_advice=analysis.diet_advice or [],
        acupoint_advice=analysis.acupoint_advice or [],
        lifestyle_advice=analysis.lifestyle_advice or [],
        risk_level=analysis.risk_level or "low",
        emergency_flag=analysis.emergency_flag,
        disclaimer=analysis.disclaimer or "",
        graph_refs=analysis.graph_refs or [],
    ).model_dump()


# ── 内部工具 ──────────────────────────────────────────────────

def _add_record(db: Session, session_id: int, role: str, type_: str, content: str, meta: Optional[dict] = None) -> None:
    db.add(ConsultationRecord(session_id=session_id, role=role, type=type_, content=content, meta=meta))
    db.commit()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                pass
    return {}


def _get_recognitions(db: Session, session_id: int) -> list[dict]:
    images = (db.query(TcmImage)
              .filter(TcmImage.session_id == session_id, TcmImage.quality_pass == 1)
              .order_by(TcmImage.image_id.desc()).all())
    out, seen = [], set()
    for img in images:
        if isinstance(img.analysis_result, dict) and img.analysis_result and img.image_type not in seen:
            out.append({**img.analysis_result, "image_type": img.image_type})
            seen.add(img.image_type)
    return out


def _extract_symptoms_via_graph(message: str) -> list[str]:
    try:
        return knowledge_service.symptom_names_contained(message)
    except Exception:  # noqa: BLE001
        return []


def _build_runtime(session: ConsultationSession) -> BoundedToolExecutor:
    memory = MemoryStore(session.tenant_id, session.user_id)
    return BoundedToolExecutor("inquiry").bind(
        load_memory=memory.read,
        save_memory=memory.write,
        extract_symptoms=_extract_symptoms_via_graph,
        ask=llm.stream_text,
    )


def _fallback_inquiry(message: str, slots: dict, new_slots: dict, runtime: BoundedToolExecutor) -> str:
    """无 LLM 时的规则追问降级，并做图谱症状实体抽取。"""
    for sym in runtime.call("extract_symptoms", message):
        new_slots["symptoms"] = sorted(set(new_slots.get("symptoms", [])) | {sym})
    if "complaint" not in slots:
        new_slots["complaint"] = message[:50]
        return "已记录您的主诉。请继续描述：怕冷还是怕热？"
    if "cold_hot" not in slots:
        new_slots["cold_hot"] = message[:50]
        return "已记录您的补充，正在根据现有信息整理报告草稿，供医生审核。"
    return "感谢补充，信息已基本收集，正在为您生成辨证分析结果…"


# ── 短路分支：护栏 / 已有报告 ──────────────────────────────────

def _handle_emergency(db: Session, session: ConsultationSession) -> Iterator[str]:
    session.risk_level = "emergency"
    session.status = "completed"
    session.end_time = datetime.now()
    db.commit()
    guidance = safety_service.emergency_guidance()
    _add_record(db, session.session_id, "assistant", "text", guidance)
    yield _sse("phase", {"phase": "emergency"})
    yield _sse("chunk", {"text": guidance})
    yield _sse("disclaimer", {"text": prompt_service.get_disclaimer(db)})
    yield _sse("done", {"session_id": session.session_id})


def _handle_block(db: Session, session: ConsultationSession) -> Iterator[str]:
    guidance = "请围绕中医健康咨询与养生保健展开，我无法提供用药处方或诊疗建议。"
    _add_record(db, session.session_id, "assistant", "text", guidance)
    yield _sse("phase", {"phase": "inquiry"})
    yield _sse("chunk", {"text": guidance})
    yield _sse("done", {"session_id": session.session_id})


def _try_return_existing_report(db: Session, session: ConsultationSession) -> Optional[Iterator[str]]:
    """force_report 时如已有辨证分析则直接返回，不重跑辨证。"""
    existing = get_latest_analysis(db, session.session_id)
    if not existing:
        return None

    from app.services.report_review_service import patient_result
    payload = patient_result(db, existing)
    kind = "result" if payload["review_status"] == "confirmed" else "review_pending"

    def _stream():
        yield _sse(kind, payload)
        yield _sse("done", {"session_id": session.session_id})

    return _stream()


# ── 上下文加载 ────────────────────────────────────────────────

def _load_slots_from_records(db: Session, session_id: int) -> dict:
    """短期记忆过期时，从历史 assistant 记录的 meta.slots 恢复问诊快照。"""
    records = (db.query(ConsultationRecord)
               .filter(ConsultationRecord.session_id == session_id)
               .order_by(ConsultationRecord.record_id.desc()).limit(100).all())
    for record in records:
        if record.role == "assistant" and isinstance(record.meta, dict):
            snapshot = record.meta.get("slots")
            if isinstance(snapshot, dict) and snapshot:
                return dict(snapshot)
    return {}


# ── Inquiry 追问 ────────────────────────────────────────────────


def _parse_inquiry_response(raw: str, slots: dict) -> tuple[str, dict, bool]:
    """解析 LLM 完整输出 → (reply, new_slots, ready)。校验 schema，失败抛 ValueError。"""
    data = _parse_json(raw)
    if not isinstance(data, dict):
        raise ValueError("invalid inquiry response")
    extracted = data.get("slots", {})
    if (
        not isinstance(data.get("reply"), str)
        or not isinstance(data.get("ready", False), bool)
        or not isinstance(extracted, dict)
    ):
        raise ValueError("invalid inquiry response")
    if "symptoms" in extracted and (
        not isinstance(extracted["symptoms"], list)
        or any(not isinstance(x, str) for x in extracted["symptoms"])
    ):
        raise ValueError("invalid symptom list")
    reply = data.get("reply", "感谢您的补充，请继续描述您的其它不适。")
    ready = bool(data.get("ready", False))
    new_slots = {**slots, **extracted}
    return reply, new_slots, ready


def _build_inquiry_prompt(
    db: Session,
    runtime: BoundedToolExecutor,
    slots: dict,
    message: str,
    profile: dict,
    recognitions: list[dict],
) -> list[dict]:
    """组装问诊 prompt messages 供 runtime.stream('ask', ...) 使用。

    system prompt 走 prompt_service DB（scene='inquiry_system'），灰度/回滚无需重新部署。
    """
    inquiry_system = prompt_service.get_active_prompt(db, "inquiry_system")
    inquiry_tpl = prompt_service.get_active_prompt(db, "inquiry")
    prompt = inquiry_tpl.format(slots=json.dumps(slots, ensure_ascii=False), message=message)
    return [
        {"role": "system", "content": inquiry_system},
        {"role": "user", "content": (
            "历史背景资料：" + json.dumps(profile, ensure_ascii=False)
            + "\n本次会话图像识别结果：" + json.dumps(recognitions, ensure_ascii=False)
            + "\n本轮追问任务：" + prompt
        )},
    ]


def _run_inquiry_fallback(
    message: str, slots: dict, runtime: BoundedToolExecutor
) -> tuple[str, dict, bool]:
    """无 LLM 或 LLM 失败时的规则降级：(reply, new_slots, ready)。"""
    new_slots = dict(slots)
    reply = _fallback_inquiry(message, slots, new_slots, runtime)
    ready = ("complaint" in new_slots and "cold_hot" in new_slots)
    return reply, new_slots, ready


# ── 症状抽取（三级兜底） ────────────────────────────────────────

def _extract_symptoms_three_ways(
    db: Session,
    session: ConsultationSession,
    runtime: BoundedToolExecutor,
    new_slots: dict,
    message: str,
) -> list[str]:
    symptoms = list(new_slots.get("symptoms", []))
    if not symptoms:
        symptoms = runtime.call("extract_symptoms", message)
    if not symptoms:
        history = (db.query(ConsultationRecord)
                   .filter(ConsultationRecord.session_id == session.session_id)
                   .order_by(ConsultationRecord.record_id.desc()).limit(20).all())
        symptoms = runtime.call("extract_symptoms", " ".join(
            r.content[:2000] for r in history if r.role == "user" and r.content))
    return symptoms


# ── 辨证 + 落库 ────────────────────────────────────────────────

def _run_syndrome_and_persist(
    db: Session,
    session: ConsultationSession,
    runtime: BoundedToolExecutor,
    symptoms: list[str],
    recognitions: list[dict],
    new_slots: dict,
    complaint: str,
    force_report: bool,
) -> Iterator[str]:
    """辨证调用 → 输出护栏 → 报告落库 → Review 创建，产出 patient_result SSE。"""
    recent_records = (db.query(ConsultationRecord)
                      .filter(ConsultationRecord.session_id == session.session_id)
                      .order_by(ConsultationRecord.record_id.desc()).limit(100).all())
    patient_messages = [
        r.content[:2000]
        for r in reversed(recent_records)
        if r.role == "user" and r.type == "text" and r.content
        and r.content.strip() not in _REPORT_KEYWORDS
    ]

    result = syndrome_service.analyze(
        db,
        {"symptoms": symptoms, "recognitions": recognitions, "risk_level": session.risk_level or "low",
         "inquiry": new_slots, "patient_messages": patient_messages},
        complaint, runtime=runtime,
    )

    # 输出护栏
    out_safety = safety_service.check_output(json.dumps(result, ensure_ascii=False), db)
    if out_safety.result == "block":
        yield _sse("error", {"code": "unsafe_output", "message": "本次结果未通过安全检查，请咨询专业医师"})
        return

    # 落库
    analysis = SyndromeAnalysis(
        session_id=session.session_id,
        syndrome=result.get("syndrome"),
        evidence=result.get("evidence"),
        differential=result.get("differential"),
        confidence=result.get("confidence"),
        treatment_principle=result.get("treatment_principle"),
        formula_suggestions=result.get("formula_suggestions"),
        diet_advice=result.get("diet_advice"),
        acupoint_advice=result.get("acupoint_advice"),
        lifestyle_advice=result.get("lifestyle_advice"),
        risk_level=result.get("risk_level"),
        emergency_flag=result.get("emergency_flag", False),
        disclaimer=result.get("disclaimer"),
        graph_refs=result.get("graph_refs"),
        model_name=settings.text_model,
        prompt_version=prompt_service.get_active_prompt_version(db, "syndrome"),
        latency_ms=result.get("latency_ms"),
    )
    db.query(ConsultationSession).filter_by(session_id=session.session_id).with_for_update().first()
    db.add(analysis)
    session.risk_level = result.get("risk_level")
    session.status = "pending_review"
    session.end_time = None
    if complaint:
        session.complaint = complaint
    db.flush()
    db.add(ReportReview(analysis_id=analysis.analysis_id, report=analysis_to_report(analysis)))
    db.commit()

    # 通知医生端新病例（Redis pub/sub，Redis 挂了降级不阻塞主流程）
    from app.services import notification_service
    notification_service.publish_case_new(
        analysis_id=analysis.analysis_id,
        session_id=session.session_id,
        user_id=session.user_id,
        syndrome=analysis.syndrome,
    )

    # 异步重算用户画像（最终一致性；Celery worker 不在时静默降级）
    try:
        from app.tasks.jobs import rebuild_user_profile
        rebuild_user_profile.delay(session.user_id)
    except Exception:  # noqa: BLE001
        logger.info("rebuild_user_profile not dispatched (celery unavailable)")

    from app.services.report_review_service import patient_result
    pending = patient_result(db, analysis)
    yield _sse("review_pending", pending)
    _add_record(db, session.session_id, "assistant", "result", pending["message"])


# ── 主骨架 ────────────────────────────────────────────────────

def chat_stream(db: Session, session: ConsultationSession, message: str) -> Iterator[str]:
    """SSE 对话流入口：会话锁 + 异常包装 + 转发到 _chat_turn 骨架。"""
    token = session_id_var.set(str(session.session_id))
    try:
        with session_lock(session.tenant_id, session.user_id, session.session_id):
            yield from _chat_turn(db, session, message)
    except SessionBusy:
        yield _sse("error", {"code": "session_busy", "message": "当前会话正在处理，请稍后重试"})
    except syndrome_service.AnalysisUnavailable as exc:
        db.rollback()
        from app.core.metrics import TURN_FAILURES
        TURN_FAILURES.inc()
        yield _sse("error", {"code": "analysis_unavailable", "message": str(exc)})
    except Exception:
        db.rollback()
        from app.core.metrics import TURN_FAILURES
        TURN_FAILURES.inc()
        logger.exception("consultation_turn_failed")
        yield _sse("error", {"code": "turn_failed", "message": "处理失败，请稍后重试"})
    finally:
        session_id_var.reset(token)


def _chat_turn(db: Session, session: ConsultationSession, message: str) -> Iterator[str]:
    """单轮对话骨架：每步调一个职责函数；流式 chunk 循环留在此处以实时 yield SSE。"""
    from contextlib import closing
    from langchain_core.utils.json import parse_partial_json

    runtime = _build_runtime(session)
    _add_record(db, session.session_id, "user", "text", message)

    # ① 输入层护栏
    safety = safety_service.check_input(message, db)
    if safety.result == "emergency":
        yield from _handle_emergency(db, session)
        return
    if safety.result == "block":
        yield from _handle_block(db, session)
        return

    # ② force_report 时如已有分析直接返回
    force_report = any(k in message for k in _REPORT_KEYWORDS)
    existing_stream = _try_return_existing_report(db, session) if force_report else None
    if existing_stream is not None:
        yield from existing_stream
        return

    # ③ 加载上下文
    saved = runtime.call("load_memory", "short", str(session.session_id))
    slots = saved[0]["value"] if saved else {}
    if force_report and not slots:
        slots = _load_slots_from_records(db, session.session_id)
    profile = runtime.call("load_memory", "long", "profile")
    recognitions = _get_recognitions(db, session.session_id)

    # ④ inquiry 追问（force_report 跳过）
    yield _sse("phase", {"phase": "syndrome" if force_report else "inquiry"})
    new_slots = dict(slots)
    if force_report:
        reply = "正在根据已有问诊记录和图像识别结果生成辨证报告，请稍候。"
        ready = True
    elif not llm.llm_configured():
        reply, new_slots, ready = _run_inquiry_fallback(message, slots, runtime)
    else:
        chunks = runtime.stream(
            "ask",
            _build_inquiry_prompt(db, runtime, slots, message, profile, recognitions),
            scene="inquiry",
        )
        raw, streamed_reply = "", ""
        try:
            with closing(chunks):
                for chunk in chunks:
                    raw += chunk
                    try:
                        partial = parse_partial_json(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(partial, dict) or "reply" not in partial:
                        continue
                    current = partial["reply"]
                    if not isinstance(current, str) or not current.startswith(streamed_reply):
                        raise ValueError("invalid streamed reply")
                    if any(0xD800 <= ord(char) <= 0xDFFF for char in current):
                        continue
                    delta = current[len(streamed_reply):]
                    streamed_reply = current
                    if delta:
                        yield _sse("chunk", {"text": delta})
        except Exception as e:
            if streamed_reply:
                raise  # 流式中已输出过内容 → 统一 SSE error
            logger.warning("inquiry LLM streaming failed: %s — fallback to rules", e)
            reply, new_slots, ready = _run_inquiry_fallback(message, slots, runtime)
        else:
            reply, new_slots, ready = _parse_inquiry_response(raw, slots)

    runtime.call("save_memory", "short", str(session.session_id), "slots", new_slots)

    # ⑤ 追问回复 + choices
    if force_report or (not llm.llm_configured() and "complaint" in new_slots and "cold_hot" in new_slots):
        # 无 LLM 时 fallback_inquiry 已产生过静态回复，不需要再补一个 chunk
        pass
    elif llm.llm_configured() and streamed_reply == "":
        # LLM 走完但没流式输出 → 补发完整回复
        yield _sse("chunk", {"text": reply})
    choices = build_choices(reply) if not ready else []
    _add_record(db, session.session_id, "assistant", "text", reply,
                meta={"slots": new_slots, "choices": choices})
    if choices:
        yield _sse("choices", {"questions": choices})

    # ⑥ 症状三级兜底
    symptoms = _extract_symptoms_three_ways(db, session, runtime, new_slots, message)
    complaint = (
        session.complaint
        or new_slots.get("complaint")
        or ("、".join(symptoms) if force_report else message[:50])
    )
    ready = ready or force_report

    if not ready:
        yield _sse("done", {"session_id": session.session_id})
        return

    # ⑦ 辨证 → 护栏 → 落库
    yield _sse("phase", {"phase": "syndrome"})
    yield from _run_syndrome_and_persist(
        db, session, runtime, symptoms, recognitions, new_slots, complaint, force_report,
    )
    yield _sse("done", {"session_id": session.session_id})
