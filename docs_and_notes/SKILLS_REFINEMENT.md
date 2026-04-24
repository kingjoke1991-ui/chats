# Chat Oracle - 流程与技能沉淀

## SKILL-001: 服务器部署流程

### 流程描述
1. 本地修改代码
2. 通过 SSH 将变更同步到服务器 `/home/ubuntu/chat-oracle`
3. 在服务器上执行 `docker compose up -d --build`
4. 若有数据库变更，在 app 容器内执行 `alembic upgrade head`
5. 验证 `https://chat.202574.xyz/health/live`

### 优化理由
每次部署都需要这套固定步骤，标准化可减少遗漏

### 标准化指令
```bash
# SSH 连接
ssh -i 'k.key' ubuntu@40.233.67.228

# 部署
cd /home/ubuntu/chat-oracle
docker compose -f deploy/compose/docker-compose.yml up -d --build

# 验证
curl https://chat.202574.xyz/health/live
```

---

*更多条目将在后续开发中持续添加*
