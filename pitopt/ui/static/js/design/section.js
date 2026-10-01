// A vertical section along a line: the designed wall (bench and berm), the optimiser shell's stair, a strip of the
// block model one cell thick, the ground, and where the road crosses. Drawn at any vertical exaggeration; the scale
// is written on the drawing itself, so a picture taken from it can never be read as 1:1 when it is not.
import { fmt } from "../util.js";
import { blockColour, classColour, css, rangeOf } from "./plan.js";

const norm = (a) => ((a % 360) + 360) % 360;
const bearing = (from, to) => norm((Math.atan2(to[0] - from[0], to[1] - from[1]) * 180) / Math.PI);
const sectorAt = (sectors, az) => sectors.find((s) => ((az - s.azimuth_from + 360) % 360) < (((s.azimuth_to - s.azimuth_from) % 360 + 360) % 360 || 360))?.name || "";

export function drawSection(canvas, sec, topo, { ve, mode, sectors, centre, p1, p2, width }) {
  const padL = 50, padR = 14, padT = 34, padB = 30;
  const rls = sec.rings.map((r) => r.rl);
  const zmin = Math.min(...rls) - sec.dz, zmax = Math.max(...rls) + sec.dz * 2;
  const s = (width - padL - padR) / sec.length;
  const h = Math.round(padT + padB + (zmax - zmin) * s * ve);
  canvas.style.width = `${width}px`; canvas.style.height = `${h}px`;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0);
  const X = (d) => padL + d * s, Y = (z) => h - padB - (z - zmin) * s * ve;
  const ink = css("--text"), muted = css("--muted"), accent = css("--accent");
  c.fillStyle = css("--panel2"); c.fillRect(0, 0, width, h);

  // block strip, faded where the design has already mined it
  const b = sec.blocks, range = rangeOf({ grade: b.grade, value: b.grade, cls: b.cls, classes: sec.classes }, mode);
  const cell = sec.cell, hw = (cell * s) / 2, hh = (sec.dz * s * ve) / 2;
  for (const alpha of [1, 0.3]) {
    c.globalAlpha = alpha;
    b.d.forEach((d, i) => {
      if ((b.mined[i] ? 0.3 : 1) !== alpha) return;
      const colour = mode === "kelas" && sec.classes.configured ? classColour(b.cls[i]) : blockColour({ ...b, classes: sec.classes, value: b.grade }, i, "kadar", range);
      c.fillStyle = colour; c.fillRect(X(d) - hw, Y(b.rl[i]) - hh, 2 * hw, 2 * hh);
    });
  }
  c.globalAlpha = 1;

  // ground
  if (topo?.series?.topo) {
    c.beginPath(); let pen = false;
    topo.distance.forEach((d, i) => { const z = topo.series.topo[i]; if (z == null) { pen = false; return; } (pen ? c.lineTo : c.moveTo).call(c, X(d), Y(z)); pen = true; });
    c.strokeStyle = css("--topo"); c.lineWidth = 2; c.stroke();
  }
  // the optimiser shell as a stair
  const edge = (pick) => sec.shell.filter((l) => l.spans.length).sort((a, b2) => a.rl - b2.rl).flatMap((l) => { const d = pick(l.spans); return [[d, l.rl - sec.dz / 2], [d, l.rl + sec.dz / 2]]; });
  const left = edge((sp) => Math.min(...sp.map((x) => x[0]))), right = edge((sp) => Math.max(...sp.map((x) => x[1])));
  if (left.length) {
    c.setLineDash([6, 4]); c.strokeStyle = ink; c.lineWidth = 1.3; c.beginPath();
    [...left, ...right.slice().reverse()].forEach(([d, z], i) => (i ? c.lineTo(X(d), Y(z)) : c.moveTo(X(d), Y(z)))); c.stroke(); c.setLineDash([]);
  }
  // the designed wall: every ring, lowest first, crest before toe at the same elevation so berms read as flats
  const rings = sec.rings.filter((r) => r.spans.length).sort((a, b2) => a.rl - b2.rl || (a.kind === "crest" ? -1 : 1));
  const wall = (pick) => rings.map((r) => [pick(r.spans), r.rl]);
  const lw = wall((sp) => Math.min(...sp.map((x) => x[0]))), rw = wall((sp) => Math.max(...sp.map((x) => x[1])));
  c.strokeStyle = css("--pit"); c.lineWidth = 2.2; c.beginPath();
  [...lw, ...rw.slice().reverse()].forEach(([d, z], i) => (i ? c.lineTo(X(d), Y(z)) : c.moveTo(X(d), Y(z)))); c.stroke();
  // the road
  c.font = "10px 'IBM Plex Mono', monospace";
  for (const r of sec.ramp) {
    c.fillStyle = accent; c.fillRect(X(r.d) - width * 0.02, Y(r.rl) - 2, width * 0.04, 4);
    c.fillText(`ramp +${fmt(r.rl, 0)}`, X(r.d) - width * 0.02, Y(r.rl) - 6);
  }
  // axes and the scale, written on the drawing
  c.fillStyle = muted; c.strokeStyle = css("--line2"); c.lineWidth = 1;
  const step = Math.max(10, Math.round(((zmax - zmin) / 6) / 10) * 10);
  for (let z = Math.ceil(zmin / step) * step; z < zmax; z += step) { c.beginPath(); c.moveTo(padL, Y(z)); c.lineTo(width - padR, Y(z)); c.stroke(); c.fillText(`+${fmt(z, 0)}`, 4, Y(z) + 3); }
  const dstep = Math.round(sec.length / 6 / 50) * 50 || 50;
  for (let d = 0; d <= sec.length; d += dstep) c.fillText(fmt(d, 0), X(d) - 8, h - padB + 14);
  c.fillText("jarak sepanjang A–A′ (m)", padL, h - 6);
  const a = sectorAt(sectors, norm(bearing(centre, p1))), z = sectorAt(sectors, norm(bearing(centre, p2)));
  c.fillStyle = ink; c.font = "600 11px 'IBM Plex Sans', sans-serif";
  c.fillText(`A  ${a} ${fmt(bearing(centre, p1), 0)}°`, padL + 4, 14); const t = `${z} ${fmt(bearing(centre, p2), 0)}°  A′`; c.fillText(t, width - padR - c.measureText(t).width - 4, 14);
  const badge = ve === 1 ? "1:1 · VE 1,0×" : `VE ${fmt(ve, 1)}×`, bw = c.measureText(badge).width + 16;
  const bx = padL + (width - padL - padR - bw) / 2;
  c.fillStyle = ve === 1 ? css("--good") : ink; c.fillRect(bx, 4, bw, 20);
  c.fillStyle = css("--bg"); c.fillText(badge, bx + 8, 18);
}
