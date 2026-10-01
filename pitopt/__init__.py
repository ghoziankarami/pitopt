"""
pitopt — open-pit ultimate pit limit optimisation.

Block model (CSV) + topography (DXF) in; nested revenue-factor shells,
discounted pit-by-pit, the final pit chosen on NPV, pushbacks, a period
mine plan and a benched pit design out — as Excel, DXF and an HTML 3D
viewer. Each shell is a maximum closure solved exactly with NetworkX preflow-push.
"""
from .config import ProjectConfig
from .pipeline import PitResult, run

__all__ = ["ProjectConfig", "PitResult", "run"]
__version__ = "0.4.0"
