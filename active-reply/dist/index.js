/**
 * QwenPaw 主动回复插件 —— Console 设置页
 *
 * 免构建的 ES Module：React / antd 由宿主（window.QwenPaw.host）提供，
 * 不需要 npm install / vite 打包，改完覆盖即生效。
 *
 * 注册：设置菜单（primary.settings）+ 路由 /settings/active-reply
 * 配置读写走 /api/active-reply/*。
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
  var API = "/api/active-reply";

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

  function request(path, options) {
    var fetcher = QP.host.fetch || window.fetch.bind(window);
    return fetcher(path, options || {}).then(function (resp) {
      return resp.json();
    });
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

    React.useEffect(function () {
      request(API + "/config")
        .then(function (data) {
          setCfg(Object.assign({}, DEFAULTS, data.config || {}));
        })
        .catch(function () {
          setCfg(Object.assign({}, DEFAULTS));
          setStatus("未能读取后端配置，显示的是默认值");
        });
      refreshStats();
    }, []);

    function refreshStats() {
      request(API + "/status")
        .then(function (data) {
          setStats(data.stats || null);
        })
        .catch(function () {
          setStats(null);
        });
    }

    function update(patch) {
      var next = Object.assign({}, cfg, patch);
      setCfg(next);
      request(API + "/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      })
        .then(function (data) {
          setCfg(Object.assign({}, DEFAULTS, (data && data.config) || next));
          setStatus("已保存，立即生效（无需重启）");
        })
        .catch(function (err) {
          setStatus("保存失败：" + err);
        });
    }

    function runSimulate() {
      request(API + "/simulate", {
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
          setSim("试算失败：" + err);
        });
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
      update({ whitelist: list });
    }

    function removeId(id) {
      update({
        whitelist: (cfg.whitelist || []).filter(function (x) {
          return x !== id;
        }),
      });
    }

    if (!cfg) {
      return h("div", { style: { padding: "24px" } }, "加载中…");
    }

    var rows = [];

    rows.push(
      h(Row, {
        key: "enabled",
        title: "主动回复",
        desc:
          "开启后，群里没 @ 机器人的消息也会按概率被接话。\n" +
          "@ 了机器人的消息始终 100% 回复，不受影响。",
        children: h(Switch, {
          checked: !!cfg.enabled,
          onChange: function (v) {
            update({ enabled: !!v });
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
            update({ method: v });
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
                  setCfg(Object.assign({}, cfg, { probability: v }));
                },
                onAfterChange: function (v) {
                  update({ probability: v });
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
                update({ probability: v == null ? 0.1 : v });
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
              update({ max_per_minute: v == null ? 0 : v });
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
            update({ cooldown_seconds: v == null ? 0 : v });
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
            update({ min_interval_seconds: v == null ? 0 : v });
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
            h("div", null, "群消息总数：" + stats.group_messages),
            h("div", null, "@ 机器人（必定回复）：" + stats.mentioned),
            h(
              "div",
              null,
              h("b", null, "主动接话：" + stats.proactive),
              "　保持沉默：" + stats.ignored,
            ),
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
              request(API + "/reset-stats", { method: "POST" }).then(function () {
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

    return h(
      "div",
      { style: { padding: "24px", maxWidth: "900px" } },
      h(Typography.Title ? Typography.Title : "h2", { level: 4 }, "主动回复"),
      h(
        "div",
        { style: { fontSize: "12px", opacity: 0.6, marginBottom: "8px" } },
        "群里没被 @ 的时候，也有机会接一句话",
      ),
      status
        ? h(Alert, {
            message: status,
            type: /失败|错误/.test(status) ? "error" : "success",
            style: { marginBottom: "12px" },
            closable: true,
          })
        : null,
      h(Card, null, rows, h(Divider, null), statsPanel),
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
