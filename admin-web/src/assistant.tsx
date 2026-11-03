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
  { valor: "faq", etiqueta: "Pregunta y respuesta" },
];

const EJEMPLOS: Record<string, string> = {
  regla: "quiero priorizar la marca ELECTROLUX cuando pregunten por cocinas",
  ocasion: "creá una ocasión para el Día del Padre con taladros y herramientas",
  conocimiento: "agregá un artículo que explique la garantía de los colchones",
  faq: "¿hacen envíos a domicilio? Sí, entregamos en 24 horas",
};

export function AssistantPanel({
  onCreado,
  tipoInicial = "regla",
  claro = false,
}: {
  onCreado?: () => void;
  tipoInicial?: string;
  claro?: boolean;
}) {
  const [tipo, setTipo] = useState(tipoInicial);
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

  const caja = claro
    ? "rounded-xl border border-slate-300 bg-white p-4"
    : "rounded-xl border border-slate-800 bg-slate-900/60 p-4";
  const titulo = claro ? "text-slate-900" : "text-white";
  const panel = claro ? "bg-slate-50" : "bg-slate-950/60";
  const burbujaBot = claro
    ? "bg-slate-100 text-slate-700"
    : "bg-slate-800/60 text-slate-200";
  const burbujaYo = claro
    ? "bg-emerald-50 text-emerald-900"
    : "bg-emerald-600/15 text-emerald-100";
  const campo = claro
    ? "border-slate-300 bg-white text-slate-900"
    : "border-slate-700 bg-slate-950 text-white";
  const suave = claro ? "text-slate-500" : "text-slate-400";

  async function enviar() {
    const limpio = texto.trim();
    if (!limpio || cargando) return;
    const nuevos: Mensaje[] = [...mensajes, { role: "user", content: limpio }];
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
      setMensajes([
        ...nuevos,
        { role: "assistant", content: respuesta || "Contame un poco más." },
      ]);
    } catch {
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
          body: JSON.stringify({
            tipo: borrador.tipo,
            borrador: borrador.borrador,
          }),
        },
      );
      const nombre = resultado.nombre || resultado.titulo || "Listo";
      setCreado(nombre);
      setMensajes([
        ...mensajes,
        { role: "assistant", content: `Listo, quedó creado: ${nombre}` },
      ]);
      setBorrador(null);
      onCreado?.();
    } catch (excepcion) {
      setError(
        excepcion instanceof Error ? excepcion.message : "No se pudo crear",
      );
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className={caja}>
      <header className="mb-3 flex items-center gap-2">
        <Bot size={18} className="text-emerald-500" />
        <h2 className={`text-sm font-semibold ${titulo}`}>
          Crear conversando
        </h2>
        <select
          value={tipo}
          onChange={(evento) => {
            setTipo(evento.target.value);
            setMensajes([]);
            setBorrador(null);
            setCreado("");
          }}
          className={`ml-auto rounded-lg border px-2 py-1 text-xs ${campo}`}
        >
          {TIPOS.map((opcion) => (
            <option key={opcion.valor} value={opcion.valor}>
              {opcion.etiqueta}
            </option>
          ))}
        </select>
      </header>

      <div
        className={`mb-3 max-h-64 space-y-2 overflow-y-auto rounded-lg p-3 text-sm ${panel}`}
      >
        {mensajes.length === 0 && (
          <p className={suave}>
            Escribí lo que querés crear. Por ejemplo: «{EJEMPLOS[tipo]}».
          </p>
        )}
        {mensajes.map((mensaje, indice) => (
          <div
            key={indice}
            className={`whitespace-pre-line rounded-lg p-2 ${
              mensaje.role === "user" ? burbujaYo : burbujaBot
            }`}
          >
            {mensaje.content}
          </div>
        ))}
        <div ref={fin} />
      </div>

      {borrador && borrador.listo && (
        <div className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
          <div className="mb-1 font-semibold text-emerald-600">
            Se va a crear
          </div>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-[11px]">
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

      {error && <p className="mb-2 text-sm text-red-500">{error}</p>}
      {creado && <p className="mb-2 text-sm text-emerald-600">Creado: {creado}</p>}

      <div className="flex gap-2">
        <input
          value={texto}
          onChange={(evento) => setTexto(evento.target.value)}
          onKeyDown={(evento) => {
            if (evento.key === "Enter") void enviar();
          }}
          placeholder={EJEMPLOS[tipo]}
          className={`flex-1 rounded-lg border px-3 py-2 text-sm ${campo}`}
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
