// The oblique 3D view of the design (Plotly): benches drawn as they arrive, the road, the shell, the sector lines.
// The vertical exaggeration is applied to the scene's aspect ratio and always shown, so the exaggerated wall is
// never mistaken for the real one.
import { D, benches } from "./core.js";
import { css, dark } from "./plan.js";

let plotly = null;
const load = () => window.Plotly ? Promise.resolve(window.Plotly) : (plotly ||= new Promise((ok, no) => {
  const s = document.createElement("script"); s.src = "/static/vendor/plotly.min.js";
  s.onload = () => ok(window.Plotly); s.onerror = () => no(new Error("Plotly gagal dimuat")); document.head.appendChild(s);
}));

const rings = (polys, z, out) => { for (const p of polys) for (const ring of [p.o, ...p.h]) { for (const [x, y] of ring) { out.x.push(x); out.y.push(y); out.z.push(z); } out.x.push(ring[0][0], null); out.y.push(ring[0][1], null); out.z.push(z, null); } };

export async function draw(el) {
  const Plotly = await load();
  const list = benches(), R = D.result, pit = css("--pit"), accent = css("--accent"), ink = css("--text");
  const crest = { x: [], y: [], z: [] }, toe = { x: [], y: [], z: [] }, shell = { x: [], y: [], z: [] };
  for (const b of list) { rings(b.crest, b.crest_rl, crest); rings(b.toe, b.toe_rl, toe); }
  if (D.layers.shell && R) for (const l of R.shell) rings(l.polys, l.rl, shell);
  const traces = [];
  if (D.layers.shell && shell.x.length) traces.push({ type: "scatter3d", mode: "lines", ...shell, line: { color: ink, width: 2, dash: "dash" }, name: "Shell PitOpt", hoverinfo: "skip", opacity: 0.55 });
  if (D.layers.bench) {
    traces.push({ type: "scatter3d", mode: "lines", ...crest, line: { color: pit, width: 3 }, name: "Crest", hoverinfo: "skip" });
    traces.push({ type: "scatter3d", mode: "lines", ...toe, line: { color: dark() ? "#8A6A3B" : "#C9A97A", width: 2 }, name: "Toe", hoverinfo: "skip" });
  }
  if (D.layers.ramp && R?.ramp && !(D.job?.status === "running")) traces.push({ type: "scatter3d", mode: "lines", x: R.ramp.x, y: R.ramp.y, z: R.ramp.z, line: { color: accent, width: 7 }, name: "Ramp centerline", hovertemplate: "RL %{z:.1f} m<extra></extra>" });
  if (D.layers.sector && R?.sector_lines?.length > 1) {
    const top = R.benches[0]?.crest_rl ?? 0, s = { x: [], y: [], z: [] };
    for (const l of R.sector_lines) { s.x.push(R.centre[0], l.to[0], null); s.y.push(R.centre[1], l.to[1], null); s.z.push(top, top, null); }
    traces.push({ type: "scatter3d", mode: "lines", ...s, line: { color: accent, width: 2, dash: "dot" }, name: "Sektor", hoverinfo: "skip" });
  }
  const all = [...crest.x, ...toe.x].filter((v) => v !== null), ally = [...crest.y, ...toe.y].filter((v) => v !== null), allz = [...crest.z, ...toe.z].filter((v) => v !== null);
  const dx = Math.max(...all) - Math.min(...all) || 1, dy = Math.max(...ally) - Math.min(...ally) || 1, dz = Math.max(...allz) - Math.min(...allz) || 1;
  const m = Math.max(dx, dy);
  const bg = css("--panel");
  await Plotly.react(el, traces, {
    margin: { l: 0, r: 0, t: 0, b: 0 }, paper_bgcolor: bg, showlegend: false,
    scene: { aspectmode: "manual", aspectratio: { x: dx / m, y: dy / m, z: (dz / m) * D.ve }, camera: { eye: { x: 1.3, y: -1.5, z: 0.9 } },
      xaxis: { visible: false }, yaxis: { visible: false }, zaxis: { title: "RL (m)", color: css("--muted"), gridcolor: css("--line2") }, bgcolor: bg },
  }, { displayModeBar: false, responsive: true });
}
