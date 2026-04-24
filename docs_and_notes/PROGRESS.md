# Chat Oracle - 工程进度

## 当前已上线能力
- 用户注册、登录、刷新、退出
- `/chat` 用户聊天界面
- `/admin` 管理后台
- 会话列表、消息记录、会话删除
- OpenAI-compatible 模型路由
- SSE 流式聊天输出
- 套餐、订阅、支付订单链路
- BEPUSDT 下单、查单、回调
- 手机号码内部命令链路
- Telegram Userbot 桥接链路
- `#搜索` 通用网页搜索模块
- `#千度` 中文语境增强搜索模块

## 当前内部命令
- `获取一个号码`
- `读取当前号码缓存短信`
- `获取最新短信列表`
- `#查询 xxx`
- `#搜索 xxx`
- `#千度 xxx`（兼容别名：`#千 xxx` / `#千问 xxx`）

## 2026-04-22 新增进展
- 新增独立的 `qiandu_search` 模块，入口为 `#千度`
- `#千度` 与 `#搜索` 分离，按可迁移模块方式封装
- 搜索 provider 已接入：
  - `Tavily`
  - `Exa`
  - `SearXNG`
  - `Snoop` 本地工具包装
  - `WeChat-Crawler` 风格的公众号本地工具包装
- 正文抽取已接入：
  - `Crawl4AI`
  - `HttpFallbackExtractor`
- 已支持按意图切换搜索策略：
  - 社交 ID 优先 `snoop`
  - 公众号优先 `wechat_crawler`
  - 企业主体优先 `qcc.com` / 企业信息方向
- `QianduSearchLLMOrchestrator.build_plan` 已增加启发式回退，不再因远端规划模型异常直接硬失败
- `SearXNG` 已部署到服务器，并启用 `baidu` / `sogou`
- `Crawl4AI`、`Playwright`、`/opt/snoop` 已随应用镜像安装
- 本地工具已增加降级逻辑：
  - `SearXNG` 公众号搜索为空时，自动回退到 `Tavily`
  - `Snoop` demo 无法输出结构化结果时，自动回退到定向社交站点搜索

## #千度 当前真实落地状态
- 代码、配置、镜像依赖、部署已完成
- 服务器运行时校验通过：
  - `crawl4ai = True`
  - `playwright = True`
  - `/opt/snoop = True`
- `Exa` key 已注入后端环境并验证通过：
  - `ExaQianduProvider().search('OpenAI latest model')` 返回 `10` 条结果
- 线上健康检查通过：
  - 内网 `http://127.0.0.1:18000/health/live`
  - 公网 [https://chat.202574.xyz/health/live](https://chat.202574.xyz/health/live)
- 公众号本地工具验证通过：
  - `run_wechat_public_search('腾讯')` 返回 `8` 条结果
- 社交账号本地工具验证通过：
  - `run_snoop_search('jack')` 返回 `10` 条回退结果

## 2026-04-23 新增进展
### Telegram Audit Gemini 增强
- `#查询` 的 txt 清洗链路新增独立审计节点 `telegram-audit-gemini`
- 节点默认使用 Gemini OpenAI 兼容接口：
  - `https://generativelanguage.googleapis.com/v1beta/openai`
  - model: `gemini-2.5-flash`
- `OpenAICompatProvider` 已支持优先使用节点级 API key，不再强制复用全局远端 LLM key
- `ModelNodeService` 启动时会自动同步 Gemini 审计节点；只有配置了 `TELEGRAM_AUDIT_GEMINI_API_KEY` 才会启用
- `TelegramParseService` 审计选路现在优先命中 `settings.telegram_audit_node_code`
- 即使 Gemini 清洗失败，`#查询` 仍会回退到本地规则清洗，不会卡死，也不会整段原样吐回 txt
- 当前线上主模型已直接切换为 `gemini-2.5-flash`

### 审计提示词（Clean Prompt）升级
- **提示词更新**：更新了 `TELEGRAM_AUDIT_SYSTEM_PROMPT`，采用更详细的结构化提取逻辑。
- **实体聚合优化**：识别并聚合互不相同的个体，支持按身份证、手机号、多重重合信息（地址/学校/单位）进行唯一性判定。
- **动态实体注入**：提示词支持根据真实查询内容动态注入核心实体（替换 “xxx” 占位符）。
- **输出格式规范化**：采用 Markdown 列表 + 特征简述格式，涵盖基本信息、联系方式、地理信息、教育工作、网络账号及关联关系等。
- **链路传递优化**：`TelegramBridgeService` 现已将 `query_text` 向下传递至审计解析层。

- **跨来源打分强化**：强制 `court.gov.cn` 及被识别社交平台的检索源权重提升，优化并保证深广度检索时高价值长尾数据点（社交账户、法律状态）不丢失。

### #千度 结构化数据多阶段搜索流程升级
- **双模式架构**：新增 `detect_structured_input` 逻辑，自动识别简单查询与结构化数据转储（如 KaliSGK 格式）。
- **多阶段流水线**：针对结构化数据，实现“实体提取 -> 搜索任务编排 -> 并发搜索执行 -> 情报融合总结”四阶段流程。
- **并发搜索加速**：采用 `asyncio.gather` 并发执行多条衍生搜索任务，大幅提升深度查询效率。
- **长报告下载集成**：整合 `TelegramDownloadService`，为超长分析报告提供独立下载/预览链接。

### SearXNG 代理增强
- **SOCKS5h 代理配置**：为服务器端 `SearXNG` 实例配置了 SOCKS5h 代理（`socks5h://...`），支持远程 DNS 解析。
- **验证通过**：经实测，`baidu` 和 `sogou` 引擎在代理模式下已恢复工作，单次查询可返回 20+ 条有效结果。

## 当前已知限制
- `Exa` key 已记录并允许通过后端环境变量设置，线上是否使用取决于当前 `.env`
- `SearXNG` 的 `baidu` / `sogou` 现已通过 SOCKS5h 代理运行，绕过了之前的 CAPTCHA 限制。
- 当前 `Snoop` 仓库为公开 demo 版，`--web-base` 受限，因此账号搜索实际上依赖自动回退策略，而不是 full version 的原生命中
- `#千度` 结构化流水线在处理极大量任务时可能会面临 LLM Token 限制或超时（当前超时设定为 90s-120s）。

## 下一步建议
- 验证结构化数据流水线在生产环境的端到端效果（特别是长报告生成的下载链接）。
- 监控代理 IP 的稳定性，必要时配置多代理轮询。
- 社交账号搜索若要提升命中率，需进一步优化 Snoop 的回退解析正则。

## 相关记录
- [Backend Runtime Secrets 2026-04-22](L:/project/chat-oracle/docs_and_notes/BACKEND_RUNTIME_SECRETS_2026-04-22.md)
- [Telegram Bridge Record 2026-04-21](L:/project/chat-oracle/docs_and_notes/TELEGRAM_BRIDGE_2026-04-21.md)
- [Search Architecture 2026-04-22](L:/project/chat-oracle/docs_and_notes/SEARCH_ARCHITECTURE_2026-04-22.md)

## 2026-04-23 Telegram Audit Gemini
- `#查询` 的 txt 清洗链路新增独立审计节点 `telegram-audit-gemini`
- 节点默认使用 Gemini OpenAI 兼容接口：
  - `https://generativelanguage.googleapis.com/v1beta/openai`
  - model: `gemini-2.5-flash`
- `OpenAICompatProvider` 已支持优先使用节点级 API key，不再强制复用全局远端 LLM key
- `ModelNodeService` 启动时会自动同步 Gemini 审计节点；只有配置了 `TELEGRAM_AUDIT_GEMINI_API_KEY` 才会启用
- `TelegramParseService` 审计选路现在优先命中 `settings.telegram_audit_node_code`
- 即使 Gemini 清洗失败，`#查询` 仍会回退到本地规则清洗，不会卡死，也不会整段原样吐回 txt
- 当前线上主模型已直接切换为 `gemini-2.5-flash`
- 仍保留兜底回退：
  - `gemini-2.5-pro`
  - `gemini-pro-latest`

## 2026-04-24 新增进展
- **仓库初始化与同步**：成功在 GitHub 创建 `chats` 仓库并将本地工程完整上传，实现了代码的云端托管。
- **核心分支合并**：完成 `origin/devin/1777001380-qiandu-comprehensive-osint` 的本地合并与推送，同步了最新的“#千度”多阶段 OSINT 流水线。
- **生产环境完整部署**：针对大规模重构，采用了 `tar` 打包同步方案（排除敏感文件），并在服务器端完成 Docker 镜像重建与应用热重启。
- **代码安全加固**：优化了 `.gitignore` 配置，自动排除 `SECRETS` 类文档及本地密钥文件（k.key 等），确保敏感信息不流入 GitHub 仓库。

## 2026-04-24 `#千度` 模块优化（本次）
针对审查报告中 `qiandu_search` 模块的问题，完成了 10 项内部优化，保留 `qiandu_search` / `web_search` 独立封装（未合并）：
1. 维度 / 别名 / 领域白名单 / 关键词统一到 `app/services/qiandu_search/dimensions.py`，`service.py` 和 `llm.py` 只引用，不再各维护一份。
2. `match_command` 支持 `#千 xxx` / `#千度 xxx` / `#千问 xxx` 三种等价写法，兼容历史文档与移动端。
3. `should_trigger_intel_pipeline` 从「任意 ≥2 字」改为信号驱动打分（手机号 +2 / 身份证 +2 / 邮箱 +1 / `@handle` +1 / 公司名 +1 / 维度关键词 +1 / 多名 +1 / 长输入 +1），阈值可经 `QIANDU_INTEL_SIGNAL_THRESHOLD` 调节，默认 2。路由结果通过 `metadata.pipeline_router` 暴露给调用方。
4. intel pipeline 外包一层 `asyncio.wait_for(..., QIANDU_TOTAL_BUDGET_SECONDS)` 硬预算，超时自动降级到 simple pipeline 并写入 `degradations`。
5. provider 全局 `asyncio.Semaphore`：远端 API (`QIANDU_PROVIDER_CONCURRENCY`) 与本地工具 (`QIANDU_LOCAL_TOOL_CONCURRENCY`) 分开限流；intel 任务自身也有 `QIANDU_INTEL_TASK_CONCURRENCY` 的并发上限。
6. `Crawl4AIMarkdownExtractor` 改为进程级共享浏览器池 + `QIANDU_CRAWL4AI_CONCURRENCY` 限流，`app_shutdown` 里统一回收；通过 `QIANDU_CRAWL4AI_SHARED_BROWSER=false` 可回退到原来的「每次重建」行为。
7. `_score_result` 的 `must_include` 由硬过滤 (`-100`) 改为软权重 (`+6 / -4`)，避免 provider snippet 截断时把真命中挡在外面。
8. `LocalCommandSearchProvider` 从 `create_subprocess_shell` 改成 `create_subprocess_exec + shlex.split`，消除命令注入风险，并在可执行文件缺失时给出明确错误码。
9. `service.py` / `providers.py` / `local_tools.py` 里零散的 `except Exception: pass` 换成 `logger.warning/exception` + `degradations.append(...)`，provider / extractor / synth / fuse 的失败会在返回 metadata 里以结构化字符串汇总。
10. `QianduSearchLLMOrchestrator._select_node` 真实执行 `requested_model` → qiandu 首选节点 → `allowed_models` 的兜底匹配，不再丢弃入参。
11. simple pipeline 复用 intel pipeline 的溢出处理：长结果自动走 `TelegramDownloadService` 生成下载链接，下载失败则写入 `degradations` 并截断。
12. 测试补齐：`match_command` 多别名、`classify_trigger` 评分、`must_include` 软打分回归、provider 崩溃时的 `degradations` 暴露、`dimensions` 模块单一真相。当前 `pytest -q` 59 passed。
