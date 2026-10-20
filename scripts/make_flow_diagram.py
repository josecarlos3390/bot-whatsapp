"""Genera un diagrama PNG del flujo actual (para docs/flujo-actual.md)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1700, 1360
BG = "#f8fafc"
INK = "#0f172a"
MUTED = "#64748b"

GREEN = ("#dcfce7", "#16a34a")
BLUE = ("#dbeafe", "#2563eb")
PURPLE = ("#ede9fe", "#7c3aed")
INDIGO = ("#e0e7ff", "#4338ca")
SLATE = ("#e2e8f0", "#475569")
AMBER = ("#fef3c7", "#d97706")
ROSE = ("#ffe4e6", "#e11d48")

FONT_DIR = Path("C:/Windows/Fonts")
FONT = FONT_DIR / "segoeui.ttf"
FONT_BOLD = FONT_DIR / "segoeuib.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT), size)


def dashed(draw: ImageDraw.ImageDraw, points, fill, width=3, dash=12):
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if length == 0:
            continue
        step = dash / length
        pos = 0.0
        while pos < 1:
            start = pos
            end = min(pos + step, 1)
            draw.line(
                [
                    (x1 + (x2 - x1) * start, y1 + (y2 - y1) * start),
                    (x1 + (x2 - x1) * end, y1 + (y2 - y1) * end),
                ],
                fill=fill,
                width=width,
            )
            pos += step * 2


def arrow(draw: ImageDraw.ImageDraw, start, end, fill="#334155", width=4):
    draw.line([start, end], fill=fill, width=width)
    (x1, y1), (x2, y2) = start, end
    angle = __import__("math").atan2(y2 - y1, x2 - x1)
    size = 14
    left = (
        x2 - size * __import__("math").cos(angle - 0.5),
        y2 - size * __import__("math").sin(angle - 0.5),
    )
    right = (
        x2 - size * __import__("math").cos(angle + 0.5),
        y2 - size * __import__("math").sin(angle + 0.5),
    )
    draw.polygon([end, left, right], fill=fill)


def box(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    lines: list[str],
    colors,
    title_size: int = 24,
    body_size: int = 17,
):
    fill, border = colors
    draw.rounded_rectangle(
        (x, y, x + w, y + h), radius=16, fill=fill, outline=border, width=3
    )
    draw.text((x + 18, y + 12), title, font=font(title_size, True), fill=INK)
    offset = y + 12 + title_size + 8
    for line in lines:
        draw.text((x + 18, offset), line, font=font(body_size), fill="#334155")
        offset += body_size + 4


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.text((60, 38), "Flujo actual del chatbot", font=font(42, True), fill=INK)
    draw.text(
        (62, 92),
        "WhatsApp Cloud API  ·  DeepSeek  ·  SAP Business One 10 (QA)  ·  19-oct-2026",
        font=font(20),
        fill=MUTED,
    )

    # Columnas
    draw.text((80, 150), "CANAL", font=font(18, True), fill=MUTED)
    draw.text((610, 150), "BACKEND / IA", font=font(18, True), fill=MUTED)
    draw.text((1210, 150), "DATOS", font=font(18, True), fill=MUTED)

    mx, mw = 600, 500
    box(draw, mx, 185, mw, 90, "Cliente WhatsApp", ["texto · botones · link"], GREEN)
    box(
        draw,
        mx,
        310,
        mw,
        90,
        "Meta Cloud API",
        ["webhook POST /webhooks/whatsapp"],
        GREEN,
    )
    box(
        draw,
        mx,
        435,
        mw,
        90,
        "FastAPI",
        ["HMAC · dedupe · 200 rápido"],
        BLUE,
    )
    box(
        draw,
        mx,
        560,
        mw,
        90,
        "Agente DeepSeek",
        ["tool calling · historial · no-thinking"],
        PURPLE,
    )
    box(
        draw,
        mx,
        685,
        mw,
        90,
        "Herramientas",
        ["buscar · ficha · carrito · checkout"],
        INDIGO,
    )
    box(
        draw,
        mx,
        835,
        mw,
        90,
        "Respuesta WhatsApp",
        ["texto consolidado + botones/CTA"],
        GREEN,
    )
    box(draw, mx, 960, mw, 90, "Pago QR", ["mock / CUCU · link de pago"], ROSE)
    box(
        draw,
        mx,
        1085,
        mw,
        90,
        "Factura + cobro",
        ["mock · SAP_WRITE_ENABLED=false"],
        ROSE,
    )

    # Datos izquierda
    box(
        draw,
        70,
        630,
        420,
        160,
        "Catálogo local",
        ["28.621 artículos", "21.971 con stock > 0", "búsqueda local (ms)"],
        SLATE,
    )
    box(
        draw,
        70,
        835,
        420,
        120,
        "Carrito",
        ["tienda · precio final", "descuento por período/cantidad"],
        SLATE,
    )

    # Datos derecha
    box(
        draw,
        1210,
        470,
        420,
        230,
        "SAP Service Layer",
        [
            "Items · stock 3 tiendas",
            "101-1001 · 102-1001 · 103-1001",
            "SpecialPrices período/cantidad",
            "caché 60 s / 300 s",
        ],
        AMBER,
    )
    # Flechas principales
    for y1, y2 in [(275, 310), (400, 435), (525, 560), (650, 685), (775, 835), (925, 960), (1050, 1085)]:
        arrow(draw, (mx + mw // 2, y1), (mx + mw // 2, y2))

    # Herramientas -> catálogo / carrito / SAP
    arrow(draw, (mx, 715), (490, 700), "#475569")
    draw.text((500, 675), "buscar", font=font(16), fill=MUTED)

    arrow(draw, (mx, 735), (490, 870), "#475569")
    draw.text((500, 810), "agregar", font=font(16), fill=MUTED)

    arrow(draw, (mx + mw, 715), (1210, 610), "#d97706")
    draw.text((1110, 640), "ficha / stock", font=font(16), fill="#b45309")

    # Banda de sincronización
    draw.rounded_rectangle(
        (70, 1195, 1630, 1275), radius=14, fill="#f1f5f9", outline="#94a3b8", width=2
    )
    draw.text(
        (90, 1207), "Sincronización de catálogo", font=font(20, True), fill=INK
    )
    draw.text(
        (90, 1241),
        "scripts/sync_catalog.py  ·  SAP Service Layer  →  catálogo local  ·  full manual/nocturna",
        font=font(16),
        fill="#334155",
    )
    dashed(draw, [(1420, 700), (1420, 1195)], "#d97706")
    draw.text((1435, 900), "Items / sync", font=font(15), fill="#b45309")

    # Leyenda
    legend_y = 1295
    for x, label, colors in [
        (70, "real", GREEN),
        (190, "SAP en vivo / caché", AMBER),
        (470, "mock", ROSE),
        (590, "datos locales", SLATE),
    ]:
        draw.rounded_rectangle(
            (x, legend_y, x + 24, legend_y + 24),
            radius=6,
            fill=colors[0],
            outline=colors[1],
            width=2,
        )
        draw.text((x + 34, legend_y + 2), label, font=font(17), fill="#334155")

    draw.text(
        (70, 1328),
        "SAP en vivo para ficha/stock; escritura SAP y pago siguen mock.",
        font=font(16),
        fill=MUTED,
    )

    out = Path(__file__).resolve().parent.parent / "docs" / "flujo-actual.png"
    img.save(out, "PNG")
    print(out)


if __name__ == "__main__":
    main()
