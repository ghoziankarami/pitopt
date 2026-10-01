"""
Excel workbook export — laid out to drop straight into a study report.

Sheet order follows how a report reads: result, what went in, the
parameters, the shells, the pushbacks cut from them, the schedule, the
sensitivity, and the figures. The Parameters sheet carries every input the
run used — a tonnage with no record of the price, recovery and cost behind
it cannot be checked by anyone, and these workbooks outlive the session
that produced them.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

import pandas as pd

from ..config import ProjectConfig


def _parameter_rows(cfg: ProjectConfig, extra: dict) -> pd.DataFrame:
    rows: list[tuple[str, str, object]] = []

    def add(group: str, source) -> None:
        data = asdict(source) if is_dataclass(source) else source
        for key, value in data.items():
            if key == "products":
                continue
            rows.append((group, key, value if not isinstance(value, (list, dict)) else str(value)))

    rows.append(("project", "name", cfg.name))
    add("block_model", cfg.block_model)
    add("surface", cfg.surface)
    add("economics", cfg.economics)
    for product in cfg.economics.products:
        add(f"product:{product.name}", product)
    add("slope", cfg.slope)
    add("shells", cfg.shells)
    add("final_pit", cfg.final_pit)
    add("pushbacks", cfg.pushbacks)
    add("schedule", cfg.schedule)
    add("sensitivity", cfg.sensitivity)
    for key, value in extra.items():
        rows.append(("run", key, value))
    return pd.DataFrame(rows, columns=["Group", "Parameter", "Value"])


def _format_for(title: str, formats: dict):
    lowered = title.lower()
    if any(k in lowered for k in ("ratio", "factor", "grade", "pct", "per_tonne")):
        return formats["rate"]
    if any(k in lowered for k in ("value", "cash", "npv", "revenue")):
        return formats["money"]
    if any(k in lowered for k in ("tonne", "volume", "blocks")):
        return formats["tonnes"]
    return None


def _write_frame(writer, name: str, frame: pd.DataFrame, formats: dict, start_row: int = 0) -> None:
    frame.to_excel(writer, sheet_name=name, index=False, startrow=start_row)
    sheet = writer.sheets[name]
    for column, title in enumerate(frame.columns):
        sheet.write(start_row, column, str(title), formats["header"])
        sheet.set_column(column, column, max(len(str(title)) + 2, 14), _format_for(str(title), formats))
    sheet.freeze_panes(start_row + 1, 0)


def _column(frame: pd.DataFrame, name: str) -> int:
    return list(frame.columns).index(name)


def write_workbook(
    path: str,
    cfg: ProjectConfig,
    summary: pd.DataFrame,
    pit_by_pit: pd.DataFrame,
    schedule: pd.DataFrame,
    schedule_worst: pd.DataFrame | None,
    sensitivity: pd.DataFrame | None,
    bench: pd.DataFrame,
    run_notes: dict,
    pushbacks: pd.DataFrame | None = None,
    inputs: pd.DataFrame | None = None,
    figures: list[tuple[str, str]] | None = None,
    schedule_best: pd.DataFrame | None = None,
    pushback_candidates: pd.DataFrame | None = None,
) -> None:
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        book = writer.book
        formats = {
            "money": book.add_format({"num_format": "#,##0"}),
            "tonnes": book.add_format({"num_format": "#,##0"}),
            "rate": book.add_format({"num_format": "0.000"}),
            "header": book.add_format({"bold": True, "bg_color": "#33475B", "font_color": "white", "border": 1}),
            "title": book.add_format({"bold": True, "font_size": 14}),
        }

        _write_frame(writer, "Summary", summary, formats)
        writer.sheets["Summary"].set_column(0, 0, 28)
        writer.sheets["Summary"].set_column(1, 1, 48)

        if inputs is not None:
            _write_frame(writer, "Input", inputs, formats)
        _write_frame(writer, "Parameters", _parameter_rows(cfg, run_notes), formats)
        writer.sheets["Parameters"].set_column(1, 1, 34)
        writer.sheets["Parameters"].set_column(2, 2, 40)

        _write_frame(writer, "Pit by Pit (RAF)", pit_by_pit, formats)
        if len(pit_by_pit):
            rows = len(pit_by_pit)
            sheet = "Pit by Pit (RAF)"
            chart = book.add_chart({"type": "column", "subtype": "stacked"})
            for name in ("ore_tonnes", "waste_tonnes"):
                chart.add_series({
                    "name": name.replace("_", " ").title(),
                    "categories": [sheet, 1, 0, rows, 0],
                    "values": [sheet, 1, _column(pit_by_pit, name), rows, _column(pit_by_pit, name)],
                })
            npv = book.add_chart({"type": "line"})
            for name in [c for c in ("npv_best", "npv_worst", "npv_average") if c in pit_by_pit]:
                npv.add_series({
                    "name": name.replace("npv_", "NPV ").title(),
                    "categories": [sheet, 1, 0, rows, 0],
                    "values": [sheet, 1, _column(pit_by_pit, name), rows, _column(pit_by_pit, name)],
                    "y2_axis": True,
                    "marker": {"type": "circle"},
                })
            if "npv_best" not in pit_by_pit:
                npv.add_series({
                    "name": "Undiscounted value",
                    "categories": [sheet, 1, 0, rows, 0],
                    "values": [sheet, 1, _column(pit_by_pit, "value"), rows, _column(pit_by_pit, "value")],
                    "y2_axis": True,
                })
            chart.combine(npv)
            chart.set_title({"name": "Pit by pit — tonnes and discounted NPV (best / worst case)"})
            chart.set_x_axis({"name": "Revenue factor"})
            chart.set_y_axis({"name": "Tonnes"})
            chart.set_y2_axis({"name": "NPV"})
            chart.set_size({"width": 820, "height": 440})
            writer.sheets[sheet].insert_chart(rows + 3, 0, chart)

        if pushback_candidates is not None and len(pushback_candidates):
            _write_frame(writer, "Pushback Selection", pushback_candidates, formats)

        if pushbacks is not None and len(pushbacks):
            _write_frame(writer, "Pushbacks", pushbacks, formats)
            rows = len(pushbacks)
            chart = book.add_chart({"type": "column", "subtype": "stacked"})
            for name in ("ore_tonnes", "waste_tonnes"):
                chart.add_series({
                    "name": name.replace("_", " ").title(),
                    "categories": ["Pushbacks", 1, 0, rows, 0],
                    "values": ["Pushbacks", 1, _column(pushbacks, name), rows, _column(pushbacks, name)],
                })
            chart.set_title({"name": "Tonnes per pushback"})
            chart.set_x_axis({"name": "Pushback"})
            chart.set_size({"width": 760, "height": 380})
            writer.sheets["Pushbacks"].insert_chart(rows + 3, 0, chart)

        if not schedule.empty:
            _write_frame(writer, "Schedule", schedule, formats)
            rows = len(schedule)
            chart = book.add_chart({"type": "column", "subtype": "stacked"})
            for name in ("ore_tonnes", "waste_tonnes"):
                chart.add_series({
                    "name": name.replace("_", " ").title(),
                    "categories": ["Schedule", 1, 0, rows, 0],
                    "values": ["Schedule", 1, _column(schedule, name), rows, _column(schedule, name)],
                })
            npv = book.add_chart({"type": "line"})
            npv.add_series({
                "name": "Cumulative NPV",
                "categories": ["Schedule", 1, 0, rows, 0],
                "values": ["Schedule", 1, _column(schedule, "npv"), rows, _column(schedule, "npv")],
                "y2_axis": True,
                "marker": {"type": "circle"},
            })
            chart.combine(npv)
            chart.set_title({"name": "Production schedule and cumulative NPV"})
            chart.set_x_axis({"name": "Period"})
            chart.set_y_axis({"name": "Tonnes"})
            chart.set_y2_axis({"name": "NPV"})
            chart.set_size({"width": 760, "height": 400})
            writer.sheets["Schedule"].insert_chart(rows + 3, 0, chart)

        if schedule_best is not None and len(schedule_best):
            _write_frame(writer, "Schedule (best case)", schedule_best, formats)
        if schedule_worst is not None and len(schedule_worst):
            _write_frame(writer, "Schedule (worst case)", schedule_worst, formats)

        if sensitivity is not None and len(sensitivity):
            _write_frame(writer, "Sensitivity", sensitivity, formats)
            chart = book.add_chart({"type": "scatter", "subtype": "straight_with_markers"})
            products = list(dict.fromkeys(sensitivity["product"])) if "product" in sensitivity else ["ALL"]
            for product in products:
                rows = sensitivity.index[sensitivity["product"] == product] if "product" in sensitivity else sensitivity.index
                first, last = int(rows.min()) + 1, int(rows.max()) + 1
                chart.add_series({
                    "name": f"NPV — {product.title()} price",
                    "categories": ["Sensitivity", first, _column(sensitivity, "price_factor"), last, _column(sensitivity, "price_factor")],
                    "values": ["Sensitivity", first, _column(sensitivity, "npv"), last, _column(sensitivity, "npv")],
                })
            chart.set_title({"name": "Price sensitivity (fixed pit) — spider"})
            chart.set_x_axis({"name": "Price factor"})
            chart.set_y_axis({"name": "NPV"})
            chart.set_size({"width": 760, "height": 420})
            writer.sheets["Sensitivity"].insert_chart(len(sensitivity) + 3, 0, chart)

        _write_frame(writer, "Bench Summary", bench, formats)

        if figures:
            from PIL import Image as PILImage

            sheet = book.add_worksheet("Figures")
            row = 0
            for caption, image in figures:
                with PILImage.open(image) as img:
                    width, height = img.size
                scale = min(1000 / width, 0.6)
                sheet.write(row, 0, caption, formats["title"])
                sheet.insert_image(row + 1, 0, image, {"x_scale": scale, "y_scale": scale, "object_position": 1})
                row += int(height * scale / 20) + 4
