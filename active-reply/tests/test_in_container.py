# -*- coding: utf-8 -*-
"""容器内端到端桩测试：验证插件确实接管了 BaseChannel._check_group_mention。

在 QwenPaw 容器里运行：
    /app/venv/bin/python /tmp/active_reply_test/tests/test_in_container.py

用一个只设置必要属性的假通道对象驱动真实的补丁逻辑，
不需要连任何聊天平台。
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

PLUGIN_DIR = Path("/app/working/plugins/active-reply")

PASSED = 0
FAILED = []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print(f"  OK   {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name} -> {detail}")


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "plugin_active_reply_test",
        PLUGIN_DIR / "plugin.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["plugin_active_reply_test"] = module
    spec.loader.exec_module(module)
    return module


class FakeApi:
    def __init__(self):
        self.plugin_id = "active-reply"
        self.config = {}
        self.manifest = {}
        self.routers = []
        self.commands = []

    def register_http_router(self, router, *, prefix="", tags=None):
        self.routers.append((prefix, tags))

    def register_control_command(self, handler, priority_level=10):
        self.commands.append(handler)


def main():
    from qwenpaw.app.channels.base import BaseChannel
    from qwenpaw.schemas import RunStatus  # noqa: F401  （确保 qwenpaw 可导入）

    module = load_plugin()
    core = module.core
    plugin = module.plugin

    print("\n[0] 注册插件")
    api = FakeApi()
    plugin.register(api)
    check("HTTP 路由已注册", ("/active-reply", ["active-reply"]) in api.routers, api.routers)
    check("/sid 命令已注册", any(getattr(c, "command_name", "") == "/sid" for c in api.commands), api.commands)
    check(
        "_check_group_mention 已被包装",
        getattr(BaseChannel, "_active_reply_patched", False)
        and BaseChannel._check_group_mention.__name__ == "_check_group_mention",
    )

    def make_channel(name="onebot", require_mention=True):
        """构造一个只带必要属性的假通道。"""
        ch = BaseChannel.__new__(BaseChannel)
        ch.channel = name
        ch.require_mention = require_mention
        return ch

    def set_cfg(**kwargs):
        plugin.config = core.ActiveReplyConfig.from_dict(kwargs)
        plugin.state = core.ReplyState()

    def mention(ch, meta, is_group=True):
        return ch._check_group_mention(is_group, meta)

    GROUP = {"group_id": "123456", "is_group": True, "bot_mentioned": False}
    AT = {"group_id": "123456", "is_group": True, "bot_mentioned": True}

    print("\n[1] @ 机器人 -> 必定回复")
    set_cfg(probability=0.0)
    ch = make_channel()
    check("概率 0 但被 @ 仍回复", mention(ch, AT) is True)

    print("\n[2] 概率 1 -> 未 @ 也回复（主动接话）")
    set_cfg(probability=1.0)
    ch = make_channel()
    check("概率 1 主动接话", mention(ch, GROUP) is True)

    print("\n[3] 概率 0 -> 未 @ 保持沉默")
    set_cfg(probability=0.0)
    ch = make_channel()
    check("概率 0 不接话", mention(ch, GROUP) is False)

    print("\n[4] 概率 0.1 的实际命中率")
    set_cfg(probability=0.1)
    ch = make_channel()
    random.seed(7)
    hits = sum(1 for _ in range(2000) if mention(ch, GROUP))
    ratio = hits / 2000
    print(f"     2000 条未 @ 消息，主动回复 {hits} 条（{ratio:.3%}）")
    check("命中率在 8%~12% 之间", 0.08 <= ratio <= 0.12, ratio)

    print("\n[5] 关闭开关 -> 回到原生行为")
    set_cfg(enabled=False, probability=1.0)
    ch = make_channel()
    check("关闭后未 @ 不回复", mention(ch, GROUP) is False)
    check("关闭后被 @ 仍回复", mention(ch, AT) is True)

    print("\n[6] 白名单")
    set_cfg(probability=1.0, whitelist=["999"])
    ch = make_channel()
    check("白名单外的群不接话", mention(ch, GROUP) is False)
    set_cfg(probability=1.0, whitelist=["123456"])
    ch = make_channel()
    check("白名单内的群接话", mention(ch, GROUP) is True)
    set_cfg(probability=1.0, whitelist=[])
    ch = make_channel()
    check("白名单为空 -> 全部群生效", mention(ch, GROUP) is True)

    print("\n[7] 通道原本是「回复全部」时，插件会把它收窄为按概率")
    set_cfg(probability=0.0)
    ch_open = make_channel(require_mention=False)
    check("全回模式 + 概率 0 -> 不接话", mention(ch_open, GROUP) is False)
    check("全回模式 + 被 @ -> 照常回复", mention(ch_open, AT) is True)

    print("\n[8] 私聊不受影响")
    set_cfg(probability=0.0)
    ch = make_channel()
    check("私聊消息照常处理", mention(ch, {"is_group": False}, is_group=False) is True)

    print("\n[9] 冷却")
    set_cfg(probability=1.0, cooldown_seconds=60)
    ch = make_channel()
    first = mention(ch, GROUP)
    second = mention(ch, GROUP)
    check("首次接话后进入冷却", first is True and second is False, (first, second))

    print("\n[10] 每分钟配额")
    set_cfg(method="rate_limit", max_per_minute=2)
    ch = make_channel()
    results = [mention(ch, GROUP) for _ in range(3)]
    check("配额 2 -> 前两条接话、第三条沉默", results == [True, True, False], results)

    print("\n[11] 统计")
    print("     stats:", plugin.stats)
    check("统计里有主动接话记录", plugin.stats["proactive"] > 0, plugin.stats)
    check("统计里有沉默记录", plugin.stats["ignored"] > 0, plugin.stats)

    print("\n[12] /sid 命令")
    sid = api.commands[0]
    check("命令名是 /sid", sid.command_name == "/sid")

    class Ctx:
        session_id = "onebot:group_123456"
        payload = {"meta": {"group_id": "123456", "is_group": True}}
        user_id = "u1"
        agent_id = "default"
        workspace = None
        channel = None
        args = {}

    import asyncio

    text = asyncio.run(sid.handle(Ctx()))
    print("     /sid 返回:")
    for line in text.splitlines():
        print("       " + line)
    check("返回里包含群 ID", "123456" in text, text)
    check("返回里包含会话 ID", "onebot:group_123456" in text, text)

    print("\n" + "=" * 60)
    print(f"通过 {PASSED} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print("  失败:", name)
        return 1
    print("容器内验证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
