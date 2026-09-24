# 微信机器人（已下线归档）

这是聊天副手 2.0 之前的另一条路子：一个真连微信的机器人，收到消息后交给模型判断并自动回消息。
2026-09-24 下线归档，原因不是它坏了，而是**职责重叠**：

- 副手 2.0 已经完整覆盖「判断 + 起草」这件事，而且是纯 PowerShell、零依赖、不用扫码。
- 这个机器人要装 Python 依赖（`requirements.txt`: `weixin-ilink[qr]`），要扫码登微信，还是唯一需要维护 Python 环境的模块。
- 两套东西同时存在，容易搞混哪个是主线。

## 想重新跑起来

```bat
:: 1. 装依赖（在归档目录里）
pip install -r requirements.txt

:: 2. 连微信，扫码
python bot.py

:: 3. 或者不连微信，本地试跑
python bot.py --demo "帮我改个文件，挺急的"
python bot.py --demo          :: 交互模式，随便打字
```

`start.bat` / `demo.bat` 是上面两条命令的启动器，里面**写死了 Python 路径**
（`C:/Users/666/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe`），
换机器时要改，或者让它回退到 PATH 里的 `python`。

## 凭据

原来在项目根目录会生成 `creds.json` + `creds.json.sync`（微信 bot token 与同步状态）。
归档时已删除，且确认过**从未进入 git 历史**。`.gitignore` 里的保护规则保留着，
以后复用不会漏。

## 不值得复活的地方

如果只是想要「帮我判断对方什么意思、该怎么说」，直接用 2.0——
它不碰你的微信账号，也不自动发消息，发送权始终在人手里。
这个机器人的「自动回复」本身就是当初被放弃的设计方向。
