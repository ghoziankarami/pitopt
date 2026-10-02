# Methodology and validation limits

Block values are calculated from grade, mass or volume basis, price, recovery,
dilution, royalties, and explicit costs. Maximum closure is reduced to a
minimum-cut problem and solved with NetworkX preflow-push. The precedence graph
represents slope constraints at block centers, not continuous geotechnical
surfaces.

Independent validation includes HiGHS linear programming, SciPy Dinic,
exhaustive enumeration of small sets, Boykov–Kolmogorov, volume conservation,
report checks, and DXF reconciliation. Agreement on the optimum does not prove
that the input assumptions are correct.

Scheduling is a heuristic with a configured pushback order. The best/worst
labels refer to the two evaluated sequences; they are not bounds on globally
optimal NPV. Price sensitivity on a fixed pit does not re-optimize its geometry.

Audited synthetic porphyry results: 75,696 blocks, 10 shells, 19 periods, and
final RF 0.5. The shell reaches the model bottom at 38 blocks, so the pit
boundary is open and deeper optima have not been investigated. Raster design
adds about 11.74% rock tonnage over the shell and about 11.47% feed. The input
overall angle is 42°; the effective template angle is about 43.96° along the
axis. Zero reported violations use the available checking tolerance and
discretization; this does not certify that every surface is exactly 42°.

All example grades, densities, prices, recoveries, and geotechnical parameters
are synthetic or assumed. Accuracy against a real deposit has not been
measured. Applying PitOpt to a real study requires data calibration, block-size
sensitivity analysis, a broader model, geotechnical validation, and independent
review by qualified professionals.
