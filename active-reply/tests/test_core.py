# -*- coding: utf-8 -*-
"""主动回复核心逻辑自测（不依赖 QwenPaw）。

运行：
    python tests/test_core.py
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import active_reply_core as core  # noqa: E402

PASSED = 0
FAILED = []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED.append(name)
        print(f"  ✗ {name}  ->  {detail}")


def cfg(**kwargs):
    return core.ActiveReplyConfig.from_dict(kwargs)


def main():
    print("\n[1] 概率边界")
    state = core.ReplyState()
    check(
        "概率 0 -> 永不回复",
        all(core.decide(cfg(probability=0), state, "k", now=i)[0] is False for i in range(50)),
    )
    state = core.ReplyState()
    check(
        "概率 1 -> 必定回复",
        all(core.decide(cfg(probability=1), state, "k", now=i)[0] is True for i in range(50)),
    )

    print("\n[2] 概率命中率接近配置")
    rng = random.Random(42).random
    state = core.ReplyState()
    c = cfg(probability=0.1)
    hits = sum(1 for i in range(20000) if core.decide(c, state, "k", now=float(i), rng=rng)[0])
    ratio = hits / 20000
    print(f"     20000 次实测命中率: {ratio:.4f}  期望 0.1")
    check("命中率误差 < 0.01", abs(ratio - 0.1) < 0.01, ratio)

    print("\n[3] 群标识提取（不同通道字段不同）")
    check(
        "OneBot group_id",
        core.group_ids({"group_id": "123456", "is_group": True}) == ["123456"],
    )
    check("Telegram chat_id", core.group_ids({"chat_id": -100123}) == ["-100123"])
    check(
        "飞书 feishu_chat_id",
        core.group_ids({"feishu_chat_id": "oc_abc"}) == ["oc_abc"],
    )
    check("空 meta", core.group_ids({}) == [])
    check("None 安全", core.group_ids(None) == [])

    print("\n[4] 白名单")
    check("空名单 = 全部群", core.in_whitelist(cfg(whitelist=[]), ["1"]) is True)
    check("命中名单", core.in_whitelist(cfg(whitelist=["111", "222"]), ["222"]) is True)
    check("不在名单", core.in_whitelist(cfg(whitelist=["111"]), ["999"]) is False)
    check(
        "多个候选 ID 任一命中即可",
        core.in_whitelist(cfg(whitelist=["999"]), ["111", "999"]) is True,
    )

    print("\n[5] 冷却与最小间隔")
    state = core.ReplyState()
    c = cfg(probability=1, cooldown_seconds=10)
    first = core.decide(c, state, "g1", now=1000)[0]
    second = core.decide(c, state, "g1", now=1005)
    third = core.decide(c, state, "g1", now=1011)[0]
    check("首次命中", first is True)
    check("冷却期内不回复", second[0] is False and second[1] == "cooldown", second)
    check("冷却结束后恢复", third is True)

    state = core.ReplyState()
    c = cfg(probability=1, min_interval_seconds=5)
    core.decide(c, state, "g2", now=100)
    blocked = core.decide(c, state, "g2", now=102)
    check("最小间隔生效", blocked[0] is False and blocked[1] == "min_interval", blocked)

    print("\n[6] 独立群互不影响")
    state = core.ReplyState()
    c = cfg(probability=1, cooldown_seconds=30)
    core.decide(c, state, "groupA", now=100)
    other = core.decide(c, state, "groupB", now=101)
    check("另一个群不受冷却影响", other[0] is True)

    print("\n[7] 每分钟配额模式")
    state = core.ReplyState()
    c = cfg(method="rate_limit", max_per_minute=3)
    results = [core.decide(c, state, "g3", now=200)[0] for _ in range(4)]
    check("前 3 条命中", results[:3] == [True, True, True], results)
    check("第 4 条被限流", results[3] is False, results)
    after = core.decide(c, state, "g3", now=261)
    check("一分钟后恢复", after[0] is True, after)

    state = core.ReplyState()
    c = cfg(method="rate_limit", max_per_minute=0)
    check("配额 0 -> 永不主动", core.decide(c, state, "g4", now=1)[0] is False)

    print("\n[8] 关闭开关")
    state = core.ReplyState()
    c = cfg(enabled=False, probability=1)
    res = core.decide(c, state, "g5", now=1)
    check("禁用时返回 disabled", res == (False, "disabled"), res)

    print("\n[9] 配置反序列化与兜底")
    c = core.ActiveReplyConfig.from_dict(
        {
            "enabled": "false",
            "probability": "0.35",
            "whitelist": "群1，群2,群3",
            "method": "不存在的方法",
            "cooldown_seconds": "-5",
            "max_per_minute": 2.7,
            "未知字段": 1,
        },
    )
    check("字符串转布尔", c.enabled is False)
    check("字符串转浮点", c.probability == 0.35, c.probability)
    check(
        "中文逗号分隔的白名单",
        c.whitelist == ["群1", "群2", "群3"],
        c.whitelist,
    )
    check("非法方法兜底", c.method == "possibility_reply", c.method)
    check("负冷却兜底", c.cooldown_seconds == 0.0, c.cooldown_seconds)
    check("浮点转整数", c.max_per_minute == 2 and isinstance(c.max_per_minute, int))
    check(
        "概率超范围被夹住",
        core.ActiveReplyConfig.from_dict({"probability": 1.5}).probability == 1.0,
    )
    check(
        "负概率被夹住",
        core.ActiveReplyConfig.from_dict({"probability": -0.2}).probability == 0.0,
    )

    print("\n[10] 状态快照")
    state = core.ReplyState()
    c = cfg(probability=1)
    core.decide(c, state, "g6", now=1000)
    core.decide(c, state, "g6", now=1030)
    snap = state.snapshot(now=1035)
    print("     快照:", snap)
    check("快照含该群", "g6" in snap)
    check("最近一次距今 5 秒", snap["g6"]["last_ago"] == 5.0, snap)
    check("1 分钟内 2 次", snap["g6"]["count_1min"] == 2, snap)

    print("\n[11] 试算")
    result = core.simulate(cfg(probability=0.1), draws=5000, seed=7)
    print("     试算结果:", result)
    check("试算条数正确", result["draws"] == 5000)
    check("试算比例接近 0.1", abs(result["ratio"] - 0.1) < 0.02, result["ratio"])

    print("\n[12] 仅 @ 回复模式（尊重频道开关）")
    state = core.ReplyState()
    c = cfg(probability=1)
    res = core.decide(c, state, "g7", now=1, require_mention=True)
    check(
        "仅 @ 模式 -> 一律不放行",
        res == (False, "mention_only"),
        res,
    )
    check("仅 @ 模式不消耗状态", state.snapshot(now=2) == {}, state.snapshot(now=2))
    c2 = cfg(enabled=False, probability=1)
    res2 = core.decide(c2, state, "g8", now=1, require_mention=True)
    check("禁用优先于仅 @ 模式", res2 == (False, "disabled"), res2)
    state2 = core.ReplyState()
    c3 = cfg(probability=1, cooldown_seconds=30)
    core.decide(c3, state2, "g9", now=100, require_mention=True)
    res3 = core.decide(c3, state2, "g9", now=101)
    check(
        "仅 @ 模式跳过不占冷却",
        res3[0] is True,
        res3,
    )
    res4 = core.decide(c3, state2, "g9", now=102, require_mention=False)
    check("默认（未传）按概率逻辑", res4[0] is False and res4[1] == "cooldown", res4)

    print("\n[13] 用户 ID 提取（不同通道字段不同）")
    check(
        "OneBot sender_id",
        core.user_ids(
            {"sender_id": "12345678", "group_id": "123456", "is_group": True},
        )
        == ["12345678"],
    )
    check(
        "元宝 raw_sender_id",
        core.user_ids({"raw_sender_id": "u_abc", "group_code": "g"}) == ["u_abc"],
    )
    check(
        "飞书 feishu_sender_id",
        core.user_ids({"feishu_sender_id": "ou_123"}) == ["ou_123"],
    )
    check(
        "嵌套 sender 对象",
        core.user_ids({"sender": {"user_id": 12345678, "nickname": "n"}})
        == ["12345678"],
    )
    check("空 meta", core.user_ids({}) == [])
    check("None 安全", core.user_ids(None) == [])

    print("\n[14] 用户规则：规整与匹配")
    c = core.ActiveReplyConfig.from_dict(
        {
            "user_rules": [
                {"sid": " 12345678 ", "probability": "1"},
                {"no_sid": 1},
                "垃圾数据",
                {"sid": "2", "method": "不存在", "cooldown_seconds": -3},
                {"user_id": "88", "min_interval_seconds": ""},
            ],
        },
    )
    check("非法规则被丢弃，剩 3 条", len(c.user_rules) == 3, c.user_rules)
    check(
        "sid 去空格 + 字符串概率转浮点",
        c.user_rules[0]["sid"] == "12345678" and c.user_rules[0]["probability"] == 1.0,
        c.user_rules[0],
    )
    check(
        "非法方法/负冷却 -> 继承全局 / 夹到 0",
        c.user_rules[1]["method"] is None and c.user_rules[1]["cooldown_seconds"] == 0.0,
        c.user_rules[1],
    )
    check(
        "user_id 别名 + 空字符串视为继承",
        c.user_rules[2]["sid"] == "88"
        and c.user_rules[2]["min_interval_seconds"] is None,
        c.user_rules[2],
    )
    check(
        "to_dict 往返后规则不变",
        core.ActiveReplyConfig.from_dict(c.to_dict()).user_rules == c.user_rules,
    )

    c1 = cfg(user_rules=[{"sid": "12345678", "probability": 1}])
    check(
        "match_user_rule 命中",
        (core.match_user_rule(c1, ["123", "12345678"]) or {}).get("sid")
        == "12345678",
    )
    check(
        "match_user_rule 未命中 -> None",
        core.match_user_rule(c1, ["999"]) is None,
    )
    check("无候选 ID -> None", core.match_user_rule(c1, []) is None)
    check(
        "多条规则取第一条",
        (
            core.match_user_rule(
                cfg(
                    user_rules=[
                        {"sid": "12345678", "probability": 0.5},
                        {"sid": "12345678", "probability": 1},
                    ],
                ),
                ["12345678"],
            )
            or {}
        ).get("probability")
        == 0.5,
    )
    print("\n[15] 用户规则：生效配置合并")
    base = cfg(probability=0.1, cooldown_seconds=30, method="possibility_reply")
    eff = core.effective_config(
        base, {"sid": "u", "probability": 1.0, "cooldown_seconds": 0.0},
    )
    check("规则概率覆盖", eff.probability == 1.0, eff.probability)
    check("规则显式 0 覆盖冷却", eff.cooldown_seconds == 0.0, eff.cooldown_seconds)
    check("未设置的字段继承全局", eff.method == base.method and eff.max_per_minute == base.max_per_minute)
    check("全局配置本身不被修改", base.probability == 0.1 and base.cooldown_seconds == 30.0)
    check(
        "空覆盖 -> 原配置对象",
        core.effective_config(base, {"sid": "u"}) is base,
    )
    check(
        "非 dict 规则 -> 原配置对象",
        core.effective_config(base, None) is base,
    )

    print("\n[16] 用户规则：判定与独立记账")
    state = core.ReplyState()
    c = cfg(probability=0, user_rules=[{"sid": "12345678", "probability": 1}])
    rule = core.match_user_rule(c, ["12345678"])
    allowed, _ = core.decide(
        core.effective_config(c, rule), state, "onebot:123456:u12345678", now=1,
    )
    check("全局概率 0 + 用户规则概率 1 -> 回复", allowed is True)
    check(
        "其他人不受规则影响",
        core.decide(c, state, "onebot:123456", now=2)[0] is False,
    )

    state = core.ReplyState()
    c = cfg(
        probability=1,
        cooldown_seconds=60,
        user_rules=[{"sid": "12345678", "cooldown_seconds": 0}],
    )
    rule = core.match_user_rule(c, ["12345678"])
    key = core.user_state_key("onebot", ["123456"], "12345678")
    first = core.decide(core.effective_config(c, rule), state, key, now=100)[0]
    second = core.decide(core.effective_config(c, rule), state, key, now=101)[0]
    other = core.decide(c, state, "onebot:123456", now=102)[0]
    check("规则用户冷却 0：连发都回", first is True and second is True)
    check(
        "规则用户独立记账，无规则者不受其冷却影响",
        other is True,
        other,
    )
    check(
        "用户键与群键互不污染",
        core.user_state_key("onebot", ["123456"], "u1") != core.state_key("onebot", ["123456"]),
    )

    print("\n[17] 用户规则：与白名单/仅 @ 开关的层级")
    check(
        "仅 @ 模式下规则也不放行（插件让位）",
        core.decide(
            core.effective_config(
                cfg(probability=1, user_rules=[{"sid": "12345678", "probability": 1}]),
                {"sid": "12345678", "probability": 1},
            ),
            core.ReplyState(),
            "k",
            now=1,
            require_mention=True,
        )[1]
        == "mention_only",
    )
    check(
        "规则不绕过群白名单（in_whitelist 先行）",
        core.in_whitelist(cfg(whitelist=["111"]), ["999"]) is False,
    )

    print("\n[18] 试算（全局与用户规则参数都走 simulate）")
    result = core.simulate(cfg(probability=0.1), draws=5000, seed=7)
    print("     试算结果:", result)
    check("试算条数正确", result["draws"] == 5000)
    check("试算比例接近 0.1", abs(result["ratio"] - 0.1) < 0.02, result["ratio"])
    always = core.simulate(cfg(probability=0, user_rules=[]), draws=100, seed=3)
    check("概率 0 试算命中 0 条", always["hits"] == 0, always)

    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print("  失败:", name)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
