# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Orebit (Ghozian Islam Karami)
"""
PDF report.

Written to be read by someone who was not in the room when the run
happened, so the assumptions and the warnings travel with the numbers
rather than living in a terminal that gets closed. The caveats page is
not padding — an ultimate pit quoted without its slope basis, resource
classes and cost assumptions is not auditable, and a reader has no way to
tell a checked number from a placeholder.
"""
from __future__ import annotations

from datetime import date
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = getSampleStyleSheet()
TITLE = ParagraphStyle("t", parent=STYLES["Title"], fontSize=20, spaceAfter=4)
SUBTITLE = ParagraphStyle("s", parent=STYLES["Normal"], fontSize=10, textColor=colors.grey, spaceAfter=12)
HEADING = ParagraphStyle("h", parent=STYLES["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6)
BODY = ParagraphStyle("b", parent=STYLES["Normal"], fontSize=9, leading=13)
WARN = ParagraphStyle("w", parent=BODY, textColor=colors.HexColor("#A33"), leading=13)

TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#33475B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F7")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
)


AVAILABLE_WIDTH = landscape(A4)[0] - 28 * mm


def _table(frame: pd.DataFrame, formats: dict | None = None, max_rows: int = 40) -> Table:
    """Render a frame, scaled to fit the page width.

    Columns are sized from their widest cell and then scaled down together
    if the total overflows, because a table that silently runs off the
    right edge drops exactly the columns that come last — which in a
    schedule is the discounted cash flow and NPV.
    """
    formats = formats or {}
    frame = frame.head(max_rows)
    header = [str(c).replace("_", " ").title() for c in frame.columns]

    rows = []
    for _, record in frame.iterrows():
        row = []
        for column in frame.columns:
            value = record[column]
            spec = formats.get(column)
            if spec and isinstance(value, (int, float)) and pd.notna(value):
                row.append(format(value, spec))
            elif isinstance(value, float) and pd.notna(value):
                row.append(f"{value:,.2f}")
            else:
                row.append("" if pd.isna(value) else str(value))
        rows.append(row)

    data = [header] + rows
    widths = []
    for index in range(len(header)):
        longest = max(len(str(row[index])) for row in data)
        widths.append(max(longest * 4.4 + 8, 34.0))

    total = sum(widths)
    if total > AVAILABLE_WIDTH:
        widths = [w * AVAILABLE_WIDTH / total for w in widths]

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TABLE_STYLE)
    return table


def _key_values(pairs: list[tuple[str, str]]) -> Table:
    table = Table(
        [[Paragraph(f"<b>{escape(str(k))}</b>", BODY), Paragraph(escape(str(v)), BODY)] for k, v in pairs],
        colWidths=[68 * mm, AVAILABLE_WIDTH - 68 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#DDDDDD")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _provenance_table(provenance: dict[str, dict]) -> Table:
    header = [Paragraph("<b>Parameter</b>", BODY), Paragraph("<b>Source</b>", BODY), Paragraph("<b>Note / Reference</b>", BODY)]
    rows = [header]
    for param, info in sorted(provenance.items()):
        if isinstance(info, dict):
            source = str(info.get("source", "unspecified"))
            note = str(info.get("note") or info.get("ref") or "")
        else:
            source = str(info)
            note = ""
        rows.append([
            Paragraph(escape(str(param)), BODY),
            Paragraph(escape(source), BODY),
            Paragraph(escape(note), BODY),
        ])
    widths = [78 * mm, 32 * mm, AVAILABLE_WIDTH - 110 * mm]
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TABLE_STYLE)
    return table


def _lookup_param(parameters: list[tuple[str, str]], *keys: str) -> str | None:
    lowered = {k.lower() for k in keys}
    for k, v in parameters:
        if str(k).strip().lower() in lowered and str(v).strip():
            return str(v).strip()
    return None


def write_report(
    path: str,
    project_name: str,
    headline: list[tuple[str, str]],
    parameters: list[tuple[str, str]],
    pit_by_pit: pd.DataFrame,
    schedule: pd.DataFrame,
    sensitivity: pd.DataFrame | None,
    warnings: list[str],
    assumptions: list[str],
    pushbacks: pd.DataFrame | None = None,
    figures: list[tuple[str, str]] | None = None,
    plan_label: str = "",
    crs: str | None = None,
    vertical_datum: str | None = None,
    provenance: dict | None = None,
    design_reconciliation: list[tuple[str, str]] | dict | None = None,
) -> None:
    doc = SimpleDocTemplate(
        path,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"{project_name} — pit optimisation",
    )
    story: list = []

    resolved_crs = crs or _lookup_param(parameters, "crs", "coordinate reference system")
    resolved_datum = vertical_datum or _lookup_param(parameters, "vertical datum", "vertical_datum")

    story.append(Paragraph(f"{escape(project_name)} — Ultimate Pit Optimisation", TITLE))
    story.append(Paragraph(f"NetworkX preflow-push maximum closure · generated {date.today().isoformat()}", SUBTITLE))
    story.append(
        Paragraph(
            f"<b>Coordinate System (CRS):</b> {escape(resolved_crs or 'Local / unspecified')} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>Vertical Datum:</b> {escape(resolved_datum or 'Local / unspecified')}",
            BODY,
        )
    )
    story.append(Spacer(1, 6))

    story.append(Paragraph("Result", HEADING))
    story.append(_key_values(headline))

    if design_reconciliation:
        recon_pairs = (
            [(str(k).replace("_", " ").title(), str(v)) for k, v in design_reconciliation.items()]
            if isinstance(design_reconciliation, dict)
            else list(design_reconciliation)
        )
        if recon_pairs:
            story.append(Paragraph("Practical Design Reconciliation", HEADING))
            story.append(_key_values(recon_pairs))

    if warnings:
        story.append(Paragraph("Warnings", HEADING))
        for warning in warnings:
            story.append(Paragraph(f"• {escape(str(warning))}", WARN))

    story.append(PageBreak())

    story.append(Paragraph("Pit by pit — revenue adjustment factor shells", HEADING))
    story.append(
        Paragraph(
            "Each shell is re-optimised at a scaled price, valued at the planning price, then scheduled at "
            "plant capacity and discounted twice: best case (shell by shell) and worst case (bench by bench). "
            "Undiscounted value peaks at RF 1.00 by construction; the final pit is chosen on discounted NPV, "
            "which peaks at a smaller shell because the outer shells' waste is paid for years before their ore.",
            BODY,
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        _table(
            pit_by_pit,
            {
                "revenue_factor": ",.2f",
                "blocks": ",.0f",
                "volume": ",.0f",
                "rock_tonnes": ",.0f",
                "ore_tonnes": ",.0f",
                "waste_tonnes": ",.0f",
                "strip_ratio": ",.2f",
                "value": ",.0f",
                "revenue": ",.0f",
                "npv_best": ",.0f",
                "npv_worst": ",.0f",
                "npv_average": ",.0f",
                "shell": ",.0f",
                "periods": ",.0f",
            },
        )
    )

    if pushbacks is not None and not pushbacks.empty:
        story.append(PageBreak())
        story.append(Paragraph("Pushbacks", HEADING))
        story.append(
            Paragraph(
                f"Mining stages inside the final pit ({plan_label}), valued at the planning price. Shell "
                "pushbacks are chosen among practical splits (minimum tonnage and mining width) for the best "
                "specified-case NPV; strips advance along the deposit with a face sloping at the wall angle.",
                BODY,
            )
        )
        story.append(Spacer(1, 4))
        story.append(
            _table(
                pushbacks,
                {
                    "pushback": ",.0f",
                    "revenue_factor": ",.2f",
                    "blocks": ",.0f",
                    "volume": ",.0f",
                    "ore_tonnes": ",.0f",
                    "waste_tonnes": ",.0f",
                    "strip_ratio": ",.2f",
                    "value": ",.0f",
                    "cumulative_value": ",.0f",
                    "value_per_tonne_mined": ",.2f",
                },
            )
        )

    if schedule is not None and not schedule.empty:
        story.append(PageBreak())
        story.append(Paragraph("Production schedule", HEADING))
        story.append(
            Paragraph(
                f"Plan schedule: {plan_label}, filled to plant capacity and discounted. Every block is mined "
                "after every block in its slope cone. The best case (shell by shell) and worst case (bench by bench) "
                "on the same final pit bracket it; see the Excel workbook for both.",
                BODY,
            )
        )
        story.append(Spacer(1, 4))
        story.append(
            _table(
                schedule,
                {
                    "period": ",.0f",
                    "blocks": ",.0f",
                    "volume": ",.0f",
                    "rock_tonnes": ",.0f",
                    "ore_tonnes": ",.0f",
                    "ore_volume": ",.0f",
                    "waste_tonnes": ",.0f",
                    "strip_ratio": ",.2f",
                    "cash_flow": ",.0f",
                    "discount_factor": ",.3f",
                    "discounted_cash_flow": ",.0f",
                    "cumulative_cash_flow": ",.0f",
                    "npv": ",.0f",
                },
            )
        )

    if sensitivity is not None and not sensitivity.empty:
        story.append(PageBreak())
        story.append(Paragraph("Price sensitivity — fixed pit", HEADING))
        story.append(
            Paragraph(
                "The pit outline is held fixed and re-valued as price moves, which is the relevant case once a "
                "design is committed. Destination is still re-decided per block, so material that stops paying "
                "is sent to waste rather than fed at a loss.",
                BODY,
            )
        )
        story.append(Spacer(1, 4))
        story.append(
            _table(
                sensitivity,
                {
                    "price_factor": ",.2f",
                    "value": ",.0f",
                    "npv": ",.0f",
                    "ore_tonnes": ",.0f",
                    "waste_tonnes": ",.0f",
                    "periods": ",.0f",
                    "blocks_as_ore": ",.0f",
                },
            )
        )

    for caption, image_path in figures or []:
        story.append(PageBreak())
        story.append(Paragraph(caption, HEADING))
        story.append(Image(image_path, width=265 * mm, height=160 * mm, kind="proportional"))

    story.append(PageBreak())
    story.append(Paragraph("Parameters & Coordinate System", HEADING))
    coord_pairs = [
        ("Coordinate System (CRS)", resolved_crs or "Local / unspecified"),
        ("Vertical Datum", resolved_datum or "Local / unspecified"),
    ]
    story.append(_key_values(coord_pairs + list(parameters)))

    if provenance:
        counts: dict[str, int] = {}
        for info in provenance.values():
            src = str(info.get("source", "unspecified")) if isinstance(info, dict) else str(info)
            counts[src] = counts.get(src, 0) + 1
        summary_text = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
        story.append(Paragraph("Parameter Provenance", HEADING))
        story.append(Paragraph(f"Provenance summary ({len(provenance)} tracked): {escape(summary_text)}", BODY))
        story.append(Spacer(1, 4))
        story.append(_provenance_table(provenance))

    story.append(Paragraph("Assumptions and limitations", HEADING))
    for assumption in assumptions:
        story.append(Paragraph(f"• {escape(str(assumption))}", BODY))

    doc.build(story)
