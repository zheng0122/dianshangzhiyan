# 电商智研 Agent 后端

五个智能体（云问 / 云创 / 云搭 / 云服 / 云析）+ 自动发布到微信公众号。

## 快速开始
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # 然后按注释填写
uvicorn app.main:app --reload --port 8000
```
- 不填 `LLM_API_KEY` 也能启动，进入**演示模式**（返回示例内容），可先跑通界面。
- 打开 http://localhost:8000/docs 可直接试所有接口。
- 运行测试：`python -m unittest tests.test_core -v`

## 网站前端（web/）
手机竖屏风格的单页应用（原生 JS，无需构建），页面：首页、云问（六大领域+对话）、云创（表单+结果+历史）、云搭（场景+3套方案）、云服（工作台+AI推荐回复）、云析（指标+趋势+AI诊断）、工作台、消息、我的、自动发布管理。
- 后端启动后直接访问 http://localhost:8000 即可（后端已托管 web/）。
- 没装 FastAPI 也能预览：先 `pip install requests python-dotenv`，再 `python dev_server.py`（接口与正式后端一致）。
- 前端与后端分开部署时：访问 `index.html?api=https://你的后端地址`，并在 `.env` 里设置 `CORS_ORIGINS`。
- 云服会话、云析指标为示例数据（页面有"示例数据"标记），AI 部分调用真实接口。

## 接入你的 Coze 智能体
1. 在 Coze（coze.cn）个人中心 → API 管理，创建个人访问令牌，填到 `COZE_TOKEN`。
2. 逐个打开你的 Bot，点「发布」并勾选 **API** 渠道；把地址栏里 `/bot/` 后面的数字填到 `COZE_BOT_WEN / CHUANG / DA / FU / XI`（云服第二个 Bot 填 `COZE_BOT_FU2`，云搭第二个 Bot 填 `COZE_BOT_DA2`；切换按钮的名字用 `COZE_FU_LABELS`、`COZE_DA_LABELS` 自定义）。
3. 重启后访问 `/api/health`，`providers` 里显示 `coze` 即接通。
- 云问发送用户原话，沿用你 Bot 自己的提示词；回复中的「猜你想问」会显示成可点击的追问按钮，并保持同一段对话上下文。
- 云创、云搭、云服、云析默认会附带 JSON 输出指令；Bot 没按 JSON 回复时也能兜底显示（云创会自动拆出标题/正文/话题）。
- 云搭的 Bot 里已插入工作流时：在 `.env` 里写 `COZE_RAW_AGENTS=da,da2`，后端会原样把需求发给 Bot（Bot 自己调用工作流），回复里的图片会直接显示；`COZE_WORKFLOW_DA` 留空。
- 云搭效果图（不经过 Bot、由后端单独调用工作流时）：把工作流 ID 填到 `COZE_WORKFLOW_DA`，并按工作流输入变量名修改 `COZE_WORKFLOW_DA_PARAMS`，方案卡片上会出现「生成使用效果图」。

## 需要你自己准备
1. **Coze 令牌和 Bot ID**（见上一节；不用 Coze 才需要下面的大模型密钥）。
1. **大模型密钥（备用）**：在火山方舟（或 DeepSeek、通义等任一 OpenAI 兼容平台）控制台**用你自己的账号**创建 API Key，把 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 填进 `.env`。
2. **公众号**：`WECHAT_APPID / WECHAT_SECRET`（公众平台 → 设置与开发 → 基本配置），并把服务器出口 IP 加入"IP 白名单"。准备一张封面图放到 `cover.jpg`。
3. **商家档案**：编辑 `data/merchant_profile.json`（店铺、主推商品、卖点、禁用词）。

## 自动发布流程
每天 `DAILY_PLAN_TIME` 到点（后台心跳每分钟检查）：选题 → 云创生成 → 合规检查 → 状态 `pending_review` 并飞书通知
→ 你在审核接口里 `approve` → `publish` 写入公众号草稿箱（认证号且 `WECHAT_AUTO_PUBLISH=true` 时继续提交发布）。

| 接口（需请求头 `X-Admin-Token`） | 说明 |
|---|---|
| POST /api/publish/plan | 立即生成一篇待审核内容 |
| GET /api/publish/tasks | 查看任务 |
| PATCH /api/publish/tasks/{id} | 修改标题/摘要/正文（会重新做合规检查） |
| POST /api/publish/tasks/{id}/approve | 审核通过（有合规风险需先修改，或 `?force=true`） |
| POST /api/publish/tasks/{id}/publish | 写入草稿箱 / 发布 |

## 消息与红点
智能体生成完成后，如果你已经离开了那个页面，会出现：顶部通知条、右上角🔔和底部「消息」的红点数字；点进「消息」页可查看历史，点任意一条会回到对应的结果（云创文案、云搭方案、云析报告等）。停留在原页面等待时不会打扰。后台的自动选题、发布计划执行/失败，也会通过 `/api/notifications` 推送为消息（需已设置管理口令）。

## 真实经营数据（首页 / 云析）
「我的 → 数据管理」导入每日 CSV（日期、访客、订单、销售额；可选：广告花费、复购订单），支持 UTF-8 和 Excel 常见的 GBK 编码，同一天重复导入会更新。导入后：首页显示最近一日的访客/订单/GMV，云析按 7/30/90 天计算销售额、订单、访客、转化率、客单价、复购率、ROI 及环比，并把真实指标交给 AI 做诊断。未导入时页面标注「示例数据」。接口：`POST /api/data/import`（需口令）、`GET /api/data/summary`、`POST /api/data/clear`。

## 系统自检
「我的 → 系统自检」会逐个测试五个智能体（含云搭/云服第二个 Bot），显示用的是 Coze/备用模型/演示、耗时、回复是否为结构化 JSON，并检查令牌、口令、公众号配置；可选「测试公众号连接」验证 AppID/AppSecret/IP 白名单。截图即可用来定位「页面和 Coze Bot 对不上」的问题。

## 公众号：存草稿箱 vs 直接发布
- 任务通过审核后，可「存入草稿箱」「直接发布到公众号」；已在草稿箱的可再「提交发布」；已提交的可「查询发布结果」。发布计划里也能选「公众号发布方式」。
- 直接发布需要公众号有「发布能力」接口权限（通常需微信认证）。没有权限时，内容仍保留在草稿箱，并提示原因，可到手机上确认发布。
- 注意：这是「发布」到公众号主页，不是向粉丝群发消息。

## 发布计划（选平台 + 选时间）
在「我的 → 自动发布管理」里，内容**审核通过**后，点「📅 发布计划」：
- 发布平台（下拉）：公众号 / 小红书 / 抖音 / 公众号+小红书 / 全部平台。
- 发布时间（下拉）：立即、30 分钟后、1 小时后、今晚 20:00、明早 09:00、自定义时间。
- 公众号：到点写入草稿箱（认证号且 `WECHAT_AUTO_PUBLISH=true` 时自动发布）。
- 小红书、抖音：**辅助发布**。到点自动把内容改写成对应平台风格（小红书笔记 / 抖音分镜脚本），推送飞书提醒（需配置 `FEISHU_WEBHOOK`），也可在本页「复制内容」后到 App 里粘贴发布。目前这两个平台没有对普通开发者开放的发帖接口。
- 待执行的计划可取消；后台调度器每 30–60 秒检查一次到点的计划。
- 接口：`GET /api/publish/platforms`、`POST /api/publish/tasks/{id}/schedule`、`GET /api/publish/schedules`、`POST /api/publish/schedules/{id}/cancel`。
- 以后拿到官方接口权限，只需在 `app/workflow.py` 的 `run_schedule` 里为该平台新增一个适配分支。

## 五个智能体接口
`POST /api/wen`、`/api/chuang`、`/api/da`、`/api/fu/replies`、`/api/xi/report`（字段见 /docs）。

## 对接前端
前端不要再带密钥，把请求地址指向本服务即可（Flutter 版可用 `--dart-define=ARK_BASE_URL=...`，接口路径需按上表调整）。
