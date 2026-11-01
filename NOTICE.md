# 来源与范围

本项目遵循 GPL-3.0，参考并抽离自 [Embykeeper](https://github.com/emby-keeper/emby-keeper)，
源码基准提交为 `facccab7001758377a4b8e332d42f162df68e83d`。
保留原作者的许可；三份站点定义来自其 `embykeeper/telegram/checkiner/`，
通用流程依据 Template A 行为重新缩减实现。

当前仅保留：惊蛰（jingzhe）、非越助手（sfcju）、Saturday（saturday）。
非越助手沿用已有部署中的 `fyemby_bot` 地址；可通过站点配置覆盖机器人用户名。
登录采用原项目的 Telethon 首次登录 → Pyrogram 会话转换方式，以及相同的客户端身份默认值。
不包含媒体播放、认证机器人、通知机器人、AI 回答、自动注册、自动水群、内部定时器。
