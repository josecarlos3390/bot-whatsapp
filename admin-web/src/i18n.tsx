import { createContext, Fragment, useContext, useEffect, useMemo, useState } from "react";

/**
 * Traducción del panel sin librerías externas.
 *
 * La clave es el texto en español: si falta una traducción, se muestra el
 * original. `t()` funciona a nivel de módulo, así que no hace falta agregar el
 * hook en cada componente; al cambiar el idioma el árbol se vuelve a montar.
 */
export type Lang = "es" | "en";

let idiomaActual: Lang = "es";

const EN: Record<string, string> = {
  // Navegación y cabecera
  "Bandeja": "Inbox",
  "Agentes": "Agents",
  "Métricas": "Metrics",
  "Operación": "Operations",
  "Administración": "Administration",
  "Reglas": "Rules",
  "Ocasiones": "Occasions",
  "Consola de asesores": "Advisor console",
  "Portal de áreas": "Area portal",
  "Notificaciones": "Notifications",
  "Guardia": "On duty",
  "Sin guardia": "No one on duty",
  "Salir": "Sign out",
  "Cerrar sesión": "Sign out",
  "Volver a bandeja": "Back to inbox",
  "Ir a atención": "Go to inbox",
  "Cargando consola…": "Loading console…",
  "Cargando estado…": "Loading status…",
  "Cargando…": "Loading…",
  // Login
  "Consola": "Console",
  "Área": "Area",
  "Usuario": "Username",
  "Contraseña": "Password",
  "Ingresar": "Sign in",
  "Ingresando…": "Signing in…",
  "Usuario o contraseña incorrectos.": "Wrong username or password.",
  "ROHO Homecenter": "ROHO Homecenter",
  // Tablero
  "Centro de operación": "Operations center",
  "¿Cómo está el bot hoy?": "How is the bot doing today?",
  "Bot WhatsApp": "WhatsApp bot",
  "API de integración": "Integration API",
  "Sincronización VTEX": "VTEX sync",
  "Embudo de venta": "Sales funnel",
  "Búsquedas sin resultados": "Searches with no results",
  "Consumo del modelo": "Model usage",
  "Latencia de respuesta": "Response latency",
  "Probar el bot": "Test the bot",
  "Control de calidad": "Quality control",
  "Calidad de respuesta": "Response quality",
  "Última sincronización": "Last sync",
  "No envía nada ni ensucia las métricas": "Sends nothing and keeps metrics clean",
  "Escribí como si fueras un cliente y mirá exactamente qué respondería el bot.":
    "Type as a customer would and see exactly what the bot would answer.",
  "Respondió en": "Answered in",
  "camino": "path",
  "Últimas pruebas": "Recent tests",
  "Repetir": "Run again",
  "Probando…": "Testing…",
  "Probar": "Test",
  "Probar un mensaje": "Test a message",
  "Mediana": "Median",
  "p95": "p95",
  "Máxima": "Max",
  "Lentas": "Slow",
  "Entrada / llamada": "Input / call",
  "Salida / llamada": "Output / call",
  "Cacheado": "Cached",
  "Total tokens": "Total tokens",
  "Sin anomalías detectadas.": "No anomalies detected.",
  "Últimos 30 días.": "Last 30 days.",
  "Indicadores de las últimas 24 horas.": "Last 24 hours indicators.",
  "Métricas · últimos 30 días": "Metrics · last 30 days",
  "Mensajes 24 h": "Messages 24 h",
  "Handoffs abiertos": "Open handoffs",
  "Tomados": "Taken",
  "Reabiertos": "Reopened",
  "Resueltos": "Resolved",
  "Fallbacks / aclaraciones": "Fallbacks / clarifications",
  "Errores de herramientas": "Tool errors",
  "Llamadas a herramientas": "Tool calls",
  "Tiempo real + respaldo cada 30 s": "Real time + fallback every 30 s",
  // Bandeja y detalle
  "Buscar por nombre, número o motivo…": "Search by name, number or reason…",
  "Elegí un handoff para ver la conversación": "Pick a handoff to see the conversation",
  "Limpiar filtros": "Clear filters",
  "Limpiar": "Clear",
  "Actualizar": "Refresh",
  "Estado": "Status",
  "Nombre": "Name",
  "Cliente": "Customer",
  "Detalle": "Detail",
  "Acciones": "Actions",
  "Asesor": "Advisor",
  "Agente": "Agent",
  "Admin": "Admin",
  "Supervisor": "Supervisor",
  "Tomar": "Take",
  "Reabrir": "Reopen",
  "Resolver": "Resolve",
  "Resolver handoff": "Resolve handoff",
  "Transferir": "Transfer",
  "Transferir caso": "Transfer case",
  "Devolver al bot": "Return to bot",
  "Resolución": "Resolution",
  "Historial": "History",
  "Contexto del bot": "Bot context",
  "Intención y filtros": "Intent and filters",
  "Pregunta pendiente": "Pending question",
  "Última recomendación": "Last recommendation",
  "Alias del cliente": "Customer alias",
  "Nota visible solo para el equipo…": "Note visible only to the team…",
  "Adjuntar imagen o documento": "Attach image or document",
  "Sin actividad todavía.": "No activity yet.",
  "Vista previa": "Preview",
  "Usuarios": "Users",
  "Usuarios de área": "Area users",
  "Usuarios, guardia y permisos.": "Users, shifts and permissions.",
  "Crear usuario": "Create user",
  "Crear usuario de área": "Create area user",
  "Cambiar rol": "Change role",
  "Resetear clave": "Reset password",
  "Crear": "Create",
  "Guardar": "Save",
  "Cancelar": "Cancel",
  "Editar": "Edit",
  "Eliminar": "Delete",
  "Quitar": "Remove",
  "Cerrar": "Close",
  "Cancelar edición": "Cancel edit",
  "Volver": "Back",
  "Sin usuarios.": "No users.",
  "contraseña": "password",
  "nombre visible": "display name",
  "usuario": "username",
  "Solo lectura": "Read only",
  "Atención al cliente": "Customer service",
  "Conversaciones": "Conversations",
  "Carrito": "Cart",
  "Pedidos": "Orders",
  "Métricas de atención": "Service metrics",
  // Reglas
  "Reglas del bot": "Bot rules",
  "Reglas por área": "Rules by area",
  "Reglas cargadas": "Loaded rules",
  "Reglas publicadas": "Published rules",
  "Administrar reglas": "Manage rules",
  "Centro de administración": "Admin center",
  "Centro de contenido": "Content center",
  "Solo vas a ver las reglas de tu área.": "You will only see your area's rules.",
  "Cada encargado administra solo sus reglas.": "Each manager handles only their own rules.",
  "Cada cambio guarda una versión restaurable.": "Every change saves a restorable version.",
  "Borradores no se usan. Publicá para que el bot los lea.":
    "Drafts are not used. Publish so the bot reads them.",
  "Mirá qué productos y reglas se aplicarían, sin crear una conversación.":
    "See which products and rules would apply, without creating a conversation.",
  "Probar una consulta antes de publicar": "Test a query before publishing",
  "Lo que el bot lee": "What the bot reads",
  "Simulador": "Simulator",
  "Priorizar una marca cuando pregunten por una categoría":
    "Prioritize a brand when a category is asked about",
  "Priorizar productos en promoción con stock": "Prioritize discounted products with stock",
  "Agregar una indicación de respuesta para un tema": "Add a response guideline for a topic",
  "Definir preguntas obligatorias para una categoría": "Define required questions for a category",
  "Crear un flujo de preguntas para devoluciones": "Create a question flow for returns",
  "Cargá instrucciones sin escribir JSON.": "Add instructions without writing JSON.",
  "¿Qué debe decir o tener en cuenta el bot?": "What should the bot say or keep in mind?",
  "Descuento mínimo (%)": "Minimum discount (%)",
  "Categoría o tema (opcional)": "Category or topic (optional)",
  "Ej: Priorizar LG en heladeras": "E.g. Prioritize LG for fridges",
  "Ej: heladera": "E.g. fridge",
  "Ej: heladera, envíos, promociones": "E.g. fridge, shipping, promotions",
  "Ej: se confirmó stock y se pasó el link de pago":
    "E.g. stock was confirmed and the payment link was sent",
  "Ej: televisor 50 pulgadas, heladera no frost...": "E.g. 50-inch TV, no-frost fridge…",
  "Ej: busco un colchón de 2 plazas": "E.g. I'm looking for a 2-seat mattress",
  "Debe responder Sí": "Should answer Yes",
  "Restaurar": "Restore",
  "Sin versiones.": "No versions.",
  "Sin reglas cargadas.": "No rules loaded.",
  "Tipo": "Type",
  "Prioridad": "Priority",
  "Categoría": "Category",
  "Marca": "Brand",
  "Desde": "From",
  "Hasta": "To",
  "Auditoría:": "Audit:",
  "Resultado tarea:": "Task result:",
  "Sin actividad": "No activity",
  "Publicado": "Published",
  "Borrador": "Draft",
  "Publicada": "Published",
  "Publicadas": "Published",
  // Ocasiones
  "Ocasiones y campañas": "Occasions and campaigns",
  "Campañas que entienden al cliente": "Campaigns that understand the customer",
  "¿Para qué sirve esta pantalla?": "What is this screen for?",
  "¿Para qué sirve?": "What is it for?",
  "Ocasiones cargadas": "Loaded occasions",
  "Guardar ocasión": "Save occasion",
  "Editar ocasión": "Edit occasion",
  "Nueva ocasión": "New occasion",
  "Cargar ejemplos": "Load examples",
  "Ver reglas": "See rules",
  "Términos directos": "Direct terms",
  "Excluir términos": "Exclude terms",
  "Excluir categorías": "Exclude categories",
  "Alternativa natural": "Natural alternative",
  "Términos de la alternativa": "Alternative terms",
  "Directo:": "Direct:",
  "Excluye:": "Excludes:",
  "Alternativa:": "Alternative:",
  "Detecta": "Detects",
  "Próxima:": "Next:",
  "Regla de oro": "Golden rule",
  "Primero EL catálogo. Después la inferencia.": "Catalog first. Inference second.",
  "Área que será dueña de la ocasión y podrá mantenerla.":
    "Area that owns the occasion and can maintain it.",
  "Halloween, Navidad, Baby shower...": "Halloween, Christmas, Baby shower…",
  "halloween, halloweén": "halloween, halloween",
  "disfraz, dulce, calabaza, vela": "costume, candy, pumpkin, candle",
  "mueble, silla, navidad": "furniture, chair, christmas",
  "televisor, tv": "television, tv",
  "una noche de película": "a movie night",
  "heladera": "fridge",
  "colchones, pintura, herramientas": "mattresses, paint, tools",
  "MUEBLES, PINTURA, HERRAMIENTAS": "FURNITURE, PAINT, TOOLS",
  "Ej: venden algo para halloween?": "E.g. do you sell anything for halloween?",
  "clave (opcional)": "key (optional)",
  "Pregunta": "Question",
  "General": "General",
  "Ecommerce": "Ecommerce",
  "Marketing": "Marketing",
  "Auditoría": "Audit",
  "ROHO HOMECENTER": "ROHO HOMECENTER",
  "ROHO": "ROHO",
  "Simulando…": "Simulating…",
  "Simular": "Run simulation",
  "Disponible": "Available",
  "Sin stock": "Out of stock",
  "Editar regla": "Edit rule",
  "Nueva regla": "New rule",
  "activo": "active",
  "inactivo": "inactive",
  "Activar": "Activate",
  "Desactivar": "Deactivate",
  "Activar modo claro": "Switch to light mode",
  "Activar modo oscuro": "Switch to dark mode",
  "Modo claro": "Light mode",
  "Modo oscuro": "Dark mode",
  // Ayudas del formulario de reglas
  "Ordena las marcas de una categoría: la elegida aparece primero. No cambia precios ni stock.": "Orders the brands in a category: the chosen one shows first. It does not change prices or stock.",
  "Destaca los productos de una categoría cuyo descuento de VTEX alcanza el mínimo. No crea descuentos.": "Highlights products in a category whose VTEX discount reaches the minimum. It does not create discounts.",
  "Define las preguntas que el bot hace, en orden, para gestionar una devolución.": "Sets the questions the bot asks, in order, to handle a return.",
  "Agrega una indicación que el bot debe respetar al hablar de ese tema.": "Adds an instruction the bot must follow when talking about that topic.",
  "El bot pregunta esto antes de cerrar la venta de esa categoría.": "The bot asks this before closing a sale in that category.",
  "Solo para identificarla en la lista; el cliente no la ve.": "Only to identify it in the list; the customer does not see it.",
  "Escribila como figura en el catálogo (ej: Heladeras). Se aplica a las búsquedas de esa categoría.": "Write it as it appears in the catalog (e.g. Refrigerators). It applies to searches in that category.",
  "Esta marca se muestra antes que las demás dentro de la categoría.": "This brand is shown before the others in the category.",
  "Se evalúa por la categoría del producto: funciona aunque el cliente busque \"taladro\" y no \"herramientas\".": "It is evaluated by the product category: it works even if the customer searches \"drill\" instead of \"tools\".",
  "Umbral para destacar. Si el descuento real de VTEX es menor, el producto no se prioriza. No modifica precios ni crea descuentos.": "Highlight threshold. If the real VTEX discount is lower, the product is not prioritized. It does not change prices or create discounts.",
  "Si la dejás vacía, la indicación se aplica a cualquier consulta.": "If left empty, the instruction applies to any query.",
  "Se agrega como indicación al bot. No reemplaza los datos del catálogo: precios y stock los sigue tomando de VTEX.": "It is added as an instruction to the bot. It does not replace catalog data: prices and stock still come from VTEX.",
  "Si la dejás vacía, la regla aplica a todas las categorías.": "If left empty, the rule applies to every category.",
  "Si dos reglas del mismo tipo aplican, gana la de número mayor.": "If two rules of the same type apply, the higher number wins.",
  "Borrador no se aplica. Publicado empieza a usarse en la próxima respuesta.": "Draft is not applied. Published is used from the next reply.",
  "Marca prioritaria": "Brand priority",
  "Promoción prioritaria": "Promotion priority",
  "Flujo de devolución": "Return flow",
  "Indicación de respuesta": "Response instruction",
  "Preguntas obligatorias": "Required questions",
  "Archivo:": "File:",
  "Ninguna registrada.": "None registered.",
  "Publicar": "Publish",
  "¿Qué querés hacer?": "What do you want to do?",
  "desde": "from",
  "% de descuento": "% off",
  "preguntas": "questions",
  "No detecta ninguna ocasión con ese mensaje. Probá sumar un alias o un término directo.": "No occasion detected for that message. Try adding an alias or a direct term.",
  "Comercio electrónico": "E-commerce",
  "ecommerce": "E-commerce",
  "calidad": "Quality",
  "marketing": "Marketing",
  "operaciones": "Operations",
  "general": "General",
  "Venta a cliente enojado": "Sale to an angry customer",
  "Frase prohibida": "Forbidden phrase",
  "Mensaje sin respuesta": "Message without reply",
  "No se pudo cargar el estado": "Could not load the status",
  "Sin alertas activas": "No active alerts",
  "En línea": "Online",
  "Ocupado": "Busy",
  "Desconectado": "Offline",
  "En cola": "Queued",
  "Escalado": "Escalated",
  "Indicadores del equipo": "Team indicators",
  "Cómo está rindiendo la atención en el período.": "How support is performing in the period.",
  "SLA cumplido": "SLA met",
  "Satisfacción": "Satisfaction",
  "Asesores activos": "Active advisors",
  "Sin tomar": "Not taken",
  "1ª respuesta": "First reply",
  "Sin actividad en el período.": "No activity in the period.",
  "Cargando indicadores…": "Loading indicators…",
  "Pendientes de revisión": "Pending review",
  "Aprobar": "Approve",
  "Descartar": "Discard",
  "Nada para revisar.": "Nothing to review.",
  "Calidad del catálogo": "Catalog quality",
  "Defectos de datos que el cliente termina viendo en las respuestas.": "Data defects the customer ends up seeing in replies.",
  "artículos activos": "active items",
  "Sin foto": "No image",
  "Títulos largos": "Long titles",
  "Títulos incoherentes": "Incoherent titles",
  "Duplicados": "Duplicates",
  "Sin precio": "No price",
  "Ejemplos a revisar": "Examples to review",
  "Lo que buscan y no existe": "Searched but missing",
  "Cargando informe…": "Loading report…",
  "Máx. casos": "Max cases",
  "Aprendizaje de búsquedas": "Search learning",
  "Lo que el bot no encontraba y ya aprendió. Las pendientes son candidatas para cargar en el catálogo.": "What the bot could not find and has learned. Pending ones are candidates to add to the catalog.",
  "aprendidas": "learned",
  "pendientes": "pending",
  "Búsquedas sin resultado": "Searches without results",
  "Sin pendientes.": "No pending items.",
  "Consultas aprendidas": "Learned queries",
  "Todavía no aprendió ninguna.": "Nothing learned yet.",
  "alerta(s)": "alert(s)",
  "Sin asignar": "Unassigned",
  "No se pudo enviar.": "Could not send.",
  "No se pudo guardar la nota.": "Could not save the note.",
  "No se pudo enviar el archivo.": "Could not send the file.",
  "Sin motivo": "No reason",
  "otro asesor": "another advisor",
  "Sin pedidos": "No orders",
  "Sin pregunta pendiente": "No pending question",
  "Sin estado guardado": "No saved state",
  "Sin recomendaciones registradas": "No recommendations recorded",
  "El asesor devolvió el caso al bot.": "The advisor returned the case to the bot.",
  "No hay casos con ese filtro.": "No cases match that filter.",
  "No hay handoffs abiertos.": "No open handoffs.",
  "El nuevo asesor podrá responder desde su consola.": "The new advisor will be able to reply from their console.",
  "El bot retomará la conversación sin marcar el caso como resuelto.": "The bot will resume the conversation without marking the case as resolved.",
  "No se pudieron cargar los agentes.": "Could not load agents.",
  "No se pudo crear.": "Could not create.",
  "No se pudieron cargar las reglas": "Could not load the rules",
  "No se pudo simular": "Could not simulate",
  "Poné un nombre a la regla": "Give the rule a name",
  "No se pudo guardar": "Could not save",
  "¿Eliminar esta regla?": "Delete this rule?",
  "No se pudo cargar el historial": "Could not load the history",
  "No se pudo restaurar": "Could not restore",
  "Sin marca": "No brand",
  "Sin categoría": "No category",
  "No se pudieron cargar los usuarios": "Could not load users",
  "No se pudo crear": "Could not create",
  "No se pudo actualizar": "Could not update",
  "No se pudo probar": "Could not test",
  "No se pudieron cargar las ocasiones": "Could not load occasions",
  "Poné un nombre a la ocasión": "Give the occasion a name",
  "No se pudo publicar": "Could not publish",
  "¿Eliminar esta ocasión?": "Delete this occasion?",
  "No se pudo eliminar": "Could not delete",
  "No se pudieron cargar los ejemplos": "Could not load the examples",
  "Tema delicado con producto": "Sensitive topic with product",
  "Producto sin pedido": "Product without a request",
  "Sincronización VTEX con error": "VTEX sync failed",
  "Revisá el último log de sincronización.": "Check the latest sync log.",
  "No se pudo leer el estado de la tarea VTEX": "Could not read the VTEX task status",
  "Revisá el Programador de tareas de Windows.": "Check the Windows Task Scheduler.",
  "Sincronización VTEX antigua": "VTEX sync is stale",
  "La última sincronización tiene más de 36 horas.": "The last sync was more than 36 hours ago.",
  "API de integración no responde": "Integration API is not responding",
  "Sin detalle": "No detail",
  "WhatsApp en modo prueba": "WhatsApp in test mode",
  "WA_DRY_RUN está activo.": "WA_DRY_RUN is enabled.",
  "Túnel temporal": "Temporary tunnel",
  "La URL pública usa trycloudflare.": "The public URL uses trycloudflare.",
  "Handoffs acumulados": "Accumulated handoffs",
  "casos abiertos.": "open cases.",
  "Sin reglas publicadas": "No published rules",
  "El bot no tiene reglas de área activas.": "The bot has no active area rules.",
  // Ayudas de ocasiones
  "Nombre interno de la campaña. El cliente no lo ve.": "Internal campaign name. The customer does not see it.",
  "Área dueña de la campaña: solo ella puede editarla.": "Area that owns the campaign: only it can edit it.",
  "Palabras que el cliente escribe para activar la campaña. Separadas por coma.": "Words the customer writes to trigger the campaign. Comma separated.",
  "Si dos campañas coinciden, gana la de número mayor.": "If two campaigns match, the higher number wins.",
  "Productos que se buscan tal cual. Separados por coma.": "Products searched as written. Comma separated.",
  "Si el mensaje contiene alguno, la campaña no se activa.": "If the message contains any of them, the campaign does not trigger.",
  "Categorías que no deben aparecer en esta campaña.": "Categories that must not appear in this campaign.",
  "Qué ofrece el bot si no hay productos de la campaña. Es una salida amable, no una categoría.": "What the bot offers when the campaign has no products. A friendly exit, not a category.",
  "Productos que se muestran como alternativa. Separados por coma.": "Products shown as an alternative. Comma separated.",
  "Opcional: cuándo empieza a aplicarse.": "Optional: when it starts applying.",
  "Opcional: cuándo deja de aplicarse.": "Optional: when it stops applying.",
  "Borrador no se usa. Publicada se aplica en la próxima conversación.": "Draft is not used. Published applies from the next conversation.",
  // Ejemplo de la regla de promociones
  "Ejemplo con esta regla (Herramientas, mínimo 5%)": "Example with this rule (Tools, minimum 5%)",
  "Cliente: \"busco un taladro\". El bot busca en la categoría y ordena así:": "Customer: \"looking for a drill\". The bot searches the category and orders like this:",
  "Taladro con 46% de descuento y stock → primero (cumple el mínimo).": "Drill with 46% off and stock → first (meets the minimum).",
  "Taladro con 19% → también primero, detrás del de mayor descuento.": "Drill with 19% off → also first, behind the highest discount.",
  "Taladro con 3% → después de los que cumplen, aunque su nombre coincida mejor.": "Drill with 3% off → after the qualifying ones, even if its name matches better.",
  "Taladro sin promoción → al final.": "Drill without promotion → last.",
  "El precio y el porcentaje son los de VTEX: la regla solo cambia el orden y lo que el bot destaca.": "Price and percentage come from VTEX: the rule only changes the order and what the bot highlights.",
  // Ejemplos de otras reglas
  "Ejemplo: Heladeras con LG primero": "Example: Refrigerators with LG first",
  "Cliente: \"busco una heladera\". El bot muestra primero las LG con stock y después el resto de las marcas, sin ocultar ninguna.": "Customer: \"looking for a fridge\". The bot shows LG in stock first, then the rest of the brands, hiding none.",
  "Los precios son los del catálogo: la regla no aplica descuentos.": "Prices come from the catalog: the rule does not apply discounts.",
  "Ejemplo: indicación para envíos": "Example: shipping instruction",
  "Cliente: \"¿hacen envíos a Santa Cruz?\". El bot responde con la indicación: entrega en 24 h y retiro en tienda, sin inventar costos de envío.": "Customer: \"do you ship to Santa Cruz?\". The bot answers with the instruction: 24 h delivery and store pickup, without inventing shipping costs.",
  "Si el dato no está publicado, ofrece derivar con un asesor en lugar de inventarlo.": "If the data is not published, it offers to hand off to an advisor instead of making it up.",
  "Ejemplo: devolución de una licuadora": "Example: returning a blender",
  "Ejemplo: preguntas antes de vender una heladera": "Example: questions before selling a fridge",
  "Preguntas en orden: \"¿Cuándo la compraste?\" → \"¿Está sin uso?\" → \"¿Tenés la factura?\". El bot las hace una por una antes de derivar el caso.": "Questions in order: \"When did you buy it?\" → \"Is it unused?\" → \"Do you have the receipt?\". The bot asks them one by one before handing off.",
  "El bot pregunta \"¿Cuántos litros necesitás?\" y \"¿Tenés 1,80 m de espacio?\" antes de cerrar la venta de una heladera.": "The bot asks \"How many liters do you need?\" and \"Do you have 1.80 m of space?\" before closing a fridge sale.",
  "Si el cliente ya respondió algo, no lo vuelve a preguntar.": "If the customer already answered, it does not ask again.",
  "Ejemplo: usuario de ecommerce": "Example: ecommerce user",
  "Usuario \"jperez\", área \"ecommerce\": solo ve y edita las reglas y ocasiones de ecommerce. No ve las de otras áreas.": "User \"jperez\", area \"ecommerce\": only sees and edits ecommerce rules and occasions. Does not see other areas.",
  "Ejemplo: campaña de Halloween": "Example: Halloween campaign",
  "Alias: \"halloween, halloweén\". Términos directos: \"disfraz, calabaza, vela\". Excluir: \"mueble, navidad\".": "Aliases: \"halloween, hallowe'en\". Direct terms: \"costume, pumpkin, candle\". Exclude: \"furniture, christmas\".",
  "Si el cliente escribe \"quiero un mueble para Halloween\", la exclusión \"mueble\" evita que la campaña se active y el bot busca el mueble normalmente.": "If the customer writes \"I want furniture for Halloween\", the \"furniture\" exclusion stops the campaign and the bot searches furniture normally.",
  "Alternativa natural: \"una noche de película\" → si no hay productos de la campaña, ofrece televisores.": "Natural alternative: \"a movie night\" → if the campaign has no products, it offers TVs.",
  "Ejemplo: alta de un asesor": "Example: adding an advisor",
  "Agente \"mflores\" con guardia activa: recibe los casos derivados y aparece en la bandeja. Supervisor: además ve las métricas del equipo. Admin: administra agentes y configuración.": "Agent \"mflores\" on duty: receives handed-off cases and appears in the inbox. Supervisor: also sees team metrics. Admin: manages agents and settings.",
};

function traducir(texto: string): string {
  if (idiomaActual === "es") return texto;
  return EN[texto] ?? texto;
}

type I18nValue = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (text: string) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

function idiomaInicial(): Lang {
  const guardado = window.localStorage.getItem("roho-lang");
  if (guardado === "es" || guardado === "en") return guardado;
  return navigator.language.toLowerCase().startsWith("en") ? "en" : "es";
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>(idiomaInicial);
  // Se asigna en render para que el `t()` de módulo use el idioma vigente.
  idiomaActual = lang;

  useEffect(() => {
    window.localStorage.setItem("roho-lang", lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const value = useMemo(
    () => ({ lang, setLang, t: traducir }),
    [lang]
  );

  return (
    <I18nContext.Provider value={value}>
      <Fragment key={lang}>{children}</Fragment>
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n debe usarse dentro de I18nProvider");
  return value;
}

/** Traducción para usar fuera de componentes (textos y props de JSX). */
export function t(texto: string): string {
  return traducir(texto);
}

export function LanguageToggle() {
  const { lang, setLang } = useI18n();
  return (
    <div
      className="flex items-center rounded-full border border-[#ffb3bd]/30 bg-[#ffffff]/10 p-0.5 text-[11px] font-semibold"
      title="Idioma / Language"
    >
      {(["es", "en"] as Lang[]).map((opcion) => (
        <button
          key={opcion}
          type="button"
          onClick={() => setLang(opcion)}
          className={`rounded-full px-2 py-1 uppercase transition ${
            lang === opcion ? "bg-[#e9082a] text-white" : "text-slate-300 hover:text-white"
          }`}
          title={opcion === "es" ? "Español" : "English"}
        >
          {opcion}
        </button>
      ))}
    </div>
  );
}
