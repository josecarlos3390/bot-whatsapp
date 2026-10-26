import { useEffect, useMemo, useState } from "react";
import { LanguageToggle, t } from "./i18n";
import { Link } from "react-router-dom";
import { api } from "./api";
import { Badge, Button, Card, Example, Input, Textarea } from "./ui";
import { ThemeToggle } from "./theme";
import type { Advisor, AreaRule, AreaUser } from "./types";

const AREAS = ["ecommerce", "calidad", "marketing", "operaciones", "general"];

export function AreaHeader({
  title,
  subtitle,
  onLogout
}: {
  title: string;
  subtitle: string;
  onLogout: () => void;
}) {
  return (
    <header className="border-b border-[#ffb3bd]/25 bg-[linear-gradient(135deg,#1f2937_0%,#111827_55%,#0a0a0a_100%)] text-[#f9fafb] shadow-lg shadow-black/20">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-3 px-4 py-3.5 lg:px-6">
        <div className="grid h-9 w-9 place-items-center rounded-xl border border-[#a90418]/50 bg-[#a90418] text-base font-black text-[#111111] shadow-inner">
          R
        </div>
        <div>
          <div className="font-brand text-[10px] text-[#ffb3bd]">ROHO HOMECENTER</div>
          <div className="font-serif text-base font-semibold tracking-tight">{title}</div>
        </div>
        <div className="ml-auto flex items-center gap-3 text-sm text-[#e5e7eb]">
          <span className="hidden rounded-full border border-[#ffb3bd]/20 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-wider sm:inline">{subtitle}</span>
          <LanguageToggle />
          <ThemeToggle />
          <button onClick={onLogout} className="rounded-lg border border-[#ffb3bd]/40 bg-white/5 px-3 py-1.5 text-xs font-semibold text-[#fde7ea] transition hover:bg-white/10">{t("Salir")}</button>
        </div>
      </div>
    </header>
  );
}

type Question = { text: string; key: string; requireYes: boolean };

type Simulation = {
  ok: boolean;
  prompt_text?: string;
  detail?: string;
  query?: string;
  area?: string;
  note?: string;
  products: {
    sku: string;
    name: string;
    brand?: string;
    category?: string;
    price: number;
    promo_price: number;
    promo_discount_percent: number;
    available: boolean;
  }[];
  rules: {
    id: string;
    name: string;
    rule_type: string;
    priority: number;
    action: Record<string, unknown>;
  }[];
};

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="mt-1 text-[11px] leading-snug text-slate-500">{children}</p>;
}

const TIPO_REGLA: Record<string, string> = {
  brand_priority: "Marca prioritaria",
  promotion_priority: "Promoción prioritaria",
  return_flow: "Flujo de devolución",
  response_rule: "Indicación de respuesta",
  required_questions: "Preguntas obligatorias",
};
function RuleBuilder({
  base,
  area,
  areas,
  canChangeArea,
  onLogout
}: {
  base: string;
  area: string;
  areas?: string[];
  canChangeArea?: boolean;
  onLogout: () => void;
}) {
  const [rules, setRules] = useState<AreaRule[]>([]);
  const [selectedArea, setSelectedArea] = useState(area);
  const [kind, setKind] = useState("brand_priority");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [brand, setBrand] = useState("");
  const [instruction, setInstruction] = useState("");
  const [minDiscount, setMinDiscount] = useState(10);
  const [priority, setPriority] = useState(100);
  const [status, setStatus] = useState("draft");
  const [questions, setQuestions] = useState<Question[]>([{ text: "", key: "", requireYes: true }]);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [versionsFor, setVersionsFor] = useState<AreaRule | null>(null);
  const [versions, setVersions] = useState<{ version: number; changed_by: string; created_at?: string }[]>([]);
  const [simQuery, setSimQuery] = useState("");
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [simBusy, setSimBusy] = useState(false);

  const areaQuery = canChangeArea ? `?area=${encodeURIComponent(selectedArea)}` : "";
  const load = async () => {
    try {
      const data = await api<{ rules: AreaRule[] }>(base + areaQuery);
      setRules(data.rules || []);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudieron cargar las reglas");
    }
  };

  useEffect(() => { void load(); }, [base, selectedArea, canChangeArea]);

  async function simulate() {
    if (!simQuery.trim()) return;
    setSimBusy(true);
    try {
      const endpoint = canChangeArea ? "/admin/rules/simulate" : "/areas/rules/simulate";
      const payload = canChangeArea
        ? { query: simQuery.trim(), area: selectedArea }
        : { query: simQuery.trim() };
      const result = await api<Simulation>(endpoint, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setSimulation(result);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo simular");
    } finally {
      setSimBusy(false);
    }
  }

  function reset() {
    setEditing(null);
    setName("");
    setCategory("");
    setBrand("");
    setInstruction("");
    setMinDiscount(10);
    setPriority(100);
    setStatus("draft");
    setKind("brand_priority");
    setQuestions([{ text: "", key: "", requireYes: true }]);
  }

  async function save() {
    try {
      if (!name.trim()) throw new Error("Poné un nombre a la regla");
      let condition: Record<string, unknown> = {};
      let action: Record<string, unknown> = {};
      if (kind === "brand_priority") {
        if (!category.trim() || !brand.trim()) throw new Error("Completá categoría y marca");
        condition = { category: category.trim() };
        action = { brand: brand.trim() };
      } else if (kind === "promotion_priority") {
        if (!category.trim()) throw new Error("Completá la categoría");
        condition = { category: category.trim() };
        action = { min_discount: minDiscount };
      } else if (kind === "return_flow") {
        const valid = questions.filter((question) => question.text.trim());
        if (!valid.length) throw new Error("Agregá al menos una pregunta");
        action = {
          questions: valid.map((question) => ({
            text: question.text.trim(),
            key: question.key.trim() || question.text.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_"),
            type: "yes_no"
          })),
          requirements: Object.fromEntries(
            valid
              .filter((question) => question.requireYes)
              .map((question) => [question.key.trim() || question.text.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_"), true])
          )
        };
        condition = { intent: "devolucion" };
      } else if (kind === "response_rule") {
        if (!instruction.trim()) throw new Error("Escribí la respuesta o indicación");
        condition = category.trim() ? { category: category.trim() } : {};
        action = { instruction: instruction.trim() };
      } else {
        const valid = questions.filter((question) => question.text.trim());
        if (!valid.length) throw new Error("Agregá al menos una pregunta");
        condition = category.trim() ? { category: category.trim() } : {};
        action = {
          questions: valid.map((question) => ({
            text: question.text.trim(),
            key: question.key.trim() || question.text.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_"),
            type: "text"
          }))
        };
      }
      const body = {
        area: canChangeArea ? selectedArea : area,
        name: name.trim(),
        rule_type: kind,
        condition,
        action,
        priority,
        status
      };
      await api(editing ? `${base}/${editing}` : base, {
        method: editing ? "PUT" : "POST",
        body: JSON.stringify(body)
      });
      reset();
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo guardar");
    }
  }

  async function publish(id: string) {
    await api(`${base}/${id}/publish`, { method: "POST" });
    await load();
  }

  async function remove(id: string) {
    if (!confirm("¿Eliminar esta regla?")) return;
    await api(`${base}/${id}`, { method: "DELETE" });
    await load();
  }

  async function history(rule: AreaRule) {
    try {
      const data = await api<{ versions: { version: number; changed_by: string; created_at?: string }[] }>(`${base}/${rule.id}/versions`);
      setVersionsFor(rule);
      setVersions(data.versions || []);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo cargar el historial");
    }
  }

  async function rollback(rule: AreaRule, version: number) {
    if (!confirm(`¿Restaurar la versión ${version}?`)) return;
    try {
      await api(`${base}/${rule.id}/rollback/${version}`, { method: "POST" });
      await load();
      await history(rule);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo restaurar");
    }
  }

  function edit(rule: AreaRule) {
    setEditing(rule.id);
    setName(rule.name);
    setPriority(rule.priority);
    setStatus(rule.status);
    if (rule.rule_type === "promotion_priority") {
      setKind("promotion_priority");
      setCategory(String((rule.condition as { category?: string }).category || ""));
      setMinDiscount(Number((rule.action as { min_discount?: number }).min_discount || 10));
    } else if (rule.rule_type === "return_flow") {
      setKind("return_flow");
      const action = rule.action as { questions?: { text?: string; key?: string }[]; requirements?: Record<string, boolean> };
      setQuestions(
        (action.questions || []).map((question) => ({
          text: question.text || "",
          key: question.key || "",
          requireYes: Boolean(action.requirements?.[question.key || ""])
        }))
      );
    } else if (rule.rule_type === "response_rule") {
      setKind("response_rule");
      setCategory(String((rule.condition as { category?: string }).category || ""));
      setInstruction(String((rule.action as { instruction?: string }).instruction || ""));
    } else if (rule.rule_type === "required_questions") {
      setKind("required_questions");
      setCategory(String((rule.condition as { category?: string }).category || ""));
      const action = rule.action as { questions?: { text?: string; key?: string }[] };
      setQuestions((action.questions || []).map((question) => ({
        text: question.text || "",
        key: question.key || "",
        requireYes: false
      })));
    } else {
      setKind("brand_priority");
      setCategory(String((rule.condition as { category?: string }).category || ""));
      setBrand(String((rule.action as { brand?: string }).brand || ""));
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function detail(rule: AreaRule) {
    if (rule.rule_type === "brand_priority") {
      return `${String((rule.condition as { category?: string }).category || "")} → ${String((rule.action as { brand?: string }).brand || "")}`;
    }
    if (rule.rule_type === "promotion_priority") {
      return `${String((rule.condition as { category?: string }).category || "")} → desde ${String((rule.action as { min_discount?: number }).min_discount || 0)}% de descuento`;
    }
    if (rule.rule_type === "return_flow") {
      const questions = (rule.action as { questions?: unknown[] }).questions || [];
      return `${questions.length} preguntas`;
    }
    if (rule.rule_type === "response_rule") {
      return String((rule.action as { instruction?: string }).instruction || "");
    }
    if (rule.rule_type === "required_questions") {
      const questions = (rule.action as { questions?: unknown[] }).questions || [];
      return `${questions.length} preguntas obligatorias`;
    }
    return JSON.stringify(rule.action);
  }

  const areasToShow = useMemo(() => areas || AREAS, [areas]);

  return (
    <>
      <AreaHeader title={t("Reglas por área")} subtitle={canChangeArea ? "Administración" : area} onLogout={onLogout} />
      <main className="mx-auto max-w-[1100px] p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">{t("Reglas del bot")}</h1>
            <p className="text-sm text-slate-500">{t("Cargá instrucciones sin escribir JSON.")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/occasions" className="rounded-lg border border-[#ffb3bd]/50 bg-white px-3 py-2 text-xs font-semibold text-[#e9082a] hover:bg-[#ffffff]">{t("Ocasiones y campañas")}</Link>
            {canChangeArea && (
              <label className="text-sm text-slate-600">{t("Área")}<select className="ml-2 rounded-lg border border-slate-300 px-3 py-2" value={selectedArea} onChange={(event) => setSelectedArea(event.target.value)}>
                  {areasToShow.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            )}
          </div>
        </div>
        <div className="mb-3 rounded-xl border border-[#ffb3bd]/40 bg-[#f9fafb] px-4 py-3 text-xs text-[#4b5563]">
          <strong className="text-[#111111]">{t("¿Para qué sirve?")}</strong> Acá definís cómo debe responder el bot en tu área:
          qué marca priorizar, qué promociones destacar, cómo manejar devoluciones o qué indicaciones debe seguir.
          Las reglas publicadas se aplican antes de la respuesta final.
        </div>
        {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <Card className="mb-4 border-[#ffb3bd]/40 bg-[#ffffff] p-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-sm font-bold text-[#111111]">{t("Probar una consulta antes de publicar")}</h2>
              <p className="text-xs text-[#4b5563]">{t("Mirá qué productos y reglas se aplicarían, sin crear una conversación.")}</p>
            </div>
            <span className="rounded-full bg-[#f3f4f6] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[#6b7280]">{t("Simulador")}</span>
          </div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <Input
              value={simQuery}
              onChange={(event) => setSimQuery(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void simulate(); }}
              placeholder={t("Ej: televisor 50 pulgadas, heladera no frost...")}
              className="border-[#e5e7eb]"
            />
            <Button onClick={() => void simulate()} disabled={simBusy || !simQuery.trim()}>
              {simBusy ? t("Simulando…") : t("Simular")}
            </Button>
          </div>
          {simulation && (
            <div className="mt-4 rounded-xl border border-[#f3f4f6] bg-white p-3">
              {!simulation.ok ? (
                <p className="text-sm text-red-700">{simulation.detail}</p>
              ) : (
                <>
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-[#4b5563]">
                    <span className="font-semibold text-[#111111]">{simulation.products.length} producto(s)</span>
                    <span>·</span>
                    <span>{simulation.rules.length} regla(s) aplicada(s)</span>
                    <span>·</span>
                    <span>área {simulation.area}</span>
                  </div>
                  {simulation.prompt_text && (
                  <div className="mt-2 rounded-xl border border-[#e5e7eb] bg-white px-3 py-2">
                    <div className="text-[10px] font-bold uppercase tracking-wide text-[#6b7280]">{t("Lo que el bot lee")}</div>
                    <pre className="mt-1 whitespace-pre-wrap text-[11px] text-[#1f2937]">{simulation.prompt_text}</pre>
                  </div>
                )}
                {simulation.rules.length > 0 && (
                    <div className="mb-3 flex flex-wrap gap-1">
                      {simulation.rules.map((rule) => (
                        <Badge key={rule.id} tone="amber">{rule.name}</Badge>
                      ))}
                    </div>
                  )}
                  <div className="space-y-2">
                    {simulation.products.map((product) => (
                      <div key={product.sku} className="flex items-start justify-between gap-3 rounded-lg border border-[#f3f4f6] px-3 py-2">
                        <div>
                          <div className="text-sm font-semibold text-[#111111]">{product.name}</div>
                          <div className="text-[11px] text-[#6b7280]">
                            {product.brand || "Sin marca"} · {product.category || "Sin categoría"} · SKU {product.sku}
                          </div>
                        </div>
                        <div className="shrink-0 text-right">
                          <div className="text-sm font-semibold text-[#111111]">Bs {product.promo_price.toFixed(2)}</div>
                          {product.promo_discount_percent > 0 && (
                            <div className="text-[10px] font-semibold text-emerald-700">-{product.promo_discount_percent}%</div>
                          )}
                          <div className="text-[10px] text-[#6b7280]">{product.available ? t("Disponible") : t("Sin stock")}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                  {simulation.note && <p className="mt-2 text-[10px] text-[#9ca3af]">{simulation.note}</p>}
                </>
              )}
            </div>
          )}
        </Card>
        <Card className="mb-4 p-4">
          <h2 className="mb-3 text-sm font-bold text-slate-900">{editing ? t("Editar regla") : t("Nueva regla")}</h2>
          <label className="mb-1 block text-xs font-semibold text-slate-600">{t("¿Qué querés hacer?")}</label>
          <select className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="brand_priority">{t("Priorizar una marca cuando pregunten por una categoría")}</option>
            <option value="promotion_priority">{t("Priorizar productos en promoción con stock")}</option>
            <option value="return_flow">{t("Crear un flujo de preguntas para devoluciones")}</option>
            <option value="response_rule">{t("Agregar una indicación de respuesta para un tema")}</option>
            <option value="required_questions">{t("Definir preguntas obligatorias para una categoría")}</option>
          </select>
          <Hint>
            {kind === "brand_priority" && t("Ordena las marcas de una categoría: la elegida aparece primero. No cambia precios ni stock.")}
            {kind === "promotion_priority" && t("Destaca los productos de una categoría cuyo descuento de VTEX alcanza el mínimo. No crea descuentos.")}
            {kind === "return_flow" && t("Define las preguntas que el bot hace, en orden, para gestionar una devolución.")}
            {kind === "response_rule" && t("Agrega una indicación que el bot debe respetar al hablar de ese tema.")}
            {kind === "required_questions" && t("El bot pregunta esto antes de cerrar la venta de esa categoría.")}
          </Hint>
          <label className="mb-1 block text-xs font-semibold text-slate-600">{t("Nombre")}</label>
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("Ej: Priorizar LG en heladeras")} />
          <Hint>{t("Solo para identificarla en la lista; el cliente no la ve.")}</Hint>
          {kind === "brand_priority" ? (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className="text-xs font-semibold text-slate-600">{t("Categoría")}<Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder={t("heladera")} />
                <Hint>{t("Escribila como figura en el catálogo (ej: Heladeras). Se aplica a las búsquedas de esa categoría.")}</Hint>
              </label>
              <label className="text-xs font-semibold text-slate-600">{t("Marca")}<Input className="mt-1" value={brand} onChange={(event) => setBrand(event.target.value)} placeholder="LG" />
                <Hint>{t("Esta marca se muestra antes que las demás dentro de la categoría.")}</Hint>
              </label>
              <div className="md:col-span-2">
                <Example title={t("Ejemplo: Heladeras con LG primero")}>
                  <div>{t("Cliente: \"busco una heladera\". El bot muestra primero las LG con stock y después el resto de las marcas, sin ocultar ninguna.")}</div>
                  <div>{t("Los precios son los del catálogo: la regla no aplica descuentos.")}</div>
                </Example>
              </div>
            </div>
          ) : kind === "promotion_priority" ? (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className="text-xs font-semibold text-slate-600">{t("Categoría")}<Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder={t("colchones, pintura, herramientas")} />
                <Hint>{t("Se evalúa por la categoría del producto: funciona aunque el cliente busque \"taladro\" y no \"herramientas\".")}</Hint>
              </label>
              <label className="text-xs font-semibold text-slate-600">{t("Descuento mínimo (%)")}<Input className="mt-1" type="number" min={0} max={100} value={minDiscount} onChange={(event) => setMinDiscount(Number(event.target.value))} />
                <Hint>{t("Umbral para destacar. Si el descuento real de VTEX es menor, el producto no se prioriza. No modifica precios ni crea descuentos.")}</Hint>
              </label>
              <div className="md:col-span-2">
                <Example title={t("Ejemplo con esta regla (Herramientas, mínimo 5%)")}>
                  <div>{t("Cliente: \"busco un taladro\". El bot busca en la categoría y ordena así:")}</div>
                  <ul className="list-disc pl-4">
                    <li>{t("Taladro con 46% de descuento y stock → primero (cumple el mínimo).")}</li>
                    <li>{t("Taladro con 19% → también primero, detrás del de mayor descuento.")}</li>
                    <li>{t("Taladro con 3% → después de los que cumplen, aunque su nombre coincida mejor.")}</li>
                    <li>{t("Taladro sin promoción → al final.")}</li>
                  </ul>
                  <div>{t("El precio y el porcentaje son los de VTEX: la regla solo cambia el orden y lo que el bot destaca.")}</div>
                </Example>
              </div>
            </div>
          ) : kind === "response_rule" ? (
            <div className="mt-3 space-y-3">
              <label className="block text-xs font-semibold text-slate-600">{t("Categoría o tema (opcional)")}<Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder={t("Ej: heladera, envíos, promociones")} />
                <Hint>{t("Si la dejás vacía, la indicación se aplica a cualquier consulta.")}</Hint>
              </label>
              <label className="block text-xs font-semibold text-slate-600">{t("¿Qué debe decir o tener en cuenta el bot?")}<Textarea className="mt-1" rows={4} value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Ej: Para envíos, informar entrega en 24 horas y retiro en tienda; no inventar costos." />
                <Hint>{t("Se agrega como indicación al bot. No reemplaza los datos del catálogo: precios y stock los sigue tomando de VTEX.")}</Hint>
              </label>
              <Example title={t("Ejemplo: indicación para envíos")}>
                <div>{t("Cliente: \"¿hacen envíos a Santa Cruz?\". El bot responde con la indicación: entrega en 24 h y retiro en tienda, sin inventar costos de envío.")}</div>
                <div>{t("Si el dato no está publicado, ofrece derivar con un asesor en lugar de inventarlo.")}</div>
              </Example>
            </div>
          ) : (
            <div className="mt-3 space-y-2">
              {kind === "required_questions" && (
                <label className="block text-xs font-semibold text-slate-600">{t("Categoría o tema (opcional)")}<Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder={t("Ej: heladera")} />
                  <Hint>{t("Si la dejás vacía, la regla aplica a todas las categorías.")}</Hint>
                </label>
              )}
              {questions.map((question, index) => (
                <div key={index} className="rounded-xl border border-slate-200 p-3">
                  <div className="grid gap-2 md:grid-cols-2">
                    <Input value={question.text} placeholder={`Pregunta ${index + 1}`} onChange={(event) => setQuestions(questions.map((item, i) => i === index ? { ...item, text: event.target.value } : item))} />
                    <Input value={question.key} placeholder={t("clave (opcional)")} onChange={(event) => setQuestions(questions.map((item, i) => i === index ? { ...item, key: event.target.value } : item))} />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    {kind === "return_flow" ? (
                      <label className="flex items-center gap-2 text-xs text-slate-600">
                        <input type="checkbox" checked={question.requireYes} onChange={(event) => setQuestions(questions.map((item, i) => i === index ? { ...item, requireYes: event.target.checked } : item))} />{t("Debe responder Sí")}</label>
                    ) : <span />}
                    <Button variant="ghost" size="sm" onClick={() => setQuestions(questions.filter((_, i) => i !== index))}>{t("Quitar")}</Button>
                  </div>
                </div>
              ))}
              <Button variant="secondary" size="sm" onClick={() => setQuestions([...questions, { text: "", key: "", requireYes: kind === "return_flow" }])}>+ Agregar pregunta</Button>
              <Example title={kind === "return_flow" ? t("Ejemplo: devolución de una licuadora") : t("Ejemplo: preguntas antes de vender una heladera")}>
                {kind === "return_flow" ? (
                  <div>{t("Preguntas en orden: \"¿Cuándo la compraste?\" → \"¿Está sin uso?\" → \"¿Tenés la factura?\". El bot las hace una por una antes de derivar el caso.")}</div>
                ) : (
                  <div>{t("El bot pregunta \"¿Cuántos litros necesitás?\" y \"¿Tenés 1,80 m de espacio?\" antes de cerrar la venta de una heladera.")}</div>
                )}
                <div>{t("Si el cliente ya respondió algo, no lo vuelve a preguntar.")}</div>
              </Example>
            </div>
          )}
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-xs font-semibold text-slate-600">{t("Prioridad")}<Input className="mt-1" type="number" value={priority} onChange={(event) => setPriority(Number(event.target.value))} />
              <Hint>{t("Si dos reglas del mismo tipo aplican, gana la de número mayor.")}</Hint>
            </label>
            <label className="text-xs font-semibold text-slate-600">{t("Estado")}<select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="draft">{t("Borrador")}</option>
                <option value="published">{t("Publicado")}</option>
              </select>
              <Hint>{t("Borrador no se aplica. Publicado empieza a usarse en la próxima respuesta.")}</Hint>
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <Button onClick={save}>{t("Guardar")}</Button>
            <Button variant="ghost" onClick={reset}>{t("Limpiar")}</Button>
          </div>
        </Card>
        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-bold text-slate-900">{t("Reglas cargadas")}</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-2">{t("Nombre")}</th><th className="px-3 py-2">{t("Tipo")}</th><th className="px-3 py-2">{t("Detalle")}</th><th className="px-3 py-2">{t("Estado")}</th><th className="px-3 py-2" /></tr>
              </thead>
              <tbody>
                {rules.length ? rules.map((rule) => (
                  <tr key={rule.id} className="border-t border-slate-100">
                    <td className="px-4 py-2 font-semibold text-slate-800">{rule.name}</td>
                    <td className="px-3 py-2 text-xs">{t(TIPO_REGLA[rule.rule_type] || rule.rule_type)}</td>
                    <td className="px-3 py-2 text-xs text-slate-600">{detail(rule)}</td>
                    <td className="px-3 py-2"><Badge tone={rule.status === "published" ? "green" : "amber"}>{rule.status}</Badge></td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        <Button variant="ghost" size="sm" onClick={() => edit(rule)}>{t("Editar")}</Button>
                        <Button variant="ghost" size="sm" onClick={() => history(rule)}>{t("Historial")}</Button>
                        {rule.status !== "published" && <Button variant="secondary" size="sm" onClick={() => publish(rule.id)}>{t("Publicar")}</Button>}
                        <Button variant="danger" size="sm" onClick={() => remove(rule.id)}>{t("Eliminar")}</Button>
                      </div>
                    </td>
                  </tr>
                )) : <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">{t("Sin reglas cargadas.")}</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
        {versionsFor && (
          <Card className="mt-4 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-slate-900">Historial · {versionsFor.name}</h3>
                <p className="text-xs text-slate-500">{t("Cada cambio guarda una versión restaurable.")}</p>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setVersionsFor(null)}>{t("Cerrar")}</Button>
            </div>
            <div className="space-y-2">
              {versions.length ? versions.map((item) => (
                <div key={item.version} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm">
                  <span className="font-semibold">Versión {item.version}</span>
                  <span className="text-xs text-slate-500">{item.changed_by} · {item.created_at ? new Date(item.created_at).toLocaleString("es-BO") : ""}</span>
                  <Button variant="secondary" size="sm" className="ml-auto" onClick={() => rollback(versionsFor, item.version)}>{t("Restaurar")}</Button>
                </div>
              )) : <p className="text-sm text-slate-500">{t("Sin versiones.")}</p>}
            </div>
          </Card>
        )}
      </main>
    </>
  );
}

export function AreaRulesPage({ user, onLogout }: { user: AreaUser; onLogout: () => void }) {
  return <RuleBuilder base="/areas/rules" area={user.area} onLogout={onLogout} />;
}

export function AdminRulesPage({ onLogout }: { onLogout: () => void }) {
  return <RuleBuilder base="/admin/area-rules" area="ecommerce" canChangeArea onLogout={onLogout} />;
}

export function AdminCenter({ me, onLogout }: { me: Advisor; onLogout: () => void }) {
  const [users, setUsers] = useState<{ id: string; username: string; display_name: string; area: string; active: boolean }[]>([]);
  const [form, setForm] = useState({ username: "", password: "", display_name: "", area: "ecommerce" });
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const data = await api<{ users: typeof users }>("/admin/area-users");
      setUsers(data.users || []);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudieron cargar los usuarios");
    }
  };

  useEffect(() => { void load(); }, []);

  async function create() {
    try {
      await api("/admin/area-users", { method: "POST", body: JSON.stringify(form) });
      setForm({ username: "", password: "", display_name: "", area: "ecommerce" });
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo crear");
    }
  }

  async function patch(id: string, body: Record<string, unknown>) {
    try {
      await api(`/admin/area-users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo actualizar");
    }
  }

  function resetPassword(id: string) {
    const password = window.prompt("Nueva contraseña (mínimo 8 caracteres):");
    if (password) void patch(id, { password });
  }

  return (
    <>
      <AreaHeader title={t("Centro de administración")} subtitle={me.display_name} onLogout={onLogout} />
      <main className="mx-auto max-w-[1100px] p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">{t("Usuarios de área")}</h1>
            <p className="text-sm text-slate-500">{t("Cada encargado administra solo sus reglas.")}</p>
          </div>
          <div className="flex gap-2">
            <Link to="/overview" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">{t("Operación")}</Link>
            <Link to="/rules" className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white">{t("Administrar reglas")}</Link>
            <Link to="/occasions" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">{t("Ocasiones")}</Link>
          </div>
        </div>
        <div className="mb-4 rounded-xl border border-[#ffb3bd]/40 bg-[#f9fafb] px-4 py-3 text-xs text-[#4b5563]">
          <strong className="text-[#111111]">{t("¿Para qué sirve?")}</strong> Desde acá creás las cuentas de los encargados.
          Cada usuario entra con su contraseña y administra las reglas y ocasiones de su área; no ve las de las demás.
        </div>
        {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <Card className="mb-4 p-4">
          <h2 className="mb-3 text-sm font-bold text-slate-900">{t("Crear usuario de área")}</h2>
          <div className="grid gap-3 md:grid-cols-2">
            <Input placeholder={t("usuario")} value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} />
            <Input placeholder={t("nombre visible")} value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} />
            <Input type="password" placeholder={t("contraseña")} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
            <select className="rounded-lg border border-slate-300 px-3 py-2" value={form.area} onChange={(event) => setForm({ ...form, area: event.target.value })}>
              {AREAS.map((area) => <option key={area}>{area}</option>)}
            </select>
          </div>
          <div className="mt-3">
            <Example title={t("Ejemplo: usuario de ecommerce")}>
              <div>{t("Usuario \"jperez\", área \"ecommerce\": solo ve y edita las reglas y ocasiones de ecommerce. No ve las de otras áreas.")}</div>
            </Example>
          </div>
          <div className="mt-3"><Button onClick={create}>{t("Crear usuario")}</Button></div>
        </Card>
        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-bold text-slate-900">{t("Usuarios")}</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-2">{t("Usuario")}</th><th className="px-3 py-2">{t("Nombre")}</th><th className="px-3 py-2">{t("Área")}</th><th className="px-3 py-2">{t("Estado")}</th><th className="px-3 py-2">{t("Acciones")}</th></tr></thead>
              <tbody>
                {users.length ? users.map((user) => (
                  <tr key={user.id} className="border-t border-slate-100">
                    <td className="px-4 py-2 font-semibold">{user.username}</td>
                    <td className="px-3 py-2">{user.display_name}</td>
                    <td className="px-3 py-2">{user.area}</td>
                    <td className="px-3 py-2"><Badge tone={user.active ? "green" : "red"}>{user.active ? t("activo") : t("inactivo")}</Badge></td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        <Button variant="ghost" size="sm" onClick={() => patch(user.id, { active: !user.active })}>{user.active ? t("Desactivar") : t("Activar")}</Button>
                        <Button variant="secondary" size="sm" onClick={() => resetPassword(user.id)}>{t("Resetear clave")}</Button>
                      </div>
                    </td>
                  </tr>
                )) : <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">{t("Sin usuarios.")}</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      </main>
    </>
  );
}
