# 上海正大乐影城《奥德赛》IMAX 周末放票微信提醒

这个项目会在 GitHub Actions 上自动运行，不需要你的电脑一直开机。

**监控目标（已预设）：**

- 影院：正大乐影城（上海正大广场 IMAX 店）
- 猫眼影院 ID：`42020`
- 影片：《奥德赛 / The Odyssey》
- 猫眼电影 ID：`1545360`
- 城市：上海（猫眼城市 ID `10`）
- 只监控：**未来周六、周日 + IMAX**
- 检查范围：未来 28 天
- 检查频率：约每 5 分钟
- 通知：Server酱 Turbo → 微信
- 去重：同一场次只提醒一次

> 说明：GitHub Actions 的计划任务并不是严格实时系统，可能偶尔延迟几分钟；官方允许的最短 schedule 间隔是 5 分钟。

---

## 一、你最终会收到什么

当正大乐影城新开放一个周末 IMAX 场次时，微信会收到类似：

**🎬 奥德赛 IMAX 放票：新增 3 场**

影院：正大乐影城（上海正大广场IMAX店）

**2026-08-29 周六**
- 15:00 · 激光IMAX厅 · 英语IMAX2D
- 18:50 · 激光IMAX厅 · 英语IMAX2D
- 22:15 · 激光IMAX厅 · 英语IMAX2D

并附猫眼影院购票页链接。

没有新增场次时，**不会发微信**，因此不会每 5 分钟消耗 Server酱额度。

---

# 二、微信通知：Server酱 Turbo 设置

## 步骤 1：微信扫码登录 Server酱

打开：

https://sct.ftqq.com

用微信扫码登录。

请使用 **Server酱 Turbo（SCT）**，因为它可以把消息推到微信。

## 步骤 2：确认微信消息通道

登录后进入 Server酱的「通道配置 / 消息通道」页面。

按页面提示完成微信通道绑定。

不同时间 Server酱后台文案可能略有调整；核心目标是让 **Turbo 的消息通道指向你的微信**。

## 步骤 3：复制 SendKey

进入「SendKey」页面。

复制一串类似：

```text
SCT123456Txxxxxxxxxxxxxxxx
```

的密钥。

**不要把它发到群里、截图公开，也不要直接写入代码。**

## 步骤 4：先测试一次微信推送

你可以在浏览器里访问（把 `你的SENDKEY` 换成真实值）：

```text
https://sctapi.ftqq.com/你的SENDKEY.send?title=奥德赛监控测试&desp=如果你看到这条消息，说明微信推送已经打通
```

或者在终端执行：

```bash
curl -X POST "https://sctapi.ftqq.com/你的SENDKEY.send" \
  -d "title=奥德赛监控测试" \
  -d "desp=如果你看到这条消息，说明微信推送已经打通"
```

微信收到消息后，再继续 GitHub 设置。

---

# 三、把项目上传到 GitHub

## 最简单方式：网页创建仓库

1. 登录 GitHub。
2. 点击右上角 `+` → `New repository`。
3. Repository name 建议：
   `odyssey-imax-monitor`
4. **如果你想长期保持 5 分钟频率，建议选择 Public。**  
   原因：公开仓库使用标准 GitHub-hosted runners 通常不计费；Private 仓库会消耗账户包含的 Actions 分钟。  
   这个项目代码本身不包含你的 SendKey，`SERVERCHAN_SENDKEY` 仍然只保存在 GitHub Secret 中，不会因为仓库 Public 而公开。
5. 创建仓库。
6. 解压本项目 ZIP，把以下内容上传到仓库根目录：

```text
.github/
  workflows/
    monitor.yml
monitor.py
requirements.txt
state.json
tests/
README.md
```

注意 `.github/workflows/monitor.yml` 的目录层级必须完全正确。

---

# 四、把 Server酱 SendKey 安全地写进 GitHub Secret

绝对不要把 SendKey 直接写到 `monitor.py`。

进入你的 GitHub 仓库：

`Settings` → `Secrets and variables` → `Actions`

点击：

`New repository secret`

填写：

**Name**

```text
SERVERCHAN_SENDKEY
```

**Secret**

```text
你的 SCT 开头 SendKey
```

点击保存。

---

# 五、第一次手动运行

进入：

`Actions` → `Odyssey IMAX Monitor`

点击：

`Run workflow` → `Run workflow`

然后点进去看运行记录。

如果成功，日志里会看到类似：

```text
监控影院: 正大乐影城（上海正大广场IMAX店）
监控影片: 奥德赛 / movieId=1545360
2026-08-29: 找到 0 个 IMAX 场次
2026-08-30: 找到 0 个 IMAX 场次
没有新增周末 IMAX 场次，不推送。
```

如果首次运行时未来周末已经有 IMAX 场次，它会直接给你发一条微信。这是正常的：这些场次会被写入 `state.json`，之后不会重复提醒。

---

# 六、之后不需要做任何事

工作流会自动：

```text
每约 5 分钟
↓
查询未来 28 天中的周六、周日
↓
只保留 IMAX 场次
↓
和 state.json 已通知记录对比
↓
发现新场次
↓
Server酱推送微信
↓
推送成功后才写入去重记录
```

所以即使 Server酱偶尔请求失败，也不会提前把场次标记为“已通知”；下一轮会继续尝试。

---

# 七、如何确认自动任务真的开启

进入 GitHub 仓库：

`Actions` → `Odyssey IMAX Monitor`

正常情况下，你会逐渐看到系统自动产生的运行记录。

工作流中配置的是：

```yaml
- cron: '3-58/5 * * * *'
  timezone: "Asia/Shanghai"
```

即每小时第 3、8、13、18……58 分钟附近运行。

GitHub 的 schedule 可能有少量排队延迟，因此它是“5 分钟级监控”，不是秒级推送。

---

# 八、如果 GitHub Actions 报错

## 情况 A：提示缺少 SERVERCHAN_SENDKEY

说明 Secret 没配好。

检查：

`Settings` → `Secrets and variables` → `Actions`

必须存在：

```text
SERVERCHAN_SENDKEY
```

注意大小写。

---

## 情况 B：猫眼返回 403 / 验证码 / 所有日期获取失败

猫眼有反爬策略，有时会要求 Cookie。

这时可以增加一个 GitHub Secret：

```text
MAOYAN_COOKIE
```

获取方法：

1. 电脑 Chrome 打开猫眼并正常访问影院页。
2. 按 `F12` 打开开发者工具。
3. 切换到 `Network`。
4. 刷新页面。
5. 点一个 `maoyan.com` 请求。
6. 在 `Request Headers` 里找到 `Cookie`。
7. 复制 Cookie 的完整值。
8. GitHub 仓库 → `Settings` → `Secrets and variables` → `Actions`。
9. 新建 Secret：
   - Name：`MAOYAN_COOKIE`
   - Secret：刚复制的 Cookie。

**Cookie 也是隐私凭证，不要发到聊天里或公开仓库。**

工作流已经预留了这个 Secret，不需要修改代码。

---

## 情况 C：state.json 无法 git push

工作流需要把“已经提醒过哪些场次”写回仓库，因此设置了：

```yaml
permissions:
  contents: write
```

如果你的仓库额外设置了严格的分支保护，可能阻止 Actions push。

最简单做法是：

- 这个监控项目单独建一个仓库；
- 不给 `main` 分支设置“禁止 GitHub Actions push”的保护规则；
- 如果仓库是 Public，注意不要把 SendKey 或 Cookie 直接写进文件，必须只用 GitHub Secrets。

---

# 九、想把频率改成 10 分钟

编辑：

`.github/workflows/monitor.yml`

把：

```yaml
- cron: '3-58/5 * * * *'
```

改成：

```yaml
- cron: '3-58/10 * * * *'
```

对于电影放票监控，我更建议保留 5 分钟。

---

# 十、停止监控

进入：

`Actions` → `Odyssey IMAX Monitor`

右上角菜单可以禁用 workflow。

或者直接删除：

```text
.github/workflows/monitor.yml
```

---

# 十一、本地测试（可选）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SERVERCHAN_SENDKEY="你的SCT密钥"
python monitor.py
```

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SERVERCHAN_SENDKEY="你的SCT密钥"
python monitor.py
```

---

# 十二、隐私与安全

- `SERVERCHAN_SENDKEY`：只放 GitHub Actions Secret。
- `MAOYAN_COOKIE`：只有猫眼开始拦截时再添加，同样只放 Secret。
- 不要把任何密钥写进 README、代码或 `state.json`。
- 如果 SendKey 意外泄露，立即在 Server酱后台重置。

---

## 项目文件作用

| 文件 | 作用 |
|---|---|
| `monitor.py` | 查询排片、筛选 IMAX、新场次判断、微信推送 |
| `.github/workflows/monitor.yml` | 每 5 分钟自动运行 |
| `state.json` | 记录已经通知过的场次，防止重复微信 |
| `requirements.txt` | Python 依赖 |
| `tests/` | 基础逻辑测试 |

