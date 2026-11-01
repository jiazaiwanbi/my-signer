# my-signer

登录 Telegram，执行一次签到，退出。由青龙控制定时。

当前内置三个站点，共用同一个 Template A 流程：

| 配置名 | 机器人 | 图片验证码 |
| --- | --- | --- |
| `jingzhe` | `@JingzheProbot` | 本地 OCR |
| `sfcju` | `@fyemby_bot` | 不识别图片 |
| `saturday` | `@saturday_lite_bot` | 本地 OCR |

流程：发送 `/start` → 点击“签到/簽到” → 如有图片验证码则本地识别 → 判断成功或今日已签到。
支持按钮回调结果、新消息和编辑消息。失败返回非零退出码，结果保存在 `data/last-run.json`。
不会联系 Embykeeper 的认证/通知 Bot，不包含观看保活、AI、自动注册、自动水群或内部定时器。

## 安装

Python 3.11 或更高版本：

```bash
git clone https://github.com/jiazaiwanbi/my-signer.git
cd my-signer
python3 -m venv .venv
.venv/bin/pip install -e '.[ocr]'
cp config.example.toml config.toml
```

修改 `config.toml`，填写手机号和自己的 [Telegram API 凭据](https://my.telegram.org/apps)。
先在 Telegram 中完成三个站点的注册或绑定，再进行签到。

## 登录和运行

```bash
# 首次登录：交互式终端输入验证码和两步验证密码
.venv/bin/python run.py login --account main

# 验证已有会话，不发送签到消息
.venv/bin/python run.py status

# 执行一次后退出；没有子命令时默认执行 run
.venv/bin/python run.py

# 只运行一个站点
.venv/bin/python run.py run --sites sfcju
```

配置文件默认是项目目录下的 `config.toml`。指定其他位置：

```bash
.venv/bin/python run.py --config /path/to/config.toml run
```

## 从原青龙 Embykeeper 迁移

**先停止并禁用原任务**，确认没有 Embykeeper 进程，然后在同一台服务器内执行：

```bash
.venv/bin/python run.py migrate-embykeeper --source /ql/data/scripts/embykeeper
.venv/bin/python run.py status
```

迁移只在本机读取原配置和 `data/cache.json`，保留原会话的授权密钥及 API 凭据，不发起新登录，
不修改原项目。目标已有配置或会话时会拒绝覆盖。迁移文件均在 Git 忽略范围内。

## 青龙

首次登录可通过 `docker exec -it ql-web-1 bash` 进入容器，再执行上述命令。
在青龙中配置：

```text
名称：my-signer
命令：/ql/data/scripts/my-signer/.venv/bin/python /ql/data/scripts/my-signer/run.py
定时：0 8 * * *
允许多实例：关闭
```

程序有文件互斥锁，重叠运行退出码为 `75`；每次运行完即断开连接，不在后台等待明天。
站点失败退出码为 `1`，全部成功或已签到时为 `0`。

## 添加同类机器人

无需新增 Python 文件，在 `sites` 中加入 `"templ_a<ExampleBot>"`，按需添加：

```toml
[checkiner."templ_a<ExampleBot>"]
command = "/start"
button_keywords = ["签到", "簽到"]
use_captcha = true
success_pattern = "签到成功"
# 图片标题匹配时才识别；不填写则识别收到的图片
# captcha_pattern = "请输入验证码"
```

这是相同交互流程的通用器；网页验证码、答题或其他交互需要另写适配。
不认识的返回内容会等待本轮超时，不会猜测回答或擅自访问外部服务。

内置站点的机器人地址变更时，可以在对应站点配置中设置 `bot_username`，不必修改源码。

## Telegram 会话处理

原项目 [Issue #67](https://github.com/emby-keeper/emby-keeper/issues/67) 记录过全设备登出问题，
并改为 Telethon 首次登录。本项目保留这条登录路径、会话格式转换和客户端身份默认值。
签到使用 Pyrogram 兼容分支 Kurigram，复用同一个授权，每个账号只建一个连接；退出时只断开连接。
运行期间不重新登录、不调用登出或终止其他设备的方法。会话失效会停止，只有显式 `login --replace` 才创建新会话。

同一数据目录的运行互斥；配置中重复授权密钥也会被拒绝。
不要在原项目、新项目或不同服务器上同时使用同一个会话。
[Telegram 文档](https://core.telegram.org/api/errors#406-not-acceptable) 说明重复主连接可能触发 `AUTH_KEY_DUPLICATED` 并使该授权失效。
这些处理不能保证 Telegram 永不触发自身的风控。

手机号、API hash、会话和运行日志请保存在本机，仓库只包含示例。

## 测试

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

自动测试使用模拟机器人，覆盖按钮回调、消息结果、本地验证码、超时清理、互斥锁、会话转换和迁移。

## 许可

GPL-3.0，来源和修改范围见 [NOTICE.md](NOTICE.md)。
