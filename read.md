# 0. 文档定位

本文档定义一个面向商业收费场景的 **ChatGPT 式聊天系统控制平面**。
系统核心职责不是训练或推理模型，而是围绕已有的 **vLLM / TGI / OpenAI-compatible 推理服务**，构建：

- 用户与会员体系
- 聊天会话与消息存储
- 流式文本输出
- Token 预占与精算
- 用户并发控制与限流
- 多模型/多节点路由
- 支付回调与订阅状态联动
- 审计、日志、运维与基础风控

当前部署约束：

- 控制平面主机：**Ubuntu, 4 vCPU, 24 GB RAM**
- 推理服务：已独立存在，提供 **vLLM/TGI/OpenAI-compatible 接口**
- 商业目标：**月费会员制**，体验接近 ChatGPT
- 当前不做内容审查引擎，但系统应预留策略钩子
- 当前不追求重微服务，追求 **稳定、可维护、可扩展**

---

# 1. 总体设计原则

## 1.1 系统定位

本系统是 **LLM Gateway + Subscription SaaS Control Plane**，不是纯代理，不是简单 UI 后端。

## 1.2 设计原则

1. **单体优先，分层清晰**
   - 当前阶段采用模块化单体架构
   - 避免提前微服务化带来的复杂度
   - 保证后续可按边界拆分

2. **控制面与推理解耦**
   - 控制面只负责业务逻辑、调度、计费、存储
   - 推理由独立模型节点承担

3. **流式优先**
   - 聊天输出必须支持 SSE 流式
   - 首字延迟、稳定性优先于花哨交互

4. **账本优先**
   - 所有 token 消耗、预占、退款、失败都必须有流水
   - 汇总不是事实来源，流水才是事实来源

5. **幂等与恢复优先**
   - 支付回调、消息提交、流式失败恢复、重试必须有幂等设计

6. **先单机可用，再平滑横向扩展**
   - 先支持单控制节点
   - 预留多节点、主备路由、任务队列扩展位

---

# 2. 目标能力范围

## 2.1 首期必须实现

- 用户注册 / 登录 / JWT 会话
- 会员订阅体系
- 聊天会话列表、消息持久化
- Chat Completions 风格接口
- SSE 流式输出
- Redis 热上下文缓存
- Token 预估 / 预占 / 精算 / 多退少补
- 用户级并发控制
- Redis 分布式限流
- 模型节点健康检查与主备切换
- 支付 Webhook
- 管理后台基础看板
- 审计日志与错误追踪

## 2.2 二期可扩展

- 多模型套餐
- 图像 / 文件上传
- 长对话自动摘要
- 标题生成
- 组织 / 团队 / API Key
- Referral / 优惠券
- 更精细的队列优先级
- OpenTelemetry 全链路追踪
- 独立 worker / 任务队列
- 后台管理系统细粒度权限

---

# 3. 推荐技术栈

## 3.1 后端

- **Python 3.12**
- **FastAPI**
- **SQLAlchemy 2.x**
- **Alembic**
- **Pydantic v2**
- **httpx**
- **uvicorn / gunicorn**
- **asyncpg**
- **redis-py**
- **orjson**

## 3.2 数据层

- **PostgreSQL 16**
- **Redis 7**

## 3.3 网关/部署

- **Nginx**
- **Docker Compose**（首期）
- 后续可迁移 Kubernetes，但首期不强制

## 3.4 认证与安全

- JWT access + refresh
- bcrypt / argon2
- 可选 TOTP 预留

## 3.5 监控

- Prometheus
- Grafana
- Sentry
- 结构化 JSON 日志

## 3.6 支付

- Stripe 优先
  如面向中国市场可替换或新增：
- 微信支付
- 支付宝
  但接口抽象统一

---

# 4. 系统逻辑架构

```text
[ Client Web / App ]
        |
        v
 [ Nginx / TLS / Basic WAF ]
        |
        v
 [ FastAPI Control Plane ]
   |      |       |        |
   |      |       |        +--> Payment Provider Webhook
   |      |       +------------> Redis
   |      +--------------------> PostgreSQL
   +---------------------------> Model Nodes (vLLM/TGI/OpenAI-compatible)
```

系统内部按逻辑分层：

1. **API Layer**
   - 路由与输入输出

2. **Application Service Layer**
   - 业务编排

3. **Domain/Policy Layer**
   - 订阅、限流、配额、调度策略

4. **Infrastructure Layer**
   - DB、Redis、HTTP 客户端、支付、日志

5. **Async/Background Layer**
   - 精算、摘要、标题、清理任务

---

# 5. 目录结构

```plaintext
platform-core/
├── app/
│   ├── api/
│   │   ├── deps.py
│   │   ├── router.py
│   │   └── v1/
│   │       ├── auth.py
│   │       ├── users.py
│   │       ├── subscriptions.py
│   │       ├── conversations.py
│   │       ├── chat.py
│   │       ├── payments.py
│   │       ├── admin.py
│   │       ├── health.py
│   │       └── models.py
│   ├── core/
│   │   ├── config.py
│   │   ├── constants.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   ├── db.py
│   │   ├── redis.py
│   │   ├── exceptions.py
│   │   └── lifecycle.py
│   ├── models/
│   │   ├── user.py
│   │   ├── auth_session.py
│   │   ├── subscription.py
│   │   ├── plan.py
│   │   ├── conversation.py
│   │   ├── message.py
│   │   ├── usage_ledger.py
│   │   ├── request_log.py
│   │   ├── payment_record.py
│   │   ├── node_registry.py
│   │   ├── quota_snapshot.py
│   │   └── audit_log.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── subscription.py
│   │   ├── conversation.py
│   │   ├── chat.py
│   │   ├── payment.py
│   │   ├── admin.py
│   │   └── common.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── subscription_service.py
│   │   ├── conversation_service.py
│   │   ├── message_service.py
│   │   ├── chat_service.py
│   │   ├── model_gateway_service.py
│   │   ├── routing_service.py
│   │   ├── quota_service.py
│   │   ├── billing_service.py
│   │   ├── tokenizer_service.py
│   │   ├── payment_service.py
│   │   ├── admin_service.py
│   │   ├── metrics_service.py
│   │   ├── summary_service.py
│   │   └── title_service.py
│   ├── policies/
│   │   ├── rate_limit_policy.py
│   │   ├── concurrency_policy.py
│   │   ├── subscription_policy.py
│   │   ├── routing_policy.py
│   │   └── usage_policy.py
│   ├── repos/
│   │   ├── user_repo.py
│   │   ├── subscription_repo.py
│   │   ├── conversation_repo.py
│   │   ├── message_repo.py
│   │   ├── usage_ledger_repo.py
│   │   ├── payment_repo.py
│   │   ├── node_repo.py
│   │   └── audit_repo.py
│   ├── middleware/
│   │   ├── auth_middleware.py
│   │   ├── request_context.py
│   │   ├── rate_limit_middleware.py
│   │   ├── access_log_middleware.py
│   │   └── exception_middleware.py
│   ├── integrations/
│   │   ├── llm/
│   │   │   ├── base.py
│   │   │   ├── openai_compat.py
│   │   │   ├── vllm.py
│   │   │   └── tgi.py
│   │   └── payment/
│   │       ├── base.py
│   │       └── stripe.py
│   ├── tasks/
│   │   ├── finalize_usage.py
│   │   ├── cleanup_sessions.py
│   │   ├── generate_title.py
│   │   ├── generate_summary.py
│   │   └── sync_metrics.py
│   ├── utils/
│   │   ├── idempotency.py
│   │   ├── time.py
│   │   ├── token_estimator.py
│   │   ├── stream_parser.py
│   │   └── json.py
│   └── main.py
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── deploy/
│   ├── docker/
│   ├── nginx/
│   ├── systemd/
│   └── compose/
├── scripts/
├── docs/
└── README.md
```

---

# 6. 核心数据模型

以下为推荐核心表。字段可按工程语言规范微调，但语义不得丢失。

---

## 6.1 users

```sql
users (
  id                    uuid pk,
  email                 varchar(255) unique null,
  phone                 varchar(32) unique null,
  username              varchar(64) unique null,
  password_hash         varchar(255) not null,
  status                varchar(32) not null,      -- active/suspended/deleted
  email_verified        boolean not null default false,
  avatar_url            text null,
  timezone              varchar(64) null,
  locale                varchar(16) null,
  created_at            timestamptz not null,
  updated_at            timestamptz not null,
  last_login_at         timestamptz null
)
```

索引：

- unique(email)
- unique(phone)
- index(status)
- index(created_at desc)

---

## 6.2 auth_sessions

用于刷新 token、踢设备、会话审计。

```sql
auth_sessions (
  id                    uuid pk,
  user_id               uuid not null references users(id),
  refresh_token_hash    varchar(255) not null,
  device_id             varchar(128) null,
  user_agent            text null,
  ip_address            inet null,
  status                varchar(32) not null,      -- active/revoked/expired
  expires_at            timestamptz not null,
  created_at            timestamptz not null,
  revoked_at            timestamptz null
)
```

索引：

- index(user_id, status)
- index(expires_at)

---

## 6.3 plans

套餐表，避免写死业务逻辑。

```sql
plans (
  id                          uuid pk,
  code                        varchar(64) unique not null,  -- free/pro/ultra
  name                        varchar(128) not null,
  monthly_price_cents         integer not null,
  currency                    varchar(16) not null,
  monthly_soft_token_limit    bigint not null,
  daily_soft_token_limit      bigint not null,
  max_concurrent_requests     integer not null,
  max_input_tokens            integer not null,
  max_output_tokens           integer not null,
  max_context_tokens          integer not null,
  priority_level              integer not null,
  allowed_models_json         jsonb not null,
  features_json               jsonb not null,
  is_active                   boolean not null default true,
  created_at                  timestamptz not null,
  updated_at                  timestamptz not null
)
```

---

## 6.4 subscriptions

```sql
subscriptions (
  id                          uuid pk,
  user_id                     uuid not null references users(id),
  plan_id                     uuid not null references plans(id),
  provider                    varchar(32) not null,     -- stripe/wechat/alipay/manual
  provider_customer_id        varchar(255) null,
  provider_subscription_id    varchar(255) null,
  status                      varchar(32) not null,     -- active/trialing/past_due/canceled/expired
  start_at                    timestamptz not null,
  end_at                      timestamptz not null,
  cancel_at_period_end        boolean not null default false,
  canceled_at                 timestamptz null,
  trial_end_at                timestamptz null,
  created_at                  timestamptz not null,
  updated_at                  timestamptz not null
)
```

约束：

- 一个用户同一时刻只有一个主订阅有效
- 历史订阅保留，不覆盖

索引：

- index(user_id, status)
- index(end_at)
- unique(provider, provider_subscription_id)

---

## 6.5 conversations

```sql
conversations (
  id                          uuid pk,
  user_id                     uuid not null references users(id),
  title                       varchar(255) null,
  summary                     text null,
  pinned                      boolean not null default false,
  archived                    boolean not null default false,
  latest_model                varchar(128) null,
  latest_message_at           timestamptz not null,
  message_count               integer not null default 0,
  created_at                  timestamptz not null,
  updated_at                  timestamptz not null,
  deleted_at                  timestamptz null
)
```

索引：

- index(user_id, latest_message_at desc)
- index(user_id, archived)
- index(deleted_at)

---

## 6.6 messages

```sql
messages (
  id                          uuid pk,
  conversation_id             uuid not null references conversations(id),
  user_id                     uuid not null references users(id),
  parent_message_id           uuid null references messages(id),
  role                        varchar(32) not null,         -- system/user/assistant/tool
  content_text                text not null,
  content_json                jsonb null,
  model                       varchar(128) null,
  status                      varchar(32) not null,         -- pending/streaming/completed/failed/canceled
  prompt_tokens               integer not null default 0,
  completion_tokens           integer not null default 0,
  total_tokens                integer not null default 0,
  finish_reason               varchar(64) null,
  error_code                  varchar(64) null,
  error_message               text null,
  request_id                  varchar(128) null,
  created_at                  timestamptz not null,
  updated_at                  timestamptz not null
)
```

索引：

- index(conversation_id, created_at)
- index(user_id, created_at desc)
- index(request_id)

---

## 6.7 usage_ledger

最关键的账本表。

```sql
usage_ledger (
  id                          uuid pk,
  user_id                     uuid not null references users(id),
  subscription_id             uuid null references subscriptions(id),
  conversation_id             uuid null references conversations(id),
  message_id                  uuid null references messages(id),
  request_id                  varchar(128) not null,
  idempotency_key             varchar(128) null,
  model                       varchar(128) not null,
  provider                    varchar(64) not null,
  node_id                     uuid null references model_nodes(id),
  estimated_input_tokens      integer not null default 0,
  reserved_tokens             integer not null default 0,
  actual_prompt_tokens        integer not null default 0,
  actual_completion_tokens    integer not null default 0,
  actual_total_tokens         integer not null default 0,
  refunded_tokens             integer not null default 0,
  billing_status              varchar(32) not null,       -- reserved/finalized/refunded/waived/failed
  request_status              varchar(32) not null,       -- initiated/streaming/completed/failed/canceled/timeout
  cost_basis_json             jsonb null,
  metadata_json               jsonb null,
  created_at                  timestamptz not null,
  finalized_at                timestamptz null
)
```

约束：

- `request_id` 全局唯一
- 一个请求只能有一条主 ledger

索引：

- unique(request_id)
- index(user_id, created_at desc)
- index(subscription_id, created_at desc)
- index(billing_status)
- index(request_status)

---

## 6.8 quota_snapshots

用于快速展示和统计，不是结算真相。

```sql
quota_snapshots (
  id                          uuid pk,
  user_id                     uuid not null references users(id),
  period_type                 varchar(16) not null,        -- daily/monthly
  period_key                  varchar(32) not null,        -- 2026-04-18 / 2026-04
  used_tokens                 bigint not null default 0,
  reserved_tokens             bigint not null default 0,
  refunded_tokens             bigint not null default 0,
  request_count               integer not null default 0,
  updated_at                  timestamptz not null
)
```

约束：

- unique(user_id, period_type, period_key)

---

## 6.9 payment_records

```sql
payment_records (
  id                          uuid pk,
  user_id                     uuid not null references users(id),
  provider                    varchar(32) not null,
  provider_event_id           varchar(255) null,
  provider_payment_id         varchar(255) null,
  provider_subscription_id    varchar(255) null,
  event_type                  varchar(64) not null,
  amount_cents                integer not null,
  currency                    varchar(16) not null,
  status                      varchar(32) not null,      -- received/verified/processed/failed/ignored
  raw_payload_json            jsonb not null,
  idempotency_key             varchar(128) null,
  created_at                  timestamptz not null,
  processed_at                timestamptz null
)
```

约束：

- unique(provider, provider_event_id)

---

## 6.10 model_nodes

```sql
model_nodes (
  id                          uuid pk,
  code                        varchar(64) unique not null,
  provider_type               varchar(32) not null,      -- vllm/tgi/openai_compat
  base_url                    text not null,
  api_key_encrypted           text null,
  model_name                  varchar(128) not null,
  enabled                     boolean not null default true,
  status                      varchar(32) not null,      -- healthy/degraded/unhealthy/draining
  weight                      integer not null default 100,
  priority                    integer not null default 100,
  max_parallel_requests       integer not null default 100,
  current_parallel_requests   integer not null default 0,
  avg_ttft_ms                 integer null,
  avg_tps                     numeric(10,2) null,
  capability_json             jsonb not null,
  metadata_json               jsonb null,
  last_healthcheck_at         timestamptz null,
  last_healthy_at             timestamptz null,
  created_at                  timestamptz not null,
  updated_at                  timestamptz not null
)
```

---

## 6.11 request_logs

```sql
request_logs (
  id                          uuid pk,
  request_id                  varchar(128) unique not null,
  user_id                     uuid null references users(id),
  path                        varchar(255) not null,
  method                      varchar(16) not null,
  status_code                 integer not null,
  latency_ms                  integer not null,
  ip_address                  inet null,
  user_agent                  text null,
  error_code                  varchar(64) null,
  created_at                  timestamptz not null
)
```

---

## 6.12 audit_logs

```sql
audit_logs (
  id                          uuid pk,
  actor_type                  varchar(32) not null,      -- user/admin/system
  actor_id                    uuid null,
  action                      varchar(128) not null,
  target_type                 varchar(64) null,
  target_id                   varchar(128) null,
  metadata_json               jsonb null,
  created_at                  timestamptz not null
)
```

---

# 7. Redis 键设计

Redis 用于热路径，不作为永久真相源。

## 7.1 会话热上下文

- `ctx:{conversation_id}`
  最近 N 条消息序列化缓存
  TTL: 1~24h，可滑动刷新

## 7.2 用户并发计数

- `active_req:{user_id}`
  当前在途请求数
  请求开始 `INCR`，结束 `DECR`

## 7.3 用户配额预占

- `quota_reserved:{user_id}:{period_key}`
  当前周期预占 token 数

## 7.4 限流

- `rate:{scope}:{key}`
  例如 `rate:user_minute:{user_id}`

## 7.5 幂等

- `idem:{idempotency_key}`
  保存已有 request_id / 结果标识

## 7.6 模型节点健康状态缓存

- `node_health:{node_code}`

## 7.7 SSE 恢复/取消控制

- `req_status:{request_id}`
  initiated/streaming/completed/canceled

---

# 8. 鉴权与会话设计

## 8.1 登录模式

- 邮箱 + 密码
- 手机 + 密码（可选）
- OAuth 可二期扩展

## 8.2 Token 设计

- access token：短时，15~60 分钟
- refresh token：长时，7~30 天
- refresh token 存 hash 到 DB
- 支持服务端撤销 session

## 8.3 权限层级

- guest
- user
- subscriber
- admin

## 8.4 中间件职责

每次请求解析 JWT 后，在 request context 注入：

- request_id
- user_id
- current_subscription
- current_plan
- client_ip
- trace metadata

---

# 9. 会员与套餐策略

## 9.1 套餐定义

至少提供：

### Free

- 免费
- 低并发
- 低每日额度
- 低优先级
- 限定低成本模型

### Pro

- 月费主力套餐
- 中等软额度
- 更大上下文
- 更快优先级
- 主流高质量模型

### Ultra

- 更高月费
- 更高并发、更大上下文
- 更高优先级
- 高成本模型可用

## 9.2 核心原则

月费不是无限制裸奔。必须有：

- 月度软上限
- 日度公平使用阈值
- 高成本模型单独限制
- 并发上限
- 单次最大输出限制

## 9.3 订阅状态影响

- `active`：正常访问
- `trialing`：试用访问
- `past_due`：可配置宽限或降级
- `canceled` 且未到期：仍可访问到周期末
- `expired`：立即降级 Free

---

# 10. 模型路由设计

---

## 10.1 路由目标

输入：

- 用户套餐
- 指定模型
- 节点健康状态
- 节点权重
- 当前并发
- 是否支持流式
- 是否支持长上下文

输出：

- 选中的模型节点
- 对应 provider adapter

---

## 10.2 路由优先级

1. 校验用户套餐是否允许请求该模型
2. 过滤不可用节点
3. 过滤不支持请求特征的节点
4. 按 priority 排序
5. 在同优先级内做 weighted round robin
6. 若主节点失败，尝试一次同组备用节点
7. 若都失败，返回统一错误

---

## 10.3 节点状态

- `healthy`
- `degraded`
- `unhealthy`
- `draining`

路由规则：

- healthy：优先
- degraded：仅在 healthy 不足时选
- unhealthy：禁止选
- draining：仅允许已有会话延续，可配置不接新流量

---

## 10.4 路由策略接口

Codex 必须将路由策略设计成可插拔：

```python
class RoutingPolicy(Protocol):
    async def select_node(
        self,
        user_plan: Plan,
        requested_model: str,
        stream: bool,
        estimated_tokens: int,
    ) -> ModelNode:
        ...
```

首期实现：

- `WeightedPriorityRoutingPolicy`

二期可加：

- `LeastConcurrencyRoutingPolicy`
- `LatencyAwareRoutingPolicy`
- `TierAwareRoutingPolicy`

---

# 11. Chat 核心流程

这是系统最关键链路。

---

## 11.1 聊天请求输入

前端调用：
`POST /v1/chat/completions`

兼容 OpenAI 风格，但系统内部做业务扩展。

请求体核心字段：

- `conversation_id` 可选
- `messages`
- `model`
- `stream`
- `temperature`
- `max_tokens`
- `metadata`
- `idempotency_key` 可选但推荐

---

## 11.2 聊天完整时序

### Step 1：鉴权

- 解析用户身份
- 获取当前订阅与套餐
- 判断是否有访问权限

### Step 2：限流与并发校验

- 用户分钟级限流
- 用户并发计数检查
- 套餐并发限制检查

### Step 3：请求幂等

- 若有 `idempotency_key`
- 查 Redis / DB 是否已有完成或进行中的请求
- 有则直接复用结果或拒绝重复提交

### Step 4：会话准备

- `conversation_id` 不存在则创建新会话
- 写入用户消息 `messages(role=user)`
- 生成 `request_id`

### Step 5：上下文组装

- 从 Redis 取热上下文
- Redis miss 时从 DB 拉取最近 N 轮
- 按上下文窗口裁剪
- 注入系统提示词
- 估算总 token

### Step 6：配额预估与预占

- 估算输入 token
- 根据套餐和请求 `max_tokens` 计算 `reserved_tokens`
- Redis 原子预占
- 写入 `usage_ledger(status=reserved, request_status=initiated)`

### Step 7：路由选节点

- `routing_service.select_node(...)`
- 记录 node_id

### Step 8：创建 assistant 占位消息

- `messages(role=assistant, status=streaming, request_id=...)`

### Step 9：发起流式请求到模型节点

- 通过 provider adapter 转发
- 读取流式 chunk
- 边读取边：
  - 向客户端 SSE 输出
  - 缓存到内存 buffer
  - 更新心跳状态

### Step 10：流结束

- 组装完整 assistant 文本
- 更新 assistant message = completed
- 异步/同步精算 token
- 更新 ledger = finalized
- 多退少补
- 更新 quota snapshots
- conversation.latest_message_at 更新
- 热上下文回写 Redis

### Step 11：异常处理

若中途失败：

- assistant message 标记 failed 或 canceled
- ledger 进入 failed / refunded
- 释放并发计数
- 回滚预占或部分扣除策略按规则执行

---

# 12. SSE 流式协议

## 12.1 选择

使用 **SSE**，不使用 WebSocket 作为首期主通道。

## 12.2 响应头

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`

## 12.3 事件格式

兼容 OpenAI 风格，至少支持：

```text
data: {"id":"...","object":"chat.completion.chunk","choices":[...]}
```

结束：

```text
data: [DONE]
```

可扩展事件：

- `event: metadata`
- `event: error`
- `event: heartbeat`

## 12.4 心跳

每 10~15 秒可发一次注释或 heartbeat，防止上游代理断开。

---

# 13. Token 计费与配额体系

---

## 13.1 核心要求

- 不相信前端上报
- 不直接相信模型节点返回值为唯一真相
- 服务端应尽量自行精算
- 所有金额/额度变化必须可审计

---

## 13.2 三阶段计费

### 阶段 A：预估

根据请求 messages + tokenizer 估算输入 token

### 阶段 B：预占

预占 = `estimated_input_tokens + reserved_output_buffer`

建议：

- `reserved_output_buffer` = min(plan.max_output_tokens, request.max_tokens or default)
- 也可增加安全倍数

### 阶段 C：精算

流式结束后：

- 实际 prompt tokens
- 实际 completion tokens
- 实际 total tokens
- 与预占比较
- 计算 refund 或补扣

---

## 13.3 计费真相优先级

1. 服务端 tokenizer 精算值
2. 模型节点返回 usage 值
3. 预估值

若 1 与 2 差异可接受，以 1 为准；若 tokenizer 不支持该模型，可退化为 2。

---

## 13.4 扣费规则

### 成功完成

- 扣实际消耗
- 返还预占多余部分

### 用户取消

- 已生成部分按实际扣费
- 未生成部分返还

### 上游模型失败（未开始输出）

- 原则上全额返还

### 上游模型失败（已输出部分）

- 按已生成部分扣费
- 若业务策略选择“失败不收费”，则标记 waived

### 系统内部错误

- 尽量不收费或仅按已确认输出扣费
- 必须写明策略，不可模糊

---

# 14. 并发与限流

---

## 14.1 用户并发控制

每个用户同时在途请求数受套餐限制。

实现：

- Redis `INCR active_req:{user_id}`
- 若超过 `plan.max_concurrent_requests`，立即拒绝
- 请求结束 `DECR`
- 必须在 finally 中保证释放

---

## 14.2 限流维度

至少三个维度：

1. **用户级**
   - 每分钟请求数
   - 每小时请求数

2. **IP 级**
   - 未登录访问或异常攻击

3. **接口级**
   - 登录、注册、支付回调单独限制

---

## 14.3 公平使用限制

按套餐设定：

- 每日软 token 限额
- 月度软 token 限额
- 每日高成本模型次数
- 单次最大输出 token

超限策略：

- 直接拒绝
- 或自动降级模型
- 或限速排队

首期建议优先用：

- 直接拒绝或降级

不建议首期做复杂排队系统。

---

# 15. 错误处理与状态机

---

## 15.1 消息状态

- `pending`
- `streaming`
- `completed`
- `failed`
- `canceled`

## 15.2 ledger 状态

- `reserved`
- `finalized`
- `refunded`
- `waived`
- `failed`

## 15.3 请求状态

- `initiated`
- `streaming`
- `completed`
- `failed`
- `canceled`
- `timeout`

---

## 15.4 失败分类

### 用户侧

- 未授权
- 配额不足
- 并发超限
- 参数非法
- 上下文超限

### 系统侧

- DB 错误
- Redis 错误
- 节点不可用
- 上游超时
- 流中断
- token 精算失败

---

## 15.5 统一错误码建议

- `AUTH_REQUIRED`
- `SUBSCRIPTION_REQUIRED`
- `PLAN_LIMIT_EXCEEDED`
- `RATE_LIMITED`
- `CONCURRENCY_LIMITED`
- `MODEL_NOT_ALLOWED`
- `MODEL_UNAVAILABLE`
- `UPSTREAM_TIMEOUT`
- `UPSTREAM_STREAM_BROKEN`
- `CONTEXT_TOO_LARGE`
- `BILLING_RESERVATION_FAILED`
- `INTERNAL_ERROR`

---

# 16. 支付与订阅联动

---

## 16.1 支付原则

- 支付结果以 webhook 为准，不以前端跳转结果为准
- 所有 webhook 必须幂等
- 所有 provider event 必须落库

---

## 16.2 Webhook 处理流程

1. 验签
2. 查是否已处理过 `provider_event_id`
3. 落 `payment_records`
4. 解析事件类型
5. 更新 subscription 状态
6. 写 audit log
7. 返回 200

---

## 16.3 关键事件

以 Stripe 为例：

- `checkout.session.completed`
- `invoice.paid`
- `invoice.payment_failed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

---

## 16.4 订阅变更规则

### 支付成功

- 创建或延续 active 订阅

### 续费失败

- 标记 `past_due`
- 可配置宽限天数

### 取消订阅

- `cancel_at_period_end = true`
- 当前周期到期前仍可用

### 到期

- 降级 Free

---

# 17. 管理后台能力

首期至少实现：

## 17.1 用户管理

- 用户列表
- 订阅状态
- 最近登录
- 封禁/解封

## 17.2 会话与消息查询

- 搜索用户会话
- 查看消息链
- 查看失败请求

## 17.3 用量看板

- 日请求数
- 日 token 消耗
- 成功率
- 平均 TTFT
- 平均响应时长
- 节点使用率

## 17.4 节点管理

- 节点列表
- 状态
- 权重
- 手动启停/排空

## 17.5 支付审计

- webhook 事件列表
- 支付成功/失败统计

---

# 18. 日志、监控、审计

---

## 18.1 结构化日志字段

每条日志应尽量带：

- timestamp
- level
- request_id
- user_id
- path
- latency_ms
- node_code
- model
- error_code

## 18.2 指标

Prometheus 指标至少包括：

### HTTP

- 请求数
- 错误率
- P50/P95/P99 延迟

### Chat

- chat_requests_total
- chat_stream_started_total
- chat_stream_completed_total
- chat_stream_failed_total
- chat_ttft_ms
- chat_total_duration_ms

### Billing

- tokens_reserved_total
- tokens_actual_total
- tokens_refunded_total

### Node

- model_node_health
- model_node_active_requests
- model_node_ttft_ms
- model_node_tps

---

## 18.3 审计要求

以下动作必须写 audit：

- 用户注册
- 登录
- 订阅开通/取消/到期
- 管理员封禁用户
- 节点权重调整
- 手动退款/补偿

---

# 19. 安全要求

---

## 19.1 基础安全

- HTTPS only
- JWT 签名密钥强随机
- API key 加密存储
- password hash 使用 argon2 或 bcrypt
- Nginx 限流保护登录与 webhook
- CORS 白名单
- 输入长度限制

## 19.2 webhook 安全

- 严格验签
- 防重放
- 幂等处理

## 19.3 敏感信息保护

- 不在日志中打印完整 access token
- 不打印支付敏感字段
- API key 入库加密
- 用户隐私字段最小采集

---

# 20. 清理与归档策略

---

## 20.1 热数据

- 最近活跃会话保留 Redis 热上下文

## 20.2 冷数据

- 30 天前会话仍保留 PostgreSQL
- 如数据增长过大，二期可迁移归档库或对象存储

## 20.3 定时任务

- 清理过期 auth sessions
- 清理幂等缓存
- 清理失效限流键
- 对长会话生成摘要
- 对无标题会话补标题

---

# 21. API 设计

以下只列首期关键接口。

---

## 21.1 Auth

### `POST /v1/auth/register`

请求：

```json
{
  "email": "user@example.com",
  "password": "StrongPassword123"
}
```

响应：

```json
{
  "user": {...},
  "access_token": "...",
  "refresh_token": "..."
}
```

### `POST /v1/auth/login`

### `POST /v1/auth/refresh`

### `POST /v1/auth/logout`

---

## 21.2 User

### `GET /v1/users/me`

返回：

- 用户信息
- 当前订阅
- 当前套餐
- quota 摘要

---

## 21.3 Conversations

### `GET /v1/conversations`

分页返回会话列表

### `POST /v1/conversations`

新建空会话

### `GET /v1/conversations/{id}`

### `GET /v1/conversations/{id}/messages`

### `PATCH /v1/conversations/{id}`

可修改 title / pinned / archived

### `DELETE /v1/conversations/{id}`

软删除

---

## 21.4 Chat

### `POST /v1/chat/completions`

请求示例：

```json
{
  "conversation_id": "uuid-optional",
  "model": "gpt-4o-mini-like",
  "stream": true,
  "messages": [{ "role": "user", "content": "你好，介绍一下你自己" }],
  "temperature": 0.7,
  "max_tokens": 1024,
  "idempotency_key": "client-generated-uuid"
}
```

流式响应：

- 标准 SSE chunk
- 结束 `[DONE]`

非流式响应：

- 返回完整 assistant message
- 附 usage

---

## 21.5 Subscription / Billing

### `GET /v1/subscriptions/current`

### `POST /v1/subscriptions/checkout-session`

返回支付跳转地址或 session 信息

### `POST /v1/payments/webhook/stripe`

---

## 21.6 Admin

### `GET /v1/admin/users`

### `GET /v1/admin/metrics/overview`

### `GET /v1/admin/nodes`

### `PATCH /v1/admin/nodes/{id}`

### `GET /v1/admin/usage-ledger`

---

# 22. 关键服务职责说明

---

## 22.1 `chat_service.py`

负责：

- 聊天主编排
- 上下文组装
- assistant 占位消息创建
- 调用 model gateway
- SSE chunk 输出
- 异常收敛

禁止：

- 直接写复杂 SQL
- 自己实现 tokenizers
- 直接耦合支付逻辑

---

## 22.2 `routing_service.py`

负责：

- 根据套餐/请求/节点状态选节点

禁止：

- 处理 quota
- 处理消息写库

---

## 22.3 `billing_service.py`

负责：

- 预占
- 精算
- ledger 更新
- snapshots 汇总

必须做到：

- 可幂等 finalize
- 可处理重复 finalize 请求
- 可处理失败补偿

---

## 22.4 `tokenizer_service.py`

负责：

- 根据模型名选择 tokenizer
- 估算与精算 token
- 不支持时做 graceful fallback

---

## 22.5 `model_gateway_service.py`

负责：

- 屏蔽 vLLM/TGI/OpenAI-compatible 差异
- 输出统一 chunk 事件
- 处理上游超时与流异常

接口建议：

```python
class ModelGatewayService:
    async def stream_chat(
        self,
        node: ModelNode,
        payload: dict,
        timeout_s: int,
    ) -> AsyncIterator[GatewayChunk]:
        ...
```

---

# 23. Provider Adapter 设计

不要把所有上游细节写死在 chat service。

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def stream_chat(self, node: ModelNode, payload: dict) -> AsyncIterator[GatewayChunk]:
        ...

    @abstractmethod
    async def healthcheck(self, node: ModelNode) -> HealthStatus:
        ...
```

实现类：

- `OpenAICompatProvider`
- `VLLMProvider`
- `TGIProvider`

统一输出：

```python
@dataclass
class GatewayChunk:
    text_delta: str
    finish_reason: str | None = None
    raw_usage: dict | None = None
    raw_payload: dict | None = None
```

---

# 24. 幂等设计

商业系统必须强制实现。

## 24.1 聊天请求幂等

若前端传 `idempotency_key`：

- Redis 查 `idem:{key}`
- 若状态为 completed，返回已有结果
- 若状态为 processing，可拒绝重复提交
- 最终将 `request_id` 绑定到 key

## 24.2 Webhook 幂等

- 以 `provider_event_id` 做唯一约束
- 已处理则直接忽略返回成功

## 24.3 Finalize 幂等

- `usage_ledger.request_id` 唯一
- finalize 只允许从 `reserved` -> `finalized/refunded/waived`
- 重复调用不允许再次扣费

---

# 25. 超时与取消策略

---

## 25.1 上游超时

分两类：

- 连接超时
- 流读取空转超时

建议：

- 连接超时 5~10s
- 首字超时 30~60s
- 流空闲超时 60~120s

## 25.2 客户端断开

当检测到客户端断开：

- 尝试终止上游连接
- assistant message 标记 canceled
- 实际已生成部分按策略扣费
- 释放并发计数

## 25.3 手动取消

可二期提供：
`POST /v1/chat/requests/{request_id}/cancel`

---

# 26. 配置项清单

应通过环境变量或配置文件管理：

```env
APP_ENV=production
APP_NAME=platform-core
APP_PORT=8000

JWT_SECRET=...
JWT_ACCESS_EXPIRE_MINUTES=30
JWT_REFRESH_EXPIRE_DAYS=14

POSTGRES_DSN=...
REDIS_URL=...

DEFAULT_CHAT_MODEL=...
DEFAULT_STREAM_TIMEOUT_SECONDS=120

RATE_LIMIT_USER_PER_MINUTE=20
RATE_LIMIT_LOGIN_PER_MINUTE=5

FREE_MAX_CONCURRENT=1
PRO_MAX_CONCURRENT=2
ULTRA_MAX_CONCURRENT=4

TITLE_GEN_ENABLED=true
SUMMARY_GEN_ENABLED=true

STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...

SENTRY_DSN=...
PROMETHEUS_ENABLED=true
```

---

# 27. 部署方案

## 27.1 首期部署

推荐 Docker Compose：

- nginx
- app
- postgres
- redis
- prometheus
- grafana
- node-exporter

## 27.2 FastAPI 运行建议

4 核机器建议：

- gunicorn workers: 2~4
- worker class: uvicorn workers
- 主要依赖 async IO，不要盲目开过多 worker

## 27.3 Nginx 关键配置

- 支持 SSE 不缓冲
- 适当的 proxy_read_timeout
- 限流登录接口与 webhook
- HTTPS 终止

关键点：

```nginx
proxy_buffering off;
proxy_cache off;
chunked_transfer_encoding on;
```

---

# 28. 开发阶段划分

---

## Phase 1：基础骨架

目标：

- 工程骨架
- 配置加载
- DB/Redis 接入
- JWT 鉴权
- 用户注册登录
- Alembic 初始化

验收：

- 能注册、登录、获取 `/me`

---

## Phase 2：会话与消息

目标：

- conversations CRUD
- messages 存储
- 会话列表与消息列表

验收：

- 用户能创建会话、查看历史消息

---

## Phase 3：流式聊天主链路

目标：

- `/v1/chat/completions`
- SSE 输出
- 上游模型转发
- assistant message 占位与完成写库

验收：

- 前端能看到稳定流式吐字
- 会话消息完整落库

---

## Phase 4：计费与配额

目标：

- token 预估
- 预占
- ledger
- finalize
- snapshots

验收：

- 每次请求账本完整
- 失败/取消不出现脏账

---

## Phase 5：限流、并发、路由

目标：

- 用户并发控制
- Redis 限流
- 节点健康检查
- 主备切换

验收：

- 超限用户被拒绝
- 主节点挂掉时可切备

---

## Phase 6：支付与订阅

目标：

- checkout session
- webhook
- 订阅联动
- 套餐权限生效

验收：

- 支付成功后权限实时变化
- webhook 幂等正确

---

## Phase 7：后台与监控

目标：

- admin metrics
- user admin
- node admin
- prom metrics
- sentry

验收：

- 可以定位失败请求与节点问题

---

# 29. 测试策略

---

## 29.1 单元测试

覆盖：

- routing policy
- billing finalize
- token estimation
- subscription permission
- idempotency

## 29.2 集成测试

覆盖：

- auth + db + redis
- chat stream + db persistence
- webhook + subscription update

## 29.3 端到端测试

覆盖：

- 用户购买会员 -> 发起聊天 -> 消耗 quota -> 查看会话

## 29.4 必测异常

- SSE 中途断流
- 上游 500
- 上游超时
- Redis 短暂不可用
- DB 提交失败
- finalize 重复执行
- webhook 重复到达

---

# 30. 验收标准

---

## 30.1 功能验收

- 用户可注册登录
- 用户可购买月费套餐
- 用户可发起流式聊天
- 消息与会话正确保存
- 用量统计正确
- 套餐限制正确生效

## 30.2 稳定性验收

- 单节点模型故障可切换
- 流式过程中客户端断开不产生死锁
- 并发计数不会泄漏
- 账本不会重复扣费

## 30.3 运维验收

- 管理后台能看到节点状态
- Prometheus 能看到关键指标
- 错误能进入 Sentry
- 支付 webhook 可追溯

---

# 31. 明确不做的事

首期不做：

- 真正复杂的任务队列编排平台
- 多租户企业组织模型
- 文件检索/RAG
- 图像生成
- WebSocket 主通道
- 复杂排队系统
- 自动内容审查系统
- Kubernetes-first 部署
- 过度微服务拆分

这些都可以二期做，但首期不要污染主链路。

---

# 32. 给 Codex 的执行约束

以下约束建议直接写进 AI IDE 全局规则。

## 32.1 开发约束

1. 所有模块必须有明确职责边界
2. 严禁在 route handler 中写大段业务逻辑
3. 严禁绕过 service 直接操作跨域业务
4. 所有状态变更必须显式
5. 所有 DB migration 必须使用 Alembic
6. 所有关键写操作必须考虑幂等
7. 所有异常必须映射成统一错误码
8. 所有流式接口必须保证 finally 释放并发占位
9. 所有账务逻辑必须可重复执行且不重复扣费
10. 所有 provider 差异必须封装在 adapter 内

## 32.2 代码质量约束

- 类型注解完整
- Pydantic schema 明确区分 request/response/internal
- 服务层函数保持短小
- 仓储层只处理数据访问
- 中间件只处理横切逻辑
- 日志必须结构化
- 单元测试优先覆盖策略与计费

---

# 33. 给 Codex 的首批任务拆分

可直接让 Codex 按以下顺序开工：

## Task 1

初始化项目骨架：

- FastAPI app
- config
- logging
- db
- redis
- health endpoints
- alembic

## Task 2

实现用户认证：

- users/auth_sessions tables
- register/login/refresh/logout
- JWT
- password hashing

## Task 3

实现 plans/subscriptions schema 与基础 service

## Task 4

实现 conversations/messages CRUD

## Task 5

实现 model_nodes、provider adapter 抽象、healthcheck

## Task 6

实现 `/v1/chat/completions` 的非流式版本

## Task 7

扩展为 SSE 流式版本

## Task 8

实现 usage_ledger + quota_snapshots + billing finalize

## Task 9

实现 Redis 并发控制、限流、中断释放

## Task 10

实现支付 checkout + webhook + 订阅联动

## Task 11

实现 admin metrics / node admin / usage query

## Task 12

补齐 tests、错误码、Sentry、Prometheus

---

# 34. 最终架构结论

对你当前 **4核24G 控制面主机**，最合理的不是大而全微服务，而是：

**模块化单体 + Postgres + Redis + SSE + 可插拔路由 + 商业账本式计费 + 支付订阅闭环**

这套架构是本次任务的参考 但不是完全约束 你有自主决定核思考的空间。

最好直接部署到服务器 不要在本地测试

- SSH：

````bash
ssh -i 'k.key' ubuntu@40.233.67.228
```   域名  chat.202574.xyz.
注意 不要影响核修改服务器上的其他服务 可以复用已经部署的基础设施。
````

**注意 在适当的时候 保持记录工程进度的操作 保存到project.md**
