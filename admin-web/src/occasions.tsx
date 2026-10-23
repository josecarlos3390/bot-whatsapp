import { useEffect, useMemo, useState } from "react";
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
  const [loading, setLoading] = useState(true);

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
      await api(editing ? `${base}/${editing}` : base, {
        method: editing ? "PUT" : "POST",
        body: JSON.stringify(payload)
      });
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
    <div className="min-h-screen bg-[#f7f2eb] text-[#2a1710]">
      <AreaHeader
        title="Ocasiones y campañas"
        subtitle={isAdmin ? "Administración" : `${userArea} · ${areaUser?.display_name || "encargado"}`}
        onLogout={onLogout}
      />
      <main className="mx-auto max-w-[1180px] px-4 py-6 lg:px-6">
        <div className="mb-5 rounded-2xl border border-[#d8b06a]/40 bg-[#fbf3e8] p-4">
          <div className="flex items-start gap-3">
            <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#6b1d2b] text-xs font-bold text-[#fffaf3]">?</div>
            <div>
              <div className="text-sm font-semibold text-[#3d1a17]">¿Para qué sirve esta pantalla?</div>
              <p className="mt-1 text-xs leading-relaxed text-[#765b4b]">
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
            <div className="mb-1 text-[10px] font-bold uppercase tracking-[.28em] text-[#a8792f]">Centro de contenido</div>
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-[#3d1a17]">Campañas que entienden al cliente</h1>
            <p className="mt-1 max-w-2xl text-sm text-[#765b4b]">
              Definí qué debe buscar el bot, qué debe excluir y qué alternativa ofrecer. Publicá para que empiece a usarlo.
            </p>
          </div>
          <div className="flex gap-2">
            {isAdmin && <Button variant="secondary" onClick={seed}>Cargar ejemplos</Button>}
            <Link to="/rules" className="rounded-lg border border-[#d9c3aa] bg-white px-3 py-2 text-sm font-semibold text-[#5b3323] hover:bg-[#fffaf4]">Ver reglas</Link>
          </div>
        </div>

        <div className="mb-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-[#e5d4bf] bg-white/80 p-4 shadow-sm">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#a8792f]">Ocasiones</div>
            <div className="mt-1 text-2xl font-semibold">{occasions.length}</div>
          </div>
          <div className="rounded-2xl border border-[#e5d4bf] bg-white/80 p-4 shadow-sm">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#a8792f]">Publicadas</div>
            <div className="mt-1 text-2xl font-semibold">{published}</div>
          </div>
          <div className="rounded-2xl border border-[#e5d4bf] bg-[#3d1a17] p-4 text-[#f7f2eb] shadow-sm">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#d8b06a]">Regla de oro</div>
            <div className="mt-1 text-sm">Primero EL catálogo. Después la inferencia.</div>
          </div>
        </div>

        {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        <Card className="mb-6 border-[#e5d4bf] bg-[#fffdf9] p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-serif text-xl font-semibold text-[#3d1a17]">{editing ? "Editar ocasión" : "Nueva ocasión"}</h2>
            {editing && <Button variant="ghost" size="sm" onClick={reset}>Cancelar edición</Button>}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-xs font-semibold text-[#765b4b]">Nombre
              <Input className="mt-1 border-[#d9c3aa] bg-white" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Halloween, Navidad, Baby shower..." />
            </label>
            <label className="text-xs font-semibold text-[#765b4b]" title="Área que será dueña de la ocasión y podrá mantenerla.">Área responsable
              {isAdmin ? (
                <select className="mt-1 w-full rounded-lg border border-[#d9c3aa] bg-white px-3 py-2 text-sm" value={form.area} onChange={(event) => setForm({ ...form, area: event.target.value })}>
                  <option value="marketing">Marketing</option>
                  <option value="ecommerce">Ecommerce</option>
                  <option value="general">General</option>
                </select>
              ) : (
                <div className="mt-1 rounded-lg border border-[#e5d4bf] bg-[#f7f2eb] px-3 py-2 text-sm font-medium text-[#5b3323]">{userArea}</div>
              )}
            </label>
            <label className="text-xs font-semibold text-[#765b4b]">Alias del cliente
              <Input className="mt-1 border-[#d9c3aa]" value={form.aliases} onChange={(event) => setForm({ ...form, aliases: event.target.value })} placeholder="halloween, halloweén" />
            </label>
            <label className="text-xs font-semibold text-[#765b4b]">Prioridad
              <Input className="mt-1 border-[#d9c3aa]" type="number" value={form.priority} onChange={(event) => setForm({ ...form, priority: Number(event.target.value) })} />
            </label>
            <label className="text-xs font-semibold text-[#765b4b]">Términos directos
              <Input className="mt-1 border-[#d9c3aa]" value={form.direct} onChange={(event) => setForm({ ...form, direct: event.target.value })} placeholder="disfraz, dulce, calabaza, vela" />
            </label>
            <label className="text-xs font-semibold text-[#765b4b]">Excluir términos
              <Input className="mt-1 border-[#d9c3aa]" value={form.exclude} onChange={(event) => setForm({ ...form, exclude: event.target.value })} placeholder="mueble, silla, navidad" />
            </label>
            <label className="text-xs font-semibold text-[#765b4b]">Excluir categorías
              <Input className="mt-1 border-[#d9c3aa]" value={form.exclude_categories} onChange={(event) => setForm({ ...form, exclude_categories: event.target.value })} placeholder="MUEBLES, PINTURA, HERRAMIENTAS" />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs font-semibold text-[#765b4b]">Desde
                <Input className="mt-1 border-[#d9c3aa]" type="date" value={form.valid_from} onChange={(event) => setForm({ ...form, valid_from: event.target.value })} />
              </label>
              <label className="text-xs font-semibold text-[#765b4b]">Hasta
                <Input className="mt-1 border-[#d9c3aa]" type="date" value={form.valid_to} onChange={(event) => setForm({ ...form, valid_to: event.target.value })} />
              </label>
            </div>
            <label className="text-xs font-semibold text-[#765b4b]">Alternativa natural
              <Input className="mt-1 border-[#d9c3aa]" value={form.bridge_label} onChange={(event) => setForm({ ...form, bridge_label: event.target.value })} placeholder="una noche de película" />
            </label>
            <label className="text-xs font-semibold text-[#765b4b]">Términos de la alternativa
              <Input className="mt-1 border-[#d9c3aa]" value={form.bridge_terms} onChange={(event) => setForm({ ...form, bridge_terms: event.target.value })} placeholder="televisor, tv" />
            </label>
            <label className="text-xs font-semibold text-[#765b4b]">Estado
              <select className="mt-1 w-full rounded-lg border border-[#d9c3aa] bg-white px-3 py-2 text-sm" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
                <option value="draft">Borrador</option>
                <option value="published">Publicada</option>
              </select>
            </label>
          </div>
          <div className="mt-5 flex gap-2">
            <Button className="bg-[#6b1d2b] hover:bg-[#54131f]" onClick={save}>Guardar ocasión</Button>
            <Button variant="ghost" onClick={reset}>Limpiar</Button>
          </div>
        </Card>

        <div className="mb-3 flex items-end justify-between">
          <div>
            <h2 className="font-serif text-xl font-semibold text-[#3d1a17]">Ocasiones cargadas</h2>
            <p className="text-xs text-[#765b4b]">Borradores no se usan. Publicá para que el bot los lea.</p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {loading ? <div className="text-sm text-[#765b4b]">Cargando…</div> : null}
          {!loading && !occasions.length ? <div className="rounded-2xl border border-dashed border-[#d9c3aa] bg-white/60 p-6 text-sm text-[#765b4b]">{isAdmin ? "Todavía no hay ocasiones. Usá “Cargar ejemplos” o creá una." : "Tu área todavía no tiene ocasiones. Creá la primera para que el bot sepa qué buscar."}</div> : null}
          {occasions.map((item) => (
            <Card key={item.id} className="border-[#e5d4bf] bg-[#fffdf9] p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-serif text-lg font-semibold text-[#3d1a17]">{item.name}</h3>
                    <Badge tone={item.status === "published" ? "green" : "amber"}>{item.status}</Badge>
                  </div>
                  <div className="mt-1 text-[11px] uppercase tracking-wide text-[#a8792f]">{item.area} · prioridad {item.priority}</div>
                </div>
                <div className="flex flex-wrap justify-end gap-1">
                  {isAdmin || item.area === userArea ? (
                    <>
                      <Button variant="ghost" size="sm" onClick={() => edit(item)}>Editar</Button>
                      {item.status !== "published" && <Button variant="secondary" size="sm" onClick={() => publish(item.id)}>Publicar</Button>}
                      <Button variant="danger" size="sm" onClick={() => remove(item.id)}>Eliminar</Button>
                    </>
                  ) : (
                    <span className="rounded-full border border-[#e5d4bf] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[#9a7d68]">Solo lectura</span>
                  )}
                </div>
              </div>
              <div className="mt-3 grid gap-2 text-xs text-[#5d463b] sm:grid-cols-2">
                <div><span className="font-semibold text-[#3d1a17]">Directo:</span> {item.direct.join(", ") || "—"}</div>
                <div><span className="font-semibold text-[#3d1a17]">Excluye:</span> {[...item.exclude, ...item.exclude_categories].join(", ") || "—"}</div>
                <div className="sm:col-span-2"><span className="font-semibold text-[#3d1a17]">Alternativa:</span> {item.bridges?.[0] ? `${item.bridges[0].label}: ${item.bridges[0].terms.join(", ")}` : "—"}</div>
              </div>
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}
