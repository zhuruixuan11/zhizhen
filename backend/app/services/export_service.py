"""报告导出 PDF：weasyprint 渲染为只读报告。

降级策略：weasyprint 未安装时返回纯 JSON 下载，不阻塞主流程。
"""
import io
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("app.report-export")


def export_pdf(report_payload: dict) -> Optional[bytes]:
    """把 PatientResult payload 渲染成 PDF。失败返回 None（降级给调用方处理）。"""
    try:
        from weasyprint import HTML  # 可选依赖
    except ImportError:
        logger.warning("weasyprint 未安装，PDF 导出降级为 JSON")
        return None

    report = report_payload.get("report", report_payload)
    html = _render_report_html(report_payload, report)
    try:
        return HTML(string=html).write_pdf()
    except Exception as e:  # noqa: BLE001
        logger.warning("weasyprint 渲染失败: %s", e)
        return None


def export_json(report_payload: dict) -> bytes:
    """降级方案：纯 JSON 下载。"""
    export = {
        "exported_at": datetime.now().isoformat(),
        "format": "zhizhen-report-v1",
        **report_payload,
    }
    return json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8")


def _render_report_html(payload: dict, report: dict) -> str:
    syndrome = report.get("syndrome") or payload.get("syndrome", "")
    confidence = report.get("confidence") or payload.get("confidence")
    risk = report.get("risk_level") or payload.get("risk_level", "low")
    evidence = report.get("evidence", [])
    differential = report.get("differential", [])
    diet = report.get("diet_advice", [])
    lifestyle = report.get("lifestyle_advice", [])
    principle = report.get("treatment_principle", "")
    disclaimer = report.get("disclaimer") or payload.get("disclaimer", "")

    def _list(items):
        if not items:
            return "<p>—</p>"
        return "<ul>" + "".join(f"<li>{e}</li>" for e in items) + "</ul>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>知诊 · 辨证报告</title>
<style>
  body {{ font-family: "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 640px; margin: 0 auto; padding: 32px; color: #2d241a; }}
  h1 {{ color: #a63d40; border-bottom: 3px solid #c8963a; padding-bottom: 8px; }}
  h2 {{ color: #2f5233; margin-top: 24px; }}
  .meta {{ color: #888; font-size: 13px; margin-top: -8px; margin-bottom: 20px; }}
  .syndrome-badge {{ display: inline-block; background: #faf0ec; border: 1px solid #a63d40; color: #a63d40; padding: 4px 12px; border-radius: 14px; font-weight: 600; }}
  .confidence {{ color: #666; font-size: 13px; margin-left: 10px; }}
  .disclaimer {{ margin-top: 32px; padding: 12px 16px; background: #faf6f1; border-left: 3px solid #c8963a; font-size: 12px; color: #888; }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 4px; }}
</style>
</head>
<body>
  <h1>知诊 · 辨证报告</h1>
  <p class="meta">导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} · 仅供参考，不能替代专业医师诊断</p>
  <p>
    <span class="syndrome-badge">{syndrome or "—"}</span>
    <span class="confidence">置信度 {round(confidence * 100)}%</span>
  </p>

  <h2>辨证依据</h2>
  {_list([f"<b>{e.get('source')}</b>：{e.get('description')}" for e in evidence])}

  <h2>鉴别证型</h2>
  {_list(differential)}

  <h2>治法原则</h2>
  <p>{principle or "—"}</p>

  <h2>饮食建议</h2>
  {_list(diet)}

  <h2>生活调摄</h2>
  {_list(lifestyle)}

  <div class="disclaimer">{disclaimer}</div>
</body>
</html>"""
