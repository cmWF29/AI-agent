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
        label: e.label || "",
        back: !!e.back,
      },
    }));

    const canvas = ensureCanvas(el);
    const rankdir = spec.direction === "TB" ? "TB" : "LR";
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
        rankdir: rankdir,
        nodeSep: 28,
        edgeSep: 20,
        rankSep: 64,
        animate: false,
        padding: 12,
      },
      style: [
        {
          selector: "node",
          style: {
            shape: "round-rectangle",
            width: 148,
            height: 64,
            "background-color": "#ffffff",
            "border-width": 1.3,
            "border-color": "data(tone)",
            label: "data(label)",
            "text-wrap": "wrap",
            "text-width-wrap": true,
            "text-valign": "top",
            "text-halign": "center",
            "font-size": 12,
            "color": "#1d2129",
            "padding-top": 8,
            "text-margin-y": 0,
          },
        },
        {
          selector: "node[?terminal]",
          style: { "border-color": "#00b42a", "background-color": "rgba(0,180,42,.06)" },
        },
        {
          selector: "node[?active]",
          style: { "border-color": "#2f6bff", "border-width": 2, "background-color": "rgba(47,107,255,.06)" },
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
            "font-size": 11,
            color: "#7c8798",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.9,
            "text-background-padding": 3,
            "text-rotation": "none",
            "text-margin-y": -4,
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
    cy.on("layoutstop", () => { cy.fit(undefined, 28); setPct(el); });
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

  function fit(el) {
    const cy = lookup(el);
    if (cy) { cy.fit(undefined, 24); setPct(el); }
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
