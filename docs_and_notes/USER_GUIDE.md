# Chat Oracle - 使用说明

## 运行环境

- Python 3.12+
- PostgreSQL 16
- Redis 7
- Docker / Docker Compose

## 本地开发

```bash
cp .env.example .env
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 主要入口

- 用户聊天页: `/chat`
- 管理后台: `/admin`
- 当前用户信息: `/v1/users/me`
- 当前订阅: `/v1/subscriptions/current`
- 套餐列表: `/v1/subscriptions/plans`
- 支付订单列表: `/v1/subscriptions/orders`
- 创建支付订单: `/v1/subscriptions/checkout-session`
- 同步待支付订单: `/v1/subscriptions/orders/sync`
- 支付 provider 回调入口: `/v1/payments/webhook/bepusdt`

## 管理员账号

- 邮箱: `admin@chatoracle.dev`
- 密码: `ChatOracleAdmin!2026`

## 模型路由

- 优先 `mode.md` 本地模型
- 本地不可达时自动切到 `models.md` 远端模型

## 支付说明

- 套餐购买通过 BEpusdt 创建订单
- 支付成功后，BEpusdt 会调用本系统 webhook；前端回跳后也会主动查单兜底同步
- webhook 验签通过后会更新订单状态并自动激活新订阅
