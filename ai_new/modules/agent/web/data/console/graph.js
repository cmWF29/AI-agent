/* HiveGraph：控制台唯一的状态机/流程图渲染出口。
   离线依赖（vendored 在 assets/）：cytoscape.min.js、dagre.min.js、cytoscape-dagre.js。
   对外只暴露 mount / fit / zoomBy；节点文案、边标签全部来自视图规格数据，本文件不写业务字面量。 */
(function (global) {
  "use strict";

  const instances = new WeakMap();

  function extRegistered() { return !!global.__hiveGraphRegistered; }
  function registerExt() {
    if (extRegistered()) return;
    if (global.cytoscape && global.cytoscapeDagre) {
      global.cytoscape.use(global.cytoscapeDagre);
      global.__hiveGraphRegistered = true;
    }
  }

  function ensureCanvas(el) {
    let canvas = el.querySelector(".graph-canvas");
    if (!canvas) {
      canvas = document.createElement("div");
      canvas.className = "graph-canvas";
      el.appendChild(canvas);
    }
    return canvas;
  }

  /* 节点配色：tone 由规格给；未给就按终态/活跃态落回中性与主题色。 */
  function toneColor(n) {
    const map = {
      idle: "#5f87dd", press: "#3fae68", drag: "#2aa9a4", scroll: "#6f7fd0",
      swallow: "#98a2b1", busy: "#dd8f3f", modal: "#9a6adb",
    };
    return map[n.tone] || (n.terminal ? "#00b42a" : "#2f6bff");
  }

  function nodeLabel(n) {
    const lines = [];
    if (n.label) lines.push(n.label);
    if (n.sub) lines.push(n.sub);
    if (n.badge) lines.push(n.badge);
    return lines.join("\n");
  }

  function mount(el, spec) {
    registerExt();
    if (!el || !global.cytoscape) return null;
    spec = spec || {};

    const prev = instances.get(el);
    if (prev) { try { prev.destroy(); } catch (e) {} }

    const nodes = (spec.nodes || []).map((n) => ({
      data: {
        id: n.id,
        label: nodeLabel(n),
        tone: toneColor(n),
        terminal: !!n.terminal,
        active: !!n.active,
      },
    }));
    const edges = (spec.edges || []).map((e) => ({
      data: {
        id: String(e.from) + "->" + String(e.to) + (e.label ? ":" + e.label : ""),
        source: e.from,
        target: e.to,
        label: spec.edgeLabels === false ? "" : (e.label || ""),
        back: !!e.back,
      },
    }));

    const canvas = ensureCanvas(el);
    // 窄屏竖排、宽屏横排：手机上横向画会把字号压到看不清，桌面横向更省高度。
    const narrow = (el.clientWidth || window.innerWidth) < 620 || window.innerWidth < 720;
    const rankDir = narrow ? "TB" : (spec.direction === "TB" ? "TB" : "LR");
    const cy = global.cytoscape({
      container: canvas,
      elements: { nodes, edges },
      minZoom: 0.3,
      maxZoom: 2.5,
      wheelSensitivity: 0.25,
      boxSelectionEnabled: false,
      autoungrabify: true,
      layout: {
        name: "dagre",
        rankDir: rankDir,
        nodeSep: 22,
        edgeSep: 18,
        rankSep: 58,
        animate: false,
        fit: false,
        padding: 12,
      },
      style: [
        {
          selector: "node",
          style: {
            shape: "round-rectangle",
            width: 156,
            height: 78,
            "background-color": "#ffffff",
            "border-width": 1.3,
            "border-color": "data(tone)",
            label: "data(label)",
            "text-wrap": "wrap",
            "text-max-width": "138px",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": 11.5,
            "line-height": 1.25,
            "color": "#1d2129",
            "text-margin-y": 0,
          },
        },
        {
          selector: "node[?terminal]",
          style: { "border-color": "#00b42a", "border-width": 1.6, "background-color": "#e8f8ee" },
        },
        {
          selector: "node[?active]",
          style: { "border-color": "#2f6bff", "border-width": 2, "background-color": "#eef3ff" },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "#8a97a8",
            "arrow-scale": 1,
            width: 1.4,
            lineColor: "#8a97a8",
            label: "data(label)",
            "font-size": 10.5,
            "line-height": 1.2,
            "text-wrap": "wrap",
            "text-max-width": "108px",
            color: "#7c8798",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.94,
            "text-background-padding": 3,
            "text-rotation": "none",
            "text-margin-y": -2,
          },
        },
        {
          selector: "edge[?back]",
          style: {
            lineColor: "#e2571e",
            "target-arrow-color": "#e2571e",
            "line-style": "dashed",
            color: "#e2571e",
          },
        },
      ],
    });

    instances.set(el, cy);
    cy.on("layoutstop", () => { safeFit(el, cy, true); });
    // dagre 在构造期同步跑完布局，事件可能已经错过；下一帧补一次 fit+居中。
    setTimeout(() => safeFit(el, cy, true), 0);
    return cy;
  }

  function lookup(el) { return instances.get(el) || null; }

  /* 把当前缩放百分比写进卡片上的 .dag-pct 观察点（验收脚本读取） */
  function setPct(el) {
    const cy = lookup(el);
    if (!cy) return;
    const card = el.closest(".flow-card");
    const pct = card && card.querySelector(".dag-pct");
    if (pct) pct.textContent = Math.round(cy.zoom() * 100) + "%";
  }

  function safeFit(el, cy, autoHeight) {
    // 固定 320px 高的图会把 7 态流程压成 60%，手机上根本读不了；
    // 首次挂载按内容撑高（有上限），之后用户手动缩放不再改容器。
    if (autoHeight) {
      const box = cy.elements().boundingBox();
      const maxH = window.innerWidth < 720 ? 980 : 720;
      const target = Math.min(maxH, Math.max(200, Math.round(box.h + 56)));
      if (Math.abs((parseFloat(el.style.height) || 0) - target) > 6) {
        el.style.height = target + "px";
        cy.resize();
      }
    }
    // 图小的时候 fit 会把它放大到糊脸：封顶 125%，只居中不继续撑。
    cy.fit(undefined, 28);
    if (cy.zoom() > 1.25) { cy.zoom(1.25); cy.center(); }
    setPct(el);
  }

  function fit(el) {
    const cy = lookup(el);
    if (cy) safeFit(el, cy, false);
  }

  function zoomBy(el, dir) {
    const cy = lookup(el);
    if (!cy) return;
    const factor = dir === "out" ? 1 / 1.2 : 1.2;
    const center = cy.pan();
    const next = Math.min(2.5, Math.max(0.3, cy.zoom() * factor));
    cy.zoom({ level: next, position: center });
    cy.center(center);
    setPct(el);
  }

  /* 容器内手势收口：滚轮/双指/拖拽只作用于图内，preventDefault 不冒泡成整页缩放或页面滚动。
     原生监听挂在容器上，passive:false 才能拦得住浏览器默认滚轮行为。 */
  function bindGestures(el) {
    if (!el || el.__hiveGesturesBound) return;
    el.__hiveGesturesBound = true;
    el.addEventListener("wheel", (e) => {
      if (e.cancelable) e.preventDefault();
    }, { passive: false });
    el.addEventListener("touchmove", (e) => {
      if (e.cancelable) e.preventDefault();
    }, { passive: false });
  }

  global.HiveGraph = { mount, fit, zoomBy, bindGestures, lookup };
})(window);
