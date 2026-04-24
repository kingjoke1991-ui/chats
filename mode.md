# Oracle e2b / Hermes 切换记录

更新时间：2026-04-15

## 1. Oracle 上的 e2b 输出配置

当前 Oracle 机器上的本地 E2B 推理服务由 `llama-server.service` 托管，配置如下：

- 服务名：`llama-server.service`
- 状态：`active (running)`
- 二进制：`/home/ubuntu/llama.cpp-gemma4/build/bin/llama-server`
- 模型文件：`/opt/openclawai/models/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive-Q6_K_P.gguf`
- 模型别名：`gemma-4-e2b-q6_k_p`
- 端口：`127.0.0.1:11435`
- 启动参数：
  - `-m /opt/openclawai/models/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive-Q6_K_P.gguf`
  - `--alias gemma-4-e2b-q6_k_p`
  - `--reasoning off`
  - `-c 100000`
  - `-t 4`
  - `--parallel 1`
  - `--host 127.0.0.1`
  - `--port 11435`

运行状态补充：

- `GET /v1/models` 返回 `gemma-4-e2b-q6_k_p`
- 该服务当前是纯文本 GGUF，本地没有多模态投影
- `llama-server` 日志里提示 gemma4 chat template 较旧，但服务已正常加载并监听

## 2. Hermes 是否能直接用 e2b

可以。

当前 Hermes 的本地切换脚本已经直接指向 Oracle 的 E2B：

- 本地 E2B：`/Volumes/extre/tools/agent/hermes-local.sh`
- 远端 sd3：`/Volumes/extre/tools/agent/hermes-remote.sh`
- 混合模式：`/Volumes/extre/tools/agent/hermes-hybrid.sh`

`hermes-local.sh` 的行为：

- 把 `/home/ubuntu/.hermes/config.yaml` 里的 `model.base_url` 改成 `http://127.0.0.1:11435/v1`
- 把 `model.api_key` 设成 `dummy`
- 把 `model.default` 改成 `gemma-4-e2b-q6_k_p`
- 把 `model.context_length` 压到 `65536`，既满足 Hermes 的最小值要求，也比原来的 100k 更轻
- 把当前安装的 Hermes skills 以及 builtin skills 全部禁用，避免技能索引把系统提示撑到几千 token
- 把 `display.streaming` 和 `streaming.enabled` 都打开，确保 Hermes 网关能实时编辑输出
- 给 `hermes-gateway.service` 和 `hermes-dashboard.service` 写入 `HERMES_SKIP_CONTEXT_FILES=1` 的 systemd drop-in，避免自动注入 `AGENTS.md` / `SOUL.md` / `.cursorrules`
- 把 `memory.memory_enabled` 和 `memory.user_profile_enabled` 关掉，避免 `MEMORY.md` / `USER.md` 继续膨胀系统提示
- 然后重启 `hermes-gateway.service` 和 `hermes-dashboard.service`

`hermes-hybrid.sh` 的行为：

- 主模型保持 `sd3`
- fallback 增加本地 `e2b`
- 同时在 `custom_providers` 里注册本地 `local-e2b`
- 不改全局 skills/toolset/streaming，保留远端模型的默认配置
- 显式恢复 `memory.memory_enabled` 和 `memory.user_profile_enabled`

## 3. 结论

- Hermes 可以直接手动切到本地 `e2b`
- 如果要临时验证本地模型，直接跑 `hermes-local.sh`
- 如果要保留远端主路并在故障时回退，跑 `hermes-hybrid.sh`
- `hermes-remote.sh` 会清掉 e2b 专用覆盖，恢复远端默认配置
- 目前不建议把 `hermes-local.sh` 当成长期默认配置，除非你就是想完全离线跑本地模型

## 4. Oracle 侧部署

Oracle 服务器上已同步部署直接执行版脚本到：

- `/home/ubuntu/bin/hermes-local.sh`
- `/home/ubuntu/bin/hermes-remote.sh`
- `/home/ubuntu/bin/hermes-hybrid.sh`

这三份是 Oracle 本机直接改写 `~/.hermes/config.yaml` 的版本，不依赖本地 SSH wrapper。
