import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, CheckCircle2, FilePlus2, RefreshCw, Save, Trash2 } from "lucide-react";
import { api } from "./api";

type Article = {
  slug: string;
  title: string;
  status: string;
  tags: string;
  content: string;
  actualizado: string;
};

type Validation = {
  ok: boolean;
  problemas: string[];
  advertencias: string[];
};

const ESTADOS = ["draft", "published", "archived"];

export function KnowledgePage({ onLogout }: { onLogout?: () => void }) {
  const [articulos, setArticulos] = useState<Article[]>([]);
  const [slug, setSlug] = useState("");
  const [titulo, setTitulo] = useState("");
  const [estado, setEstado] = useState("draft");
  const [tags, setTags] = useState("");
  const [contenido, setContenido] = useState("");
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");
  const [validacion, setValidacion] = useState<Validation | null>(null);
  const [guardando, setGuardando] = useState(false);

  async function cargar() {
    try {
      const datos = await api<{ articulos: Article[] }>("/admin/knowledge-base");
      setArticulos(datos.articulos);
    } catch (exc) {
      setError("No se pudo cargar la base de conocimiento");
    }
  }

  useEffect(() => {
    void cargar();
  }, []);

  function abrir(articulo: Article) {
    setSlug(articulo.slug);
    setTitulo(articulo.title);
    setEstado(articulo.status);
    setTags(articulo.tags);
    setContenido(articulo.content);
    setAviso("");
    setError("");
  }

  function nuevo() {
    setSlug("");
    setTitulo("");
    setEstado("draft");
    setTags("");
    setContenido("");
    setAviso("Artículo nuevo: completá el título y guardá");
    setError("");
  }

  async function guardar() {
    setError("");
    setAviso("");
    setGuardando(true);
    try {
      const cuerpo = { title: titulo, status: estado, tags, content: contenido };
      const guardado = slug
        ? await api<Article>(`/admin/knowledge-base/${slug}`, {
            method: "PUT",
            body: JSON.stringify(cuerpo),
          })
        : await api<Article>("/admin/knowledge-base", {
            method: "POST",
            body: JSON.stringify(cuerpo),
          });
      setSlug(guardado.slug);
      setAviso(`Guardado: ${guardado.slug}`);
      await cargar();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  }

  async function archivar() {
    if (!slug) return;
    if (!window.confirm(`¿Archivar «${titulo}»?`)) return;
    try {
      await api(`/admin/knowledge-base/${slug}`, { method: "DELETE" });
      setAviso("Artículo archivado");
      nuevo();
      await cargar();
    } catch (exc) {
      setError("No se pudo archivar");
    }
  }

  async function validar() {
    try {
      const datos = await api<Validation>("/admin/knowledge-base-base/validar", {
        method: "POST",
      });
      setValidacion(datos);
    } catch (exc) {
      setError("No se pudo validar");
    }
  }

  const publicados = useMemo(
    () => articulos.filter((a) => a.status === "published").length,
    [articulos],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <BookOpen className="text-emerald-400" size={22} />
        <h1 className="text-xl font-semibold text-white">Base de conocimiento</h1>
        <span className="rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300">
          {publicados} publicados de {articulos.length}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            onClick={nuevo}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-500"
          >
            <FilePlus2 size={15} /> Nuevo
          </button>
          <button
            onClick={validar}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
          >
            <CheckCircle2 size={15} /> Validar
          </button>
          <button
            onClick={() => void cargar()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </header>

      {validacion && (
        <div
          className={`mb-4 rounded-lg p-3 text-sm ${validacion.ok ? "bg-emerald-500/10 text-emerald-300" : "bg-red-500/10 text-red-300"}`}
        >
          {validacion.ok
            ? "Todos los artículos están bien formados"
            : validacion.problemas.join(" · ")}
          {validacion.advertencias.length > 0 && (
            <div className="mt-1 text-xs text-amber-300">
              {validacion.advertencias.join(" · ")}
            </div>
          )}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[260px_1fr]">
        <aside className="rounded-xl border border-slate-800 bg-slate-900/60 p-2">
          {articulos.map((articulo) => (
            <button
              key={articulo.slug}
              onClick={() => abrir(articulo)}
              className={`mb-1 w-full rounded-lg px-3 py-2 text-left text-sm ${slug === articulo.slug ? "bg-emerald-600/20 text-white" : "text-slate-300 hover:bg-slate-800"}`}
            >
              <div className="truncate">{articulo.title}</div>
              <div className="text-xs text-slate-500">
                {articulo.status} · {articulo.slug}
              </div>
            </button>
          ))}
        </aside>

        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm text-slate-300">
              Título
              <input
                value={titulo}
                onChange={(event) => setTitulo(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
                placeholder="Garantía de heladeras"
              />
            </label>
            <label className="text-sm text-slate-300">
              Estado
              <select
                value={estado}
                onChange={(event) => setEstado(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              >
                {ESTADOS.map((valor) => (
                  <option key={valor} value={valor}>
                    {valor}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="mt-3 block text-sm text-slate-300">
            Etiquetas (separadas por coma)
            <input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              placeholder="garantia, heladera, cambio"
            />
          </label>

          <label className="mt-3 block text-sm text-slate-300">
            Contenido (markdown)
            <textarea
              value={contenido}
              onChange={(event) => setContenido(event.target.value)}
              rows={16}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-white"
              placeholder="## Garantía&#10;&#10;- Cubre 12 meses por falla de fábrica."
            />
          </label>

          {aviso && <p className="mt-2 text-sm text-emerald-300">{aviso}</p>}
          {error && <p className="mt-2 text-sm text-red-300">{error}</p>}

          <div className="mt-4 flex gap-2">
            <button
              onClick={guardar}
              disabled={guardando || !titulo.trim() || !contenido.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-40"
            >
              <Save size={15} /> {guardando ? "Guardando…" : "Guardar"}
            </button>
            {slug && (
              <button
                onClick={archivar}
                className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 px-3 py-2 text-sm text-red-300 hover:bg-red-500/10"
              >
                <Trash2 size={15} /> Archivar
              </button>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
