from __future__ import annotations

from pathlib import Path

from schedule_calculator.calendar_view import ScheduleCalendarView, minutes_to_label
from schedule_calculator.errors import ConfigurationError


def render_schedule_calendar_pdf(
    view: ScheduleCalendarView,
    output_path: str | Path,
) -> Path:
    reportlab = _load_reportlab()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    canvas = reportlab["canvas"]
    colors = reportlab["colors"]
    landscape = reportlab["landscape"]
    letter = reportlab["letter"]
    simple_split = reportlab["simple_split"]

    page_width, page_height = landscape(letter)
    pdf = canvas.Canvas(str(path), pagesize=(page_width, page_height))

    margin = 36
    time_column_width = 42
    day_header_height = 20
    legend_height = 48
    title_y = page_height - margin

    pdf.setTitle("UTP Schedule Calendar")
    pdf.setAuthor("schedule-calculator-project")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(margin, title_y, "UTP Schedule Calendar")

    summary_width = page_width - (margin * 2)
    pdf.setFont("Helvetica", 9)
    summary_lines = simple_split(
        f"Enrollments: {view.enrollment_summary}",
        "Helvetica",
        9,
        summary_width,
    )
    detail_lines = simple_split(
        (
            f"Province: {view.requested_province} | "
            f"Requested availability: {view.availability_start.strftime('%H:%M')}-"
            f"{view.availability_end.strftime('%H:%M')} | "
            f"Rendered range: {minutes_to_label(view.visible_start_minutes)}-"
            f"{minutes_to_label(view.visible_end_minutes)} | "
            f"Idle time: {view.total_idle_minutes} min"
        ),
        "Helvetica",
        9,
        summary_width,
    )

    text_y = title_y - 18
    for line in summary_lines + detail_lines:
        pdf.drawString(margin, text_y, line)
        text_y -= 12

    grid_top = text_y - 8
    grid_bottom = margin + legend_height
    grid_left = margin + time_column_width
    grid_right = page_width - margin
    grid_width = grid_right - grid_left
    grid_height = grid_top - grid_bottom
    day_width = grid_width / max(len(view.days), 1)
    body_top = grid_top - day_header_height
    body_height = body_top - grid_bottom
    visible_duration = max(view.visible_end_minutes - view.visible_start_minutes, 30)

    pdf.setStrokeColor(colors.HexColor("#B8C5D6"))
    pdf.setLineWidth(0.6)

    for index, day in enumerate(view.days):
        left = grid_left + (index * day_width)
        pdf.setFillColor(colors.HexColor("#F7FAFD" if index % 2 == 0 else "#EEF4FA"))
        pdf.rect(left, grid_bottom, day_width, grid_height, fill=1, stroke=0)
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(left + (day_width / 2), grid_top - 14, day.label)
        pdf.line(left, grid_bottom, left, grid_top)
    pdf.line(grid_right, grid_bottom, grid_right, grid_top)
    pdf.line(grid_left, body_top, grid_right, body_top)
    pdf.rect(grid_left, grid_bottom, grid_width, grid_height, fill=0, stroke=1)

    pdf.setFont("Helvetica", 8)
    for marker in view.time_markers:
        y = body_top - (((marker - view.visible_start_minutes) / visible_duration) * body_height)
        pdf.line(grid_left, y, grid_right, y)
        pdf.drawRightString(grid_left - 6, y - 3, minutes_to_label(marker))

    for block in view.blocks:
        day_index = next(
            (index for index, day in enumerate(view.days) if day.key == block.day),
            None,
        )
        if day_index is None:
            continue
        block_left = grid_left + (day_index * day_width) + 3
        block_right = grid_left + ((day_index + 1) * day_width) - 3
        block_top = body_top - (
            ((block.start_minutes - view.visible_start_minutes) / visible_duration) * body_height
        )
        block_bottom = body_top - (
            ((block.end_minutes - view.visible_start_minutes) / visible_duration) * body_height
        )
        block_height = max(block_top - block_bottom, 12)

        pdf.setFillColor(colors.HexColor(block.color_hex))
        pdf.setStrokeColor(colors.HexColor("#5A6B7D"))
        pdf.roundRect(
            block_left,
            block_bottom + 1,
            block_right - block_left,
            block_height - 2,
            4,
            fill=1,
            stroke=1,
        )
        pdf.setFillColor(colors.black)
        _draw_block_text(
            pdf,
            block.label_lines,
            block_left + 4,
            block_top - 10,
            (block_right - block_left) - 8,
            block_height - 6,
            simple_split,
        )

    legend_top = margin + 28
    legend_width = page_width - (margin * 2)
    items_per_row = 3 if len(view.legend) > 3 else max(len(view.legend), 1)
    item_width = legend_width / items_per_row
    for index, item in enumerate(view.legend):
        row = index // items_per_row
        column = index % items_per_row
        item_left = margin + (column * item_width)
        item_y = legend_top - (row * 16)
        pdf.setFillColor(colors.HexColor(item.color_hex))
        pdf.rect(item_left, item_y - 7, 10, 10, fill=1, stroke=0)
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica", 8)
        legend_label = simple_split(item.label, "Helvetica", 8, item_width - 18)
        if legend_label:
            pdf.drawString(item_left + 14, item_y - 1, legend_label[0])

    pdf.save()
    return path


def _draw_block_text(
    pdf,
    label_lines: tuple[str, ...],
    x: float,
    y: float,
    width: float,
    height: float,
    simple_split,
) -> None:
    if height < 18:
        lines = label_lines[:1]
        font_size = 7
        line_height = 8
    elif height < 32:
        lines = (label_lines[0], label_lines[2])
        font_size = 6.5
        line_height = 7
    else:
        lines = label_lines
        font_size = 6.5
        line_height = 7

    pdf.setFont("Helvetica", font_size)
    current_y = y
    max_lines = max(int(height // line_height), 1)
    rendered_lines = 0
    for line in lines:
        wrapped = simple_split(line, "Helvetica", font_size, width)
        for wrapped_line in wrapped[: max_lines - rendered_lines]:
            pdf.drawString(x, current_y, wrapped_line)
            current_y -= line_height
            rendered_lines += 1
            if rendered_lines >= max_lines:
                return


def _load_reportlab() -> dict[str, object]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.utils import simpleSplit
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as exc:
        raise ConfigurationError(
            "reportlab is not installed. Install it to use PDF schedule export."
        ) from exc
    return {
        "canvas": canvas,
        "colors": colors,
        "landscape": landscape,
        "letter": letter,
        "simple_split": simpleSplit,
    }
