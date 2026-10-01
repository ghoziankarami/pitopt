# Third-party notices

The MIT license covers PitOpt original code and public documentation. It does
not replace the licenses of dependencies, fonts or benchmark data.

## Bundled assets

- `pitopt/ui/static/fonts/*.woff2`: IBM Plex, Copyright 2017 IBM Corp.,
  Reserved Font Name Plex, SIL Open Font License 1.1. The complete upstream
  license accompanies the fonts in `pitopt/ui/static/fonts/OFL.txt`.
  Source: https://github.com/IBM/plex . Font files retain their own license.
- `benchmarks/minelib_zuck_small/*.blocks` and `*.prec`: MineLib data,
  CC BY-SA 3.0 Unported. Attribution, source and modifications are documented
  in that directory's README. https://minelib.org/v1/ . This dataset is a
  separate work; adapting or redistributing it requires its attribution and
  share-alike terms. It is not included in the Python wheel.
- Generated tin/porphyry fixtures were authored for PitOpt; they represent
  synthetic deposits, not customer resource models.

## Installed dependencies (not vendored)

NetworkX: BSD-3-Clause; NumPy/SciPy/pandas: BSD-style licenses; PyYAML,
ezdxf, XlsxWriter, openpyxl and Plotly: MIT; Shapely: BSD-3-Clause;
Matplotlib: its PSF-based license; ReportLab: BSD-style; Pillow: HPND.
These packages may include additional bundled components and notices.
Preserve their installed license files when shipping binaries or containers.
Plotly's installed JavaScript bundle is served from the installed package;
its bundled notices must remain intact. Optional MCP SDK uses its own MIT
license; audit an actual frozen deployment when distributing it.

The historical `pseudoflow` package is explicitly noncommercial and not
open-source. It is removed from public-release dependencies and code. The
public solver is NetworkX preflow-push; no pseudoflow implementation is copied.

This inventory identifies known notices; it is not a legal warranty or a
claim of clearance of patents, ownership or contract obligations.
