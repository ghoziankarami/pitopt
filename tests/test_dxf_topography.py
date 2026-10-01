"""
Topography delivered as DXF, in every form survey and CAD packages write it.

One analytic surface is written as a TIN of 3DFACEs, a polyface mesh, a MESH, 3D polylines, contour lines as
LWPOLYLINE and as old-style 2D POLYLINE (elevation in the header, vertices flat), a point cloud, loose LINEs, and a
TIN wrapped in a block reference. Each must read back to the same heights. The forms that used to fail are named:
a polyface mixes its vertices with face records stored at (0, 0, 0), which leaked a false point at the origin;
LINE and INSERT were not read at all; and a 2D contour string would have read at elevation zero.
"""
from __future__ import annotations

import ezdxf
import numpy as np
import pytest

from pitopt.io.dxf import read_surface, read_surface_points
from pitopt.ui.onboard import inspect_surface

X0, Y0 = 500_000.0, 9_150_000.0                  # real-world UTM, so a stray origin point would be far outside
XS = np.arange(0, 201, 10.0)
GX, GY = np.meshgrid(XS, XS, indexing="ij")


def height(x, y):
    return 100 + 0.05 * x - 0.03 * y + 5 * np.sin(x / 40)


GZ = height(GX, GY)


def corner(i, j):
    return (X0 + GX[i, j], Y0 + GY[i, j], GZ[i, j])


def tin(layout):
    for i in range(len(XS) - 1):
        for j in range(len(XS) - 1):
            a, b, c, d = corner(i, j), corner(i + 1, j), corner(i + 1, j + 1), corner(i, j + 1)
            layout.add_3dface([a, b, c, c])
            layout.add_3dface([a, c, d, d])


def contours(add):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fine = np.arange(0, 200.01, 1.0)
    fx, fy = np.meshgrid(fine, fine, indexing="ij")
    fz = height(fx, fy)
    cs = plt.contour(fx, fy, fz, levels=np.arange(np.floor(fz.min()), fz.max(), 1.0))
    for level, segments in zip(cs.levels, cs.allsegs):
        for seg in segments:
            if len(seg) > 1:
                add([(X0 + p[0], Y0 + p[1]) for p in seg], float(level))
    plt.close("all")


def build(kind, doc, msp):
    if kind == "tin":
        tin(msp)
    elif kind == "polyface":
        pf = msp.add_polyface()
        for i in range(len(XS) - 1):
            for j in range(len(XS) - 1):
                pf.append_face([corner(i, j), corner(i + 1, j), corner(i + 1, j + 1), corner(i, j + 1)])
        pf.optimize()
    elif kind == "mesh":
        n = len(XS)
        m = msp.add_mesh()
        with m.edit_data() as data:
            data.vertices = [corner(i, j) for i in range(n) for j in range(n)]
            data.faces = [(i * n + j, (i + 1) * n + j, (i + 1) * n + j + 1, i * n + j + 1) for i in range(n - 1) for j in range(n - 1)]
    elif kind == "polyline3d":
        for j in range(len(XS)):
            msp.add_polyline3d([corner(i, j) for i in range(len(XS))])
    elif kind == "contours_lwpolyline":
        contours(lambda pts, z: msp.add_lwpolyline(pts, dxfattribs={"elevation": z}))
    elif kind == "contours_polyline2d":
        contours(lambda pts, z: msp.add_polyline2d(pts, dxfattribs={"elevation": (0, 0, z)}))
    elif kind == "points":
        for i in range(len(XS)):
            for j in range(len(XS)):
                msp.add_point(corner(i, j))
    elif kind == "lines":
        for i in range(len(XS) - 1):
            for j in range(len(XS)):
                msp.add_line(corner(i, j), corner(i + 1, j))
    elif kind == "block_reference":
        tin(doc.blocks.new("TOPO"))
        msp.add_blockref("TOPO", (0, 0, 0))


# contours are 1 m apart, so linear interpolation between them can be off by up to about half a contour
FORMS = {"tin": 0.05, "polyface": 0.05, "mesh": 0.05, "polyline3d": 0.05, "contours_lwpolyline": 0.6,
         "contours_polyline2d": 0.6, "points": 0.05, "lines": 0.05, "block_reference": 0.05}


@pytest.mark.parametrize("kind", FORMS)
def test_each_dxf_form_reads_back_to_the_surface_it_was_written_from(tmp_path, kind):
    doc = ezdxf.new("R2010")
    build(kind, doc, doc.modelspace())
    path = tmp_path / f"{kind}.dxf"
    doc.saveas(path)

    points = read_surface_points(str(path))
    assert points[:, 0].min() >= X0 - 1e-6 and points[:, 1].min() >= Y0 - 1e-6       # no stray point at the origin
    assert points[:, 2].min() >= GZ.min() - 1e-6 and points[:, 2].max() <= GZ.max() + 1e-6

    rng = np.random.default_rng(7)
    qx, qy = rng.uniform(15, 185, 300), rng.uniform(15, 185, 300)
    error = np.abs(read_surface(str(path))(X0 + qx, Y0 + qy) - height(qx, qy))
    assert error.max() < FORMS[kind], f"{kind}: max error {error.max():.3f} m"


def test_a_dxf_with_nothing_that_carries_height_is_refused(tmp_path):
    doc = ezdxf.new("R2010")
    doc.modelspace().add_text("TOPO")
    path = tmp_path / "empty.dxf"
    doc.saveas(path)
    with pytest.raises(ValueError, match="No usable geometry"):
        read_surface_points(str(path))


def test_contours_that_lost_their_elevation_are_flagged_at_upload(tmp_path):
    doc = ezdxf.new("R2010")
    contours(lambda pts, z: doc.modelspace().add_lwpolyline(pts))           # elevation dropped: all at 0
    path = tmp_path / "flat.dxf"
    doc.saveas(path)
    info = inspect_surface(path)
    assert info["warnings"] and "elevasi" in info["warnings"][0]
    doc = ezdxf.new("R2010")
    tin(doc.modelspace())
    doc.saveas(tmp_path / "ok.dxf")
    assert inspect_surface(tmp_path / "ok.dxf")["warnings"] == []
