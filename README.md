<p align="center">
  <h1 align="center">知诊 · Zhizhen</h1>
  <p align="center"><strong>中医智能健康问诊系统</strong> · TCM AI Clinical Consultation Platform</p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python" />
    <img src="https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi" />
    <img src="https://img.shields.io/badge/Vue-3-42b883?logo=vue" />
    <img src="https://img.shields.io/badge/LangGraph-Agent-orange?logo=langchain" />
    <img src="https://img.shields.io/badge/Milvus-Vector-179c3a" />
    <img src="https://img.shields.io/badge/Neo4j-Graph-4581c3?logo=neo4j" />
    <img src="https://img.shields.io/badge/Redis-PubSub-dc382d?logo=redis" />
    <img src="https://img.shields.io/badge/Celery-Async-37814a?logo=celery" />
  </p>
</p>

---

## ✨ 亮点 · 为什么是它

| 特性 | 说明 |
|---|---|
| 🧠 **多智能体编排** | LangGraph StateGraph 驱动问诊→辨证→论治→审方四阶段流转，每阶段独立 Agent，可插拔、可回放 |
| 📚 **GraphRAG 混合检索** | Milvus 向量 + Neo4j 证型-症状-治法图谱，RRF 融合排序，辨证有据可追溯 |
| 🛡️ **安全护栏三层设计** | 输入护栏屏蔽 prompt injection · 输出护栏拦截确定性诊断/处方剂量 · 急危重症自动短路推送就医指南 |
| 💬 **SSE 实时流式问诊** | 槽位驱动的追问链路，每轮仅问 1~2 个具体问题，渐进式收集四诊信息 |
| 🧾 **长短时记忆系统** | agent_memory 表存储会话级槽位快照 + 跨会话健康画像，下次问诊自动参考历史 |
| 👁️ **多模态望诊** | DashScope 视觉模型识别舌象/面色，置信度低时主动说明不确定之处，不强行推断 |
| 👨‍⚕️ **医患双端 + 人工审核** | 患者提交报告草稿 → Redis pub/sub 实时推送给医生 → 医生审核确认后回传患者 |
| 🔗 **分享链接** | HMAC 签名 + 时效 token，生成后可直接发给亲友/医生查看，无需登录 |
| 📤 **报告导出** | PDF / JSON 一键下载，weasyprint 不可用时自动降级，无外部依赖也能用 |
| 📊 **完整可观测性** | Prometheus + Grafana 仪表盘 + OpenTelemetry 全链路 Trace + LangSmith LLM 调用追踪 |
| 🔧 **企业级工程化** | Alembic 迁移 + AES-256-GCM 字段加密 + prompt 版本化热更新 + Session 超时自动清理 |

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
│       ├── core/          graph(LangGraph) · llm · milvus · neo4j · redis · security
│       ├── services/      consultation · syndrome · safety · share · export · notification
│       ├── tasks/         Celery beat: session 超时清理 · 用户画像重算 · memory 过期
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
用户输入 ──▶ [输入护栏] ──▶ LangGraph StateGraph
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              问诊 Agent    辨证 Agent    论治 Agent
              (槽位追问)   (GraphRAG)    (方剂+食疗)
                    │           │           │
                    └───────────┼───────────┘
                                ▼
                        [输出护栏] ──▶ SyndromeAnalysis 落库
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
- **Agent 编排**：LangGraph StateGraph
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

### 部署
- Docker Compose 一键起全套
- 预置 Nginx 反向代理 + CORS + WebSocket 升级
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
# 默认管理员：admin / admin123
# 默认医生：dr_zhang / doctor123（种子数据）
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
pytest tests/ -v --tb=short
# 预期：53 passed, 3 skipped（跳过项为可选依赖/环境预置）
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
| 外部依赖降级 | 全局 | Redis/Celery/weasyprint 任一不可用时主链路不中断，日志 warning 即可 |

---

## 📁 核心模块索引

| 模块 | 文件 | 职责 |
|---|---|---|
| 多智能体编排 | `backend/app/core/graph.py` | LangGraph `StateGraph` + `DiagnosisState` TypedDict |
| 问诊主链路 | `backend/app/services/consultation_service.py` | 流式问诊骨架 + 安全护栏 + 辨证落库（401 行 → 骨架+8 职责函数） |
| GraphRAG 检索 | `backend/app/services/syndrome_service.py` | Milvus 向量 + Neo4j 图谱 + RRF 融合 |
| 系统提示词 | `backend/app/services/prompt_service.py` | `prompt_version` 表热更新，含 `inquiry_system` scene |
| 分享链接 | `backend/app/services/share_service.py` | HMAC 签名 token + /consultation/public/share/{token} 公开端点 |
| 实时通知 | `backend/app/services/notification_service.py` + `api/notifications.py` | Redis pub/sub + SSE `/notify/stream` |
| PDF 导出 | `backend/app/services/export_service.py` | weasyprint + 自动降级 JSON |
| 用户画像 | `backend/app/tasks/jobs.py::rebuild_user_profile` | Celery 异步，扫历史报告算证型趋势 + 季节性 |

---

## 📄 License

MIT License — 个人学习和学术交流免费使用。

> ⚠️ **免责声明**：知诊是 AI 辅助健康科普工具，输出内容仅作为健康参考，不构成医疗诊断、处方或治疗建议。危急健康问题请及时就医。
