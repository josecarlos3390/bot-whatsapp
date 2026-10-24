import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { Badge, Button, Card, Input, Textarea } from "./ui";
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
          <div className="text-[10px] font-bold uppercase tracking-[.28em] text-[#ffb3bd]">ROHO Homecenter</div>
          <div className="font-serif text-base font-semibold tracking-tight">{title}</div>
        </div>
        <div className="ml-auto flex items-center gap-3 text-sm text-[#e5e7eb]">
          <span className="hidden rounded-full border border-[#ffb3bd]/20 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-wider sm:inline">{subtitle}</span>
          <button onClick={onLogout} className="rounded-lg border border-[#ffb3bd]/40 bg-white/5 px-3 py-1.5 text-xs font-semibold text-[#fde7ea] transition hover:bg-white/10">
            Salir
          </button>
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
      <AreaHeader title="Reglas por área" subtitle={canChangeArea ? "Administración" : area} onLogout={onLogout} />
      <main className="mx-auto max-w-[1100px] p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Reglas del bot</h1>
            <p className="text-sm text-slate-500">Cargá instrucciones sin escribir JSON.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/occasions" className="rounded-lg border border-[#ffb3bd]/50 bg-white px-3 py-2 text-xs font-semibold text-[#e9082a] hover:bg-[#ffffff]">
              Ocasiones y campañas
            </Link>
            {canChangeArea && (
              <label className="text-sm text-slate-600">
                Área
                <select className="ml-2 rounded-lg border border-slate-300 px-3 py-2" value={selectedArea} onChange={(event) => setSelectedArea(event.target.value)}>
                  {areasToShow.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            )}
          </div>
        </div>
        <div className="mb-3 rounded-xl border border-[#ffb3bd]/40 bg-[#f9fafb] px-4 py-3 text-xs text-[#4b5563]">
          <strong className="text-[#111111]">¿Para qué sirve?</strong> Acá definís cómo debe responder el bot en tu área:
          qué marca priorizar, qué promociones destacar, cómo manejar devoluciones o qué indicaciones debe seguir.
          Las reglas publicadas se aplican antes de la respuesta final.
        </div>
        {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <Card className="mb-4 border-[#ffb3bd]/40 bg-[#ffffff] p-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-sm font-bold text-[#111111]">Probar una consulta antes de publicar</h2>
              <p className="text-xs text-[#4b5563]">Mirá qué productos y reglas se aplicarían, sin crear una conversación.</p>
            </div>
            <span className="rounded-full bg-[#f3f4f6] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[#6b7280]">Simulador</span>
          </div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <Input
              value={simQuery}
              onChange={(event) => setSimQuery(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void simulate(); }}
              placeholder="Ej: televisor 50 pulgadas, heladera no frost..."
              className="border-[#e5e7eb]"
            />
            <Button onClick={() => void simulate()} disabled={simBusy || !simQuery.trim()}>
              {simBusy ? "Simulando…" : "Simular"}
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
                    <div className="text-[10px] font-bold uppercase tracking-wide text-[#6b7280]">Lo que el bot lee</div>
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
                          <div className="text-[10px] text-[#6b7280]">{product.available ? "Disponible" : "Sin stock"}</div>
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
          <h2 className="mb-3 text-sm font-bold text-slate-900">{editing ? "Editar regla" : "Nueva regla"}</h2>
          <label className="mb-1 block text-xs font-semibold text-slate-600">¿Qué querés hacer?</label>
          <select className="mb-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="brand_priority">Priorizar una marca cuando pregunten por una categoría</option>
            <option value="promotion_priority">Priorizar productos en promoción con stock</option>
            <option value="return_flow">Crear un flujo de preguntas para devoluciones</option>
            <option value="response_rule">Agregar una indicación de respuesta para un tema</option>
            <option value="required_questions">Definir preguntas obligatorias para una categoría</option>
          </select>
          <label className="mb-1 block text-xs font-semibold text-slate-600">Nombre</label>
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Ej: Priorizar LG en heladeras" />
          {kind === "brand_priority" ? (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className="text-xs font-semibold text-slate-600">Categoría
                <Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="heladera" />
              </label>
              <label className="text-xs font-semibold text-slate-600">Marca
                <Input className="mt-1" value={brand} onChange={(event) => setBrand(event.target.value)} placeholder="LG" />
              </label>
            </div>
          ) : kind === "promotion_priority" ? (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className="text-xs font-semibold text-slate-600">Categoría
                <Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="colchones, pintura, herramientas" />
              </label>
              <label className="text-xs font-semibold text-slate-600">Descuento mínimo (%)
                <Input className="mt-1" type="number" min={0} max={100} value={minDiscount} onChange={(event) => setMinDiscount(Number(event.target.value))} />
              </label>
            </div>
          ) : kind === "response_rule" ? (
            <div className="mt-3 space-y-3">
              <label className="block text-xs font-semibold text-slate-600">Categoría o tema (opcional)
                <Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Ej: heladera, envíos, promociones" />
              </label>
              <label className="block text-xs font-semibold text-slate-600">¿Qué debe decir o tener en cuenta el bot?
                <Textarea className="mt-1" rows={4} value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Ej: Para envíos, informar entrega en 24 horas y retiro en tienda; no inventar costos." />
              </label>
            </div>
          ) : (
            <div className="mt-3 space-y-2">
              {kind === "required_questions" && (
                <label className="block text-xs font-semibold text-slate-600">Categoría o tema (opcional)
                  <Input className="mt-1" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Ej: heladera" />
                </label>
              )}
              {questions.map((question, index) => (
                <div key={index} className="rounded-xl border border-slate-200 p-3">
                  <div className="grid gap-2 md:grid-cols-2">
                    <Input value={question.text} placeholder={`Pregunta ${index + 1}`} onChange={(event) => setQuestions(questions.map((item, i) => i === index ? { ...item, text: event.target.value } : item))} />
                    <Input value={question.key} placeholder="clave (opcional)" onChange={(event) => setQuestions(questions.map((item, i) => i === index ? { ...item, key: event.target.value } : item))} />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    {kind === "return_flow" ? (
                      <label className="flex items-center gap-2 text-xs text-slate-600">
                        <input type="checkbox" checked={question.requireYes} onChange={(event) => setQuestions(questions.map((item, i) => i === index ? { ...item, requireYes: event.target.checked } : item))} />
                        Debe responder Sí
                      </label>
                    ) : <span />}
                    <Button variant="ghost" size="sm" onClick={() => setQuestions(questions.filter((_, i) => i !== index))}>Quitar</Button>
                  </div>
                </div>
              ))}
              <Button variant="secondary" size="sm" onClick={() => setQuestions([...questions, { text: "", key: "", requireYes: kind === "return_flow" }])}>+ Agregar pregunta</Button>
            </div>
          )}
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-xs font-semibold text-slate-600">Prioridad
              <Input className="mt-1" type="number" value={priority} onChange={(event) => setPriority(Number(event.target.value))} />
            </label>
            <label className="text-xs font-semibold text-slate-600">Estado
              <select className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="draft">Borrador</option>
                <option value="published">Publicado</option>
              </select>
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <Button onClick={save}>Guardar</Button>
            <Button variant="ghost" onClick={reset}>Limpiar</Button>
          </div>
        </Card>
        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-bold text-slate-900">Reglas cargadas</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-2">Nombre</th><th className="px-3 py-2">Tipo</th><th className="px-3 py-2">Detalle</th><th className="px-3 py-2">Estado</th><th className="px-3 py-2" /></tr>
              </thead>
              <tbody>
                {rules.length ? rules.map((rule) => (
                  <tr key={rule.id} className="border-t border-slate-100">
                    <td className="px-4 py-2 font-semibold text-slate-800">{rule.name}</td>
                    <td className="px-3 py-2 text-xs">{rule.rule_type}</td>
                    <td className="px-3 py-2 text-xs text-slate-600">{detail(rule)}</td>
                    <td className="px-3 py-2"><Badge tone={rule.status === "published" ? "green" : "amber"}>{rule.status}</Badge></td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        <Button variant="ghost" size="sm" onClick={() => edit(rule)}>Editar</Button>
                        <Button variant="ghost" size="sm" onClick={() => history(rule)}>Historial</Button>
                        {rule.status !== "published" && <Button variant="secondary" size="sm" onClick={() => publish(rule.id)}>Publicar</Button>}
                        <Button variant="danger" size="sm" onClick={() => remove(rule.id)}>Eliminar</Button>
                      </div>
                    </td>
                  </tr>
                )) : <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Sin reglas cargadas.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
        {versionsFor && (
          <Card className="mt-4 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-slate-900">Historial · {versionsFor.name}</h3>
                <p className="text-xs text-slate-500">Cada cambio guarda una versión restaurable.</p>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setVersionsFor(null)}>Cerrar</Button>
            </div>
            <div className="space-y-2">
              {versions.length ? versions.map((item) => (
                <div key={item.version} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm">
                  <span className="font-semibold">Versión {item.version}</span>
                  <span className="text-xs text-slate-500">{item.changed_by} · {item.created_at ? new Date(item.created_at).toLocaleString("es-BO") : ""}</span>
                  <Button variant="secondary" size="sm" className="ml-auto" onClick={() => rollback(versionsFor, item.version)}>Restaurar</Button>
                </div>
              )) : <p className="text-sm text-slate-500">Sin versiones.</p>}
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
      <AreaHeader title="Centro de administración" subtitle={me.display_name} onLogout={onLogout} />
      <main className="mx-auto max-w-[1100px] p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Usuarios de área</h1>
            <p className="text-sm text-slate-500">Cada encargado administra solo sus reglas.</p>
          </div>
          <div className="flex gap-2">
            <Link to="/overview" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">Operación</Link>
            <Link to="/rules" className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white">Administrar reglas</Link>
            <Link to="/occasions" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">Ocasiones</Link>
          </div>
        </div>
        <div className="mb-4 rounded-xl border border-[#ffb3bd]/40 bg-[#f9fafb] px-4 py-3 text-xs text-[#4b5563]">
          <strong className="text-[#111111]">¿Para qué sirve?</strong> Desde acá creás las cuentas de los encargados.
          Cada usuario entra con su contraseña y administra las reglas y ocasiones de su área; no ve las de las demás.
        </div>
        {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <Card className="mb-4 p-4">
          <h2 className="mb-3 text-sm font-bold text-slate-900">Crear usuario de área</h2>
          <div className="grid gap-3 md:grid-cols-2">
            <Input placeholder="usuario" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} />
            <Input placeholder="nombre visible" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} />
            <Input type="password" placeholder="contraseña" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
            <select className="rounded-lg border border-slate-300 px-3 py-2" value={form.area} onChange={(event) => setForm({ ...form, area: event.target.value })}>
              {AREAS.map((area) => <option key={area}>{area}</option>)}
            </select>
          </div>
          <div className="mt-3"><Button onClick={create}>Crear usuario</Button></div>
        </Card>
        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-bold text-slate-900">Usuarios</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-2">Usuario</th><th className="px-3 py-2">Nombre</th><th className="px-3 py-2">Área</th><th className="px-3 py-2">Estado</th><th className="px-3 py-2">Acciones</th></tr></thead>
              <tbody>
                {users.length ? users.map((user) => (
                  <tr key={user.id} className="border-t border-slate-100">
                    <td className="px-4 py-2 font-semibold">{user.username}</td>
                    <td className="px-3 py-2">{user.display_name}</td>
                    <td className="px-3 py-2">{user.area}</td>
                    <td className="px-3 py-2"><Badge tone={user.active ? "green" : "red"}>{user.active ? "activo" : "inactivo"}</Badge></td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        <Button variant="ghost" size="sm" onClick={() => patch(user.id, { active: !user.active })}>{user.active ? "Desactivar" : "Activar"}</Button>
                        <Button variant="secondary" size="sm" onClick={() => resetPassword(user.id)}>Resetear clave</Button>
                      </div>
                    </td>
                  </tr>
                )) : <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">Sin usuarios.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      </main>
    </>
  );
}
