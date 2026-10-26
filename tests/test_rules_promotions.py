"""Reglas de promoción: la categoría se evalúa contra el producto."""

from types import SimpleNamespace

from app.services.rules_engine import order_promotions


def _regla(categoria: str, minimo: float) -> SimpleNamespace:
    return SimpleNamespace(
        rule_type="promotion_priority",
        condition={"category": categoria},
        action={"min_discount": minimo},
        priority=0,
    )


def test_promocion_aplica_a_la_categoria_del_producto():
    productos = [
        {
            "sku": "TAL-3",
            "category": "Herramientas",
            "promo_discount_percent": "3",
            "stock": 4,
        },
        {
            "sku": "TAL-10",
            "category": "Herramientas",
            "promo_discount_percent": "10",
            "stock": 4,
        },
        {
            "sku": "COL-20",
            "category": "Colchones",
            "promo_discount_percent": "20",
            "stock": 4,
        },
    ]

    orden = [
        producto["sku"]
        for producto in order_promotions(productos, [_regla("Herramientas", 5)])
    ]

    # El taladro con 10% cumple el mínimo de su categoría y va primero.
    assert orden[0] == "TAL-10"
    # El colchón no se prioriza por una regla de Herramientas.
    assert orden.index("COL-20") > 0


def test_sin_reglas_no_cambia_el_orden():
    productos = [
        {"sku": "A", "category": "TV", "promo_discount_percent": "0", "stock": 1},
        {"sku": "B", "category": "TV", "promo_discount_percent": "30", "stock": 1},
    ]
    orden = [p["sku"] for p in order_promotions(productos, [])]
    assert orden == ["A", "B"]
