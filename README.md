# 主动回复（active-reply）· QwenPaw 插件

群里的机器人原本只有两种活法：**每条都回**，或者**只有 @ 它才回**。
这个插件给出第三种：**按概率选择性回复**——没 @ 它的消息，也有机会被接一句话。

> 效果：群里 100 条没 @ 它的消息，按 0.1 的概率，大约会有 10 条被它接话，像群友一样偶尔插一句。

---

## 一、规则（先看这里）

插件的行为**跟随频道「仅 @ 回复」开关**，不与之对抗：

| 频道「仅 @ 回复」 | 消息情况 | 行为 |
| --- | --- | --- |
| **关闭** | @ 了机器人 | **100% 回复** |
| **关闭** | 没 @，命中概率 | **主动接话** |
| **关闭** | 没 @，没命中 | 保持沉默 |
| **开启** | 任何消息 | **只有 @ 才回复**，插件不主动插话 |
| — | 私聊 | 不受影响 |

两种模式一句话：

- 「仅 @ 回复」**关闭**（频道原本是「回复全部消息」）→ 插件把「全回」**收窄**成「@ 必回 + 不 @ 按概率回」，**这是插件的生效场景**；
- 「仅 @ 回复」**开启**（你显式要求只回 @）→ 插件**完全让位**，保持频道原生行为，绝不插嘴。

当前频道的开关状态会显示在插件**设置页顶部**的常驻提示里；在群里 @ 机器人发 `/sid` 也能看到。

在 1.1.0 之后，还可以**对特定用户（sid）单独设定回复参数**——比如让某个用户的未 @ 消息 100% 被接话，见「四、配置项」里的 `user_rules`。

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

插件在群聊闸门上包一层。原生逻辑是：

```python
def _check_group_mention(self, is_group, meta):
    if not is_group or not self.require_mention:
        return True
    return bool(meta.get("bot_mentioned") or meta.get("has_bot_command"))
```

插件的改写规则（`require_mention` 即频道的「仅 @ 回复」开关）：

```python
require_mention=True  → 未 @ 消息一律不放行（尊重频道设置，只有 @ 才回）
require_mention=False → 未 @ 消息掷骰子，命中则放行进入 agent 流程
```

**不改 QwenPaw 任何源码**，卸载插件后立即恢复原生行为。

## 三、安装

```bash
# WebUI：Console → 插件 → 安装插件，拖入 active-reply-1.1.0.zip
# 或命令行
qwenpaw plugin install ./active-reply
```

装好后在 **Console → 设置 → 主动回复** 里配置。设置页采用**显式保存**：改动后点击卡片底部的「保存更改」才写入后端，有未保存更改时页面顶部会有提示，保存结果（成功 / 失败及详细原因）明确展示。

## 四、配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 总开关，关闭后完全回到原生行为 |
| `method` | `possibility_reply` | `possibility_reply` 每条消息掷骰子；`rate_limit` 每分钟配额 |
| `probability` | `0.1` | 回复概率，0.0~1.0。仅 `possibility_reply` 生效 |
| `whitelist` | `[]` | 主动回复白名单（群 ID）。为空表示对所有群生效；设置后仅名单内的群按概率主动回复，名单外的群保持频道原生行为 |
| `cooldown_seconds` | `0` | 主动回复一次后，隔多久才允许再次主动回复 |
| `min_interval_seconds` | `0` | 同一群两条主动回复之间的最小间隔 |
| `max_per_minute` | `3` | `rate_limit` 模式下每个群每分钟的主动回复上限 |
| `user_rules` | `[]` | **指定用户规则**：对特定用户（sid）单独设定回复参数，见下节 |

### 指定用户规则（user_rules）

给某个人单独设参数。比如对 sid（用户 ID）为 `12345678` 的用户，未 @ 也 100% 主动接话：

```json
{
  "user_rules": [
    { "sid": "12345678", "probability": 1.0 }
  ]
}
```

每条规则可用的字段（除 `sid` 外**留空 / `null` 都表示继承全局配置**）：

| 字段 | 说明 |
| --- | --- |
| `sid` | 必填。用户 ID（QQ 号 / open_id 等），在群里 @ 机器人发 `/sid` 即可拿到 |
| `probability` | 覆盖全局概率，0.0~1.0 |
| `method` | 覆盖全局方法（`possibility_reply` / `rate_limit`） |
| `max_per_minute` | `rate_limit` 模式下每分钟配额 |
| `cooldown_seconds` | 冷却秒数。**显式 `0` = 该用户不冷却**（区别于留空继承全局） |
| `min_interval_seconds` | 最小间隔秒数 |

规则要点：

1. **层级**：判定顺序是 频道「仅 @ 回复」开关 → 群白名单 → 用户规则。规则只在白名单放行的群里、且「仅 @ 回复」关闭时才起作用。
2. **独立记账**：命中的用户按「群 + 用户」独立计算冷却 / 最小间隔 / 配额，与群里其他用户互不影响；该用户的主动回复也不占用群维度的冷却。
3. **`0` 与留空不同**：留空 = 继承全局；显式 `0` = 强制关闭。想让人「必回且永不被冷却卡住」就写 `probability: 1.0` + `cooldown_seconds: 0`。
4. **顺序即优先级**：一个用户命中多条规则时取第一条。
5. **概率跟方法走**：`probability` 仅在 `possibility_reply` 下生效。如果全局方法是 `rate_limit`，规则里要同时写 `"method": "possibility_reply"`（或改为覆盖 `max_per_minute`）。
6. **通道支持**：OneBot/QQ、飞书、元宝在消息闸门处就带用户 ID，规则可用；Telegram / Discord 的用户 ID 在闸门之后才进入流程，这两家的规则暂不生效。

### 用户 ID / 群 ID 怎么拿

在群里 **@ 机器人 然后发 `/sid`**，它会回你：

```
📍 会话 ID：onebot:group_123456
👥 群 ID：123456
把上面的群 ID 填进「主动回复白名单」即可。
👤 用户 ID：12345678（填进「指定用户规则」可对这个人单独设定回复参数）
⚙️ 当前状态：开启 · possibility_reply · 概率 0.1
📢 频道「仅 @ 回复」：关闭 → @ 必回，不 @ 按概率回
```

把 `123456` 填进白名单、把 `12345678` 填进指定用户规则即可。白名单留空则对所有群生效。

> 注意：群里若开启了「仅 @ 回复」，`/sid` 本身也需要 @ 机器人才会被处理——这是原逻辑的闸门，插件不改变它。

## 五、HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/active-reply/config` | 读取配置 |
| PUT | `/api/active-reply/config` | 热更新配置，立即生效 |
| GET | `/api/active-reply/status` | 运行统计；含 `require_mention`（频道开关状态）与 `user_rule_count` |
| POST | `/api/active-reply/simulate` | 按当前概率模拟 1000 条，返回预计回复条数；body 传 `{"sid": "..."}` 可按该用户命中的规则参数试算 |
| POST | `/api/active-reply/reset-stats` | 统计清零 |

```bash
# 把概率调到 0.3
curl -X PUT http://127.0.0.1:8088/api/active-reply/config \
  -H 'Content-Type: application/json' -d '{"probability": 0.3}'

# 给用户 12345678 单独设 100% 概率（与全局配置合并保存）
curl -X PUT http://127.0.0.1:8088/api/active-reply/config \
  -H 'Content-Type: application/json' \
  -d '{"user_rules": [{"sid": "12345678", "probability": 1.0}]}'

# 按该用户命中的规则参数试算 1000 条
curl -X POST http://127.0.0.1:8088/api/active-reply/simulate \
  -H 'Content-Type: application/json' -d '{"sid": "12345678"}'

# 看看有没有真的生效（require_mention 即频道开关状态）
curl -s http://127.0.0.1:8088/api/active-reply/status
```

## 六、注意事项

1. **只对群聊生效**，私聊完全不受影响。
2. **被 @ 的消息永远回复**，概率只作用于「没 @ 的」。
3. **频道「仅 @ 回复」开启时插件不主动插话**——这是有意设计，见「一、规则」。
4. 主动接话后，agent 拿到的就是那条普通群消息，它并不知道自己是"随机插话"的。
   如果希望它更像群友，可以在 agent 的 persona 里加一句「群聊中偶尔接话，不必每次都长篇回复」。
5. 概率是**每条消息独立**计算的，不保证均匀分布——0.1 也可能连续命中 2 条，
   想避免连续刷屏就把「冷却时间」或「最小间隔」调大一点。
6. 属 monkey-patch 类型插件，安装或卸载后建议重启一次 QwenPaw。
7. Matrix 通道有自己的提及判断逻辑（`_was_mentioned`），本插件不影响它。

## 七、自测

```bash
python tests/test_core.py            # 核心逻辑 71 项（纯 Python，无需 QwenPaw）
```

容器内端到端验证（真实调用 `_check_group_mention`，38 项）：

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

## 九、版本历史

| 版本 | 说明 |
| --- | --- |
| 1.1.1 | 兼容 QwenPaw 2.0.x：放宽 `qwenpaw_version.min` 到 2.0.0（此前 2.2.0 会导致插件在 2.0.1 上被判定不兼容、后端不加载，设置页保存报 HTTP 405）；内部模块 `core.py` 改名 `active_reply_core.py`，避免与其它插件同名模块冲突 |
| 1.1.0 | 新增「指定用户规则」：对特定用户（sid）单独设定概率 / 方法 / 每分钟配额 / 冷却 / 最小间隔（留空继承全局，显式 0 强制关闭），规则命中按「群+用户」独立记账，`/sid` 增加用户 ID 输出，`/simulate` 支持按 sid 试算，设置页新增规则编辑区。另修复全新安装时 config.json 空文件误报「解析失败」、`defaults()` 对 `default_factory` 字段返回 MISSING 哨兵的问题 |
| 1.0.4 | 设置页菜单项增加图标 💬（扩展设置列表中可见），功能无变化 |
| 1.0.3 | 修复设置页「保存失败：HTTP 405 Method Not Allowed」以及刷新后参数丢失。原因：宿主 `QP.host.fetch` 内部会先过 `getApiUrl()`（等价于再补一个 `/api`），前端若传 `/api/active-reply/config` 会被拼成 `/api/api/active-reply/config` → GET 404（页面只能显示默认值）、PUT 405。现按宿主规则自动选择正确写法，并在 404/405 时自动换写法重试一次 |
| 1.0.2 | 设置页改为显式保存（「保存更改」/「撤销更改」按钮 + 未保存提示），保存失败显示具体原因 |
| 1.0.1 | 尊重频道「仅 @ 回复」开关：开启时插件完全让位（只有 @ 才回复）；关闭时 @ 必回、不 @ 按概率回。规则写进设置页顶部提示、README 开篇与 `/sid` 输出 |
| 1.0.0 | 首个版本：概率 / 配额两种主动回复方式、白名单、冷却与最小间隔、`/sid` 命令、设置页与 HTTP 接口 |

> **给插件开发者的提醒（踩过的坑）**：Console 里请这样调接口——
> `window.QwenPaw.host.fetch("/active-reply/config", {...})`，**不要再带 `/api` 前缀**，
> 它会自己拼成 `/api/active-reply/config`。官方 `docs/plugins.zh.md` 里
> `host.fetch("/api/v1/my-endpoint")` 的例子按当前实现会被拼成 `/api/api/v1/...`，请留意。
