<p align="center">
  <h1 align="center">知诊 · Zhizhen</h1>
  <p align="center"><strong>中医智能健康问诊系统</strong> · TCM AI Clinical Consultation Platform</p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python" />
    <img src="https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi" />
    <img src="https://img.shields.io/badge/Vue-3-42b883?logo=vue" />
    <img src="https://img.shields.io/badge/LangGraph-3--Node-orange?logo=langchain" />
    <img src="https://img.shields.io/badge/Milvus-Vector-179c3a" />
    <img src="https://img.shields.io/badge/Neo4j-Graph-4581c3?logo=neo4j" />
    <img src="https://img.shields.io/badge/Redis-PubSub-dc382d?logo=redis" />
    <img src="https://img.shields.io/badge/Celery-Async-37814a?logo=celery" />
  </p>
</p>

---

## ✨ 亮点

| 特性 | 代码里的实现 |
|---|---|
| 🧠 **LangGraph 三节点 StateGraph** | `retrieve → differentiate → recommend`，`DiagnosisState` TypedDict，链路可回放、可插拔。问诊和审方在图外骨架层 |
| 📚 **Neo4j 图谱定证型 + Milvus 向量补位** | 图检索沿 `MANIFESTS` 关系按症状命中数排序取 top5，名称去重后取 top3 证型；向量 `top_k=3` 仅补图检索未覆盖的节点，最终再次去重。两套通道互补、不相互加权 |
| 🛡️ **三层安全护栏** | `safety_service.check_input` 屏蔽 prompt injection / 非医疗内容；`safety_service.check_output` 拦截确定性诊断措辞、处方剂量；急危重症（胸痛/呼吸困难/意识障碍/自伤倾向）由 `consultation_service._handle_emergency` 短路，直接返回急救指南、终止问诊 |
| 💬 **SSE 流式问诊 + 槽位驱动** | 后端用 `StreamingResponse` 以 `text/event-stream` 逐 chunk yield，前端用 `fetch + ReadableStream` 消费；每轮 LLM 回复按槽位追问 1~2 个具体问题，渐进式收集四诊信息 |
| 🧾 **长短时记忆** | `agent_memory` 表分短（本次会话槽位快照）长（跨会话健康画像）两层，下次问诊从 DB 恢复槽位，画像在每次辨证落库后由 Celery 异步重算 |
| 👁️ **多模态望诊** | DashScope 视觉模型识别舌象/面色，`vision_service` 对低置信度结果返回结构化 `uncertain: true`，不强行推断 |
| 👨‍⚕️ **医患双端 + 人工审核** | 患者提交报告草稿 → 辨证落库后 `notification_service.publish_case_new` 经 Redis pub/sub 发布 → 医生端订阅 `/api/v1/notify/stream` SSE 实时收到 |
| 🔗 **HMAC 签名分享链接** | `share_service` 用 `hashlib.sha256` 生成带过期时间的签名 token，公开端点 `/api/v1/consultation/public/share/{token}` 无需登录、7 天过期自动拒绝 |
| 📤 **报告导出 PDF / JSON** | `export_service` 优先用 `weasyprint` 渲染 PDF，未安装时自动降级 JSON 下载，带 `X-Export-Warning` 响应头，无外部依赖也能用 |
| 📊 **可观测性** | `observability/` 目录含 Prometheus alerts + Grafana dashboards；`main.py` 埋 `prometheus_client` metrics；Celery 任务挂 LangSmith traces |
| 🔧 **企业级工程化** | `AES-256-GCM` 字段加密（`core.security.encrypt_field`）；`prompt_version` 表热更新 system prompt（`prompt_service` 含 `inquiry_system` scene）；Celery beat 每 30 分钟清理 24h 未活跃的 ongoing 会话 |

---

## 🏗️ 架构总览

```
知诊 / Zhizhen
├── frontend/              Vue 3 + TS + Element Plus + Vite
│   └── src/
│       ├── components/    问诊对话 / 四诊进度条 / 报告编辑器 / 图谱卡片
│       ├── views/         首页 / 问诊 / 报告 / 医生工作台 / 管理后台
│       └── api/           axios + 统一拦截器（含 silentError 静默降级）
│
├── backend/               FastAPI + SQLAlchemy + Celery
│   └── app/
│       ├── api/           auth · consultation · notifications · admin · knowledge
│       ├── core/          graph(LangGraph 3-node) · llm · milvus · neo4j · redis · security
│       ├── services/      consultation · knowledge · safety · share · export · notification
│       ├── tasks/         Celery beat: session 超时清理 · 用户画像重算
│       └── models/        User · ConsultationSession · ConsultationRecord
│                          SyndromeAnalysis · ReportReview · AgentMemory · PromptVersion
│
├── init/                  建表 SQL + 种子数据 + Neo4j Cypher
├── observability/         Prometheus alerts + Grafana dashboards
├── docker-compose.yml     一键起全套（MySQL+Redis+Neo4j+Milvus+API+Worker+前端）
└── .env.example           环境变量模板
```

### 核心数据流

```
用户输入 ──▶ [输入护栏] ──▶ 问诊骨架层（consultation_service._chat_turn）
                                │
                    流式槽位追问（LangGraph 外）
                                │
                                ▼
                        [输出护栏]
                                │
                                ▼
                LangGraph StateGraph（3 节点）
                    retrieve → differentiate → recommend
                                │
                                ▼
                        SyndromeAnalysis 落库
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
       ReportReview 草稿               Redis pub/sub
       (医生审核队列)                  notify:case:new → 医生端 SSE
```

---

## 🛠️ 技术栈

### 后端
- **语言**：Python 3.11+
- **框架**：FastAPI 0.110+ · SQLAlchemy 2.0 · Pydantic v2
- **Agent 编排**：LangGraph StateGraph（3 节点 `retrieve → differentiate → recommend`）
- **向量检索**：Milvus (pymilvus)
- **图谱检索**：Neo4j (neo4j driver)
- **缓存 & Pub/Sub**：Redis (redis-py, aioredis)
- **异步任务**：Celery 5 + beat
- **数据库**：PostgreSQL 16
- **LLM**：DashScope（文本 + 多模态视觉 + text-embedding-v3）
- **安全**：AES-256-GCM 字段加密 · JWT · bcrypt
- **可观测性**：Prometheus + Grafana + OpenTelemetry + LangSmith

### 前端
- **框架**：Vue 3 + TypeScript 5
- **UI**：Element Plus
- **状态**：Pinia
- **构建**：Vite 5
- **流式消费**：`fetch + ReadableStream`（text/event-stream）

### 部署
- Docker Compose 一键起全套
- 预置 Nginx 反向代理 + CORS
- Celery worker 与 beat 独立容器

---

## 🚀 快速开始

### 前置
- Docker Desktop 已安装并运行
- DashScope API Key（[阿里云百炼](https://bailian.console.aliyun.com/) 申请）

### 一键起

```bash
# 1. 克隆
git clone https://github.com/zhuruixuan11/zhizhen.git
cd zhizhen

# 2. 配环境变量
cp .env.example .env.local
# 编辑 .env.local，填 DASHSCOPE_API_KEY

# 3. 全套起
docker compose up -d --build

# 4. 打开浏览器
open http://localhost
# 管理员账号由 ADMIN_USERNAME / ADMIN_PASSWORD 环境变量控制，未设置时默认 admin / admin123
```

### 开发模式（前后端分离）

```bash
# 后端：只起依赖服务
docker compose up -d mysql redis neo4j milvus

cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev -- --port 5174
```

### 跑测试

```bash
cd backend
python -m unittest discover -s tests -v
# 16 个测试文件，61 个测试方法
```

---

## 🔒 安全设计

| 层级 | 位置 | 策略 |
|---|---|---|
| 输入护栏 | `safety_service.check_input` | 屏蔽 prompt injection（"忽略之前的指令"等）、非医疗内容 |
| 输出护栏 | `safety_service.check_output` | 拦截确定性诊断措辞、处方剂量、诱导越权 |
| 急危重症短路 | `consultation_service._handle_emergency` | 识别胸痛/呼吸困难/意识障碍/自伤倾向 → 立即返回急救指南，终止问诊 |
| 字段加密 | `core.security.encrypt_field` | 敏感数据（医生证号、患者画像）AES-256-GCM 加密落库 |
| API 鉴权 | `api.deps.get_current_user` | JWT access token + role-based 权限拦截 |
| 分享链接 | `services.share_service` | HMAC-SHA256 签名 + 时效控制，伪造/篡改/过期均拒绝 |
| 外部依赖降级 | 全局 | Redis pub/sub / Celery worker / weasyprint 任一不可用时主链路不中断，日志 warning 即可 |

---

## 📁 核心模块索引

| 模块 | 文件 | 职责 |
|---|---|---|
| LangGraph 三节点编排 | `backend/app/core/graph.py` | `StateGraph(retrieve → differentiate → recommend)` + `DiagnosisState` TypedDict |
| 问诊主链路 | `backend/app/services/consultation_service.py` | 流式问诊骨架（`_chat_turn` 105 行）+ 安全护栏 + 辨证落库 |
| 图谱优先 + 向量补位 | `backend/app/services/knowledge_service.py::graphrag_retrieve` | Neo4j `MANIFESTS` 命中数排序取 top3 证型；Milvus `top_k=3` 补位；名称去重 |
| 系统提示词热更新 | `backend/app/services/prompt_service.py` | `prompt_version` 表驱动，含 `inquiry_system` scene |
| 分享链接 | `backend/app/services/share_service.py` | HMAC-SHA256 签名 token + `/consultation/public/share/{token}` 公开端点 |
| 医生端 SSE 通知 | `backend/app/services/notification_service.py` + `api/notifications.py` | Redis pub/sub + `/notify/stream` |
| 报告导出 | `backend/app/services/export_service.py` | weasyprint PDF + 自动降级 JSON |
| 用户画像异步重算 | `backend/app/tasks/jobs.py::rebuild_user_profile` | Celery beat + 事件触发，扫历史报告算证型趋势 |
| Session 超时清理 | `backend/app/tasks/jobs.py::close_stale_sessions` | Celery beat 每 30 分钟扫 24h 未活跃 ongoing 会话 |

---

## 📄 License

MIT License — 个人学习和学术交流免费使用。

> ⚠️ **免责声明**：知诊是 AI 辅助健康科普工具，输出内容仅作为健康参考，不构成医疗诊断、处方或治疗建议。危急健康问题请及时就医。
