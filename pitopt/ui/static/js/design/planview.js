// The plan view every design screen paints: the block slice, the shell and the design outline, the road and the
// sector lines. Everything is drawn from the plan and result the server sent; nothing is recomputed here.
import { D } from "./core.js";
import { View, axes, blockColour, boundsOf, classColour, css, dark, drawBlocks, line, north, rangeOf, scaleBar, stroke, tracePoly } from "./plan.js";

function wedge(centre, r, from, to) {
  const span = ((to - from) % 360 + 360) % 360 || 360, pts = [centre];
  for (let a = 0; a <= 48; a++) { const az = ((from + (span * a) / 48) * Math.PI) / 180; pts.push([centre[0] + r * Math.sin(az), centre[1] + r * Math.cos(az)]); }
  return { o: pts, h: [] };
}

/** opts: plan, result?, layers, mode, sel (sector index), sectors (state.sectors), extra(view) for screen-specific overlays */
export function paintPlan(canvas, opts) {
  const { plan, result, layers = {}, mode = "kelas", sel = null, sectors = [], showDesign = true, showRamp = true } = opts;
  const outline = [...plan.shell, ...(showDesign ? plan.design : []), ...(result?.benches?.length ? result.benches[0].crest : [])];
  const v = new View(canvas, boundsOf(outline.length ? outline : [{ o: [[plan.x[0] - 50, plan.y[0] - 50], [plan.x[0] + 50, plan.y[0] + 50]] }]));
  v.clear(css("--panel2") || "#F7F8FA");
  const range = rangeOf(plan, mode);
  if (layers.blocks !== false) {
    const colours = plan.x.map((_, i) => blockColour(plan, i, mode, range));
    const inside = (i) => plan.in_shell[i] || plan.in_design[i];
    drawBlocks(v, plan, colours, plan.x.map((_, i) => !inside(i)));
  }
  const ink = css("--text"), accent = css("--accent"), pit = css("--pit");
  if (sel !== null && sectors[sel] && result) {
    const s = sectors[sel];
    const rmax = Math.max(...result.benches[0].crest.flatMap((p) => p.o.map(([x, y]) => Math.hypot(x - result.centre[0], y - result.centre[1])))) * 1.05;
    tracePoly(v, [wedge(result.centre, rmax, s.azimuth_from, s.azimuth_to)]);
    v.ctx.fillStyle = dark() ? "rgba(127,163,232,.18)" : "rgba(43,76,140,.12)"; v.ctx.fill();
  }
  if (layers.shell !== false) {
    stroke(v, plan.shell, { color: dark() ? "rgba(0,0,0,.55)" : "rgba(255,255,255,.85)", width: 3.4 });      // halo: legible over any block colour
    stroke(v, plan.shell, { color: ink, width: 1.4, dash: [6, 4] });
  }
  if (showDesign && plan.design.length) stroke(v, plan.design, { color: accent, width: 2.2 });
  if (result && layers.sector !== false && (result.sector_lines || []).length > 1) {
    for (const s of result.sector_lines) line(v, [result.centre, s.to], { color: pit, width: 1, dash: [2, 4] });
  }
  if (result?.ramp && showRamp && layers.ramp !== false) {
    if (result.ramp.edges) for (const e of [result.ramp.edges.left, result.ramp.edges.right]) line(v, e, { color: accent, width: 0.8 });
    line(v, result.ramp.x.map((x, i) => [x, result.ramp.y[i]]), { color: accent, width: 2.6 });
  }
  axes(v, ink); scaleBar(v, ink); north(v, ink);
  opts.extra?.(v);
  return v;
}
export const centreOf = () => D.result?.centre;
