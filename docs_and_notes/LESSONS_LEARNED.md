# Chat Oracle - 经验总结与错误库

## 架构决策记录

### DEC-001: 选择 FastAPI 单体模块化
- **决策**: 使用 FastAPI 模块化单体而非微服务
- **理由**: 4核24G 控制面主机，单体架构减少运维复杂度和资源开销
- **结果**: 分层清晰 (API → Service → Repo → Model)，后续可按边界拆分

### DEC-002: 使用 Caddy 而非 Nginx
- **决策**: 复用服务器现有 Caddy 作为反向代理
- **理由**: 服务器已有 Caddy 在运行，添加站点配置即可，无需额外部署 Nginx
- **注意**: Caddy admin API 已关闭，需重启容器加载新配置

### ERR-001: 跨容器与宿主机网络超时 (`host.docker.internal` 在 Linux 上的隔离限制)
- **技术栈 (Tech Stack)**: Docker Compose, Linux Firewall (iptables), UFW.
- **错误点 (Error Point)**: 在 Docker 容器内使用 `host.docker.internal` 或者 `172.17.0.1` 访问宿主机中绑定的 `0.0.0.0:11435` LLM 推理接口，提示 Connection Refused 或 Timeout。
- **诱因 (Root Cause)**: Linux 上 `host.docker.internal` 需要结合 `--add-host` 显式设置网关IP。但即使通信链路物理联通，如果宿主机的服务只绑定了 `127.0.0.1`，或者 Docker 会生成特定的 iptables 防火墙策略隔离网桥流入本机的请求，都会被拦截。
- **解决方案 (Resolution)**: 
  - 第一步：确保服务 (如 llama.cpp) 绑定到 `0.0.0.0` 而非 `127.0.0.1`。
  - 第二步：通过 Docker network inspector 或 `ip route` 获取网关 IP (`172.21.0.1`) 访问。
  - 第三步：如果宿主机 `iptables INPUT` 只放行 `22/80/443`，需要额外允许 Docker 网段访问本地推理端口，例如 `iptables -I INPUT 4 -s 172.16.0.0/12 -p tcp --dport 11435 -j ACCEPT`，否则容器内健康检查会把本地节点判成 `unhealthy`。
  - 临时解决与快速闭环：在主服务中建立一层内建的 Mock Fallback。当捕捉到底层的 `AppException` 包含 Connection / timeout 时，直接组装一段打字机 Mock 数据输出。这允许即使在物理节点掉队的环境下，也不阻塞 UI、流式推送与账单统计的常规逻辑测试。

### DEC-003: 基础依赖容器需要随主应用一起自启动
- **决策**: `postgres` 和 `redis` 在 Compose 中也必须配置 `restart: unless-stopped`
- **理由**: 如果主机重启后只有 `app` 自动拉起，而数据库和缓存维持停止状态，应用会在启动阶段直接失败并导致前端站点对外表现为 `502`
- **结果**: 部署配置应保证 `postgres` / `redis` / `app` 的重启策略一致，避免控制面“代理在、后端不在”的半故障状态

### ERR-002: Caddy 默认缓冲阻断 Server-Sent Events 流式传输 
- **技术栈 (Tech Stack)**: Caddy Server, FastAPI StreamingResponse.
- **错误点 (Error Point)**: 后端 API 返回 `text/event-stream` 大量分块，但前端并非逐字接收，而是一次性或大分块弹出。
- **诱因 (Root Cause)**: 现代反向代理（如 Nginx、Caddy）默认会尝试缓冲后端数据并压缩后才给客户端发包。
- **解决方案 (Resolution)**: 在 Caddyfile 的 `reverse_proxy` 路由块中，增加 `flush_interval -1`，彻底禁用缓冲，直接穿透将分块下推。
```caddy
reverse_proxy 127.0.0.1:18000 {
    flush_interval -1
}
```

---

### ERR-003: Windows 到 Linux 的大文件/多目录同步效率瓶颈
- **技术栈 (Tech Stack)**: PowerShell, SSH, tar, Docker Compose.
- **错误点 (Error Point)**: 传统的 `scp -r` 在同步包含大量源码文件或深层目录结构（尤其是包含虚拟环境或 `.git` 时）速度极慢，且难以做到原子性更新。
- **诱因 (Root Cause)**: SCP 采用逐个文件传输协议，对于小文件极多的场景 IO 等待严重。
- **解决方案 (Resolution)**: 
  - 第一步：使用 Windows 10+ 自带的 `tar` 工具将 `app`, `deploy`, `migrations` 等核心目录打包。
  - 第二步：通过 `scp` 一次性上传压缩包（减少连接建立开销）。
  - 第三步：利用 SSH 组合指令完成“解压 -> 构建 -> 清理”闭环：`cd path && tar -xzf project.tar.gz && docker compose up -d --build app && rm project.tar.gz`。
- **结果**: 实现秒级代码同步，且保证了远程端代码在构建前的完整性。

*更多条目将在后续开发中持续添加*
