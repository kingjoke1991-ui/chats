# Chat Oracle

`chat-oracle` 是面向商业聊天场景的控制面后端，当前栈为 `FastAPI + PostgreSQL + Redis + Alembic`。

当前已经落地的闭环：

- 用户注册、登录、刷新、退出
- `/chat` 用户聊天入口，支持真实 SSE 流式输出
- `/v1/conversations` 会话 CRUD，含删除
- `/admin` 管理后台，支持用户、节点、套餐、订单、会话查询
- 模型节点健康检查与本地优先、远端回退
- BEpusdt 订阅支付下单、查单与回调处理
- 支付订单台账与订阅生效链路

## 目录

```text
app/
  api/
  core/
  models/
  repos/
  schemas/
  services/
deploy/
  caddy/
  compose/
migrations/
tests/
```

## 本地启动

```bash
cp .env.example .env
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker 部署

```bash
docker compose -f deploy/compose/docker-compose.yml up -d --build
```

默认会将应用绑定到 `127.0.0.1:18000`，供反向代理接入。

## 当前入口

- 用户聊天: `https://chat.202574.xyz/chat`
- 管理后台: `https://chat.202574.xyz/admin`

## 管理员引导账号

- 邮箱: `admin@chatoracle.dev`
- 密码: `ChatOracleAdmin!2026`

## 支付配置

订阅支付使用 `BEpusdt` 接口，至少需要配置以下环境变量：

- `PUBLIC_BASE_URL`
- `BEPUSDT_BASE_URL`
- `BEPUSDT_API_TOKEN`
- `BEPUSDT_CURRENCIES`
- `BEPUSDT_TIMEOUT_SECONDS`
- `BEPUSDT_REQUEST_TIMEOUT_SECONDS`
- `BEPUSDT_TRADE_TYPE`
- `BEPUSDT_REDIRECT_PATH`
