/**
 * QwenPaw 主动回复插件 —— Console 设置页
 *
 * 免构建的 ES Module：React / antd 由宿主（window.QwenPaw.host）提供，
 * 不需要 npm install / vite 打包，改完覆盖即生效。
 *
 * 注册：设置菜单（primary.settings）+ 路由 /settings/active-reply
 * 配置读写走 /api/active-reply/*。
 *
 * 保存策略（v1.0.2 起）：显式保存。
 * 控件改动只更新页面本地状态，点击「保存更改」才写入后端；
 * 保存结果（成功 / 失败及详细原因）明确提示，杜绝"改了不知道存没存"。
 *
 * v1.0.3：修复保存报 405 / 配置读不到（显示默认值）的问题。
 * 宿主的 QP.host.fetch 内部会先过一遍 getApiUrl()，等价于 "/api" + path；
 * 再传 "/api/active-reply/config" 会被拼成 "/api/api/active-reply/config"
 * → GET 404、PUT 405。这里按宿主规则自动选择正确写法，并留了 404/405 重试兜底。
 */

(function () {
  var QP = window.QwenPaw;
  if (!QP || !QP.host || !QP.host.React) {
    return;
  }

  var React = QP.host.React;
  var antd = QP.host.antd || {};
  var h = React.createElement;

  var PLUGIN_ID = "active-reply";

  var REL_API = "/active-reply"; // 不带 /api 前缀（宿主 fetch 会自己补）
  var FULL_API = "/api" + REL_API; // 完整路径（原生 fetch 用）

  var USE_HOST_FETCH = !!(QP.host && typeof QP.host.fetch === "function");

  // 探测宿主是否会补 /api：getApiUrl("/x") 返回 "/api/x" 说明会自动补
  var HOST_ADDS_PREFIX = (function () {
    try {
      if (QP.host && typeof QP.host.getApiUrl === "function") {
        var probe = QP.host.getApiUrl("/__active_reply_probe__");
        return typeof probe === "string" && probe.indexOf("/api") === 0;
      }
    } catch (err) {
      /* 探测失败时按默认处理 */
    }
    return true; // 有 host.fetch 的宿主默认会补 /api（当前实现如此）
  })();

  var API = USE_HOST_FETCH && HOST_ADDS_PREFIX ? REL_API : FULL_API;
  // 兜底写法：万一上面判断反了，遇到 404/405 时换一种再试一次
  var API_ALT = API === REL_API ? FULL_API : USE_HOST_FETCH ? REL_API : null;

  var Card = antd.Card;
  var Switch = antd.Switch;
  var Input = antd.Input;
  var InputNumber = antd.InputNumber;
  var Select = antd.Select;
  var Slider = antd.Slider;
  var Button = antd.Button;
  var Space = antd.Space || function () { return null; };
  var Typography = antd.Typography || {};
  var Tag = antd.Tag;
  var Alert = antd.Alert;
  var Divider = antd.Divider;

  var DEFAULTS = {
    enabled: true,
    method: "possibility_reply",
    probability: 0.1,
    whitelist: [],
    cooldown_seconds: 0,
    max_per_minute: 3,
    min_interval_seconds: 0,
  };

  function callFetch(url, options) {
    if (USE_HOST_FETCH) {
      return QP.host.fetch(url, options || {});
    }
    return window.fetch(url, options || {});
  }

  function request(path, options) {
    function attempt(url) {
      return callFetch(url, options).then(function (resp) {
        return resp.text().then(function (text) {
          var data = null;
          try {
            data = JSON.parse(text);
          } catch (err) {
            data = null;
          }
          if (!resp.ok) {
            var detail =
              data && data.detail ? data.detail : String(text || "").slice(0, 120);
            throw new Error(
              "HTTP " + resp.status + " " + detail + "（地址：" + url + "）",
            );
          }
          return data;
        });
      });
    }
    return attempt(API + path).catch(function (err) {
      // 路径被宿主二次拼接（404/405）时，换另一种写法再试一次
      if (API_ALT && /HTTP (?:404|405)\b/.test(err.message)) {
        return attempt(API_ALT + path);
      }
      throw err;
    });
  }

  function sameConfig(a, b) {
    return JSON.stringify(a || {}) === JSON.stringify(b || {});
  }

  function Row(props) {
    return h(
      "div",
      {
        style: {
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "24px",
          padding: "12px 0",
          borderBottom: "1px solid rgba(128,128,128,0.15)",
        },
      },
      h(
        "div",
        { style: { flex: "1 1 auto", minWidth: 0 } },
        h("div", { style: { fontWeight: 600, marginBottom: "4px" } }, props.title),
        props.desc
          ? h(
              "div",
              {
                style: {
                  fontSize: "12px",
                  opacity: 0.65,
                  lineHeight: "1.6",
                  whiteSpace: "pre-wrap",
                },
              },
              props.desc,
            )
          : null,
      ),
      h(
        "div",
        {
          style: {
            flex: "0 0 auto",
            minWidth: props.wide ? "340px" : "220px",
            textAlign: "right",
          },
        },
        props.children,
      ),
    );
  }

  function ActiveReplySettings() {
    var cfgState = React.useState(null);
    var cfg = cfgState[0];
    var setCfg = cfgState[1];

    var savedState = React.useState(null);
    var saved = savedState[0];
    var setSaved = savedState[1];

    var statusState = React.useState("");
    var status = statusState[0];
    var setStatus = statusState[1];

    var statsState = React.useState(null);
    var stats = statsState[0];
    var setStats = statsState[1];

    var newIdState = React.useState("");
    var newId = newIdState[0];
    var setNewId = newIdState[1];

    var simState = React.useState("");
    var sim = simState[0];
    var setSim = simState[1];

    var savingState = React.useState(false);
    var saving = savingState[0];
    var setSaving = savingState[1];

    var mentionState = React.useState(null);
    var requireMention = mentionState[0];
    var setRequireMention = mentionState[1];

    React.useEffect(function () {
      request("/config")
        .then(function (data) {
          var loaded = Object.assign({}, DEFAULTS, data.config || {});
          setCfg(loaded);
          setSaved(loaded);
        })
        .catch(function (err) {
          setCfg(Object.assign({}, DEFAULTS));
          setSaved(Object.assign({}, DEFAULTS));
          setStatus("读取配置失败：" + err.message + "（显示的是默认值，保存前请先排查）");
        });
      refreshStats();
    }, []);

    function refreshStats() {
      request("/status")
        .then(function (data) {
          setStats(data.stats || null);
          setRequireMention(
            data.require_mention === true || data.require_mention === false
              ? data.require_mention
              : null,
          );
        })
        .catch(function () {
          setStats(null);
        });
    }

    function setField(patch) {
      setCfg(Object.assign({}, cfg, patch));
    }

    var dirty = !!cfg && !!saved && !sameConfig(cfg, saved);

    function save() {
      if (!cfg || saving) {
        return;
      }
      setSaving(true);
      setStatus("正在保存…");
      request("/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      })
        .then(function (data) {
          var applied = Object.assign({}, DEFAULTS, (data && data.config) || cfg);
          setCfg(applied);
          setSaved(applied);
          setStatus("已保存，重启后依然生效");
        })
        .catch(function (err) {
          setStatus("保存失败：" + err.message + "（配置未写入，请重试或截图反馈）");
        })
        .then(function () {
          setSaving(false);
        });
    }

    function revert() {
      setCfg(Object.assign({}, saved || DEFAULTS));
      setStatus("已撤销未保存的更改");
    }

    function addId() {
      var value = (newId || "").trim();
      if (!value) {
        return;
      }
      var list = (cfg.whitelist || []).slice();
      if (list.indexOf(value) === -1) {
        list.push(value);
      }
      setNewId("");
      setField({ whitelist: list });
    }

    function removeId(id) {
      setField({
        whitelist: (cfg.whitelist || []).filter(function (x) {
          return x !== id;
        }),
      });
    }

    if (!cfg) {
      return h("div", { style: { padding: "24px" } }, "加载中…");
    }

    var saveButtons = h(
      Space,
      null,
      h(
        Button,
        {
          type: "primary",
          loading: saving,
          disabled: !dirty || saving,
          onClick: save,
        },
        "保存更改",
      ),
      h(
        Button,
        {
          disabled: !dirty || saving,
          onClick: revert,
        },
        "撤销更改",
      ),
    );

    var rows = [];

    rows.push(
      h(Row, {
        key: "enabled",
        title: "主动回复",
        desc:
          "在频道「仅 @ 回复」关闭时生效：@ 必回，没 @ 的按概率接话。\n" +
          "频道「仅 @ 回复」开启时本插件不生效（只有 @ 才回复），见页面顶部提示。",
        children: h(Switch, {
          checked: !!cfg.enabled,
          onChange: function (v) {
            setField({ enabled: !!v });
          },
        }),
      }),
    );

    rows.push(
      h(Row, {
        key: "method",
        title: "主动回复方法",
        desc:
          "possibility_reply：每条未 @ 的消息独立掷骰子；\n" +
          "rate_limit：每个群每分钟最多主动回复 N 条（配额内必回）。",
        children: h(Select, {
          value: cfg.method,
          style: { width: "100%" },
          onChange: function (v) {
            setField({ method: v });
          },
          options: [
            { value: "possibility_reply", label: "possibility_reply（概率）" },
            { value: "rate_limit", label: "rate_limit（每分钟配额）" },
          ],
        }),
      }),
    );

    if (cfg.method === "possibility_reply") {
      rows.push(
        h(Row, {
          key: "prob",
          title: "回复概率",
          desc: "0.0~1.0 之间的数值。0.1 表示平均每 10 条未 @ 的消息回 1 条。",
          wide: true,
          children: h(
            "div",
            { style: { display: "flex", alignItems: "center", gap: "10px" } },
            h("span", { style: { opacity: 0.6 } }, "0"),
            h("div", { style: { flex: "1 1 auto", minWidth: "160px" } },
              h(Slider, {
                min: 0,
                max: 1,
                step: 0.01,
                value: Number(cfg.probability),
                onChange: function (v) {
                  setField({ probability: v });
                },
              }),
            ),
            h("span", { style: { opacity: 0.6 } }, "1"),
            h(InputNumber, {
              min: 0,
              max: 1,
              step: 0.01,
              value: Number(cfg.probability),
              style: { width: "90px" },
              onChange: function (v) {
                setField({ probability: v == null ? 0.1 : v });
              },
            }),
          ),
        }),
      );
    } else {
      rows.push(
        h(Row, {
          key: "quota",
          title: "每分钟最多回复",
          desc: "每个群每分钟允许主动回复的最大条数。",
          children: h(InputNumber, {
            min: 0,
            step: 1,
            value: cfg.max_per_minute,
            style: { width: "100%" },
            onChange: function (v) {
              setField({ max_per_minute: v == null ? 0 : v });
            },
          }),
        }),
      );
    }

    rows.push(
      h(Row, {
        key: "whitelist",
        title: "主动回复白名单",
        desc:
          "为空时不启用白名单过滤（对所有群生效）。\n" +
          "在群里 @ 机器人 发 /sid 即可拿到群 ID。",
        wide: true,
        children: h(
          "div",
          null,
          h(
            "div",
            { style: { display: "flex", gap: "8px" } },
            h(Input, {
              value: newId,
              placeholder: "群 ID",
              onChange: function (e) {
                setNewId(e.target.value);
              },
              onPressEnter: addId,
            }),
            h(Button, { type: "primary", ghost: true, onClick: addId }, "添加更多"),
          ),
          (cfg.whitelist || []).length
            ? h(
                "div",
                { style: { marginTop: "8px", textAlign: "left" } },
                (cfg.whitelist || []).map(function (id) {
                  return h(
                    Tag,
                    {
                      key: id,
                      closable: true,
                      color: "blue",
                      style: { marginBottom: "4px" },
                      onClose: function () {
                        removeId(id);
                      },
                    },
                    id,
                  );
                }),
              )
            : h(
                "div",
                { style: { marginTop: "8px", fontSize: "12px", opacity: 0.5 } },
                "当前未设置，对所有群生效",
              ),
        ),
      }),
    );

    rows.push(
      h(Row, {
        key: "cooldown",
        title: "冷却时间（秒）",
        desc: "主动回复一次后，需要隔多久才允许再次主动回复。0 表示不限制。",
        children: h(InputNumber, {
          min: 0,
          step: 1,
          value: cfg.cooldown_seconds,
          style: { width: "100%" },
          onChange: function (v) {
            setField({ cooldown_seconds: v == null ? 0 : v });
          },
        }),
      }),
    );

    rows.push(
      h(Row, {
        key: "mininterval",
        title: "最小间隔（秒）",
        desc: "同一群里两条主动回复之间的最短间隔，防止连续接话。",
        children: h(InputNumber, {
          min: 0,
          step: 1,
          value: cfg.min_interval_seconds,
          style: { width: "100%" },
          onChange: function (v) {
            setField({ min_interval_seconds: v == null ? 0 : v });
          },
        }),
      }),
    );

    var statsPanel = h(
      "div",
      { style: { marginTop: "16px" } },
      h(
        "div",
        { style: { fontSize: "15px", fontWeight: 700, marginBottom: "8px" } },
        "运行状态",
      ),
      stats
        ? h(
            "div",
            { style: { fontSize: "13px", lineHeight: "2" } },
            h(
              "div",
              null,
              "频道「仅 @ 回复」：" +
                (requireMention === null
                  ? "未识别（收到群消息后显示）"
                  : requireMention
                    ? "开启 → 插件不主动接话"
                    : "关闭 → @ 必回，不 @ 按概率回"),
            ),
            h("div", null, "群消息总数：" + stats.group_messages),
            h("div", null, "@ 机器人（必定回复）：" + stats.mentioned),
            h(
              "div",
              null,
              h("b", null, "主动接话：" + stats.proactive),
              "　保持沉默：" + stats.ignored,
            ),
            stats.mention_mode
              ? h("div", null, "仅 @ 回复模式跳过：" + stats.mention_mode)
              : null,
            stats.whitelist_skipped
              ? h("div", null, "因白名单跳过：" + stats.whitelist_skipped)
              : null,
            stats.errors ? h("div", null, "判定异常回退：" + stats.errors) : null,
          )
        : h("div", { style: { fontSize: "13px", opacity: 0.6 } }, "读取中…"),
      h(
        Space,
        { style: { marginTop: "8px" } },
        h(Button, { size: "small", onClick: refreshStats }, "刷新状态"),
        h(Button, { size: "small", onClick: runSimulate }, "试算 1000 条"),
        h(
          Button,
          {
            size: "small",
            danger: true,
            onClick: function () {
              request("/reset-stats", { method: "POST" }).then(function () {
                refreshStats();
              });
            },
          },
          "清零统计",
        ),
      ),
      sim
        ? h(
            "div",
            { style: { marginTop: "8px", fontSize: "12px", opacity: 0.7 } },
            sim,
          )
        : null,
    );

    function runSimulate() {
      request("/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draws: 1000 }),
      })
        .then(function (data) {
          setSim(
            "模拟 1000 条未 @ 的群消息，预计回复 " +
              data.hits +
              " 条（占比 " +
              (data.ratio * 100).toFixed(1) +
              "%）",
          );
        })
        .catch(function (err) {
          setSim("试算失败：" + err.message);
        });
    }

    return h(
      "div",
      { style: { padding: "24px", maxWidth: "900px" } },
      h(Typography.Title ? Typography.Title : "h2", { level: 4 }, "主动回复"),
      h(
        "div",
        { style: { fontSize: "12px", opacity: 0.6, marginBottom: "12px" } },
        "让机器人在群里像群友一样，偶尔接一句没 @ 它的话",
      ),
      h(
        Alert,
        {
          type:
            requireMention === null
              ? "info"
              : requireMention
                ? "warning"
                : "success",
          showIcon: true,
          style: { marginBottom: "12px" },
          message:
            requireMention === null
              ? "行为说明：频道「仅 @ 回复」关闭时，@ 必回、没 @ 按概率回；开启时只有 @ 才回复。收到群消息后这里会显示当前状态。"
              : requireMention
                ? "当前频道「仅 @ 回复」已开启：机器人只回复 @ 它的消息，本插件不主动接话。想启用主动回复，请到频道设置里关闭「仅 @ 回复」。"
                : "当前频道「仅 @ 回复」已关闭：@ 机器人的消息 100% 回复；没 @ 的消息按下方概率决定是否接话。",
        },
      ),
      dirty
        ? h(
            Alert,
            {
              type: "warning",
              showIcon: true,
              style: { marginBottom: "12px" },
              message: "有未保存的更改，记得点击「保存更改」",
            },
          )
        : null,
      status
        ? h(Alert, {
            message: status,
            type: /失败|错误/.test(status) ? "error" : /保存中/.test(status) ? "info" : "success",
            style: { marginBottom: "12px" },
            closable: true,
          })
        : null,
      h(
        Card,
        null,
        rows,
        h(Divider, null),
        h(
          "div",
          { style: { display: "flex", justifyContent: "flex-end", gap: "8px" } },
          saveButtons,
        ),
        h(Divider, null),
        statsPanel,
      ),
    );
  }

  try {
    if (QP.menu && QP.menu.add) {
      QP.menu.add(PLUGIN_ID, {
        id: "active-reply.settings",
        label: "主动回复",
        route: "active-reply.settings",
        location: "primary.settings",
        order: 101,
      });
    }
    if (QP.route && QP.route.add) {
      QP.route.add(PLUGIN_ID, {
        id: "active-reply.settings",
        path: "/settings/active-reply",
        component: ActiveReplySettings,
      });
    }
  } catch (err) {
    if (window.console) {
      window.console.error("[active-reply] 注册设置页失败", err);
    }
  }
})();
