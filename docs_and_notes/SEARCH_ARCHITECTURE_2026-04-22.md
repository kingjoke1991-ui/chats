# Search Architecture 2026-04-22

## 背景
工程原本已有一套 `#搜索` 通用网页搜索链路，偏向官方文档、英文网页、changelog 和最新信息场景。

为了覆盖中文语境下的情报式检索，又新增了独立的 `#千度` 模块，目标包括：
- 中国社交账号 / ID 检索
- 公众号检索
- 企业主体 / 法人 /股东 / 注册信息检索
- 需要登录态或浏览器级抓取的网页

## 命令入口
- `#搜索 xxx`
  - 通用 Web Search
  - 优先官方站点、文档、新闻、更新日志
- `#千度 xxx`（也接受 `#千 xxx` / `#千问 xxx`，等价别名，便于移动端手残输入）
  - 中文语境增强检索
  - 优先处理社交账号、公众号、企业信息、多源拼接
  - 信号驱动路由：含手机号 / 身份证 / 邮箱 / `@handle` / 公司名 / 维度关键词（法人/裁判/学历/公众号…）时触发 intel pipeline；仅含一个普通中文名则走 simple pipeline
  - 可通过 `QIANDU_INTEL_SIGNAL_THRESHOLD`（默认 2）调整触发阈值
  - 全流水线由 `QIANDU_TOTAL_BUDGET_SECONDS`（默认 240s）硬时限保护，超时自动降级到 simple pipeline
  - provider 并发由 `QIANDU_PROVIDER_CONCURRENCY`、`QIANDU_LOCAL_TOOL_CONCURRENCY` 限流；Crawl4AI 浏览器进程级复用，由 `QIANDU_CRAWL4AI_CONCURRENCY` 限制同时运行的页面数
  - provider / extractor / synth / fuse 中的失败会以 `degradations` 字段汇总到返回 metadata，便于用户看到哪条路被降级了

## 模块边界
`#千度` 采用独立包：
- [__init__.py](L:/project/chat-oracle/app/services/qiandu_search/__init__.py)
- [models.py](L:/project/chat-oracle/app/services/qiandu_search/models.py)
- [llm.py](L:/project/chat-oracle/app/services/qiandu_search/llm.py)
- [providers.py](L:/project/chat-oracle/app/services/qiandu_search/providers.py)
- [local_tools.py](L:/project/chat-oracle/app/services/qiandu_search/local_tools.py)
- [service.py](L:/project/chat-oracle/app/services/qiandu_search/service.py)

聊天接入口：
- [chat_service.py](L:/project/chat-oracle/app/services/chat_service.py)

## 技术路径
1. 用户发送 `#千度 xxx`
2. `QianduSearchService.match_command` 命中内部命令
3. `QianduSearchLLMOrchestrator.build_plan` 产出搜索计划：
   - `queries`
   - `intent`
   - `topic`
   - `include_domains`
   - `exclude_domains`
   - `preferred_providers`
4. `QianduSearchService` 按意图重排 provider 顺序
5. provider 联合搜索：
   - `Snoop`
   - `WeChat-Crawler`
   - `Tavily`
   - `Exa`
   - `SearXNG`
6. extractor 抽取正文：
   - `Crawl4AI`
   - `HttpFallbackExtractor`
7. 本地 chunk + rerank
8. LLM 基于证据生成最终回答，并附来源链接

## Provider 设计
### Tavily
- 作为广度搜索主力
- 也是当前线上最稳定的后备搜索源
- 在 `SearXNG` 或 `Snoop` 不可用时承担兜底

### Exa
- 负责深度语义搜索
- 代码已接好，并支持两种后端环境变量：
  - `QIANDU_EXA_API_KEY`
  - `EXA_API_KEY`
- 当前记录值见：
  - [Backend Runtime Secrets 2026-04-22](L:/project/chat-oracle/docs_and_notes/BACKEND_RUNTIME_SECRETS_2026-04-22.md)
- 2026-04-22 已在线验证：
  - `ExaQianduProvider().search('OpenAI latest model')` 返回 `10` 条结果
- 当前参数按官方文档修正为：
  - `type="auto"`
  - `contents.highlights.maxCharacters`
  - 不再使用已废弃的 `numSentences` / `highlightsPerUrl`

### SearXNG
- 以独立服务部署，当前 compose 中服务名为 `searxng`
- 当前启用引擎：
  - `baidu`
  - `sogou`
- 真实线上状态：
  - 服务健康
  - 查询可达
  - 但百度和搜狗都会触发 CAPTCHA，日志可见 `SearxEngineCaptchaException`
- 因此目前它更像“已接好但不稳定的备路”

### Snoop
- 通过本地 CLI 包装接入
- 当前默认命令：
  - `python -m app.services.qiandu_search.local_tools snoop --query {query}`
- 镜像中已自动拉取：
  - `/opt/snoop`
- 真实线上状态：
  - 公开 demo 版可运行
  - 但 `--web-base` 属于 full version 功能，demo 不会产出真正可用 CSV
- 为避免空结果，已实现自动降级：
  - 发现 demo 限制或无 CSV 时，回退到定向社交站点搜索

### WeChat-Crawler 风格本地工具
- 当前默认命令：
  - `python -m app.services.qiandu_search.local_tools wechat --query {query}`
- 优先尝试 `SearXNG` 搜公众号
- 若结果为空或引擎异常，自动回退到 `Tavily + include_domains=['mp.weixin.qq.com']`

## 本地工具降级策略
### 社交账号搜索降级
当 `Snoop` 缺失、失败、demo 受限或无结构化结果时，自动回退到：
- `Tavily`
- 定向站点：
  - `weibo.com`
  - `bilibili.com`
  - `zhihu.com`
  - `xiaohongshu.com`
  - `douyin.com`
  - `github.com`

### 公众号搜索降级
当 `SearXNG` 公众号结果为空时，自动回退到：
- `Tavily`
- 域名限定：
  - `mp.weixin.qq.com`

## Crawl4AI 设计
- 默认启用：`QIANDU_CRAWL4AI_ENABLED=true`
- 镜像内已安装：
  - `crawl4ai`
  - `playwright`
  - Chromium
- 当前支持配置：
  - `QIANDU_CRAWL4AI_COOKIES_JSON`
  - `QIANDU_CRAWL4AI_HEADERS_JSON`
  - `QIANDU_CRAWL4AI_PROFILE_DIR`
- `QIANDU_CRAWL4AI_PROFILE_DIR` 已接到 `BrowserConfig.user_data_dir`
- 这意味着后续可以通过持久 profile 或 cookies 支持登录态内页抓取

## 部署侧改动
- [Dockerfile](L:/project/chat-oracle/Dockerfile)
  - 安装 `git`
  - 克隆 `/opt/snoop`
  - 安装 `snoop` 依赖
  - 安装 `playwright chromium`
- [deploy/compose/docker-compose.yml](L:/project/chat-oracle/deploy/compose/docker-compose.yml)
  - 新增 `searxng` 服务
  - `app` 依赖 `searxng`
- [deploy/searxng/settings.yml](L:/project/chat-oracle/deploy/searxng/settings.yml)
  - 保留 `baidu` / `sogou`
  - 开启 `json` 格式

## 关键配置项
见：
- [.env.example](L:/project/chat-oracle/.env.example)
- [config.py](L:/project/chat-oracle/app/core/config.py)

核心项：
- `QIANDU_TAVILY_API_KEY`
- `QIANDU_EXA_API_KEY`
- `QIANDU_SEARXNG_BASE_URL`
- `QIANDU_SEARXNG_ENGINES`
- `QIANDU_PROVIDER_PREFERENCE`
- `QIANDU_SNOOP_COMMAND`
- `QIANDU_WECHAT_CRAWLER_COMMAND`
- `QIANDU_CRAWL4AI_ENABLED`
- `QIANDU_CRAWL4AI_COOKIES_JSON`
- `QIANDU_CRAWL4AI_HEADERS_JSON`
- `QIANDU_CRAWL4AI_PROFILE_DIR`

## 线上验证结果
- `crawl4ai = True`
- `playwright = True`
- `/opt/snoop = True`
- `run_wechat_public_search('腾讯')` 返回 `8` 条结果
- `run_snoop_search('jack')` 返回 `10` 条结果，provider 为 `snoop_fallback`
- 内网健康检查正常：`http://127.0.0.1:18000/health/live`
- 公网健康检查正常：[https://chat.202574.xyz/health/live](https://chat.202574.xyz/health/live)

## 当前结论
这套 `#千度` 已经补成“可运行、可迁移、可扩展”的模块：
- 代码层完整
- 依赖层完整
- 部署层完整
- 线上健康正常
- 本地工具具备降级能力

但要达到更强命中率，仍有两个现实瓶颈：
- `Exa` 虽已允许后端注入 key，但效果还要看线上实际查询质量和限流情况
- `SearXNG` 中文引擎受到 CAPTCHA 限制
