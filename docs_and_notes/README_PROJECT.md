# Chat Oracle - 工程说明

## 项目背景

Chat Oracle 是一个面向商业聊天场景的 **LLM Gateway + Subscription SaaS Control Plane** 控制面后端。
系统围绕已有的 vLLM / TGI / OpenAI-compatible 推理服务，构建用户体系、会员订阅、聊天会话、Token 计费、模型路由等商业闭环。

## 核心架构

- **技术栈**: Python 3.12 + FastAPI + SQLAlchemy 2.x + Alembic + PostgreSQL 16 + Redis 7
- **设计模式**: 模块化单体，分层清晰（API → Service → Repo → Model）
- **部署方式**: Docker Compose（Postgres + Redis + App），Caddy 反向代理
- **目标域名**: `chat.202574.xyz`
- **上游模型**: `https://sd3.202574.xyz/v1`（OpenAI-compatible 接口）
- **支付状态**: 已接通 `BEpusdt` 下单、查单、回调和订阅生效链路

## 目录结构

```
app/
  api/           # 路由层 (auth, chat, conversations, admin, health, users, subscriptions)
  core/          # 核心层 (config, db, redis, security, lifecycle, exceptions, logging, constants)
  models/        # ORM 模型 (User, AuthSession, Plan, Subscription, Conversation, Message, ModelNode)
  repos/         # 仓储层 (对应各 Model 的数据访问逻辑)
  schemas/       # Pydantic Schema (请求/响应分离)
  services/      # 业务服务层 (auth, chat, conversation, subscription, admin)
  providers/     # LLM Provider 适配器 (base, openai_compat)
  templates/     # HTML 模板 (admin 后台页面)
  static/        # 静态前端资源 (chat 界面等)
deploy/
  compose/       # Docker Compose 编排
  caddy/         # Caddy 反向代理配置
migrations/      # Alembic 数据库迁移
tests/           # 测试文件
```

## 服务器环境

- **控制面主机**: Ubuntu, 4 vCPU, 24 GB RAM
- **SSH**: `ssh -i 'k.key' ubuntu@40.233.67.228`
- **部署目录**: `/home/ubuntu/chat-oracle`
- **反向代理**: Caddy (共用服务器现有 Caddy)
- **应用端口**: 内部 8000，映射 `127.0.0.1:18000`，Caddy 反代到 `chat.202574.xyz`
