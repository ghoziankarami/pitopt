// The plan view: honest scale (one metre is the same number of pixels both ways), blocks at their real size,
// outlines, the road and the sector lines. Blocks are drawn one path per colour, not one element per cell, so a
// bench of tens of thousands of blocks stays fast.
import { viridis } from "../util.js";

// Sequential purples for grade classes, light to dark; the first (waste) is a neutral. Dark mode keeps the order.
const CLASS = {
  light: ["#E7E3D8", "#D9D3EF", "#A99BD8", "#6C4FB8", "#3E2A86", "#241A5E"],
  dark: ["#3A3D3A", "#4A4570", "#6F62B0", "#9A86E0", "#C0B0FF", "#E0D8FF"],
};
export const dark = () => document.documentElement.dataset.theme === "dark";
export const classColour = (i) => (dark() ? CLASS.dark : CLASS.light)[Math.min(Math.max(i, 0), 5)];

/** The colour of a block under the chosen mode; `range` is [min, max] of the plotted variable. */
export function blockColour(plan, i, mode, range) {
  if (mode === "kelas" && plan.classes.configured) return classColour(plan.cls[i]);
  const v = mode === "nilai" ? plan.value[i] : plan.grade[i];
  if (mode !== "nilai" && v < 0) return classColour(0);
  const [lo, hi] = range;
  return viridis(hi > lo ? (v - lo) / (hi - lo) : 0.5);
}
export function rangeOf(plan, mode) {
  const v = (mode === "nilai" ? plan.value : plan.grade).filter((x) => x >= 0 || mode === "nilai");
  return v.length ? [Math.min(...v), Math.max(...v)] : [0, 1];
}

export class View {
  constructor(canvas, bounds, pad = 34) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || canvas.width, h = canvas.clientHeight || canvas.height;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    this.ctx = canvas.getContext("2d");
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w; this.h = h;
    const [x0, y0, x1, y1] = bounds;
    this.s = Math.min((w - 2 * pad) / (x1 - x0 || 1), (h - 2 * pad) / (y1 - y0 || 1));
    this.ox = pad + ((w - 2 * pad) - this.s * (x1 - x0)) / 2 - this.s * x0;
    this.oy = h - pad - ((h - 2 * pad) - this.s * (y1 - y0)) / 2 + this.s * y0;
    this.bounds = bounds;
  }
  X(x) { return this.ox + this.s * x; }
  Y(y) { return this.oy - this.s * y; }
  world(px, py) { return [(px - this.ox) / this.s, (this.oy - py) / this.s]; }
  clear(bg) { this.ctx.fillStyle = bg; this.ctx.fillRect(0, 0, this.w, this.h); }
}

export function boundsOf(polys, margin = 0.06) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of polys) for (const [x, y] of p.o) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  const mx = (x1 - x0) * margin, my = (y1 - y0) * margin;
  return [x0 - mx, y0 - my, x1 + mx, y1 + my];
}

export function tracePoly(v, polys) {
  const c = v.ctx; c.beginPath();
  for (const p of polys) for (const ring of [p.o, ...p.h]) {
    ring.forEach(([x, y], i) => (i ? c.lineTo(v.X(x), v.Y(y)) : c.moveTo(v.X(x), v.Y(y))));
    c.closePath();
  }
}
export function stroke(v, polys, { color, width = 1.4, dash = [] }) {
  const c = v.ctx; tracePoly(v, polys); c.strokeStyle = color; c.lineWidth = width; c.setLineDash(dash); c.stroke(); c.setLineDash([]);
}
export function line(v, pts, { color, width = 2, dash = [] }) {
  const c = v.ctx; c.beginPath(); pts.forEach(([x, y], i) => (i ? c.lineTo(v.X(x), v.Y(y)) : c.moveTo(v.X(x), v.Y(y))));
  c.strokeStyle = color; c.lineWidth = width; c.setLineDash(dash); c.stroke(); c.setLineDash([]);
}

/** Blocks as filled squares of their true size; `faded[i]` draws a block half-transparent. */
export function drawBlocks(v, plan, colours, faded) {
  const c = v.ctx, hx = (plan.dx * v.s) / 2, hy = (plan.dy * v.s) / 2;
  for (const alpha of [1, 0.32]) {
    const byColour = new Map();
    for (let i = 0; i < plan.x.length; i++) {
      if ((faded[i] ? 0.32 : 1) !== alpha) continue;
      (byColour.get(colours[i]) || byColour.set(colours[i], new Path2D()).get(colours[i])).rect(v.X(plan.x[i]) - hx, v.Y(plan.y[i]) - hy, 2 * hx, 2 * hy);
    }
    c.globalAlpha = alpha;
    for (const [colour, path] of byColour) { c.fillStyle = colour; c.fill(path); }
  }
  c.globalAlpha = 1;
}

const nice = (m) => { const e = 10 ** Math.floor(Math.log10(m)); const f = m / e; return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * e; };
export function scaleBar(v, colour) {
  const len = nice(v.w * 0.16 / v.s), c = v.ctx, x = 16, y = v.h - 16;
  c.strokeStyle = c.fillStyle = colour; c.lineWidth = 2; c.beginPath(); c.moveTo(x, y); c.lineTo(x + len * v.s, y); c.stroke();
  c.font = "11px 'IBM Plex Mono', monospace"; c.fillText(`${len} m`, x, y - 6);
}
export function north(v, colour) {
  const c = v.ctx, x = v.w - 22, y = 30;
  c.fillStyle = c.strokeStyle = colour; c.beginPath(); c.moveTo(x, y - 14); c.lineTo(x - 6, y + 4); c.lineTo(x + 6, y + 4); c.closePath(); c.fill();
  c.font = "600 11px 'IBM Plex Sans', sans-serif"; c.textAlign = "center"; c.fillText("U", x, y + 18); c.textAlign = "left";
}
export function axes(v, colour) {
  const c = v.ctx, [x0, y0, x1, y1] = v.bounds, step = nice(80 / v.s);
  c.fillStyle = colour; c.font = "10px 'IBM Plex Mono', monospace"; c.globalAlpha = 0.75;
  for (let x = Math.ceil(x0 / step) * step; x < x1; x += step) c.fillText(Math.round(x), v.X(x) - 14, v.h - 4);
  for (let y = Math.ceil(y0 / step) * step; y < y1; y += step) c.fillText(Math.round(y), 2, v.Y(y) + 3);
  c.globalAlpha = 1;
}
export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
