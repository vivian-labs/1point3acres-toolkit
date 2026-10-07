# 一亩三分地本地工具：使用说明

在自己的电脑上跑一亩三分地的每日签到、每日答题，以及 Stripe 面经采集、离线搜索和导出。用命令行，也能接入支持本地 stdio 的 MCP 客户端；两者共用同一份账号会话和资料库。

支持 **macOS 与 Windows**，都需要 **Chrome + Git + Python 3.12**。账号身份、密码、浏览器会话和数据库只留在本机：密码在 macOS 存进登录钥匙串、在 Windows 用 DPAPI 加密，都不写进仓库。

依赖清单见 [requirements.txt](./requirements.txt)。想先看带图的原理讲解（签到、答题、奖励核对、失败重试、调度各是怎么做的），读仓库根目录的 [README](../../README.md)；本文是操作手册。

目录：[工作原理](#principle) · [交给 AI](#ai) · [源码安装](#install) · [软件包安装](#pip) · [配置账号](#account) · [首次运行](#first-run) · [每日自动](#automation) · [面经](#interviews) · [命令参考](#commands) · [MCP](#mcp) · [排查](#troubleshooting) · [维护](#maintenance)

<a id="principle"></a>

## 工作原理

它在本机开一个专用 Chrome，用你自己的登录会话按网页正常流程操作，不用服务器代跑、不用打码平台。

- **签到**：打开签到页 → 选一个心情（默认随机，见下条）→ 提交签到。提交后读取积分流水，确认当天「签到奖励」大米到账才算成功。
- **答题**：从站点接口 `dailyQuestion.get` 读出题目和选项，和内置题库 [`answers.json`](./answers.json)（194 道纯文本问答对）逐字比对（做 NFKC 归一化，按选项文字匹配、不按位置）。命中就点选项、提交答案，再确认「每日答题」奖励到账。题库没有的题标记 `answer_needed` 停下，不瞎猜。补答一次并**确认奖励到账**后写进本机题库 `work/local-toolkit-state/learned-answers.json`，下次同题直接命中；本机实测过的答案优先于仓库自带的快照。答过但没到账的选项记为已知错误，下次即使被当作答案传进来也拒绝提交，不重复扣米。没等到站点响应时什么都不学。
- **心情 / 日记**：默认开启随机心情。系统随机源按配置权重抽取，只有昨天的记录参与延续；同账号同站点日的心情和短句在操作页面前保存，重试不重抽。优先从离线语料库摘取文字，原心情模板作为后备；不生成个人经历。短句避开之前 365 个日历日用过及高度相似的内容；候选用尽时改选「没心情」并留空。短句可能成为主页公开记录；设置 `"checkin_mood_random": false` 立即停止发布，优先于已存随机计划。风格和来源见[语料说明](#journal-corpus)。
- **成功判定**：不以「点到按钮」或退出码为准。只有查到当天、本账号名下、正数的大米奖励流水，签到和答题两项才报 `complete`；网站或验证异常时如实报失败。原始结果留在本机 `work/local-toolkit-state/latest-daily.json`，可离线复查。

<a id="ai"></a>

## 最快：交给 AI 助手，默认自动更新

把项目链接或仓库交给一个能在本机执行命令的 AI 编程助手（Claude Code、Codex 等），直接说“装好并配置每天自动签到答题，启用自动更新”。普通用户默认安装已发布的软件包；拿到仓库是为了阅读说明，不代表需要从源码运行。

**安装助手按以下步骤执行：**

1. 检查 Chrome、Git、Python 3.12 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)，补齐缺少的运行环境，找到 `uvx` 的绝对路径。
2. 执行 `uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli info` 验证软件包能启动。后续命令使用同一前缀；不要把 uv 缓存目录里的 Python 或脚本路径保存成启动入口。
3. 按 [软件包安装](#pip) 和 [配置账号](#account) 设置个人数据目录、账号和登录。已有安装先按迁移步骤保留数据；MCP 和每日计划使用同一个数据目录。
4. 将 MCP 注册为 `uvx 1point3acres-toolkit@latest`，保留客户端其他配置和环境变量；连接后用 `runtime_info` 核对版本。
5. 按 [首次运行](#first-run) 验证登录和每日任务，再按 [每日自动运行](#automation) 创建唯一的系统每日计划，入口必须是 `uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli daily --resume`。
6. 读回客户端注册和系统任务，确认两处都使用 `@latest`、`uvx` 绝对路径和相同数据目录；报告安装版本、任务是否启用，以及 MCP 已连接时也会在当前调用结束后更新。不能只执行一次安装命令就宣称已经配置自动更新。

默认不使用 `git clone` + 虚拟环境、单独 `pip install` 或 `uv tool install` 作为用户的自动更新方案。这些方式以及固定版本仅在用户明确选择时使用。`@latest` 获取最新兼容的软件包启动器。1.2.0 起，启动器会继续检查组织仓库 main 的最新提交，只有该提交通过完整 CI 才准备并启用。CLI 在业务命令前更新，常驻 MCP 在业务调用前及空闲时检查，等当前调用结束后切换后台进程。需要 Git 和网络；下载、依赖或校验失败时继续运行上次可用版本。

你只需要参与两件事：

- 提供自己的论坛用户名和数字 uid（写进 `account.json`）。
- 在助手弹出的安全输入框里输一次论坛密码。密码直接进系统钥匙串 / DPAPI，不进仓库、不进对话、助手也不经手明文。

之后由计划自动运行；电脑需要可用，异常由健康观察报告。想自己动手并保持自动更新，按 [软件包安装](#pip) 配置；下面的源码安装供开发者使用；源码入口也默认启用相同的更新逻辑。

<a id="install"></a>

## 源码安装（开发者）

前置：装好 Git、Chrome、Python 3.12（macOS 用 `python3.12`，Windows 用 `py -3.12`）。

**克隆并建环境**，在放项目的目录里执行。macOS / Linux：

```sh
git clone https://github.com/vivian-labs/1point3acres-toolkit.git
cd 1point3acres-toolkit
python3.12 -m venv work/cf-probe-venv
work/cf-probe-venv/bin/python -m pip install -r "outputs/一亩三分地本地工具/requirements.txt"
"outputs/一亩三分地本地工具/检查.sh" --sync
```

最后一步报 `permission denied` 说明 clone 丢了可执行位（旧版本或经 Windows 中转），先 `chmod +x "outputs/一亩三分地本地工具/"*.sh` 再执行。

Windows（PowerShell）：

```powershell
git clone https://github.com/vivian-labs/1point3acres-toolkit.git
Set-Location 1point3acres-toolkit
py -3.12 -m venv work\cf-probe-venv
work\cf-probe-venv\Scripts\python.exe -m pip install -r outputs\一亩三分地本地工具\requirements.txt
& 'outputs\一亩三分地本地工具\检查.cmd' --sync
```

`--sync` 会核对依赖、生成本机 MCP 配置、跑离线检查，并启动一次临时 Chrome 验证阅读器（不登录、不签到）。成功时输出 `status=complete`。

之后除标注“仓库根目录”外，命令都在**工具目录** `outputs/一亩三分地本地工具` 执行。入口：macOS/Linux 用 `./运行.sh`、`./检查.sh`，Windows 用 `运行.cmd`、`检查.cmd`。

<a id="pip"></a>

## 安装为软件包（pip / uvx）

不想克隆仓库、只想把工具接给 MCP 客户端或者用命令行，可以直接装 [PyPI 上已发布的 `1point3acres-toolkit`](https://pypi.org/project/1point3acres-toolkit/)（同样需要 Chrome 和 Python 3.12；推荐方式还需先[安装 uv](https://docs.astral.sh/uv/getting-started/installation/)，它提供 `uvx`）：

```sh
uvx 1point3acres-toolkit@latest          # 在隔离环境准备最新版，再启动 MCP 服务
pip install 1point3acres-toolkit  # 或者装进自己的环境
```

使用 pip 安装后有两个命令：`1point3acres-toolkit` 启动 MCP 服务；`1point3acres-toolkit-cli` 和 `运行.sh` 是同一个命令行，子命令、参数、输出完全相同（例如 `1point3acres-toolkit-cli status`）。

软件包版本没有仓库，也没有 `work/`，所有可写内容都放在一个个人数据目录里：macOS 是 `~/Library/Application Support/1point3acres-toolkit`，Windows 是 `%LOCALAPPDATA%\1point3acres-toolkit`；设环境变量 `ONEPOINT3ACRES_HOME` 可以换地方。目录里：

- `state/account.json`：账号配置，内容和[配置账号](#account)一节完全一样；
- `state/interviews.sqlite`、`state/latest-daily.json`：资料库和每日结果；
- `chrome-profile/`：专用 Chrome 的配置目录；
- `Stripe面经资料/`：导出文件；
- `mcp.config.json`：首次启动时生成的 `uvx …@latest` 客户端配置，需要 uv；保留个人数据目录，可合并进 MCP 客户端。

使用 pip 安装时，后面各节的命令把 `./运行.sh` 换成 `1point3acres-toolkit-cli` 即可：存密码是 `1point3acres-toolkit-cli save-credentials`（输入格式不变），每日计划指向 `1point3acres-toolkit-cli daily --resume`。两种安装方式互不影响，克隆仓库的版本继续用仓库旁的 `work/`。注册到 MCP 客户端：

```sh
claude mcp add --scope user 1point3acres-local -e PYTHONUTF8=1 -- uvx 1point3acres-toolkit@latest
codex mcp add 1point3acres-local --env PYTHONUTF8=1 -- uvx 1point3acres-toolkit@latest
```

推荐普通用户使用上面的 `@latest` 接入，开发者继续使用仓库源码。`uvx` 不会把命令行入口永久放到 PATH；使用命令行时要显式指定软件包：

```sh
uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli info
uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli status
```

后文的 `./运行.sh` 可替换为 `uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli`，例如后接 `save-credentials`。密码输入方式不变。

`@latest` 在每次启动时请求 PyPI 上最新的兼容启动器。1.2.0 起，启动器还能直接跟踪通过 CI 的 main，已连接的 MCP 会在调用结束后更新业务进程，保留连接。不带 `@latest` 的 `uvx` 会复用缓存，不能保证获取新发布的版本。见 [uv 的工具版本说明](https://docs.astral.sh/uv/concepts/tools/#tool-versions)。

**已有用户迁移**：在客户端现有的 `1point3acres-local` 配置中把 `command` 改为 `uvx`，把整个 `args` 改为 `["1point3acres-toolkit@latest"]`，保留原来的环境变量；客户端找不到 uvx 时填写其绝对路径。停止旧服务后重连，再调用 `runtime_info` 核对版本。只更新仓库里的配置文件不会修改客户端已保存的注册。pip 用户可先用 pip 升级到 1.2.0，再继续调用原安装环境中的 `1point3acres-toolkit`；该入口同样跟踪通过 CI 的 main。旧进程首次迁移仍需重连一次。

仓库版和软件包版默认数据目录不同，改启动命令不会自动迁移账号和历史。从仓库迁移前停掉旧 MCP 和每日计划，备份数据；将 `work/local-toolkit-state/` 的内容复制到软件包数据目录的 `state/`，将 `work/account-browser/chrome-profile/` 复制到 `chrome-profile/`，已有目标文件不要直接覆盖。导出资料按需复制；凭据仍按原平台方式管理。迁移后核对账号、会话和历史，再恢复唯一的每日计划；不要删除旧数据。自定义 `ONEPOINT3ACRES_HOME` 时，MCP 和定时任务必须使用相同值。

<a id="account"></a>

## 配置账号与密码

**身份**：在仓库根目录建 `work/local-toolkit-state/account.json`，填用户名和数字 uid，取自你论坛个人空间链接里的 `uid=数字`：

```json
{ "username": "你的用户名", "uid": 123456 }
```

**计划时间（可选）**：默认 `schedule_mode` 为 `random`，统一使用 `America/Los_Angeles` 的 10:00–12:00，按 Beta(3,3) 曲线抽取到分钟，11 点附近概率较高。操作系统随机源提供随机数，每账号、站点日只生成并保存一次；重试、重启和并发触发复用已有计划。无需自己采集环境噪声或使用固定种子。

已有 `schedule_time` 配置自动按 `fixed` 模式兼容，配合 `schedule_timezone` 使用。显式加 `"schedule_mode": "random"` 可切回随机模式；随机模式的时区始终是洛杉矶。当天计划已生成后，配置变更从下一站点日生效。固定模式示例：

```json
{ "username": "你的用户名", "uid": 123456, "schedule_time": "07:05", "schedule_timezone": "America/New_York" }
```

**随机心情（可选，默认开启）**：签到时随机选心情并配一句「说说」，每天会以你的名义在主页发布一句话（原理见[工作原理](#principle)）。不想要就在同一个文件里加 `"checkin_mood_random": false`，必须是布尔值，之后每天固定选「没心情」、不写任何内容：

```json
{ "username": "你的用户名", "uid": 123456, "checkin_mood_random": false }
```

值不合法会报 `invalid_local_schedule_config`，不会悄悄退回默认。检查命令输出的 `schedule` 段说明模式、时区、曲线与建议触发频率。随机模式建议操作系统每分钟直接调用 `daily --resume`，不要每分钟启动 AI 会话；未到点和已完成时仅查询本机数据。实际执行可能因调度延迟、休眠或网络超过目标时间，醒来后仅恢复当前站点日。

<a id="journal-corpus"></a>

### 大文本库与文案风格

内置 `journal-corpus.json` 从 **136,320 个原始片段**筛选、去重，含 **35,469 条真实摘句**：35,432 条带作者的唐诗摘句，37 条现代短句。它不是几万条现代口语。数据约 2.4 MB，日常运行完全离线读取，不下载巨型数据、不调用外部文案 API。

在本机 `account.json` 增加一个可选字段：

```json
{ "username": "你的用户名", "uid": 123456, "journal_style": "mixed" }
```

- `mixed`（默认）：优先选现代短句的概率 80%，诗句 20%。某类没有合格候选就尝试另一类；由于现代池很小，长期运行后诗句比例可能远高于 20%。
- `modern`：只从现代池选语料，不使用诗词；用尽时尝试原心情模板。因此这项配置并不能提供几万条口语。
- `poetry`：从诗词池选语料；用尽时尝试原心情模板。摘句保留原文和作者，可能有繁体字。

心情权重与文案风格分开配置，摘句不保证与心情标签语义一致。风格变化不覆盖当天已保存的选择；关闭 `checkin_mood_random` 仍立即生效。不改变执行时间、站点日、签到和答题奖励核验。

`journal_style` 只能使用上面三个字符串，非法值返回 `invalid_local_account_config`，不会悄悄换风格。

选择时用操作系统随机源，过滤该账号之前 365 个日历日的已用文案；去掉标点、空格和诗句署名后比较字符三元组，Dice 相似度 ≥80% 的候选也排除。原模板后备遵守同样的规则。所有候选耗尽时留空，不无限重抽。未完成的当天计划重试仍复用原句。繁简转换及语义改写不在此近似检测的保证范围内；不同账号不共享历史，不能保证全站零碰撞。

**来源与授权：** [Common Voice](https://github.com/common-voice/common-voice) 的 CC0 句子文本、[moztw/cc0-sentences](https://github.com/moztw/cc0-sentences) 的 CC0 文本、[chinese-poetry](https://github.com/chinese-poetry/chinese-poetry) 的古代唐诗数据库（MIT）。许可证说明保存在 `corpus-notices.txt`；`journal-corpus.json` 的 `sources` 记录固定提交、原文件路径和 SHA-256，每条记录还包含来源编号和从零开始的原文位置。筛选限制长度、文字类型及主题，排除大量新闻、地址、人物、法律、医疗和不完整片段；规则筛选不等同于逐句人工审定。没有把授权不清晰的网页语料直接搬进仓库。

**开发者重建词库：** 从源码包的工具目录执行。只用于更新语料，日常用户无需运行。准备一个仓库外的缓存目录，从内置 `sources` 下载固定版本文件并核对哈希：

```python
# 保存为仓库外的 prepare-corpus.py，再从工具目录运行。
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

cache = Path('../../work/corpus-inputs')
cache.mkdir(parents=True, exist_ok=True)
sources = json.loads(Path('journal-corpus.json').read_text(encoding='utf-8'))['sources']
for source in sources:
    project = source['repository'].removeprefix('https://github.com/')
    url = 'https://raw.githubusercontent.com/' + project + '/' + source['revision'] + '/' + quote(source['path'], safe='/')
    with urlopen(url, timeout=60) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ValueError('Source hash mismatch; do not rebuild')
    (cache / source['file']).write_bytes(raw)
(cache / 'sources.json').write_text(json.dumps(sources, ensure_ascii=False), encoding='utf-8')
```

然后用已安装工具依赖的 Python 运行：

```text
python -X utf8 corpus.py --sources ../../work/corpus-inputs/sources.json --inputs ../../work/corpus-inputs --output journal-corpus.json
```

提取器不联网；再次核验固定源文件哈希、过滤、去重，校验完整结果后原子替换。没有候选、文件损坏或超过 4 MB 时拒绝更新。修改筛选或源版本后应走正常 PR、对应回归与 CI，并同步这里的实际数量。原始文本缓存和使用历史不提交 Git；语料更新计入运行指纹，并包含在自动准备的新版本中。已安装 1.2.0 启动器后，常驻 MCP 会在当前调用结束后使用通过 CI 的新语料，无需为每次语料变更单独发布软件包。

**密码**：交互输入一次，存进钥匙串 / DPAPI。下面这行用 Python 的隐藏输入读取密码、按 `account.json` 的用户名封装后交给 `save-credentials`，密码不进 shell 历史，macOS 上也不进 `security` 的命令行参数（钥匙串只接受可打印 ASCII 口令，其他字符会报 `unsupported_password_characters`）。在仓库根目录执行。

macOS / Linux：

```sh
work/cf-probe-venv/bin/python -c "import json,getpass;a=json.load(open('work/local-toolkit-state/account.json',encoding='utf-8-sig'));print(json.dumps({'username':a['username'],'password':getpass.getpass('论坛密码: ')}))" | "outputs/一亩三分地本地工具/运行.sh" save-credentials
```

Windows（PowerShell）：

```powershell
work\cf-probe-venv\Scripts\python.exe -c "import json,getpass;a=json.load(open('work/local-toolkit-state/account.json',encoding='utf-8-sig'));print(json.dumps({'username':a['username'],'password':getpass.getpass('论坛密码: ')}))" | & 'outputs\一亩三分地本地工具\运行.cmd' save-credentials
```

成功返回 `status=complete`，`credential_storage` 为 `macos_keychain` 或 `windows_dpapi`。改过论坛密码就重跑这一段。微信注册的账号先在网站或公众号设置一个登录密码再用。

<a id="first-run"></a>

## 首次运行

在工具目录登录一次，再手动跑一次每日业务。`运行.sh` / `运行.cmd` 只在工具目录 `outputs/一亩三分地本地工具/` 里，先 cd 进去（在别的目录直接敲会报「无法识别」）。macOS 示例，Windows 把 `./运行.sh` 换成 `运行.cmd`：

```sh
cd outputs/一亩三分地本地工具
./运行.sh session-login
./运行.sh daily
```

`session-login` 出现 `session_usable=true` 才算登录成功。不想存密码、只想扫一次码的话用 `./运行.sh session-login --method wechat`：工具的 Chrome 窗口会弹到屏幕上显示站点官方微信二维码，用微信扫码并在手机上确认即可（默认最多等 180 秒）；之后的日常自动恢复仍然需要钥匙串里的密码。`daily` 会跳过已完成的项目，按网站流程提交，并核对当天到账的大米奖励；只有签到和答题两项的完成状态与奖励都确认，才报 `status=complete`。已完成的当天再跑会返回 `already_done`。

若结果里出现 `answer_needed`，说明题库没有这道题的答案，补答一次：

```sh
./运行.sh daily --question '完整原题' --answer '正确选项的完整文字'
```

答案按选项文字匹配，不按 A/B/C 或第几项。

<a id="quiz-recovery"></a>

### 答题提交结果不明时恢复

`quiz_submission_unconfirmed` 表示工具无法确定上次提交是否被网站处理，并不表示答错。输出的 `attention` 给出 `account_uid`、`site_day`、`run_id` 和处理提示。定时任务先补查一次；仍未确认且签到已核验时，返回 `decision=manual_recovery_required`、`status=needs_attention`，后续只更新心跳，不再自动打开浏览器。把这个状态接入自己的通知渠道；工具本身不保证弹出桌面通知。

1. 先运行 `./运行.sh status`，只核验当前完成状态与奖励。已到账时无需重交，下一次定时触发会正常结束。
2. 仍未完成时，可直接在网页答题，再运行 `status` 核验。也可确认愿意承担重复提交风险后，使用下面的人工恢复命令。
3. 从 `attention` 复制账号、洛杉矶日期和失败记录编号，并填写网站当前原题和正确选项完整文字：

```sh
./运行.sh daily --retry-quiz 'RUN_ID' --site-day 'YYYY-MM-DD' --account-uid 123456 \
  --question '完整原题' --answer '正确选项的完整文字'
```

这里的编号、日期和 uid 都是占位示例。Windows 使用 `运行.cmd`，把命令写在一行；软件包安装使用 `1point3acres-toolkit-cli`。

`--retry-quiz` 是明确授权一次重试，不能与 `--resume` 同用。工具在浏览器锁内校验当前账号、当前站点日和待处理记录，重新查询完成状态、积分奖励和题目。已完成或有奖励时不重交；账号/日期不符报 `invalid_quiz_recovery`，记录过期或已被重试报 `quiz_recovery_stale`，题目变化报 `question_changed_or_not_confirmed`。重试仍没有回执时会生成新的待处理编号，旧编号不能重复使用；明确没有点击时保留原编号。不能用它补过去站点日的题目，也不要删除数据库绕过保护。

运行历史新增 `submission_phase`（`click_started`、`click_returned`、`response_seen`）和人工恢复的 `retry_of`。`click_started` 只表示已保存即将调用点击的意图，不证明请求已发出；`submission_attempts` 统计有提交意图或回执证据的运行次数，不是服务端接收次数。旧记录没有阶段信息时，计数为 0 也不能证明从未提交。


<a id="automation"></a>

## 每日自动运行

失败后按 5、10、20、40、60 分钟逐步延长恢复间隔，上限 60 分钟。间隔依据已保存的运行记录计算，重启不重置；等待期返回 `decision=recovery_wait`、`status=needs_attention` 和 `retry_at`，不开浏览器，不表示签到答题已成功。只读查询不计入失败次数；明确提供完整原题和答案的补答可直接核对并尝试，仍受提交保护约束。

思路：让操作系统每分钟通过 `uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli daily --resume` 启动一次。uvx 先检查启动器软件包更新，启动器检查通过 CI 的源码版本，工具再判断是否到点、当天是否已完成；`not_due` / `already_complete` 时不开浏览器，只有真正该签到时才动作。等待与已完成状态不产生论坛请求，但启动器仍可能访问包索引。手动 `daily` 不受随机窗口约束；定时计划必须使用 `daily --resume`。

**uvx 软件包版**：定时任务的程序填 `uvx` 的绝对路径，参数依次填写 `--from`、`1point3acres-toolkit@latest`、`1point3acres-toolkit-cli`、`daily`、`--resume`。macOS 可用 `command -v uvx`，Windows 可用 `where.exe uvx` 查找路径。任务与 MCP 必须使用同一个 `ONEPOINT3ACRES_HOME`（或都使用默认目录），并设置 `PYTHONUTF8=1`；替换旧任务，避免重复执行。每次触发都会检查软件包更新，可能访问包索引，有网络和启动开销；业务层的“未到点只读本地记录”不包含 uvx 的更新检查。若不希望检查更新，可设置 `ONEPOINT3ACRES_AUTO_UPDATE=0`，并自行维护版本。

- **交给 AI 助手最省事**：让它按你的系统装好计划（macOS 用 launchd LaunchAgent，Windows 用任务计划程序），使用上面的 uvx 自动更新入口，并读回任务配置核对。
- **自己配**：按下面的软件包配置或样例创建任务。计划时间在 `account.json` 里配（见[配置账号](#account)）；执行 `uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli info`，输出的 `schedule` 段给出当前模式、时区、轮询间隔与 rrule。随机模式的具体时间按账号与站点日保存在本机数据库，不在每次检查时重抽。

### Windows：软件包每日计划（默认自动更新）

在任务计划程序中创建当前用户的任务，或让安装助手使用系统的 ScheduledTasks 命令创建，配置如下：

| 项目 | 配置 |
|:--|:--|
| 名称 | `1point3acres-toolkit-daily`；迁移时先停用旧任务并等待运行结束，再替换 |
| 程序 | `where.exe uvx` 返回的 `uvx.exe` 绝对路径 |
| 参数 | `--from 1point3acres-toolkit@latest 1point3acres-toolkit-cli daily --resume` |
| 触发 | 每 1 分钟重复，无限期；错过后尽快启动 |
| 身份 | 当前用户，仅在用户登录时运行，无需管理员权限 |
| 并发 | 已在运行时不启动新实例 |
| 时限 | 至少覆盖 `info` 的 `daily_run_timeout × (daily_retry_limit + 1) + 120` 秒，并为下载安装预留时间 |

任务必须设置 `PYTHONUTF8=1`；若 MCP 设置了 `ONEPOINT3ACRES_HOME`，任务也要传入相同值。任务计划程序没有单独的环境变量输入栏，可让助手在个人数据目录创建本机 PowerShell 启动脚本，在脚本中设置这两个变量后用 `&` 调用 uvx 的绝对路径及上述参数，并以 `exit $LASTEXITCODE` 返回结果；任务通过 `powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File` 调用该脚本。不要将密码写入脚本或任务参数。

安装完成后读回任务的程序、参数和包装脚本，核对 `@latest`。仅在终端跑过一次 uvx，并不能证明任务入口已经更新；源码任务则须确认其入口已升级到 1.2.0 启动器。电脑需开机且当前用户已登录；休眠、注销时不能保证执行。任务退出成功不等于奖励到账，用 `daily-history` 核对业务结果。

### Windows：源码版每日计划（开发者）

在工具目录的 PowerShell 中执行：

```powershell
.\运行.cmd info
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\计划.ps1 -Action Install -WhatIf
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\计划.ps1 -Action Install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\计划.ps1 -Action Status
```

`info` 离线输出当前源码版本、指纹和有效配置，不输出账号身份或密码。先确认 `schedule.mode=random`、`schedule.timezone=America/Los_Angeles`、窗口为 10:00–12:00。旧配置含 `schedule_time` 时保留固定模式；要切换需在账号配置设置 `"schedule_mode": "random"`。

安装脚本从统一配置读取轮询间隔，注册 `1point3acres-toolkit-daily`，使用当前虚拟环境的 `pythonw.exe`，直接执行 `daily --resume`。默认每分钟触发；同一任务尚未退出时忽略新实例，运行时限覆盖更新准备与一次自动重试。重复安装更新同一任务，拒绝覆盖其他 checkout 的同名任务。安装不要求管理员权限，也不保存 Windows 密码。

电脑必须开机、当前 Windows 用户已登录；锁屏可以保持登录，注销、关机或休眠期间不能保证运行。计划不会唤醒电脑；恢复可用后补检查当天。任务计划程序的成功退出只表示调用完成；当天是否成功请看 `daily-history`，不能只看 `last_result=0`。

安装前停用旧的每日执行计划，避免两个调度器轮流触发。需要暂停或卸载时：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\计划.ps1 -Action Remove
```

卸载先禁用后续触发；若还有运行中的实例，会报错并要求等待当前运行结束，再执行 `Remove`。不要在它仍运行时更新依赖或移动源码。移除成功后保留账号、会话与历史；恢复时重新 `Install`。移动仓库前应先移除旧计划，移动后重新安装。

### macOS：LaunchAgent（默认自动更新）

macOS LaunchAgent 样例，存为 `~/Library/LaunchAgents/local.1point3acres-toolkit.daily.plist`。把 `/ABSOLUTE/PATH/uvx` 换成 `command -v uvx` 返回的绝对路径，把 `/DATA_HOME` 换成个人数据目录的绝对路径并提前创建该目录；MCP 使用相同的 `ONEPOINT3ACRES_HOME`。plist 中不能使用 `~` 或 `$HOME` 代替绝对路径，路径含 `&` 等 XML 特殊字符时需要转义。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.1point3acres-toolkit.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/ABSOLUTE/PATH/uvx</string>
    <string>--from</string>
    <string>1point3acres-toolkit@latest</string>
    <string>1point3acres-toolkit-cli</string>
    <string>daily</string>
    <string>--resume</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUTF8</key><string>1</string>
    <key>ONEPOINT3ACRES_HOME</key><string>/DATA_HOME</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>/DATA_HOME/launchd-daily.log</string>
  <key>StandardErrorPath</key><string>/DATA_HOME/launchd-daily.log</string>
</dict>
</plist>
```

装载：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.1point3acres-toolkit.daily.plist`；停用：`launchctl bootout gui/$(id -u)/local.1point3acres-toolkit.daily`。改过 plist 要先停用再装载，再用 `launchctl print gui/$(id -u)/local.1point3acres-toolkit.daily` 核对已加载的程序和参数。要用下面的 `pmset` / `caffeinate` 加固时，把 `ProgramArguments` 换成你的包装脚本，脚本仍须调用 uvx 的 `@latest` 入口。

开发者使用源码时，将 `ProgramArguments` 改为仓库内 `运行.sh` 的绝对路径、`daily`、`--resume`，并使数据目录与源码版 MCP 一致。1.2.0 起，这种入口也通过同一启动器更新；开发分支应设置 `ONEPOINT3ACRES_AUTO_UPDATE=0`。

- **macOS 可选加固（写在本机包装脚本里，不进仓库）**：合盖后的短暂后台唤醒（DarkWake）里也可能触发计划，脚本开头加 `pmset -g systemstate | grep -q Graphics || exit 0` 可以避开；用 `caffeinate -i` 包住运行命令能防止空闲睡眠（合盖仍会睡，只是减少中途被打断的概率）。另外，工具的 Chrome 在后台运行时，从 Dock / Spotlight 打开 Chrome 会进入工具的专用配置目录（同一个应用只保留一个实例）：想开自己的 Chrome，等任务结束，或用 `open -na "Google Chrome"` 另起一个实例；如果发现自己的登录落进了 `work/account-browser/chrome-profile`，在那个实例里退出登录即可。
- **macOS 窗口行为**：系统不允许把窗口放到屏幕外，所以专用 Chrome 启动瞬间会短暂出现并切到前台（约 1 秒），随后自动最小化到 Dock、把焦点还给你之前正在用的应用；这个瞬间无法消除。微信扫码登录时窗口会被调到屏幕上，结束后同样最小化。Windows 上窗口始终隐藏。

计划由 `daily --resume` 决定是否执行，它不会补过去站点日的签到。电脑休眠错过的触发，会在唤醒后的下一次检查补上；跑到一半睡着的那次会在运行截止（settings 的 `DAILY_RUN_TIMEOUT`，默认 15 分钟）内以 `daily_run_timeout` / `browser_connection_lost` 结束并收掉浏览器；确定尚未提交时重开一次，结果不明时保留提交保护，答题补查一次后提示人工处理。同一账号只保留一个每日执行计划。

### AI 助手补答与指纹

MCP 是调用协议，不会隐藏浏览器自动化特征。工具复用专用 Chrome 配置和会话，不轮换指纹；随机时间、短句和间隔只是运行策略，不能保证通过 Cloudflare 或避免机器人识别。

原有 AI 定时计划若继续保留，应改为离线健康观察，并仅在当前站点日的 `answer_needed` 有完整题目和选项时查证答案，再调用一次 `daily --resume --question '完整原题' --answer '正确选项完整文字'`。不得猜答案、重交待确认请求，也不要无条件调用第二个每日执行器。助手是否可用取决于客户端自己的运行条件；无人值守不等于任何故障都能自动解决。

### 再配一个独立的健康观察者

上面那个计划**发现不了自己没被触发** —— 一个进程无法察觉自己的缺席。IM 的心跳之所以有效，靠的是观察者在链路的另一端。所以再配一个**独立**的计划，只做只读检查。

它和上面那条警告不冲突：警告针对的是重复提交，而这个观察者不开浏览器、不碰账号、不提交任何东西，只读本机数据库。

`daily-history --fail-on-alert` 在需要处理时返回退出码 3（查询本身失败仍是 2，`warn` 不触发），所以观察者不必解析 JSON。

**macOS**，写 `work/health-watch.sh`：

```sh
#!/bin/sh
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/health-watch.log"
OUT="$("$DIR/../outputs/一亩三分地本地工具/运行.sh" daily-history --limit 40 --fail-on-alert 2>&1)"
CODE=$?
VERDICT="$(printf '%s' "$OUT" | sed -n 's/.*"verdict": "\([a-z]*\)".*/\1/p')"
printf '%s  exit=%s  verdict=%s\n' "$(date '+%Y-%m-%d %H:%M')" "$CODE" "$VERDICT" >> "$LOG"
[ "$CODE" -eq 0 ] && exit 0
osascript -e 'display notification "每日签到答题需要处理" with title "一亩三分地"' 2>>"$LOG"
exit "$CODE"
```

`chmod +x` 后配一个 LaunchAgent，每天跑一次（`StartCalendarInterval`），指向这个脚本。

**Windows**，写 `work\health-watch.ps1` 做同样的事（用 `运行.cmd`，通知用 `System.Windows.Forms.NotifyIcon` 气泡），然后：

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<脚本绝对路径>"'
$trigger = New-ScheduledTaskTrigger -Daily -At 20:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName '1p3a-health-watch' -Action $action -Trigger $trigger -Settings $settings
```

`-StartWhenAvailable` 让关机错过的那次在开机后补跑 —— 观察者本身也不能指望“恰好在线”。

两边都把脚本放 `work/`，那里不进仓库：路径、时间、通知方式都因机器而异。日志是可靠记录，桌面通知是尽力而为，可能被系统静音。

<a id="interviews"></a>

## 采集、搜索与阅读面经

按需选用，安装时不必跑。当前固定采集 Stripe，采到的内容以当前账号可见范围为准。

| 需求 | 命令（工具目录） |
|---|---|
| 采集 Stripe 面经并导出 | `./运行.sh collect-stripe --limit 12 --list-pages 3` |
| 搜索已采集的资料 | `./运行.sh search '滑动窗口' --limit 20` |
| 按岗位、级别、发帖日期筛选 | `./运行.sh search '' --role SWE --level 'New Grad' --date-from 2026-09-01 --date-to 2026-09-30` |
| 搜索网站上的帖子（不入库） | `./运行.sh site-search 'Stripe' --limit 10` |
| 读取指定帖子（不入库） | `./运行.sh thread-detail 123 --max-thread-pages 2` |
| 从已有库重新导出 | `./运行.sh export` |

导出的 JSON、CSV、Markdown 和离线阅读器在 `outputs/Stripe面经资料/`，用浏览器打开 `打开阅读器.html` 即可离线搜索。站内搜索的结果不会自动入库；离线 `search` 只搜已采集保存的内容。

<a id="commands"></a>

## 命令参考

所有命令输出 JSON。`status` 为 `complete` / `needs_attention` / `failed`，后两者退出码为 2（`search` 返回 `records` / `matched` / `filters`、`export` 返回路径，没有 `status`）。加 `--help` 看单个命令的选项。

| 命令 | 作用 |
|---|---|
| `info` | 离线版本与配置诊断；源码或配置与当前进程不一致时报 `runtime_restart_required` |
| `status` | 只查签到/答题状态与奖励，必要时恢复登录 |
| `session-status` | 只诊断当前会话，不登录、不签到 |
| `session-logout` | 退出本工具专用浏览器里的本站登录：只删专用配置里 `1point3acres.com` / `1p3a.com` 的 Cookie，不碰钥匙串凭据、账号配置、资料库或别的浏览器配置；删完用身份接口核实站点确实不认得账号了才算 `complete`。**不会自动重新登录**，要恢复就再跑 `session-login`；重复退出无害；别的任务正占着浏览器时直接失败、不清理 |
| `session-login` | 用钥匙串里的密码建立/恢复会话。`--method wechat` 改为微信扫码：打开站点自己的微信登录页，把本工具的 Chrome 窗口移到屏幕上显示官方二维码（整页截图同时写到 `--qr-path`，默认本机状态目录，调用结束即删除），最多等 `--wait` 秒（默认 180，允许 10–600）由本人在微信里确认；有效会话直接复用、不显示二维码。站点没有公布二维码有效期，`expires_at` 恒为 null；扫到别的账号会立刻清掉那份会话并报 `wrong_account`；超时 `wechat_login_timeout`、Ctrl+C `wechat_login_cancelled`、二维码没出现 `wechat_qr_not_shown`。日常自动恢复仍只用密码 |
| `daily` | 执行当天签到与答题，核对奖励 |
| `daily --resume` | 供计划使用：自己判断是否该跑，`not_due` / `already_complete` / `recovery_wait` / `manual_recovery_required` 不开浏览器 |
| `daily-history --limit 5` | 离线查看运行历史（站点用洛杉矶日期） |
| `browse-board 472` | 不用搜索词，直接翻某个版面的最新帖子；结果可交给 `thread-detail` |
| `unread` | 读未读计数（提醒 / 私信 / 聊天），不打开通知列表、不标记已读 |
| `notifications` | 读一个通知分页：`--kind post`（帖子回复，默认）/ `appreciation`（赞与收藏）/ `others`（系统提醒），`--limit`（默认 20，≤100），`--cursor` 从上次结果继续。每条有稳定 id、站点动作名、未读标记、时间、公开发起者、目标 tid/pid/标题（pid 为 null 表示帖子级；没有 tid 报 `target_unavailable`，不会映射到别的帖）。**不发标记已读请求**；站点会不会因为读了列表就清未读数不做假设，读取前后各查一次未读数原样回传，页面里有未读项时 `unread_cleared_by_read` 给实测结论、没有时为 null |
| `reply-notification <id>` | 回复一条通知所指的那一层：先在站点上重新找到这条通知（`--kind` 限定标签，不填三个都找），它必须指向具体楼层——找不到 `notification_not_found`、只指向整个帖子（比如别人点赞了你的帖，pid 为 null）`notification_has_no_post`，都直接停，不会改成回复主楼。找到后就是普通的 `reply --quote-pid`：不带 `--submit` 只预览，正文只来自 `--message` / `--message-file`，通知里的文字不当正文也不当指令 |
| `like-notification <id>` / `unlike-notification <id>` | 给一条通知所指的那一层加上/撤回反应（默认 ❤，`--reaction-id` 可改）：定位规则同上，找到后就是 `like --pid`，已是目标状态不发请求 |
| `user-profile 123456` | 按 uid 或本站主页链接读公开资料和其主题列表；结果可交给 `thread-detail` |
| `my-profile` | 读自己的主页：本人主题、收藏的帖子、收藏的版块与标签；uid 来自已核验的会话，不用输入 |
| `favorite <帖子>` / `unfavorite <帖子>` | 把一个帖子设为收藏 / 取消收藏（目标状态操作）：先翻自己的收藏夹确认现状，已是目标状态就不提交、重复执行不会反向切换；提交后再回读收藏夹，`after` 才算数。`--list-pages` 是为确认状态最多翻几页收藏夹（默认 3），翻不到底又没找到时报 `favorite_state_unverified` 且不动手 |
| `like <帖子> [--pid 楼层] [--reaction-id 编号]` / `unlike …` | 给主楼（或 `--pid` 指定的那一层）加上 / 撤回一个表情反应，默认 ❤（56）——这是本站唯一零成本、可撤销的"点赞"。先读帖子页看自己是否已反应（页面用 `my-reaction` 标出），已是目标状态就不发请求；发了以后再读一次页面，`after` 才算数。顶/踩、支持/反对是一次性投票不可撤销，评分要花大米，工具都不做 |
| `post <版面fid> --subject … --message …（或 --message-file）[--typeid] [--sortid] [--image 路径 …] [--video 路径] [--submit]` | 发一篇文字帖子，可带一个本地视频（mp4/mov/webm ≤50MB，走站点原生视频上传：申请一次性地址 → 直传 → 注册得 `video_id` → 发帖携带，发布后按帖子的 `videos` 核对，视频上传失败就不发帖），可带你明确选定的本地图片（png/jpg/gif/webp，单张 ≤8MB、最多 9 张；正文里用 `[image:N]` 放第 N 张，没放的按顺序接在正文后，预览会列出实际顺序）。`--submit` 时先按顺序上传，任一张失败就停、不发帖、只删本次已传的素材；发布后按帖子的附件列表核对每张图确实在站上，否则 `images_not_visible`。**不带 `--submit` 只预览**：读版面名称、可选分类、发帖权限并校验标题正文，不写站点；版面有分类时必须给 `--typeid`（预览会列出）。`--submit` 用同样内容只提交一次，然后按 tid 读回标题正文核对，一致才 `confirmed=true`；站点送审时 `needs_attention / pending_review`（不给 tid，也不能重发）；响应丢失时先查自己的主题列表（`recovered=true`），查不到报 `api_submission_unconfirmed`、不重发 |
| `reply <帖子> --message …（或 --message-file）[--quote-pid 楼层] [--submit]` | 回复帖子；`--quote-pid` 是针对某一层的定向回复（带引用）。不带 `--submit` 只预览：确认帖子存在未关闭、站点回复权限通过、楼层确实在这个帖子里（不在则 `quoted_post_not_in_thread`，不会降级成普通回复）。`--submit` 只提交一次，按新 pid 读回所在页核对正文与引用关系 |
| `organize <帖子>` | 把已入库的帖子整理成轮次与题目条目，每条带来源 pid 与原文摘录，区分楼主与网友、标出推测语气；规则提取，需人工核对；原记录不变，按原文哈希存版本 |
| `save-thread <帖子>` | 把一个指定帖子存进资料库；`--company` 是你声明的公司标签，不填保持未标注；已存完整的默认复用，`--refresh` 强制重读 |
| `search --company ""` | 不按公司过滤，可查到未标注公司的记录 |
| `search --role SWE --level 'New Grad' --date-from 2026-09-01 --date-to 2026-09-30` | 岗位、级别精确匹配（`未标注` 也是可选值）；日期是闭区间，按**发帖日期**（主楼发表时间，其次列表页日期）筛，不是采集时间，发帖日期未知的记录在设了日期时不会命中；离线阅读器有同样的筛选控件 |
| `collect <公司>` | 为指定公司做一次有界面经采集：默认走站内搜索（`--query` 可改关键词），或 `--listing` 指定本站公司标签页。标签页的帖子归属该公司；搜索命中只有标题含公司名才归属，否则存为未标注并报 `unconfirmed` |
| `task-create <公司> [--query|--listing] [--limit …]` | 把一次公司采集保存为本地任务：参数当场冻结，返回 `task_id`，**不执行**。之后 `task-run <id>` 在当前进程执行到完成 / 失败 / 暂停点；`task-status <id>` 查进度（`state` / `diagnosis` / `progress`，执行者心跳超时会报 `executor_missing`，不会把没人跑的任务显示成正常推进）；`task-pause <id>` 在下一次页面请求前暂停并释放浏览器，已读的页安全入库；`task-resume <id>` 放回队列，再 `task-run` 从已确认位置继续，不跳页不重复；`task-list` 列最近任务。同一时刻只有一个活着的执行者 |
| `archive-media <帖子> [--limit]` | 把已入库帖子当前可见的图片/附件下载到 `work/local-toolkit-state/media/<tid>/`，索引存库、原文不变。只下本站自己主机的文件（外链 `skipped_external`），权限受限的附件不碰（`skipped_restricted`），单文件 ≤10MB、每次最多 30 个；相同内容按哈希只存一份，文件名只由哈希和核过的扩展名组成。之后 `export` 会把已归档文件复制进导出目录的 `媒体/`，阅读器断网也能看，未归档的明确标出 |
| `recognize-media <帖子> [--limit]` | 对已归档的图片做**本机**文字识别（`rapidocr-onnxruntime`，不把图片发给任何第三方）。结果按图片内容哈希单独存放、与原文分开；同一张图不识别两次，低置信度的行丢弃，空白图片记为 `no_text` 不凭空产生内容。搜索时加 `--include-ocr` 才会命中识别文本，这类命中 `matched_in=recognized_text`；导出和阅读器把识别文本放在图片下方并标明"机器识别，非原文" |
| `collect-stripe` / `search` / `site-search` / `thread-detail` / `export` | 面经采集（等价于 `collect Stripe --listing` Stripe 标签页）、搜索与导出 |

`user-profile` 读到的主页 uid 必须和请求一致，否则报 `profile_identity_mismatch`，不会悄悄换成别人；用户不存在 / 隐私限制 / 需要登录 / 挑战页分别是 `profile_not_found` / `profile_restricted` / `profile_requires_login` / `profile_challenge`。页面没有的资料字段为 `null`，不填零。注意：以登录身份访问别人的主页，论坛可能会把你记进对方的「最近访客」。

`unread` 的来源是站点身份接口随身份一起返回的三个计数，也就是工具每次运行本来就在读的那个接口——所以读取本身不会把任何通知标成已读。站点没给或不是整数的计数显示为 `null` 并列进 `missing`，**未知不当作零**；登录失效时 `status=failed`、各计数为 `null`，不当作没有通知。

`browse-board` 只收版面数字编号或本站 `/bbs/forum-<编号>-<页>.html` 地址，别的地址会拒绝。`pagination_complete` 只有在站点确实没有下一页、且没有因为上限丢结果时才为 true——**读到上限不等于版面没有更多帖子**，那种情况看 `truncated_reason`（`result_limit` 或 `page_limit`）和 `next_url`。置顶帖在每页都会重复出现，跨页按 `tid` 去重，只算一次。

每日原始结果存在本机 `work/local-toolkit-state/latest-daily.json`，可能含私人信息，不要整段贴到 Issue。

<a id="mcp"></a>

## MCP 接入

先跑一次 `检查.sh --sync`（Windows：`检查.cmd --sync`），它会生成工具目录下的 `mcp.config.json`——包含本机路径、不含密码、不入库。把其中 `1point3acres-local` 这一项合并进你 MCP 客户端的配置即可；这是本地 stdio 服务，不需要公开 URL。

两个常见客户端的一行注册（把两个路径换成 `mcp.config.json` 里生成的那两个）：

```bash
claude mcp add --scope user 1point3acres-local -e PYTHONUTF8=1 -- <venv 的 python.exe> <工具目录>/mcp_server.py
```

```bash
codex mcp add 1point3acres-local --env PYTHONUTF8=1 -- <venv 的 python.exe> <工具目录>/mcp_server.py
```

软件包版本不用生成配置，把上面两条里的两个路径换成 `uvx 1point3acres-toolkit@latest` 即可（见[软件包安装](#pip)）。`claude mcp list` 会做一次握手并显示 `✔ Connected`；`codex mcp list` 显示 `enabled`。注册信息写在各客户端自己的用户配置里（`~/.claude.json`、`~/.codex/config.toml`），含本机绝对路径，不进仓库。

连接后先调用 `runtime_info`，确认 `restart_required=false`、`loaded.fingerprint` 与 `disk.fingerprint` 一致，且版本符合预期。兼容的源码更新会自动切换，账号配置变更仍需重连；1.1.0 或更旧服务首次迁移时也需要重连一次。版本指纹只覆盖运行源码与公共资源，不覆盖凭据、Cookie 或数据库；无 Git 的 ZIP 安装 `revision` 为 null，指纹仍可用。`disk.dirty` 表示 Git 已跟踪文件是否存在本地修改。

也可调用 `interviews_search`（query 传空字符串）验证：应返回 `records` 和 `stats`，新库为空是正常的，这一步不访问网站。`daily_run`、`stripe_collect` 会执行真实业务，确认要做时再调。可用工具名以 `architecture.json` 的 `public_tools` 为准。

<a id="troubleshooting"></a>

## 常见问题

每日提交按钮会检查浏览器输入事件。工具通过 CDP 发送原生鼠标事件，按按钮完整文字定位，并在点击前核对可见性、禁用状态与遮挡；不移动桌面鼠标。不要把这里改回 JavaScript `element.click()`：按钮可能直接忽略合成事件，表现为一直 `submission_unconfirmed`。该输入方式不代表保证通过站点验证；缺少回执时仍保留待确认记录，不自动清库或反复提交。

专用 Chrome 的窗口隐藏或最小化时，工具会通过 CDP 保持页面处于活动状态，避免后台页面忽略输入或暂停验证回调；这不需要激活桌面窗口。浏览器集成检查使用正式启动流程和独立的合成账号、临时配置，核验页面能接收可信点击，且不改变桌面前台应用。

| 现象 / 错误 | 处理 |
|---|---|
| `account_not_configured` / `invalid_local_account_config` | 检查 `work/local-toolkit-state/account.json`：UTF-8、`username`+`uid`（可选 `schedule_mode`、`schedule_time`、`schedule_timezone`、`checkin_mood_random`）、uid 为正整数、`checkin_mood_random` 必须是布尔值 |
| `login_required_credentials_not_configured` | 还没存密码，重跑配置密码那一段 |
| `login_rejected` / `automatic_login_failed` | 核对账号密码与网站账号状态，不要连续重试同一密码 |
| `button_not_ready` | 浏览器没点成按钮，保留失败等下次计划；持续出现附脱敏错误提 Issue |
| `page_challenge_not_resolved` / `..._verification_timeout` | 自动验证没过，本次保留失败，看后续计划是否恢复 |
| `answer_needed` | 题库没这道题，按首次运行那节补答一次 |
| `another_task_is_using_the_browser` | 有任务在用浏览器，等它结束，别同时开第二个 |
| `chrome_profile_busy_or_start_failed` | 检查 Chrome 是否安装、专用任务是否还在跑，别杀掉所有 Chrome |
| `browser_connection_lost` | 浏览器连接中途断了；确定尚未提交时自动重开一次，提交结果不明时保留保护并提示处理 |
| `daily_run_timeout` | 单次每日运行超过截止并强制结束；尚未提交时重试一次，提交结果不明时保留保护 |
| `quiz_submission_unconfirmed` / `manual_recovery_required` | 先运行 `status` 核验，再按 [人工恢复步骤](#quiz-recovery) 处理 |
| `consistency_check_failed` | 跑 `检查.sh`，按提示修；派生文件过期时加 `--sync` |
| 自动计划没跑 | 确认计划已启用、启动程序的绝对路径有效、电脑当时可用；uvx 入口还需能准备软件包，`not_due` 不是故障 |

提 Issue 时给出系统 / Python / Chrome 版本、`git rev-parse --short HEAD`、用到的命令和脱敏后的 `status` / `error`，先搜有没有相同 Issue，不要贴账号配置或完整 JSON。

<a id="maintenance"></a>

## 更新与维护

`work/` 目录保存运行环境、加密凭据、数据库、专用 Chrome 会话和每日历史，都不入库；加密凭据与本机绑定，换电脑要重新配置，不能只拷贝密文。

**默认行为（1.2.0 起）**：业务 CLI 启动时检查 `vivian-labs/1point3acres-toolkit` 的 main。只有相同提交的 Project consistency push 检查已全部通过，才在独立目录准备代码和依赖，完成依赖、静态和启动校验，再原子切换。不会在你正在使用的 checkout 里执行 pull，也不会覆盖个人改动。`info`、`daily-history` 读取本地状态，不检查网络更新；uvx 本身仍可能访问软件包索引。

**常驻 MCP**：启动、业务工具调用前以及空闲时每 60 秒检查。已有调用执行完才切换业务进程；准备期间新业务请求排队，版本、历史和任务控制工具仍可用。客户端连接保留，并收到工具列表变更通知。不会重放已经发送的请求。取消尚未发送的请求会移除队列项；已经开始的业务请求为保护提交状态会安全结束，取消后的结果不再返回客户端，长任务请使用 `control_task` 暂停。协议或能力不兼容的新进程会被拒绝，保留旧进程并报告 `mcp_fallback`，此时需升级客户端或重连处理。

**安装与首次迁移**：安装 Chrome、Git、Python 3.12+ 和 uv；使用前面的 `uvx …@latest` 入口。pip 用户执行 `python -m pip install --upgrade 1point3acres-toolkit`。源码用户暂停每日计划并等待正在执行的操作结束，确认工作区干净后 `git pull --ff-only`，安装依赖，再执行 `检查.cmd --sync` / `检查.sh --sync`。从 1.1.0 或更旧版本迁移，需要停止旧 MCP 并重连一次，确认 `runtime_info` 已加载新启动器。之后兼容的业务源码变更无需每次发 PyPI 或重连。启动器本身、账号配置或不兼容协议变更仍可能需要重启。源码 Windows 用户重新执行 `计划.ps1 -Action Install`，更新原任务的执行时限，保留唯一每日计划。

**数据与缓存**：保留同一个 `ONEPOINT3ACRES_HOME`。账号、凭据、专用 Chrome、历史和导出路径不随版本变化。源码更新缓存在原工作区的 `work/toolkit-updates`，软件包缓存在个人数据目录的 `updates`；也可用 `ONEPOINT3ACRES_UPDATE_CACHE` 指定私有位置。缓存含 Git 镜像、按提交隔离的源码、必要时的依赖环境和激活指针，不提交到 Git。不要删除 `work/`、账号数据目录或 Chrome 配置来升级。失败时不自动删除或覆盖这些数据。

**确认实际版本**：CLI 用 `info`，MCP 用 `runtime_info` 查看 `loaded.revision` 和指纹；根目录 `git log` 只代表启动器 checkout。`updates` 给出最后检查时间、激活和可用提交。`current` / `updated` 是更新状态，`waiting_for_ci` 表示新提交尚未通过 CI，`fallback` 表示无法完成更新；均不代表签到、答题或奖励成功。业务结果仍用 `daily-history` 核对。网络故障、Git 不可用、依赖安装失败或同时有其他进程准备版本时，继续使用已验证版本，错误不输出凭据或子进程原始日志。

**离线与开发分支**：源码单次命令用 `运行.cmd --offline status` / `./运行.sh --offline status`，启动器用 `python launcher.py mcp --offline`。设置环境变量 `ONEPOINT3ACRES_AUTO_UPDATE=0` 可停用自动检查；开发和测试自己的分支时应使用该变量，避免启动器转去运行 main。离线模式使用已激活缓存（没有缓存则使用当前安装源码），无法保证最新。uvx 的包索引检查独立于本工具开关；完全离线时使用已安装的绝对入口路径。
<a id="publishing"></a>

### 发布新版本（维护者）

GitHub Trusted Publishing 授权已配置；1.2.0 是自动更新启动器的基础版本。后续使用 [Publish to PyPI](https://github.com/vivian-labs/1point3acres-toolkit/actions/workflows/publish.yml) 工作流，无需长期 API token。合并 main 或创建 GitHub Release 都不会自动上传到 PyPI，仍需手动触发工作流。

1. 同步修改根目录 `pyproject.toml` 和 `server.json` 中的版本号，通过 PR 合并到 main。版本必须是尚未在 PyPI 发布的新版本；检查命令会核对版本、依赖和入口配置。
2. 等待该提交的 Project consistency 检查全部通过，在该提交上创建对应 `v版本号` 标签及正式 GitHub Release。
3. 在 Actions 中选择 Publish to PyPI，从 `main` 运行，`tag` 填上一步的标签。命令行等价命令为 `gh workflow run publish.yml --ref main -f tag=v版本号`（把 `v版本号` 替换为实际标签；已经发布的版本不要再次上传）。
4. 工作流核对标签、软件包版本、正式 Release 和该提交的 CI，构建 wheel/sdist 并做严格检查，再由独立发布任务使用短期 OIDC 身份上传。
5. 确认工作流成功、PyPI 页面出现新版本，再实测 `uvx --from 1point3acres-toolkit@latest 1point3acres-toolkit-cli info` 和 MCP 的 `runtime_info`，更新 Release 说明。

当前授权绑定 GitHub owner `vivian-labs`、仓库 `1point3acres-toolkit`、工作流 `publish.yml`、环境 `pypi`；GitHub 的 `pypi` 环境仅允许 `main` 分支部署。迁移仓库或工作流时同步修改 PyPI 项目的 Publishing 配置。首次建立新项目的方式见 [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)。失败时查看 Actions 日志，确认已有文件是否上传成功后再处理；不要覆盖或重复上传已发布版本。

PyPI 页面上的说明来自 `PYPI_README.md`，修改它需要随新版本发布，单独合并 README 不会刷新已有包的页面。末尾的 `mcp-name:` 用于目录核对包归属，不能删除。

**MCP 官方目录登记是独立步骤。** PyPI 发布成功不代表已登记到 MCP 官方目录。`server.json` 保留明确的发布版本，目录安装可能固定该版本；1.2.0 起入口默认跟踪通过 CI 的 main；`@latest` 另外检查启动器软件包发布。需要登记时，安装 `mcp-publisher`，执行 `mcp-publisher login github`，用有 vivian-labs 组织权限的账号登录，再执行 `mcp-publisher publish`。

### 提交中断恢复

签到确认后，从 30–70 秒均匀抽取一次等待时间，把确认时间、间隔和截止时间写入当日计划。答题准备完成后只等待剩余部分；重启、补答复用截止时间，已经过去则不再等待。原有待确认签到仍保留保护，独立答题以首次恢复观察作为保守计时起点。网络处理可能使实际间隔更长。只读查询不等待；等待跨站点日时停止提交，系统时钟大幅回拨时返回 `daily_clock_changed`，留待后续正常触发恢复。

签到和答题点击前先提交本机数据库记录，存储失败则不点击。进程在提交后中断时，下一次只查询完成状态和奖励；未收到回执不能证明未执行，不自动重交；答题的人工恢复见 [答题提交结果不明时恢复](#quiz-recovery)。明确的 `button_not_ready` 表示没有点击，可以在下次重试。记录更新按同一 run_id 保存，不重复计数。
