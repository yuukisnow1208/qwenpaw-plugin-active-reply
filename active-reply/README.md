# 主动回复（active-reply）· QwenPaw 插件

群里的机器人原本只有两种活法：**每条都回**，或者**只有 @ 它才回**。
这个插件给出第三种：**按概率选择性回复**——没 @ 它的消息，也有机会被接一句话。

> 效果：群里 100 条没 @ 它的消息，按 0.1 的概率，大约会有 10 条被它接话，像群友一样偶尔插一句。

---

## 一、规则

对**群聊**里每一条消息：

| 情况 | 行为 |
| --- | --- |
| 消息里 @ 了机器人 | **100% 回复**（与原逻辑一致，不受插件影响） |
| 没 @，命中概率 | **主动接话** |
| 没 @，没命中 | 保持沉默 |
| 私聊 | 不受影响 |

这条规则同时解决两种情况：

- 通道原本配置为「**仅 @ 时回复**」→ 插件在此之上**增加**随机的主动回复
- 通道原本配置为「**回复所有消息**」→ 插件把「全回」**收窄**成「按概率回」

两种配置最终都变成「选择性回复」。

## 二、实现原理

所有支持群聊的通道（OneBot/QQ、Telegram、飞书、Discord、元宝……）收到群消息后，
都会走同一个闸门：

```python
if not self._check_group_mention(is_group, meta):
    return          # 静默丢弃这条消息
```

而 `_check_group_mention` 只在 `BaseChannel` 里实现一次：

```python
def _check_group_mention(self, is_group, meta):
    if not is_group or not self.require_mention:
        return True
    return bool(meta.get("bot_mentioned") or meta.get("has_bot_command"))
```

插件在这个方法上包一层，把「全回 / 只回@」的二选一改成「按概率回」。
**不改 QwenPaw 任何源码**，卸载插件后立即恢复原生行为。

## 三、安装

```bash
# WebUI：Console → 插件 → 安装插件，拖入 active-reply-1.0.0.zip
# 或命令行
qwenpaw plugin install ./active-reply
```

装好后在 **Console → 设置 → 主动回复** 里配置。

## 四、配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 总开关，关闭后完全回到原生行为 |
| `method` | `possibility_reply` | `possibility_reply` 每条消息掷骰子；`rate_limit` 每分钟配额 |
| `probability` | `0.1` | 回复概率，0.0~1.0。仅 `possibility_reply` 生效 |
| `whitelist` | `[]` | 主动回复白名单（群 ID）。为空表示对所有群生效 |
| `cooldown_seconds` | `0` | 主动回复一次后，隔多久才允许再次主动回复 |
| `min_interval_seconds` | `0` | 同一群两条主动回复之间的最小间隔 |
| `max_per_minute` | `3` | `rate_limit` 模式下每个群每分钟的主动回复上限 |

### 白名单怎么拿群 ID

在群里 **@ 机器人 然后发 `/sid`**，它会回你：

```
📍 会话 ID：onebot:group_123456
👥 群 ID：123456
把上面的群 ID 填进「主动回复白名单」即可。
⚙️ 当前状态：开启 · possibility_reply · 概率 0.1
```

把 `123456` 填进白名单即可。留空则对所有群生效。

> 注意：群里若开启了「仅 @ 时回复」，`/sid` 本身也需要 @ 机器人才会被处理——这是原逻辑的闸门，插件不改变它。

## 五、HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/active-reply/config` | 读取配置 |
| PUT | `/api/active-reply/config` | 热更新配置，立即生效 |
| GET | `/api/active-reply/status` | 运行统计（群消息数 / 主动接话 / 沉默 / 各群最近状态） |
| POST | `/api/active-reply/simulate` | 按当前概率模拟 1000 条，返回预计回复条数 |
| POST | `/api/active-reply/reset-stats` | 统计清零 |

```bash
# 把概率调到 0.3
curl -X PUT http://127.0.0.1:8088/api/active-reply/config \
  -H 'Content-Type: application/json' -d '{"probability": 0.3}'

# 看看有没有真的生效
curl -s http://127.0.0.1:8088/api/active-reply/status
```

## 六、注意事项

1. **只对群聊生效**，私聊完全不受影响。
2. **被 @ 的消息永远回复**，概率只作用于「没 @ 的」。
3. 主动接话后，agent 拿到的就是那条普通群消息，它并不知道自己是"随机插话"的。
   如果希望它更像群友，可以在 agent 的 persona 里加一句「群聊中偶尔接话，不必每次都长篇回复」。
4. 概率是**每条消息独立**计算的，不保证均匀分布——0.1 也可能连续命中 2 条，
   想避免连续刷屏就把「冷却时间」或「最小间隔」调大一点。
5. 属 monkey-patch 类型插件，安装或卸载后建议重启一次 QwenPaw。
6. Matrix 通道有自己的提及判断逻辑（`_was_mentioned`），本插件不影响它。

## 七、自测

```bash
python tests/test_core.py            # 核心逻辑 35 项（纯 Python，无需 QwenPaw）
```

容器内端到端验证（真实调用 `_check_group_mention`）：

```bash
/app/venv/bin/python /tmp/active_reply_test/tests/test_in_container.py
```

## 八、文件结构

```
active-reply/
├── plugin.json      # 插件清单
├── plugin.py        # 包装 _check_group_mention + /sid 命令 + 配置接口
├── core.py          # 概率/白名单/冷却/限流（纯 Python，可单测）
├── config.json      # 运行后生成的配置文件
├── dist/index.js    # Console 设置页（免构建 ES Module）
├── tests/
└── README.md
```
