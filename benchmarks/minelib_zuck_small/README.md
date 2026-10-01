# MineLib `zuck_small`

Real block model from the Zuck deposit, one of the published [MineLib](
https://web.archive.org/web/2023/https://mansci-web.uai.cl/minelib/) benchmark
instances (Espinoza et al., 2012, *"MineLib: a library of open pit mining
problems"*, Annals of Operations Research). MineLib's own site is behind a
WAF that blocks scripted access; these files were pulled from the mirror at
[douglasmazzinghy/2026-MME](https://github.com/douglasmazzinghy/2026-MME)
(`02_zuck_small/`), which redistributes the same MineLib instance unmodified.

## Files

| File | Contents |
|---|---|
| `zuck_small.blocks` | 9,400 blocks: `id x y z cost value rock_tonnes ore_tonnes` (whitespace-separated, no header). `x y z` are integer grid indices, not metric coordinates. |
| `zuck_small.prec` | Precedence: `id num_preds pred_1 pred_2 ...` per line — the blocks that must be extracted before `id`. Already encodes the pit's slope/boundary; there is no separate slope angle to set. |

## Using it

This instance validates the solver on its own. Block value is already
computed (`value - cost`) and the precedence is given, so valuation and
the slope template are bypassed and only the maximum-closure solve runs:

```bash
make minelib        # python scripts/run_minelib.py benchmarks/minelib_zuck_small zuck_small
```

The pit value must come out at or above the take-everything value — the
optimality condition for this instance.

## License and attribution

These two data files are a separate work under **CC BY-SA 3.0 Unported**,
not the software license. Authors: Daniel Espinoza, Marcos Goycoolea, Eduardo
Moreno and Alexandra N. Newman. Source: https://minelib.org/v1/ .
Citation: MineLib: A Library of Open Pit Mining Problems (2012),
Annals of Operations Research 206(1), 91–114, DOI 10.1007/s10479-012-1258-3.
License: https://creativecommons.org/licenses/by-sa/3.0/ .
Only whitespace/line endings have been normalised; no block values or arcs
were intentionally changed. Distribute this notice with the dataset and
license adapted datasets under the same terms.

A value above the take-everything value is a sanity check, not proof of
optimality. Use a published reference optimum or an independent solver.
