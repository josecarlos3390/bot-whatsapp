from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CatalogItem

DEMO_ITEMS = [
    # Filtros
    {
        "sku": "FILT-001",
        "name": "Filtro de aceite WIX 51394",
        "description": "Filtro de aceite para motores nafteros 1.4 a 2.0. Rosca 3/4-16.",
        "category": "Filtros",
        "brand": "WIX",
        "price": 85,
        "stock": 24,
        "keywords": "filtro aceite motor cambio service",
    },
    {
        "sku": "FILT-002",
        "name": "Filtro de aire Mann C25114",
        "description": "Filtro de aire de panel, alto flujo, para camionetas y SUV.",
        "category": "Filtros",
        "brand": "Mann",
        "price": 120,
        "stock": 15,
        "keywords": "filtro aire motor admision panel",
    },
    {
        "sku": "FILT-003",
        "name": "Filtro de combustible Bosch 0450905001",
        "description": "Filtro de combustible en línea, compatible con inyección electrónica.",
        "category": "Filtros",
        "brand": "Bosch",
        "price": 95,
        "stock": 18,
        "keywords": "filtro combustible nafta gasolina inyeccion",
    },
    {
        "sku": "FILT-004",
        "name": "Filtro de cabina Mahle LAK 234",
        "description": "Filtro de habitáculo con carbón activado, retiene polvo y polen.",
        "category": "Filtros",
        "brand": "Mahle",
        "price": 140,
        "stock": 10,
        "keywords": "filtro cabina aire acondicionado polen",
    },
    # Aceites
    {
        "sku": "ACEI-001",
        "name": "Aceite Mobil 1 5W-30 4L",
        "description": "Aceite sintético full API SP, ideal para motores modernos.",
        "category": "Aceites",
        "brand": "Mobil",
        "price": 380,
        "stock": 30,
        "keywords": "aceite sintetico 5w30 motor lubricante",
    },
    {
        "sku": "ACEI-002",
        "name": "Aceite Castrol GTX 20W-50 4L",
        "description": "Aceite mineral para motores con alto kilometraje.",
        "category": "Aceites",
        "brand": "Castrol",
        "price": 240,
        "stock": 20,
        "keywords": "aceite mineral 20w50 motor lubricante",
    },
    {
        "sku": "ACEI-003",
        "name": "Aceite Shell Helix HX7 10W-40 4L",
        "description": "Semisintético, protege contra desgaste y lodos.",
        "category": "Aceites",
        "brand": "Shell",
        "price": 320,
        "stock": 12,
        "keywords": "aceite semisintetico 10w40 motor",
    },
    {
        "sku": "ACEI-004",
        "name": "Aceite de transmisión Valvoline ATF 1L",
        "description": "Fluido para cajas automáticas y dirección hidráulica.",
        "category": "Aceites",
        "brand": "Valvoline",
        "price": 110,
        "stock": 25,
        "keywords": "aceite transmision atf caja automatica",
    },
    # Frenos
    {
        "sku": "FREN-001",
        "name": "Pastillas de freno Brembo delanteras",
        "description": "Juego de pastillas cerámicas para eje delantero.",
        "category": "Frenos",
        "brand": "Brembo",
        "price": 450,
        "stock": 8,
        "keywords": "pastillas freno delanteras ceramicas",
    },
    {
        "sku": "FREN-002",
        "name": "Discos de freno ventilados (par)",
        "description": "Par de discos ventilados, diámetro 280 mm.",
        "category": "Frenos",
        "brand": "Brembo",
        "price": 780,
        "stock": 6,
        "keywords": "discos freno ventilados par",
    },
    {
        "sku": "FREN-003",
        "name": "Líquido de frenos DOT 4 500ml",
        "description": "Alto punto de ebullición, para sistemas ABS.",
        "category": "Frenos",
        "brand": "Bosch",
        "price": 65,
        "stock": 40,
        "keywords": "liquido frenos dot4 abs",
    },
    {
        "sku": "FREN-004",
        "name": "Kit de frenos trasero",
        "description": "Pastillas y discos para eje trasero, uso urbano.",
        "category": "Frenos",
        "brand": "TRW",
        "price": 520,
        "stock": 5,
        "keywords": "kit frenos trasero pastillas discos",
    },
    # Baterías
    {
        "sku": "BATE-001",
        "name": "Batería Bosch S4 12V 60Ah",
        "description": "Batería libre de mantenimiento, 540 CCA.",
        "category": "Baterías",
        "brand": "Bosch",
        "price": 950,
        "stock": 7,
        "keywords": "bateria 12v 60ah bosch auto",
    },
    {
        "sku": "BATE-002",
        "name": "Batería Willard 12V 75Ah",
        "description": "Batería para camionetas y vehículos con accesorios.",
        "category": "Baterías",
        "brand": "Willard",
        "price": 1150,
        "stock": 4,
        "keywords": "bateria 12v 75ah willard camioneta",
    },
    {
        "sku": "BATE-003",
        "name": "Cargador de batería 12V 10A",
        "description": "Cargador automático con protección de sobrecarga.",
        "category": "Baterías",
        "brand": "Einhell",
        "price": 420,
        "stock": 9,
        "keywords": "cargador bateria 12v automatico",
    },
    {
        "sku": "BATE-004",
        "name": "Bornes y cables de batería",
        "description": "Juego de bornes y cable de masa calibre 4.",
        "category": "Baterías",
        "brand": "Generico",
        "price": 85,
        "stock": 30,
        "keywords": "bornes cables bateria masa",
    },
    # Herramientas
    {
        "sku": "HERR-001",
        "name": "Juego de llaves combinadas 12 piezas",
        "description": "Llaves de 8 a 19 mm, acero cromo vanadio.",
        "category": "Herramientas",
        "brand": "Stanley",
        "price": 260,
        "stock": 14,
        "keywords": "juego llaves combinadas herramientas",
    },
    {
        "sku": "HERR-002",
        "name": "Gato hidráulico 2 toneladas",
        "description": "Gato de patín con maletín, altura mínima 135 mm.",
        "category": "Herramientas",
        "brand": "Einhell",
        "price": 480,
        "stock": 6,
        "keywords": "gato hidraulico 2 toneladas taller",
    },
    {
        "sku": "HERR-003",
        "name": "Llave de torque 1/2 pulgada",
        "description": "Torquímetro de 20 a 200 Nm con estuche.",
        "category": "Herramientas",
        "brand": "Stanley",
        "price": 390,
        "stock": 5,
        "keywords": "llave torque torquimetro 1/2",
    },
    {
        "sku": "HERR-004",
        "name": "Kit de destornilladores 20 piezas",
        "description": "Puntas planas, Phillips y Torx, mango ergonómico.",
        "category": "Herramientas",
        "brand": "Stanley",
        "price": 150,
        "stock": 22,
        "keywords": "destornilladores kit puntas torx",
    },
    # Lubricantes
    {
        "sku": "LUBR-001",
        "name": "Grasa multipropósito 1kg",
        "description": "Grasa de litio para rodamientos y articulaciones.",
        "category": "Lubricantes",
        "brand": "Shell",
        "price": 75,
        "stock": 35,
        "keywords": "grasa litio rodamientos multiproposito",
    },
    {
        "sku": "LUBR-002",
        "name": "Limpiador de inyectores 300ml",
        "description": "Aditivo concentrado para limpieza del sistema de inyección.",
        "category": "Lubricantes",
        "brand": "Wynn's",
        "price": 55,
        "stock": 50,
        "keywords": "limpiador inyectores aditivo combustible",
    },
    {
        "sku": "LUBR-003",
        "name": "Silicona automotriz 85g",
        "description": "Sellador de silicona resistente a altas temperaturas.",
        "category": "Lubricantes",
        "brand": "Loctite",
        "price": 35,
        "stock": 60,
        "keywords": "silicona automotriz sellador juntas",
    },
    {
        "sku": "LUBR-004",
        "name": "Refrigerante anticongelante 1L",
        "description": "Refrigerante listo para usar, protección -35 °C.",
        "category": "Lubricantes",
        "brand": "Prestone",
        "price": 60,
        "stock": 28,
        "keywords": "refrigerante anticongelante radiador",
    },
]


async def seed_demo(session: AsyncSession, force: bool = False) -> int:
    if not force:
        count = await session.scalar(select(func.count()).select_from(CatalogItem))
        if count:
            return 0
    existing = set((await session.scalars(select(CatalogItem.sku))).all())
    added = 0
    for row in DEMO_ITEMS:
        if row["sku"] in existing:
            continue
        session.add(CatalogItem(**row, currency="BOB"))
        added += 1
    if added:
        await session.commit()
    return added
