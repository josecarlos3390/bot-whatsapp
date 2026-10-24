import { useEffect, useMemo, useState } from "react";
import { t } from "./i18n";
import { Link } from "react-router-dom";
import { api } from "./api";
import { AreaHeader } from "./areas";
import { Badge, Button, Card, Input } from "./ui";
import type { Advisor, AreaUser, Occasion } from "./types";

const EMPTY = {
  name: "",
  aliases: "",
  direct: "",
  exclude: "",
  exclude_categories: "",
  bridge_label: "",
  bridge_terms: "",
  area: "marketing",
  status: "draft",
  priority: 100,
  valid_from: "",
  valid_to: ""
};

function list(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function joined(value: string[] | undefined): string {
  return (value || []).join(", ");
}

export function OccasionsPage({
  onLogout,
  me,
  areaUser
}: {
  onLogout: () => void;
  me?: Advisor | null;
  areaUser?: AreaUser | null;
}) {
  const isAdmin = Boolean(me?.is_admin);
  const base = isAdmin ? "/admin/occasions" : "/areas/occasions";
  const userArea = areaUser?.area || "marketing";
  const [occasions, setOccasions] = useState<Occasion[]>([]);
  const [form, setForm] = useState({ ...EMPTY, area: userArea });
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<{
    detected: { label: string; matched: string | null; direct: string[] } | null;
    would_search: string[];
  } | null>(null);
  const [testing, setTesting] = useState(false);

  async function runTest() {
    if (!testText.trim()) return;
    setTesting(true);
    try {
      const result = await api<{
        detected: { label: string; matched: string | null; direct: string[] } | null;
        would_search: string[];
      }>("/areas/occasions/simulate", {
        method: "POST",
        body: JSON.stringify({ query: testText.trim(), area: userArea })
      });
      setTestResult(result);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo probar");
    } finally {
      setTesting(false);
    }
  }

  const load = async () => {
    try {
      const data = await api<{ occasions: Occasion[] }>(base);
      setOccasions(data.occasions || []);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudieron cargar las ocasiones");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [base]);

  const published = useMemo(
    () => occasions.filter((item) => item.status === "published").length,
    [occasions]
  );

  function reset() {
    setEditing(null);
    setForm({ ...EMPTY });
  }

  async function save() {
    try {
      if (!form.name.trim()) throw new Error("Poné un nombre a la ocasión");
      if (!form.direct.trim() && !form.bridge_terms.trim()) {
        throw new Error("Agregá términos directos o una alternativa");
      }
      const payload = {
        name: form.name.trim(),
        aliases: list(form.aliases),
        direct: list(form.direct),
        exclude: list(form.exclude),
        exclude_categories: list(form.exclude_categories),
        bridges: form.bridge_terms.trim()
          ? [{ label: form.bridge_label.trim() || "alternativa", terms: list(form.bridge_terms) }]
          : [],
        area: isAdmin ? form.area : userArea,
        status: form.status,
        priority: Number(form.priority),
        valid_from: form.valid_from || null,
        valid_to: form.valid_to || null
      };
      const saved = await api<{ warnings?: { alias: string; occasion: string }[] }>(
        editing ? `${base}/${editing}` : base,
        {
          method: editing ? "PUT" : "POST",
          body: JSON.stringify(payload)
        }
      );
      const choques = saved.warnings || [];
      setNotice(
        choques.length
          ? `Ojo: ${choques.map((item) => `"${item.alias}" ya lo usa ${item.occasion}`).join("; ")}.`
          : ""
      );
      reset();
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo guardar");
    }
  }

  function edit(item: Occasion) {
    setEditing(item.id);
    setForm({
      name: item.name,
      aliases: joined(item.aliases),
      direct: joined(item.direct),
      exclude: joined(item.exclude),
      exclude_categories: joined(item.exclude_categories),
      bridge_label: item.bridges?.[0]?.label || "",
      bridge_terms: joined(item.bridges?.[0]?.terms),
      area: item.area,
      status: item.status,
      priority: item.priority,
      valid_from: item.valid_from || "",
      valid_to: item.valid_to || ""
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function publish(id: string) {
    try {
      await api(`${base}/${id}/publish`, { method: "POST" });
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo publicar");
    }
  }

  async function remove(id: string) {
    if (!confirm("¿Eliminar esta ocasión?")) return;
    try {
      await api(`${base}/${id}`, { method: "DELETE" });
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo eliminar");
    }
  }

  async function seed() {
    try {
      await api("/admin/occasions/seed", { method: "POST" });
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudieron cargar los ejemplos");
    }
  }

  return (
    <div className="min-h-screen bg-[#f5f6f8] text-[#111111]">
      <AreaHeader
        title={t("Ocasiones y campañas")}
        subtitle={isAdmin ? "Administración" : `${userArea} · ${areaUser?.display_name || "encargado"}`}
        onLogout={onLogout}
      />
      <main className="mx-auto max-w-[1180px] px-4 py-6 lg:px-6">
        <div className="mb-5 rounded-2xl border border-[#ffb3bd]/40 bg-[#f9fafb] p-4">
          <div className="flex items-start gap-3">
            <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#e9082a] text-xs font-bold text-[#ffffff]">?</div>
            <div>
              <div className="text-sm font-semibold text-[#111111]">{t("¿Para qué sirve esta pantalla?")}</div>
              <p className="mt-1 text-xs leading-relaxed text-[#4b5563]">
                Una ocasión le dice al bot qué buscar cuando el cliente pregunta por algo amplio:
                “Halloween”, “baby shower”, “mudanza”. El bot busca los términos directos en VTEX,
                excluye lo que no corresponde y, si no hay nada, ofrece la alternativa natural.
                Nunca inventa productos ni muestra stock.
              </p>
            </div>
          </div>
        </div>
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-[.28em] text-[#e9082a]">{t("Centro de contenido")}</div>
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-[#111111]">{t("Campañas que entienden al cliente")}</h1>
            <p className="mt-1 max-w-2xl text-sm text-[#4b5563]">
              Definí qué debe buscar el bot, qué debe excluir y qué alternativa ofrecer. Publicá para que empiece a usarlo.
            </p>
          </div>
          <div className="flex gap-2">
            {isAdmin && <Button variant="secondary" onClick={seed}>{t("Cargar ejemplos")}</Button>}
            <Link to="/rules" className="rounded-lg border border-[#e5e7eb] bg-white px-3 py-2 text-sm font-semibold text-[#1f2937] hover:bg-[#fffaf4]">{t("Ver reglas")}</Link>
          </div>
        </div>

        <div className="mb-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-[#e5e7eb] bg-white/80 p-4 shadow-sm">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#e9082a]">{t("Ocasiones")}</div>
            <div className="mt-1 text-2xl font-semibold">{occasions.length}</div>
          </div>
          <div className="rounded-2xl border border-[#e5e7eb] bg-white/80 p-4 shadow-sm">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#e9082a]">{t("Publicadas")}</div>
            <div className="mt-1 text-2xl font-semibold">{published}</div>
          </div>
          <div className="rounded-2xl border border-[#e5e7eb] bg-[#111111] p-4 text-[#f5f6f8] shadow-sm">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#ffb3bd]">{t("Regla de oro")}</div>
            <div className="mt-1 text-sm">{t("Primero EL catálogo. Después la inferencia.")}</div>
          </div>
        </div>

        {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        {notice && <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{notice}</div>}

        <Card className="mb-5 border-[#e5e7eb] bg-white/80 p-4">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-bold text-[#111111]">{t("Probar un mensaje")}</h2>
            <span className="rounded-full bg-[#f3f4f6] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[#6b7280]">{t("Simulador")}</span>
          </div>
          <p className="mb-2 text-xs text-[#4b5563]">
            Escribí lo que diría un cliente y fijate qué ocasión detecta el bot y qué buscaría. No modifica nada.
          </p>
          <div className="flex flex-wrap gap-2">
            <Input
              className="min-w-[240px] flex-1 border-[#e5e7eb] bg-white"
              value={testText}
              onChange={(event) => setTestText(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void runTest(); }}
              placeholder={t("Ej: venden algo para halloween?")}
            />
            <Button onClick={() => void runTest()} disabled={testing || !testText.trim()}>
              {testing ? "Probando…" : "Probar"}
            </Button>
          </div>
          {testResult && (
            <div className="mt-3 rounded-xl border border-[#e5e7eb] bg-[#ffffff] px-3 py-2 text-xs text-[#1f2937]">
              {testResult.detected ? (
                <>
                  <div>{t("Detecta")}<strong>{testResult.detected.label}</strong>
                    {testResult.detected.matched ? <> (coincidió con «{testResult.detected.matched}»)</> : null}.
                  </div>
                  {testResult.would_search.length > 0 && (
                    <div className="mt-1 text-[#6b7280]">
                      Buscaría: {testResult.would_search.join(", ")}
                    </div>
                  )}
                </>
              ) : (
                <div>No detecta ninguna ocasión con ese mensaje. Probá sumar un alias o un término directo.</div>
              )}
            </div>
          )}
        </Card>

        <Card className="mb-6 border-[#e5e7eb] bg-[#ffffff] p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-serif text-xl font-semibold text-[#111111]">{editing ? "Editar ocasión" : "Nueva ocasión"}</h2>
            {editing && <Button variant="ghost" size="sm" onClick={reset}>{t("Cancelar edición")}</Button>}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-xs font-semibold text-[#4b5563]">{t("Nombre")}<Input className="mt-1 border-[#e5e7eb] bg-white" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder={t("Halloween, Navidad, Baby shower...")} />
            </label>
            <label className="text-xs font-semibold text-[#4b5563]" title={t("Área que será dueña de la ocasión y podrá mantenerla.")}>Área responsable
              {isAdmin ? (
                <select className="mt-1 w-full rounded-lg border border-[#e5e7eb] bg-white px-3 py-2 text-sm" value={form.area} onChange={(event) => setForm({ ...form, area: event.target.value })}>
                  <option value="marketing">{t("Marketing")}</option>
                  <option value="ecommerce">{t("Ecommerce")}</option>
                  <option value="general">{t("General")}</option>
                </select>
              ) : (
                <div className="mt-1 rounded-lg border border-[#e5e7eb] bg-[#f5f6f8] px-3 py-2 text-sm font-medium text-[#1f2937]">{userArea}</div>
              )}
            </label>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Alias del cliente")}<Input className="mt-1 border-[#e5e7eb]" value={form.aliases} onChange={(event) => setForm({ ...form, aliases: event.target.value })} placeholder={t("halloween, halloweén")} />
            </label>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Prioridad")}<Input className="mt-1 border-[#e5e7eb]" type="number" value={form.priority} onChange={(event) => setForm({ ...form, priority: Number(event.target.value) })} />
            </label>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Términos directos")}<Input className="mt-1 border-[#e5e7eb]" value={form.direct} onChange={(event) => setForm({ ...form, direct: event.target.value })} placeholder={t("disfraz, dulce, calabaza, vela")} />
            </label>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Excluir términos")}<Input className="mt-1 border-[#e5e7eb]" value={form.exclude} onChange={(event) => setForm({ ...form, exclude: event.target.value })} placeholder={t("mueble, silla, navidad")} />
            </label>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Excluir categorías")}<Input className="mt-1 border-[#e5e7eb]" value={form.exclude_categories} onChange={(event) => setForm({ ...form, exclude_categories: event.target.value })} placeholder={t("MUEBLES, PINTURA, HERRAMIENTAS")} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs font-semibold text-[#4b5563]">{t("Desde")}<Input className="mt-1 border-[#e5e7eb]" type="date" value={form.valid_from} onChange={(event) => setForm({ ...form, valid_from: event.target.value })} />
              </label>
              <label className="text-xs font-semibold text-[#4b5563]">{t("Hasta")}<Input className="mt-1 border-[#e5e7eb]" type="date" value={form.valid_to} onChange={(event) => setForm({ ...form, valid_to: event.target.value })} />
              </label>
            </div>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Alternativa natural")}<Input className="mt-1 border-[#e5e7eb]" value={form.bridge_label} onChange={(event) => setForm({ ...form, bridge_label: event.target.value })} placeholder={t("una noche de película")} />
            </label>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Términos de la alternativa")}<Input className="mt-1 border-[#e5e7eb]" value={form.bridge_terms} onChange={(event) => setForm({ ...form, bridge_terms: event.target.value })} placeholder={t("televisor, tv")} />
            </label>
            <label className="text-xs font-semibold text-[#4b5563]">{t("Estado")}<select className="mt-1 w-full rounded-lg border border-[#e5e7eb] bg-white px-3 py-2 text-sm" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
                <option value="draft">{t("Borrador")}</option>
                <option value="published">{t("Publicada")}</option>
              </select>
            </label>
          </div>
          <div className="mt-5 flex gap-2">
            <Button className="bg-[#e9082a] hover:bg-[#a90418]" onClick={save}>{t("Guardar ocasión")}</Button>
            <Button variant="ghost" onClick={reset}>{t("Limpiar")}</Button>
          </div>
        </Card>

        <div className="mb-3 flex items-end justify-between">
          <div>
            <h2 className="font-serif text-xl font-semibold text-[#111111]">{t("Ocasiones cargadas")}</h2>
            <p className="text-xs text-[#4b5563]">{t("Borradores no se usan. Publicá para que el bot los lea.")}</p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {loading ? <div className="text-sm text-[#4b5563]">{t("Cargando…")}</div> : null}
          {!loading && !occasions.length ? <div className="rounded-2xl border border-dashed border-[#e5e7eb] bg-white/60 p-6 text-sm text-[#4b5563]">{isAdmin ? "Todavía no hay ocasiones. Usá “Cargar ejemplos” o creá una." : "Tu área todavía no tiene ocasiones. Creá la primera para que el bot sepa qué buscar."}</div> : null}
          {occasions.map((item) => (
            <Card key={item.id} className="border-[#e5e7eb] bg-[#ffffff] p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-serif text-lg font-semibold text-[#111111]">{item.name}</h3>
                    <Badge tone={item.status === "published" ? "green" : "amber"}>{item.status}</Badge>
              {item.validity && <span className="text-[11px] text-[#6b7280]">{item.validity}</span>}
                  </div>
                  <div className="mt-1 text-[11px] uppercase tracking-wide text-[#e9082a]">{item.area} · prioridad {item.priority}</div>
                </div>
                <div className="flex flex-wrap justify-end gap-1">
                  {isAdmin || item.area === userArea ? (
                    <>
                      <Button variant="ghost" size="sm" onClick={() => edit(item)}>{t("Editar")}</Button>
                      {item.status !== "published" && <Button variant="secondary" size="sm" onClick={() => publish(item.id)}>{t("Publicar")}</Button>}
                      <Button variant="danger" size="sm" onClick={() => remove(item.id)}>{t("Eliminar")}</Button>
                    </>
                  ) : (
                    <span className="rounded-full border border-[#e5e7eb] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[#9ca3af]">{t("Solo lectura")}</span>
                  )}
                </div>
              </div>
              <div className="mt-3 grid gap-2 text-xs text-[#374151] sm:grid-cols-2">
                <div><span className="font-semibold text-[#111111]">{t("Directo:")}</span> {item.direct.join(", ") || "—"}</div>
                <div><span className="font-semibold text-[#111111]">{t("Excluye:")}</span> {[...item.exclude, ...item.exclude_categories].join(", ") || "—"}</div>
                <div className="sm:col-span-2"><span className="font-semibold text-[#111111]">{t("Alternativa:")}</span> {item.bridges?.[0] ? `${item.bridges[0].label}: ${item.bridges[0].terms.join(", ")}` : "—"}</div>
              </div>
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}
