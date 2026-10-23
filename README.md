# QwenPaw 主动回复插件（active-reply）

群里的机器人原本只有两种活法：**每条都回**，或者**只有 @ 它才回**。
这个插件给出第三种：**按概率选择性回复**——没 @ 它的消息，也有机会被接一句话。

> 效果：群里 100 条没 @ 它的消息，按 0.1 的概率，大约会有 10 条被它接话，像群友一样偶尔插一句。

## 效果

```
群友A：今天天气不错啊            → （沉默）
群友B：谁周末去爬山？            → 🤖 「这周末天气可以，适合出去走走」
群友C：@机器人 帮我查下快递      → 🤖 100% 回复（被 @ 必回，原逻辑不变）
群友D：刚跑完 5 公里             → （沉默）
```

## 安装

**方式一：WebUI 上传 ZIP**

Console → 插件 → 安装插件，拖入 [Releases](https://github.com/yuukisnow1208/qwenpaw-plugin-active-reply/releases) 里的 `active-reply-x.y.z.zip`。

**方式二：命令行**

```bash
git clone https://github.com/yuukisnow1208/qwenpaw-plugin-active-reply.git
qwenpaw plugin install ./qwenpaw-plugin-active-reply/active-reply
```

安装后在 **Console → 设置 → 主动回复** 里配置。群里 @ 机器人发 `/sid` 可获取群 ID 填入白名单。

## 功能

| 能力 | 说明 |
| --- | --- |
| 概率主动回复 | 未 @ 的消息按概率（默认 0.1）决定是否接话 |
| 被 @ 必回 | @ 或带命令的消息 100% 回复，不受概率影响 |
| 白名单 | 限定只在指定群生效，留空则全部群 |
| 回复方法 | `possibility_reply` 逐条掷骰子 / `rate_limit` 每分钟配额 |
| 冷却与间隔 | 主动回复一次后隔多久才能再次主动回复 |
| 运行统计 | 群消息数 / 主动接话 / 沉默次数，实时可查 |
| 概率试算 | 设置页按当前概率模拟 1000 条消息的预计回复量 |
| 配置热更新 | HTTP 接口改配置立即生效，无需重启 |

## 实现原理

所有支持群聊的通道（OneBot/QQ、Telegram、飞书、Discord、元宝……）收到群消息后都走同一个闸门：

```python
if not self._check_group_mention(is_group, meta):
    return          # 静默丢弃这条消息
```

而 `_check_group_mention` 只在 `BaseChannel` 里实现一次。插件在这个方法上包一层，
把「全回 / 只回 @」的二选一改成「按概率回」——通道原本「仅 @ 时回复」的，在上面增加随机主动回复；
原本「回复所有消息」的，把全回收窄成按概率回。两种配置最终都变成「选择性回复」。

不改动 QwenPaw 任何源码，卸载插件后立即恢复原生行为。

## 注意事项

- 只对群聊生效，私聊完全不受影响
- 概率是每条消息独立计算的，想避免连续刷屏就调大「冷却时间」或「最小间隔」
- Matrix 通道有自己的提及判断逻辑，本插件不影响它
- 属 monkey-patch 类型插件，安装或卸载后建议重启一次 QwenPaw

## 开发

```bash
python active-reply/tests/test_core.py   # 核心逻辑 35 项单测（纯 Python，无需 QwenPaw）
python build_plugin_zip.py active-reply  # 打 WebUI 可上传的 ZIP
```

容器内端到端验证：`active-reply/tests/test_in_container.py`（在 QwenPaw 容器里运行）。

完整配置项、HTTP 接口与使用细节见 [active-reply/README.md](active-reply/README.md)。

## 兼容性

QwenPaw `>= 2.2.0`（在 2.2.2.post1 上验证）。

## License

MIT
