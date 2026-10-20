# 完整观察企业微信交付 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将同日完整观察的成功、局部缺失或失败通知接入已配置的企业微信机器人，保留WxPusher，分别防重并守住14:59。

**Architecture:** 保留旧`outbox.json`的WxPusher身份/分片与sent、uncertain保护；新增独立`outbox-wecom.json`，复用`send_wecom_text`和原观察正文。runner将WeCom优先置于有限子预算内，再给WxPusher剩余窗口；任一路普通失败/未知不阻止另一路，真实进程退出保留dispatching且不吞信号。

**Tech Stack:** Python3.9、现有requests发送器、文件锁/原子JSON、SIGALRM、unittest；无新依赖、线程或服务。

用户已明确批准“确认，接入现有企业微信”。此前只发WxPusher的渠道限制在本批被替代，既有发送/发布授权沿用；本实施树只交付源码/测试/计划，不commit/push/部署、不新建Webhook、不改env、不发送真实测试或补发19日。实施树`codex/intraday-wecom-20261020`基线为最新`origin/main@0b183362`；配置沿用已实际核验的gpt-6.1-sol/xhigh/default、Fast关闭。

涉及B06真实渠道与provider受理状态、B09通知身份/幂等/生产隔离、B10反例和演进证据；B01—B05/B07/B08策略、来源、名单、排序、90%门与事实/采集/计算/发送截止均不改变。19日完整观察来源失败仍保持失败，不将渠道接入称为行情已修复。

1. 新测试先在原源失败：实际入口未传WECOM、双渠道独立回执与旧unknown、完整UTF8分片、截止与单路卡住不饿死另路。
2. 最小产品改动仅`chanlun/intraday_observation_delivery.py`与`intraday_observation_run.py`。WeCom正文按UTF8不超过2048字节分片，全名单不截断；WxPusher默认分片字节/旧outbox保持。WeCom sidecar保存确定分片hash与总数、实际Webhook的SHA256指纹（不存密钥），每段先持久dispatching再调用sender；已sent跳过，已有unknown或rejected不盲重发。
3. 两路均配置时，先为WxPusher保留`min(10秒, 剩余窗口/2)`，WeCom优先使用其余硬子预算；WeCom提前完成后WxPusher取得全部剩余窗口，单路配置时使用全部剩余。使用单调时间帽和原14:59绝对截止，每请求仍最多10秒，不新开后台线程。配置缺失按渠道not_configured，不阻断已配置路径；总体成功仅表示所有已配置渠道的全部段被provider受理，WxPusher可局部未完成但不得冒充全收。
4. WeCom尝试至少间隔4秒，本通道不超过15条/分钟，给既有预跑等同机器人消费者留余量；遇业务拒绝不循环重试。参考[腾讯官方机器人说明](https://cloud.tencent.com/document/product/248/50413)20条/分钟，91770页面本次不可达，文本2048字节采用保守限制。极大名单或慢请求不能在剩余预算内发完时，保留冻结完整名单与分片hash，明确partial/deadline及剩余段，不截断伪报成功、不延截止、不补发昨日。
5. 离线使用真实formatter、冻结成功/失败snapshot、stub发送器/响应；测试中文/emoji长度、全部代码与顺序、旧sent/uncertain零重发、HTTP/业务拒绝/超时、真实BaseException、并发、原出箱不受新路影响、子预算和入口参数。跑直接通知回归，核对产品hash、规则/计划跟踪和有限进程清理。§12.4演进记录只追加本批原因和边界。

证据：`/private/tmp/chanlun-wecom-delivery-20261020/`。独立验收、上线及实际群收件由主进程分别核验；不以离线sender stub成功冒充用户收到。

## 本地验证与交付状态

原基线入口行为红例确认scheduled发送参数缺少WeCom配置，初始新验收红例保留；最小实现后8个直接/相邻模块146项通过（HTTP统一拦截，真实HTTP尝试0）。覆盖中文/emoji完整分片、渠道失败/未知隔离、旧Wx回执原字节、中断后unknown、目的地/分片hash、并发、跨重入节流及硬截止。
冻结原版formatter与新默认Wx正文9组逐字节一致；190只候选WeCom为2018/2024/1981字节三段。测试启动的17个有限子进程全部退出，alarm清零，无服务、监听或后台任务。
产品只改两个文件，新测试独立一份；规则/引用方案及本计划已核对受跟踪。尚未提交、上线或真实发送；超大名单/慢请求可在截止留下部分未受理，旧unknown不自动补发，19日来源失败保留原结论。

### 审查截止反例的限定修正

独立反例证明原候选的TimeoutError截止会被sender的普通Exception处理吞掉，一次性alarm触发后仍写最终回执，0.12秒窗口实际耗时0.27秒并挤掉Wx。内部截止改为专用BaseException，仅渠道外层明确捕获；设置alarm本身也进入try/finally恢复边界，不吞KeyboardInterrupt/SystemExit。截止后保留原dispatching未知，不强求最终receipt落盘，也不自动重发。
原候选反例与alarm启动瞬间中断均先红后绿；原单Wx测试改为严格dispatching并加重入零发送断言。限定修正后直接5模块86项、相邻8模块149项及独立10项通过；同目录旧146项记录保留。本批仍不保证不可中断的操作系统I/O能瞬间取消，不延截止、不为补写最终回执占用另一渠道窗口。

提交前主进程在再次同步的最新`origin/main=0b183362`上独立运行8模块149项通过，socket连接尝试0，退出仅MainThread；独立审查最终12项组合反例和112项相关回归通过，六文件冻结hash核对一致。源码只改变通知路由与截止处理，原行情来源失败仍是独立待验证项。合并/两个运行目录版本及自然群收件继续分别记录。
