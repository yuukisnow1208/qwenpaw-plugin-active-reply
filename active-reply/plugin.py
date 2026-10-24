# -*- coding: utf-8 -*-
"""QwenPaw 主动回复插件（active-reply）。

群里机器人原本只有两种活法：要么每条都回，要么只有 @ 它才回。
这个插件给了第三种：**按概率选择性回复**——没 @ 它的消息，也有机会被接话。

行为规则（与频道「仅 @ 回复」开关协同）：
    - 频道「仅 @ 回复」**开启**：只有 @ 才回复，插件不主动插话（尊重频道设置）
    - 频道「仅 @ 回复」**关闭**：@ 必回；没 @ 的按概率回

实现原理
--------
所有支持群聊的通道（QQ/OneBot、Telegram、飞书、Discord、元宝……）在收到群消息后，
都会调用同一个闸门：

    if not self._check_group_mention(is_group, meta):
        return          # 静默丢弃这条消息

而 ``_check_group_mention`` 只在 ``BaseChannel`` 里实现一次：

    def _check_group_mention(self, is_group, meta):
        if not is_group or not self.require_mention:
            return True
        return bool(meta.get("bot_mentioned") or meta.get("has_bot_command"))

所以在这里包一层，把「全回」模式收窄成「按概率回」：

    原:  群里没 @ 且 require_mention=False → 全部放行（每条都回）
    改:  群里没 @ 且 require_mention=False → 掷骰子 → 命中则进入 agent 流程

如果频道把 ``require_mention`` 开了（仅 @ 回复），插件直接让位，保持原生行为。
@ 了机器人依然 100% 回复，不受影响。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import core  # noqa: E402  （同目录下的纯逻辑模块）

logger = logging.getLogger("qwenpaw.plugin.active_reply")

PLUGIN_ID = "active-reply"
VERSION = "1.0.4"

#: 判定原因 -> 中文说明，用于日志与设置页统计
REASON_TEXT = {
    "hit": "命中概率，主动回复",
    "miss": "未命中概率，保持沉默",
    "rate_limited": "超出每分钟配额，保持沉默",
    "cooldown": "冷却中，保持沉默",
    "min_interval": "未到最小间隔，保持沉默",
    "mention_only": "频道仅 @ 回复模式，不主动插话",
    "disabled": "插件已关闭",
}


class ActiveReplyPlugin:
    """插件主体：加载配置 -> 包装群聊闸门 -> 注册 /sid 与配置接口。"""

    def __init__(self) -> None:
        self.api: Any = None
        self.config: core.ActiveReplyConfig = core.ActiveReplyConfig()
        self.config_path: Optional[Path] = None
        self.state = core.ReplyState()
        self.stats: Dict[str, int] = {
            "group_messages": 0,
            "mentioned": 0,
            "proactive": 0,
            "ignored": 0,
            "mention_mode": 0,
            "whitelist_skipped": 0,
            "errors": 0,
        }
        self.require_mention_state: Optional[bool] = None
        self._patched = False
        self._original = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def register(self, api: Any) -> None:
        self.api = api
        self._load_config(getattr(api, "config", None) or {})
        self._patch_channels()
        self._register_command()
        self._register_routes()
        logger.info(
            "主动回复插件已加载 v%s | 配置=%s | 启用=%s | 方法=%s | 概率=%s | 白名单=%s",
            VERSION,
            self.config_path,
            self.config.enabled,
            self.config.method,
            self.config.probability,
            self.config.whitelist or "全部群",
        )

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def _load_config(self, seed: Dict[str, Any]) -> None:
        path = self._resolve_config_path()
        file_data: Dict[str, Any] = {}
        if path.exists():
            try:
                file_data = json.loads(path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                logger.warning("主动回复：配置文件解析失败，使用默认配置 %s", path)
                file_data = {}

        merged = {**core.ActiveReplyConfig.defaults(), **(seed or {}), **file_data}
        self.config = core.ActiveReplyConfig.from_dict(merged)
        self.config_path = path
        self._save_config()

    def _resolve_config_path(self) -> Path:
        candidate = _HERE / "config.json"
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            if not candidate.exists():
                with candidate.open("a", encoding="utf-8"):
                    pass
            return candidate
        except OSError:
            fallback = Path.home() / ".qwenpaw" / "active-reply.json"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            return fallback

    def _save_config(self) -> None:
        if not self.config_path:
            return
        try:
            self.config_path.write_text(
                json.dumps(self.config.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("主动回复：配置保存失败 %s", exc)

    def update_config(self, patch: Dict[str, Any]) -> core.ActiveReplyConfig:
        self.config = self.config.merge(patch or {})
        self._save_config()
        return self.config

    # ------------------------------------------------------------------
    # 包装群聊闸门
    # ------------------------------------------------------------------
    def _patch_channels(self) -> None:
        try:
            from qwenpaw.app.channels.base import BaseChannel
        except ImportError as exc:  # pragma: no cover
            logger.error("主动回复：无法导入 BaseChannel，插件未生效 %s", exc)
            return

        if getattr(BaseChannel, "_active_reply_patched", False):
            logger.info("主动回复：BaseChannel._check_group_mention 已被包装，跳过")
            self._patched = True
            return

        self._original = BaseChannel._check_group_mention
        plugin = self

        def patched_check_group_mention(
            self,  # noqa: N805  （channel 实例）
            is_group: bool,
            meta: dict,
        ) -> bool:
            try:
                return plugin._decide(self, is_group, meta)
            except Exception:  # pylint: disable=broad-except
                plugin.stats["errors"] += 1
                logger.exception("主动回复：判定异常，回退原生行为")
                return plugin._original(self, is_group, meta)

        patched_check_group_mention.__name__ = "_check_group_mention"
        patched_check_group_mention.__qualname__ = (
            "BaseChannel._check_group_mention"
        )
        BaseChannel._check_group_mention = patched_check_group_mention
        BaseChannel._active_reply_patched = True  # type: ignore[attr-defined]
        self._patched = True

    def _decide(self, channel: Any, is_group: bool, meta: dict) -> bool:
        """核心判定：先跑原生逻辑，再按「仅 @ 回复」开关与概率改写「未 @」的结论。"""
        original = self._original
        original_result = original(channel, is_group, meta)

        cfg = self.config
        if not is_group or not cfg.enabled:
            return original_result

        self.stats["group_messages"] += 1
        meta = meta or {}

        # @ 了机器人 / 在群里用了命令 -> 一定回复，不变
        if meta.get("bot_mentioned") or meta.get("has_bot_command"):
            self.stats["mentioned"] += 1
            return True

        # 频道开启了「仅 @ 回复」-> 尊重该设置，未 @ 消息一律不主动回复。
        # 这是用户在频道设置里的显式选择，插件不与之对抗。
        require_mention = bool(getattr(channel, "require_mention", False))
        self.require_mention_state = require_mention
        if require_mention:
            self.stats["mention_mode"] += 1
            logger.debug(
                "主动回复: channel=%s 仅 @ 回复模式，未 @ 消息保持沉默",
                getattr(channel, "channel", "?"),
            )
            return False

        ids = core.group_ids(meta)
        if not core.in_whitelist(cfg, ids):
            self.stats["whitelist_skipped"] += 1
            return original_result

        key = core.state_key(getattr(channel, "channel", ""), ids)
        allowed, reason = core.decide(
            cfg, self.state, key, now=time.time(), require_mention=require_mention
        )

        if allowed:
            self.stats["proactive"] += 1
            logger.info(
                "主动回复: channel=%s group=%s 概率=%s 方法=%s -> 接话",
                getattr(channel, "channel", "?"),
                ids[0] if ids else "-",
                cfg.probability,
                cfg.method,
            )
            return True

        if reason == "mention_only":
            self.stats["mention_mode"] += 1
        else:
            self.stats["ignored"] += 1
        logger.debug(
            "主动回复: channel=%s group=%s -> %s",
            getattr(channel, "channel", "?"),
            ids[0] if ids else "-",
            REASON_TEXT.get(reason, reason),
        )
        return False

    # ------------------------------------------------------------------
    # /sid 命令：方便拿群 ID 填白名单
    # ------------------------------------------------------------------
    def _register_command(self) -> None:
        try:
            from qwenpaw.runtime.commands.control.base import (
                BaseControlCommandHandler,
            )
        except ImportError as exc:  # pragma: no cover
            logger.warning("主动回复：无法导入命令基类，跳过 /sid %s", exc)
            return

        plugin = self

        class SidCommand(BaseControlCommandHandler):
            command_name = "/sid"
            description = "查看当前会话 / 群 ID（用于主动回复白名单）"

            async def handle(self, context: Any) -> str:
                meta = plugin._payload_meta(getattr(context, "payload", None))
                ids = core.group_ids(meta)
                lines = ["📍 会话 ID：" + str(getattr(context, "session_id", "") or "-")]
                if ids:
                    lines.append("👥 群 ID：" + ids[0])
                    extra = [i for i in ids[1:]]
                    if extra:
                        lines.append("　其它标识：" + "、".join(extra))
                    lines.append("把上面的群 ID 填进「主动回复白名单」即可。" if plugin.config.whitelist else "把上面的群 ID 填进「主动回复白名单」可限定生效范围。")
                else:
                    lines.append("👥 群 ID：（当前会话不是群聊）")
                lines.append(
                    f"⚙️ 当前状态：{'开启' if plugin.config.enabled else '关闭'} · "
                    f"{plugin.config.method} · 概率 {plugin.config.probability}",
                )
                if plugin.require_mention_state is not None:
                    lines.append(
                        "📢 频道「仅 @ 回复」："
                        + ("开启 → 只有 @ 才回复，插件不主动接话"
                           if plugin.require_mention_state
                           else "关闭 → @ 必回，不 @ 按概率回")
                    )
                return "\n".join(lines)

        try:
            self.api.register_control_command(SidCommand())
            logger.info("主动回复：已注册 /sid 命令")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("主动回复：注册 /sid 失败 %s", exc)

    @staticmethod
    def _payload_meta(payload: Any) -> Dict[str, Any]:
        """从 payload（dict 或 AgentRequest）里挖出 meta。"""
        if isinstance(payload, dict):
            meta = payload.get("meta")
            if isinstance(meta, dict) and meta:
                return meta
            return {
                key: payload[key]
                for key in core.GROUP_ID_KEYS
                if payload.get(key) not in (None, "")
            }
        meta = getattr(payload, "channel_meta", None)
        return meta if isinstance(meta, dict) else {}

    # ------------------------------------------------------------------
    # HTTP 接口（Console 设置页）
    # ------------------------------------------------------------------
    def _register_routes(self) -> None:
        try:
            from fastapi import APIRouter, Body, HTTPException
        except ImportError:  # pragma: no cover
            logger.warning("主动回复：FastAPI 不可用，跳过配置接口注册")
            return

        router = APIRouter()
        plugin = self

        @router.get("/config")
        async def get_config() -> Dict[str, Any]:
            return {
                "ok": True,
                "config": plugin.config.to_dict(),
                "path": str(plugin.config_path or ""),
                "version": VERSION,
                "patched": plugin._patched,
            }

        @router.put("/config")
        async def put_config(
            patch: Dict[str, Any] = Body(default={}),
        ) -> Dict[str, Any]:
            if not isinstance(patch, dict):
                raise HTTPException(status_code=400, detail="配置必须是 JSON 对象")
            unknown = [
                key for key in patch if key not in core.ActiveReplyConfig.defaults()
            ]
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=f"未知配置项: {', '.join(unknown)}",
                )
            config = plugin.update_config(patch)
            return {"ok": True, "config": config.to_dict()}

        @router.get("/status")
        async def status() -> Dict[str, Any]:
            return {
                "ok": True,
                "id": PLUGIN_ID,
                "version": VERSION,
                "enabled": plugin.config.enabled,
                "patched": plugin._patched,
                "stats": dict(plugin.stats),
                "groups": plugin.state.snapshot(),
                "require_mention": plugin.require_mention_state,
                "config_path": str(plugin.config_path or ""),
            }

        @router.post("/simulate")
        async def simulate(
            payload: Dict[str, Any] = Body(default={}),
        ) -> Dict[str, Any]:
            draws = int(payload.get("draws") or 1000)
            override = payload.get("config") or {}
            cfg = plugin.config.merge(override) if isinstance(override, dict) and override else plugin.config
            return {"ok": True, **core.simulate(cfg, draws=draws)}

        @router.post("/reset-stats")
        async def reset_stats() -> Dict[str, Any]:
            for key in plugin.stats:
                plugin.stats[key] = 0
            plugin.state.reset()
            return {"ok": True}

        try:
            self.api.register_http_router(
                router,
                prefix="/active-reply",
                tags=["active-reply"],
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("主动回复：注册 HTTP 接口失败 %s", exc)


# 模块级实例：插件加载器要求导出 `plugin`
plugin = ActiveReplyPlugin()
