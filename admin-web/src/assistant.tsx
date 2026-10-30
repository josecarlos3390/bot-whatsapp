import { useEffect, useRef, useState } from "react";
import { Bot, Check, Send } from "lucide-react";
import { api } from "./api";

type Mensaje = { role: "user" | "assistant"; content: string };

type Borrador = {
  tipo: string;
  listo: boolean;
  borrador: Record<string, unknown>;
  faltantes: string[];
  preguntas: string[];
  resumen: string;
};

const TIPOS = [
  { valor: "regla", etiqueta: "Regla" },
  { valor: "ocasion", etiqueta: "Ocasión" },
  { valor: "conocimiento", etiqueta: "Artículo" },
];

const EJEMPLOS: Record<string, string> = {
  regla: "quiero una regla que priorice la marca ELECTROLUX cuando pregunten por cocinas",
  ocasion: "creá una ocasión para el Día del Padre con taladros y sets de herramientas",
  conocimiento: "agregá un artículo que explique la garantía de los colchones",
};

export function AssistantPanel({ onCreado }: { onCreado?: () => void }) {
  const [tipo, setTipo] = useState("regla");
  const [texto, setTexto] = useState("");
  const [mensajes, setMensajes] = useState<Mensaje[]>([]);
  const [borrador, setBorrador] = useState<Borrador | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState("");
  const [creado, setCreado] = useState("");
  const fin = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fin.current?.scrollIntoView({ behavior: "smooth" });
  }, [mensajes, borrador]);

  async function enviar() {
    const limpio = texto.trim();
    if (!limpio || cargando) return;
    const nuevos = [...mensajes, { role: "user" as const, content: limpio }];
    setMensajes(nuevos);
    setTexto("");
    setError("");
    setCreado("");
    setCargando(true);
    try {
      const datos = await api<Borrador>("/admin/assistant/chat", {
        method: "POST",
        body: JSON.stringify({ tipo, mensajes: nuevos }),
      });
      setBorrador(datos);
      const respuesta = datos.listo
        ? `${datos.resumen}\n\n¿Confirmás la creación?`
        : [datos.resumen, ...datos.preguntas].filter(Boolean).join("\n\n");
      setMensajes([...nuevos, { role: "assistant", content: respuesta }]);
    } catch (exc) {
      setError("No se pudo interpretar. Probá con otra frase.");
    } finally {
      setCargando(false);
    }
  }

  async function confirmar() {
    if (!borrador) return;
    setCargando(true);
    setError("");
    try {
      const resultado = await api<{ nombre?: string; titulo?: string }>(
        "/admin/assistant/crear",
        {
          method: "POST",
          body: JSON.stringify({ tipo: borrador.tipo, borrador: borrador.borrador }),
        },
      );
      setCreado(resultado.nombre || resultado.titulo || "Creado");
      setMensajes([
        ...mensajes,
        {
          role: "assistant",
          content: `Listo, quedó creado: ${resultado.nombre || resultado.titulo}`,
        },
      ]);
      setBorrador(null);
      onCreado?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "No se pudo crear");
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <header className="mb-3 flex items-center gap-2">
        <Bot size={18} className="text-emerald-400" />
        <h2 className="text-sm font-semibold text-white">Crear conversando</h2>
        <select
          value={tipo}
          onChange={(event) => {
            setTipo(event.target.value);
            setMensajes([]);
            setBorrador(null);
            setCreado("");
          }}
          className="ml-auto rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white"
        >
          {TIPOS.map((opcion) => (
            <option key={opcion.valor} value={opcion.valor}>
              {opcion.etiqueta}
            </option>
          ))}
        </select>
      </header>

      <div className="mb-3 max-h-64 space-y-2 overflow-y-auto rounded-lg bg-slate-950/60 p-3 text-sm">
        {mensajes.length === 0 && (
          <p className="text-slate-400">
            Escribí lo que querés crear. Por ejemplo: «{EJEMPLOS[tipo]}».
          </p>
        )}
        {mensajes.map((mensaje, indice) => (
          <div
            key={indice}
            className={
              mensaje.role === "user"
                ? "rounded-lg bg-emerald-600/15 p-2 text-emerald-100"
                : "whitespace-pre-line rounded-lg bg-slate-800/60 p-2 text-slate-200"
            }
          >
            {mensaje.content}
          </div>
        ))}
        <div ref={fin} />
      </div>

      {borrador && borrador.listo && (
        <div className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-slate-200">
          <div className="mb-1 font-semibold text-emerald-300">Se va a crear</div>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap">
            {JSON.stringify(borrador.borrador, null, 2)}
          </pre>
          <button
            onClick={confirmar}
            disabled={cargando}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            <Check size={14} /> Confirmar y crear
          </button>
        </div>
      )}

      {error && <p className="mb-2 text-sm text-red-300">{error}</p>}
      {creado && (
        <p className="mb-2 text-sm text-emerald-300">Creado: {creado}</p>
      )}

      <div className="flex gap-2">
        <input
          value={texto}
          onChange={(event) => setTexto(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void enviar();
          }}
          placeholder={EJEMPLOS[tipo]}
          className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
        />
        <button
          onClick={enviar}
          disabled={cargando || !texto.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white disabled:opacity-40"
        >
          <Send size={14} /> {cargando ? "…" : "Enviar"}
        </button>
      </div>
    </div>
  );
}
