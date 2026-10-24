# -*- coding: utf-8 -*-
"""主动回复核心逻辑。

纯 Python，不依赖 QwenPaw，方便单独跑单元测试。

判定规则（对群聊里「没有 @ 机器人」的消息）：
    - @ 了机器人                     → 一定回复（与原逻辑一致，不受本插件影响）
    - 频道开着「仅 @ 回复」            → 一律不主动回复（尊重频道设置，只有 @ 才回）
    - 频道关着「仅 @ 回复」且未 @：
        - 命中概率                    → 回复（这就是「主动回复」）
        - 没命中                      → 不回复

也就是说，插件只在频道「回复全部消息」的模式下工作，把「全回」收窄成
「@ 必回 + 不 @ 按概率回」；频道一旦切到「仅 @ 回复」，插件自动让位。
"""

from __future__ import annotations

import random
import time
from dataclasses import MISSING, dataclass, field, fields
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: 主动回复方法
#: possibility_reply - 每条未 @ 消息独立掷骰子
#: rate_limit        - 每分钟最多主动回复 N 条（配额内必回）
METHODS = ("possibility_reply", "rate_limit")

#: 不同通道描述群/会话标识的字段名不一样，统一在这里取
GROUP_ID_KEYS = (
    "group_id",
    "chat_id",
    "feishu_chat_id",
    "feishu_receive_id",
    "channel_id",
    "guild_id",
    "room_id",
    "conversation_id",
)

#: 不同通道在闸门处的 meta 里描述「发消息的人」的字段名（按优先级）。
#: OneBot/QQ: sender_id；元宝: raw_sender_id；飞书: feishu_sender_id。
#: Telegram / Discord 在闸门时还没把用户 ID 放进 meta，指定用户规则对它们不生效。
USER_ID_KEYS = (
    "sender_id",
    "user_id",
    "acl_sender_id",
    "raw_sender_id",
    "feishu_sender_id",
    "qq",
)

#: 用户规则里可覆盖的配置字段（sid 是必填标识，不在此列）
USER_RULE_FIELDS = (
    "probability",
    "method",
    "max_per_minute",
    "cooldown_seconds",
    "min_interval_seconds",
)


@dataclass
class ActiveReplyConfig:
    """主动回复配置，字段与 Console 设置页一一对应。"""

    enabled: bool = True
    """总开关。关闭后完全回到 QwenPaw 原生行为。"""

    method: str = "possibility_reply"
    """主动回复方法：possibility_reply（概率）/ rate_limit（每分钟配额）。"""

    probability: float = 0.1
    """回复概率，0.0~1.0。仅 method=possibility_reply 时生效。"""

    whitelist: List[str] = field(default_factory=list)
    """主动回复白名单（群 ID）。为空表示对所有群生效。"""

    cooldown_seconds: float = 0.0
    """冷却时间（秒）：主动回复一次后，隔多久才允许再次主动回复。0 表示不限制。"""

    max_per_minute: int = 3
    """method=rate_limit 时，每个群每分钟最多主动回复几条。"""

    min_interval_seconds: float = 0.0
    """同一群里两条主动回复之间的最小间隔（秒）。0 表示不限制。"""

    user_rules: List[Dict[str, Any]] = field(default_factory=list)
    """指定用户规则。每条规则：{"sid": 用户ID, ...可覆盖字段}。

    可覆盖字段（值为 None / 缺省表示继承全局配置）：
        probability / method / max_per_minute / cooldown_seconds / min_interval_seconds
    规则命中的消息按「群 + 用户」独立记账冷却、间隔与配额。
    顺序即优先级：一个用户命中多条规则时取第一条。
    """

    # ------------------------------------------------------------------
    @classmethod
    def defaults(cls) -> Dict[str, Any]:
        return {f.name: _copy_default(f) for f in fields(cls)}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ActiveReplyConfig":
        cfg = cls()
        if not isinstance(data, dict):
            return cfg
        valid = {f.name for f in fields(cls)}
        baseline = cls()
        for key, value in data.items():
            if key not in valid or value is None:
                continue
            if key == "user_rules":
                # 规则列表交给 sanitize 逐条规整，这里不能按字符串列表强行转换
                cfg.user_rules = value if isinstance(value, list) else []
                continue
            setattr(cfg, key, _coerce(key, value, getattr(baseline, key)))
        return sanitize(cfg)

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def merge(self, patch: Dict[str, Any]) -> "ActiveReplyConfig":
        return ActiveReplyConfig.from_dict({**self.to_dict(), **(patch or {})})


def _copy_default(f) -> Any:
    if f.default is not MISSING:
        value = f.default
        return list(value) if isinstance(value, list) else value
    if f.default_factory is not MISSING:
        try:
            return f.default_factory()
        except TypeError:
            return None
    return None


def _coerce(key: str, value: Any, default: Any) -> Any:
    """把 JSON / 表单里的字符串转成配置字段应有的类型。"""
    try:
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on", "是"}
            return bool(value)
        if isinstance(default, int) and not isinstance(default, bool):
            return int(float(value))
        if isinstance(default, float):
            return float(value)
        if isinstance(default, list):
            if isinstance(value, str):
                return [v.strip() for v in value.replace("，", ",").split(",") if v.strip()]
            return [str(v).strip() for v in value if str(v).strip()]
        return str(value)
    except (TypeError, ValueError):
        return default


def sanitize(cfg: ActiveReplyConfig) -> ActiveReplyConfig:
    """兜底修正非法值，保证配置写错也不会把插件搞崩。"""
    if cfg.method not in METHODS:
        cfg.method = "possibility_reply"
    try:
        cfg.probability = min(1.0, max(0.0, float(cfg.probability)))
    except (TypeError, ValueError):
        cfg.probability = 0.1
    cfg.cooldown_seconds = max(0.0, cfg.cooldown_seconds)
    cfg.min_interval_seconds = max(0.0, cfg.min_interval_seconds)
    cfg.max_per_minute = max(0, cfg.max_per_minute)
    cfg.whitelist = [str(x).strip() for x in cfg.whitelist if str(x).strip()]
    rules = cfg.user_rules if isinstance(cfg.user_rules, list) else []
    cfg.user_rules = [
        rule for rule in (normalize_user_rule(raw) for raw in rules) if rule
    ]
    return cfg


# ----------------------------------------------------------------------
# 指定用户规则
# ----------------------------------------------------------------------
def _rule_number(value: Any, cast, clamp) -> Optional[Any]:
    """规则字段转数字；空 / 非法一律视为 None（继承全局）。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return clamp(cast(value))
    except (TypeError, ValueError):
        return None


def normalize_user_rule(raw: Any) -> Optional[Dict[str, Any]]:
    """规整一条用户规则；sid 缺失等无效规则返回 None（会被丢弃）。

    字段值为 None 表示「继承全局配置」；显式 0 是合法覆盖（比如冷却 0 = 不冷却）。
    """
    if not isinstance(raw, dict):
        return None
    sid = str(raw.get("sid") or raw.get("user_id") or "").strip()
    if not sid:
        return None
    rule: Dict[str, Any] = {"sid": sid}
    rule["probability"] = _rule_number(
        raw.get("probability"), float, lambda v: min(1.0, max(0.0, v)),
    )
    method = raw.get("method")
    rule["method"] = (
        str(method).strip() if str(method or "").strip() in METHODS else None
    )
    rule["max_per_minute"] = _rule_number(
        raw.get("max_per_minute"), lambda v: int(float(v)), lambda v: max(0, v),
    )
    rule["cooldown_seconds"] = _rule_number(
        raw.get("cooldown_seconds"), float, lambda v: max(0.0, v),
    )
    rule["min_interval_seconds"] = _rule_number(
        raw.get("min_interval_seconds"), float, lambda v: max(0.0, v),
    )
    return rule


# ----------------------------------------------------------------------
# 群标识
# ----------------------------------------------------------------------
def group_ids(meta: Optional[Dict[str, Any]]) -> List[str]:
    """从 meta 里取出所有可能的群/会话标识（不同通道字段名不同）。"""
    if not isinstance(meta, dict):
        return []
    out: List[str] = []
    for key in GROUP_ID_KEYS:
        value = meta.get(key)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out


def in_whitelist(cfg: ActiveReplyConfig, ids: Iterable[str]) -> bool:
    """白名单为空表示不过滤；否则只要任一 ID 命中即通过。"""
    allowed = {str(x).strip() for x in cfg.whitelist if str(x).strip()}
    if not allowed:
        return True
    return any(str(i) in allowed for i in ids)


def user_ids(meta: Optional[Dict[str, Any]]) -> List[str]:
    """从 meta 里取出所有可能的「发消息的人」标识（不同通道字段名不同）。"""
    if not isinstance(meta, dict):
        return []
    out: List[str] = []

    def _push(value: Any) -> None:
        if value in (None, ""):
            return
        text = str(value).strip()
        if text and text not in out:
            out.append(text)

    for key in USER_ID_KEYS:
        _push(meta.get(key))
    # 有些通道把发送者塞进嵌套的 sender / author 对象
    for key in ("sender", "author"):
        nested = meta.get(key)
        if isinstance(nested, dict):
            for sub in ("user_id", "id", "qq", "sender_id"):
                _push(nested.get(sub))
    return out


def match_user_rule(
    cfg: ActiveReplyConfig,
    ids: Iterable[str],
) -> Optional[Dict[str, Any]]:
    """返回第一条命中的用户规则；没命中返回 None。配置顺序即优先级。"""
    candidates = {str(i).strip() for i in ids if str(i).strip()}
    if not candidates:
        return None
    for rule in cfg.user_rules or []:
        sid = str(rule.get("sid", "")).strip() if isinstance(rule, dict) else ""
        if sid and sid in candidates:
            return rule
    return None


def effective_config(
    cfg: ActiveReplyConfig,
    rule: Optional[Dict[str, Any]],
) -> ActiveReplyConfig:
    """把规则里显式设置的字段叠加到全局配置上；None 的字段继承全局。"""
    if not isinstance(rule, dict):
        return cfg
    patch = {
        key: rule[key]
        for key in USER_RULE_FIELDS
        if rule.get(key) is not None
    }
    if not patch:
        return cfg
    return cfg.merge(patch)


def state_key(channel_name: str, ids: Iterable[str]) -> str:
    """冷却/限流的状态键：通道 + 群标识。"""
    ids = list(ids)
    return f"{channel_name or '?'}:{ids[0] if ids else '-'}"


def user_state_key(
    channel_name: str,
    ids: Iterable[str],
    user_id: str,
) -> str:
    """指定用户命中的消息按「群 + 用户」记账，冷却/间隔/配额与群里其他人互不影响。"""
    ids = list(ids)
    return f"{channel_name or '?'}:{ids[0] if ids else '-'}:u{user_id}"


# ----------------------------------------------------------------------
# 状态（冷却 / 限流）
# ----------------------------------------------------------------------
class ReplyState:
    """记录每个群最近的主动回复时间，用于冷却与限流。"""

    def __init__(self) -> None:
        self._hits: Dict[str, List[float]] = {}

    def reset(self) -> None:
        self._hits.clear()

    def hits(self, key: str) -> List[float]:
        return self._hits.get(key, [])

    def record(self, key: str, now: float) -> None:
        self._hits.setdefault(key, []).append(now)

    def last(self, key: str) -> Optional[float]:
        items = self._hits.get(key)
        return items[-1] if items else None

    def count_since(self, key: str, since: float) -> int:
        return sum(1 for ts in self._hits.get(key, []) if ts >= since)

    def prune(self, key: str, keep_after: float) -> None:
        items = [ts for ts in self._hits.get(key, []) if ts >= keep_after]
        if items:
            self._hits[key] = items
        else:
            self._hits.pop(key, None)

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        now = time.time() if now is None else now
        return {
            key: {
                "last": max(ts) if (ts := self._hits.get(key, [])) else None,
                "last_ago": round(now - max(ts), 1) if ts else None,
                "count_1min": self.count_since(key, now - 60),
            }
            for key in list(self._hits)
        }


# ----------------------------------------------------------------------
# 核心判定
# ----------------------------------------------------------------------
def decide(
    cfg: ActiveReplyConfig,
    state: ReplyState,
    key: str,
    now: Optional[float] = None,
    rng: Optional[Any] = None,
    require_mention: bool = False,
) -> Tuple[bool, str]:
    """判断这条「未 @ 机器人」的群消息要不要主动回复。

    Args:
        require_mention: 频道是否开启了「仅 @ 回复」。开启时一律不主动回复，
            尊重用户在频道设置里的显式选择。

    Returns:
        (是否回复, 原因)。原因用于日志与统计：``hit`` / ``miss`` /
        ``rate_limited`` / ``cooldown`` / ``min_interval`` / ``disabled`` /
        ``mention_only``。
    """
    if not cfg.enabled:
        return False, "disabled"

    if require_mention:
        return False, "mention_only"

    now = time.time() if now is None else now
    rng = random.random if rng is None else rng

    last = state.last(key)
    if last is not None:
        if cfg.cooldown_seconds > 0 and now - last < cfg.cooldown_seconds:
            return False, "cooldown"
        if cfg.min_interval_seconds > 0 and now - last < cfg.min_interval_seconds:
            return False, "min_interval"

    if cfg.method == "rate_limit":
        if cfg.max_per_minute <= 0:
            return False, "rate_limited"
        used = state.count_since(key, now - 60)
        if used >= cfg.max_per_minute:
            return False, "rate_limited"
        state.record(key, now)
        return True, "hit"

    # possibility_reply
    if cfg.probability <= 0:
        return False, "miss"
    if cfg.probability >= 1:
        state.record(key, now)
        return True, "hit"
    if rng() < cfg.probability:
        state.record(key, now)
        return True, "hit"
    return False, "miss"


def simulate(
    cfg: ActiveReplyConfig,
    draws: int = 1000,
    seed: Optional[int] = None,
    rng: Optional[Any] = None,
) -> Dict[str, Any]:
    """按当前配置模拟 N 条未 @ 消息，返回预计命中数（设置页用来试算）。"""
    draws = max(1, min(int(draws or 1000), 100000))
    generator = rng or random.Random(seed).random
    state = ReplyState()
    hits = 0
    for index in range(draws):
        allowed, _ = decide(cfg, state, "sim", now=float(index), rng=generator)
        if allowed:
            hits += 1
            if cfg.method == "rate_limit":
                # 限流模式下模拟时间以秒推进，命中即计
                pass
    return {
        "draws": draws,
        "hits": hits,
        "ratio": round(hits / draws, 4),
        "expected": round(cfg.probability, 4)
        if cfg.method == "possibility_reply"
        else None,
    }
