import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { AreaHeader } from "./areas";
import { Badge, Button, Card, Input } from "./ui";
import { t, useI18n } from "./i18n";

type Overview = {
  generated_at: string;
  overall: "ok" | "attention" | "critical";
  bot: {
    ok: boolean;
    mode: string;
    public_base_url: string;
    whatsapp_number: string;
    dry_run: boolean;
  };
  api: { ok: boolean; status?: number; detail?: string };
  sync: {
    at: string | null;
    failed: boolean | null;
    file: string | null;
    summary: string;
    task: { available: boolean; last_result: number | null; next_run: string | null };
  };
  counts: Record<string, number>;
  quality: { fallbacks_24h: number; tools: { calls: number; failures: number } };
  funnel: {
    days: number;
    revenue: string;
    steps: {
      step: string;
      label: string;
      contacts: number;
      events: number;
      conversion: number | null;
    }[];
  };
  search_gaps: { query: string; count: number; last_seen: string | null }[];
  qa: {
    hours: number;
    total: number;
    counts: Record<string, number>;
    issues: { kind: string; inbound: string; outbound: string | null; at: string | null }[];
  };
  learning: {
    aprendidas: number;
    pendientes: number;
    top_pendientes: { term: string; misses: number }[];
    top_aprendidas: { term: string; query: string; hits: number }[];
  };
  tokens: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    avg_prompt: number;
    avg_completion: number;
    cache_hit_tokens: number;
    cache_hit_rate: number;
  };
  latency: {
    count: number;
    p50_ms: number;
    p95_ms: number;
    max_ms: number;
    slow: number;
    slow_limit_ms: number;
  };
  alerts: { level: "critical" | "warning"; title: string; detail: string }[];
};

const QA_LABELS: Record<string, string> = {
  tema_delicitado: t("Tema delicado con producto"),
  enojo_con_venta: t("Venta a cliente enojado"),
  producto_sin_pedido: t("Producto sin pedido"),
  frase_prohibida: t("Frase prohibida"),
  sin_respuesta: t("Mensaje sin respuesta")
};

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("es-BO", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`} />
  );
}

function Metric({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-[#e5e7eb] bg-[#ffffff] p-4 shadow-sm">
      <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#e9082a]">{label}</div>
      <div className="mt-1 font-serif text-3xl font-semibold text-[#111111]">{value}</div>
      {hint && <div className="mt-1 text-[11px] text-[#6b7280]">{hint}</div>}
    </div>
  );
}

type ProbeReply = {
  kind: string;
  text: string | null;
  buttons: { title: string }[];
  sections: { rows: { title: string; description?: string }[] }[];
};

type ProbeTrace = string[];

type ProbeEntry = {
  at: string;
  text: string;
  ms: number;
  trace: string[];
  preview: string;
  error: string | null;
};

export function OverviewPage({ onLogout }: { onLogout: () => void }) {
  const { t } = useI18n();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [probe, setProbe] = useState("");
  const [probeReplies, setProbeReplies] = useState<ProbeReply[]>([]);
  const [probeMs, setProbeMs] = useState(0);
  const [probeError, setProbeError] = useState("");
  const [probeTrace, setProbeTrace] = useState<ProbeTrace>([]);
  const [probing, setProbing] = useState(false);
  const [probeHistory, setProbeHistory] = useState<ProbeEntry[]>([]);
  const [pendientes, setPendientes] = useState<
    { id: string; term: string; query: string | null; hits: number; misses: number }[]
  >([]);
  const [editando, setEditando] = useState<Record<string, string>>({});

  async function cargarAprendizaje() {
    try {
      const data = await api<{
        pending: { id: string; term: string; query: string | null; hits: number; misses: number }[];
      }>("/admin/learning");
      setPendientes(data.pending);
    } catch {
      // La revisión no debe romper el tablero.
    }
  }

  async function decidir(id: string, approve: boolean) {
    try {
      await api(`/admin/learning/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ approve, query: editando[id] || undefined })
      });
      await cargarAprendizaje();
    } catch {
      // Sin conexión: se reintenta al recargar.
    }
  }

  async function loadProbeHistory() {
    try {
      const result = await api<{ items: ProbeEntry[] }>("/admin/simulate/history");
      setProbeHistory(result.items || []);
    } catch {
      // el historial es opcional
    }
  }

  useEffect(() => {
    void loadProbeHistory();
  }, []);

  async function runProbe(texto?: string) {
    const message = (texto ?? probe).trim();
    if (!message) return;
    setProbing(true);
    setProbeError("");
    try {
      const result = await api<{ replies: ProbeReply[]; ms: number; trace?: ProbeTrace; error?: string | null }>("/admin/simulate", {
        method: "POST",
        body: JSON.stringify({ text: message })
      });
      setProbeReplies(result.replies || []);
      setProbeMs(result.ms || 0);
      setProbeTrace(result.trace || []);
      if (result.error) setProbeError(result.error);
      void loadProbeHistory();
    } catch (exception) {
      setProbeError(exception instanceof Error ? exception.message : t("No se pudo probar"));
      setProbeReplies([]);
    } finally {
      setProbing(false);
    }
  }

  const load = async () => {
    try {
      const result = await api<Overview>("/admin/overview");
      setData(result);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : t("No se pudo cargar el estado"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const overall = data?.overall || "attention";
  const overallLabel =
    overall === "ok" ? "Operación estable" : overall === "critical" ? "Requiere atención urgente" : "Con advertencias";
  const overallTone =
    overall === "ok" ? "green" : overall === "critical" ? "red" : "amber";

  return (
    <div className="min-h-screen bg-[#f5f6f8] text-[#111111]">
      <AreaHeader title={t("Operación")} subtitle="Estado consolidado del bot" onLogout={onLogout} />
      <main className="mx-auto max-w-[1180px] px-4 py-6 lg:px-6">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-[.28em] text-[#e9082a]">{t("Centro de operación")}</div>
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-[#111111]">{t("¿Cómo está el bot hoy?")}</h1>
            <p className="mt-1 text-sm text-[#4b5563]">
              Una sola vista para revisar datos, sincronización, conversaciones y reglas.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => void load()}>{t("Actualizar")}</Button>
            <Link to="/inbox" className="rounded-lg bg-[#e9082a] px-3 py-2 text-sm font-semibold text-[#ffffff]">{t("Ir a atención")}</Link>
          </div>
        </div>

        {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        <Card className="mb-5 overflow-hidden border-[#e5e7eb] bg-[#ffffff]">
          <div className="flex flex-wrap items-center gap-4 p-5">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#111111] font-serif text-lg font-semibold text-[#a90418]">R</div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-serif text-xl font-semibold text-[#111111]">{overallLabel}</h2>
                <Badge tone={overallTone as "green" | "amber" | "red"}>{overall}</Badge>
              </div>
              <p className="text-xs text-[#6b7280]">Actualizado {formatDate(data?.generated_at)} · refresco automático cada 30 s</p>
            </div>
            <div className="ml-auto text-xs text-[#6b7280]">
              {data?.alerts?.length ? `${data.alerts.length} alerta(s)` : t("Sin alertas activas")}
            </div>
          </div>
          {data?.alerts?.length ? (
            <div className="border-t border-[#f3f4f6] bg-[#fff8ee] px-5 py-3">
              {data.alerts.map((alert, index) => (
                <div key={`${alert.title}-${index}`} className="flex items-start gap-2 py-1 text-xs">
                  <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${alert.level === "critical" ? "bg-red-500" : "bg-amber-500"}`} />
                  <span><strong className="text-[#111111]">{alert.title}:</strong> <span className="text-[#4b5563]">{alert.detail}</span></span>
                </div>
              ))}
            </div>
          ) : null}
        </Card>

        {loading && !data ? <div className="text-sm text-[#4b5563]">{t("Cargando estado…")}</div> : null}

        {data && (
          <>
            <div className="mb-5 grid gap-3 md:grid-cols-3">
              <Card className="border-[#e5e7eb] bg-[#ffffff] p-4">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#e9082a]">{t("Bot WhatsApp")}</div>
                  <StatusDot ok={data.bot.ok} />
                </div>
                <div className="mt-2 text-lg font-semibold text-[#111111]">{data.bot.ok ? "Escuchando" : "Sin respuesta"}</div>
                <div className="mt-1 text-xs text-[#4b5563]">{data.bot.whatsapp_number || "Número no configurado"} · {data.bot.mode}</div>
              </Card>
              <Card className="border-[#e5e7eb] bg-[#ffffff] p-4">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#e9082a]">{t("API de integración")}</div>
                  <StatusDot ok={data.api.ok} />
                </div>
                <div className="mt-2 text-lg font-semibold text-[#111111]">{data.api.ok ? "Disponible" : "No responde"}</div>
                <div className="mt-1 truncate text-xs text-[#4b5563]">{data.api.detail || "Sin detalle"}</div>
              </Card>
              <Card className="border-[#e5e7eb] bg-[#ffffff] p-4">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#e9082a]">{t("Sincronización VTEX")}</div>
                  <StatusDot ok={!data.sync.failed} />
                </div>
                <div className="mt-2 text-lg font-semibold text-[#111111]">{data.sync.failed ? "Con error" : "Al día"}</div>
                <div className="mt-1 text-xs text-[#4b5563]">Última: {formatDate(data.sync.at)}</div>
              </Card>
            </div>

            <Card className="mb-5 border-[#e5e7eb] bg-[#ffffff] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#e9082a]">{t("Aprendizaje de búsquedas")}</div>
                  <p className="text-xs text-[#6b7280]">{t("Lo que el bot no encontraba y ya aprendió. Las pendientes son candidatas para cargar en el catálogo.")}</p>
                </div>
                <div className="flex gap-4 text-xs">
                  <span><strong className="text-[#111111]">{data.learning?.aprendidas ?? 0}</strong> {t("aprendidas")}</span>
                  <span><strong className="text-[#111111]">{data.learning?.pendientes ?? 0}</strong> {t("pendientes")}</span>
                </div>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-[#6b7280]">{t("Búsquedas sin resultado")}</div>
                  {data.learning?.top_pendientes?.length ? (
                    <ul className="mt-1 space-y-1 text-xs text-[#4b5563]">
                      {data.learning.top_pendientes.map((item) => (
                        <li key={item.term} className="flex justify-between gap-2">
                          <span className="truncate">{item.term}</span>
                          <span className="font-semibold text-[#111111]">{item.misses}×</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 text-xs text-[#6b7280]">{t("Sin pendientes.")}</p>
                  )}
                </div>
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-[#6b7280]">{t("Consultas aprendidas")}</div>
                  {data.learning?.top_aprendidas?.length ? (
                    <ul className="mt-1 space-y-1 text-xs text-[#4b5563]">
                      {data.learning.top_aprendidas.map((item) => (
                        <li key={item.term} className="truncate">
                          <span className="text-[#111111]">{item.term}</span> → {item.query}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 text-xs text-[#6b7280]">{t("Todavía no aprendió ninguna.")}</p>
                  )}
                </div>
              </div>
              <div className="mt-4 border-t border-[#e5e7eb] pt-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-[#6b7280]">{t("Pendientes de revisión")}</div>
                {pendientes.length ? (
                  <ul className="mt-2 space-y-2">
                    {pendientes.map((item) => (
                      <li key={item.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-[#e5e7eb] px-2 py-1.5 text-xs">
                        <span className="font-semibold text-[#111111]">{item.term}</span>
                        <span className="text-[#6b7280]">→</span>
                        <input
                          className="min-w-[160px] flex-1 rounded-lg border border-[#e5e7eb] px-2 py-1"
                          defaultValue={item.query ?? ""}
                          onChange={(event) => setEditando((prev) => ({ ...prev, [item.id]: event.target.value }))}
                        />
                        <button onClick={() => void decidir(item.id, true)} className="rounded-lg bg-[#e9082a] px-2 py-1 font-semibold text-white">{t("Aprobar")}</button>
                        <button onClick={() => void decidir(item.id, false)} className="rounded-lg border border-[#e5e7eb] px-2 py-1 font-semibold text-[#4b5563]">{t("Descartar")}</button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-[#6b7280]">{t("Nada para revisar.")}</p>
                )}
              </div>
            </Card>

            <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric label={t("Conversaciones")} value={data.counts.conversations} hint={`${data.counts.contacts} contactos`} />
              <Metric label={t("Mensajes 24 h")} value={data.counts.messages_24h} hint={`${data.counts.active_flows} flujos activos`} />
              <Metric label={t("Handoffs abiertos")} value={data.counts.handoffs_open} hint="Pendientes o en atención" />
              <Metric label={t("Reglas publicadas")} value={data.counts.rules_published} hint={`${data.counts.occasions_published} ocasiones`} />
            </div>

            <Card className="mb-5 border-[#e5e7eb] bg-[#ffffff] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Embudo de venta")}</h3>
                <span className="text-[11px] text-[#6b7280]">
                  Últimos {data.funnel.days} días · {data.funnel.revenue} Bs cobrados
                </span>
              </div>
              <p className="mb-3 text-xs text-[#6b7280]">
                Contactos únicos que llegaron a cada paso. La conversión compara con el paso anterior.
              </p>
              <div className="space-y-1.5">
                {data.funnel.steps.map((row) => {
                  const max = Math.max(...data.funnel.steps.map((item) => item.contacts), 1);
                  const width = Math.round((row.contacts / max) * 100);
                  return (
                    <div key={row.step} className="flex items-center gap-3">
                      <div className="w-40 shrink-0 text-xs text-[#374151]">{row.label}</div>
                      <div className="h-6 flex-1 overflow-hidden rounded-md bg-[#f9fafb]">
                        <div
                          className="flex h-6 items-center justify-end rounded-md bg-[#c99a52] px-2 text-[11px] font-semibold text-white"
                          style={{ width: `${Math.max(width, row.contacts ? 8 : 0)}%` }}
                        >
                          {row.contacts}
                        </div>
                      </div>
                      <div className="w-16 shrink-0 text-right text-[11px] text-[#6b7280]">
                        {row.conversion === null ? "—" : `${row.conversion}%`}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>

            <Card className="mb-5 border-[#e5e7eb] bg-[#ffffff] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Búsquedas sin resultados")}</h3>
                <span className="text-[11px] text-[#6b7280]">
                  Últimos 30 días · {(data.search_gaps ?? []).reduce((total, row) => total + row.count, 0)} casos
                </span>
              </div>
              <p className="mb-3 text-xs text-[#6b7280]">
                Consultas que no encontraron nada: sirven para detectar artículos que faltan o sinónimos por agregar.
              </p>
              {(data.search_gaps ?? []).length === 0 ? (
                <p className="text-sm text-[#6b7280]">{t("Ninguna registrada.")}</p>
              ) : (
                <div className="space-y-1.5">
                  {(data.search_gaps ?? []).slice(0, 8).map((row) => (
                    <div key={row.query} className="flex items-center justify-between border-b border-[#f3f4f6] py-1.5 text-sm">
                      <span className="text-[#111111]">{row.query}</span>
                      <span className="text-[11px] text-[#6b7280]">
                        {row.count}× · {formatDate(row.last_seen)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card className="mb-5 border-[#e5e7eb] bg-[#ffffff] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Consumo del modelo")}</h3>
                <span className={`text-[11px] ${(data.tokens?.cache_hit_rate ?? 0) >= 80 ? "text-emerald-600" : "text-amber-700"}`}>
                  Caché {data.tokens?.cache_hit_rate ?? 0}% · {(data.tokens?.calls ?? 0)} llamadas
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">{t("Entrada / llamada")}</div>
                  <div className="text-xl font-semibold text-[#111111]">{(data.tokens?.avg_prompt ?? 0).toLocaleString("es")}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">{t("Salida / llamada")}</div>
                  <div className="text-xl font-semibold text-[#111111]">{(data.tokens?.avg_completion ?? 0).toLocaleString("es")}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">{t("Cacheado")}</div>
                  <div className="text-xl font-semibold text-emerald-700">{(data.tokens?.cache_hit_tokens ?? 0).toLocaleString("es")}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">{t("Total tokens")}</div>
                  <div className="text-xl font-semibold text-[#111111]">{(data.tokens?.total_tokens ?? 0).toLocaleString("es")}</div>
                </div>
              </div>
            </Card>

            <Card className="mb-5 border-[#e5e7eb] bg-[#ffffff] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Latencia de respuesta")}</h3>
                <span className={`text-[11px] ${(data.latency?.slow ?? 0) > 0 ? "text-amber-700" : "text-emerald-600"}`}>
                  Últimas {data.latency?.count ?? 0} respuestas
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">{t("Mediana")}</div>
                  <div className="text-xl font-semibold text-[#111111]">{((data.latency?.p50_ms ?? 0) / 1000).toFixed(1)} s</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">p95</div>
                  <div className={`text-xl font-semibold ${(data.latency?.p95_ms ?? 0) >= 8000 ? "text-red-600" : "text-[#111111]"}`}>
                    {((data.latency?.p95_ms ?? 0) / 1000).toFixed(1)} s
                  </div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">{t("Máxima")}</div>
                  <div className="text-xl font-semibold text-[#111111]">{((data.latency?.max_ms ?? 0) / 1000).toFixed(1)} s</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-[#6b7280]">{t("Lentas")}</div>
                  <div className={`text-xl font-semibold ${(data.latency?.slow ?? 0) > 0 ? "text-red-600" : "text-emerald-700"}`}>
                    {data.latency?.slow ?? 0}
                  </div>
                  <div className="text-[10px] text-[#6b7280]">≥ {((data.latency?.slow_limit_ms ?? 8000) / 1000).toFixed(0)} s</div>
                </div>
              </div>
            </Card>

            <Card className="mb-5 border-[#e5e7eb] bg-[#ffffff] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Probar el bot")}</h3>
                <span className="text-[11px] text-[#6b7280]">{t("No envía nada ni ensucia las métricas")}</span>
              </div>
              <p className="mb-2 text-xs text-[#6b7280]">
                Escribí como si fueras un cliente y mirá exactamente qué respondería el bot.
              </p>
              <div className="flex flex-wrap gap-2">
                <Input
                  className="min-w-[240px] flex-1 border-[#e5e7eb] bg-white"
                  value={probe}
                  onChange={(event) => setProbe(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void runProbe(); }}
                  placeholder={t("Ej: busco un colchón de 2 plazas")}
                />
                <Button onClick={() => void runProbe()} disabled={probing || !probe.trim()}>
                  {probing ? "Probando…" : "Probar"}
                </Button>
              </div>
              {probeError && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{probeError}</div>}
              {probeReplies.length > 0 && (
                <div className="mt-3 space-y-2">
                  <div className="text-[11px] text-[#6b7280]">
                    Respondió en {(probeMs / 1000).toFixed(1)} s
                    {probeTrace.length > 0 && <> · camino: {probeTrace.join(" → ")}</>}
                  </div>
                  {probeReplies.map((reply, index) => (
                    <div key={index} className="rounded-xl border border-[#e5e7eb] bg-white px-3 py-2 text-sm text-[#111111]">
                      {reply.text && <div className="whitespace-pre-line">{reply.text}</div>}
                      {reply.kind === "image" && <div className="mt-1 text-[11px] text-[#6b7280]">[imagen del producto]</div>}
                      {reply.buttons.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {reply.buttons.map((button) => (
                            <span key={button.title} className="rounded-full bg-[#f3f4f6] px-2 py-0.5 text-[11px] text-[#1f2937]">{button.title}</span>
                          ))}
                        </div>
                      )}
                      {reply.sections.flatMap((section) => section.rows).length > 0 && (
                        <ul className="mt-1 list-disc pl-4 text-[12px] text-[#1f2937]">
                          {reply.sections.flatMap((section) => section.rows).map((row) => (
                            <li key={row.title}>{row.title}{row.description ? ` — ${row.description}` : ""}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {probeHistory.length > 0 && (
                <div className="mt-4 border-t border-[#f3f4f6] pt-3">
                  <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-[#6b7280]">{t("Últimas pruebas")}</div>
                  <div className="space-y-1">
                    {probeHistory.map((item) => (
                      <div key={item.at + item.text} className="flex flex-wrap items-center gap-2 text-[11px] text-[#1f2937]">
                        <span className="text-[#6b7280]">{new Date(item.at).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}</span>
                        <span className="flex-1 truncate">{item.text}</span>
                        <span className="text-[#6b7280]">{(item.ms / 1000).toFixed(1)} s</span>
                        {item.error && <span className="text-red-600">error</span>}
                        <button
                          type="button"
                          className="rounded-full border border-[#e5e7eb] px-2 py-0.5 font-semibold text-[#1f2937] hover:bg-[#f9fafb]"
                          onClick={() => { setProbe(item.text); void runProbe(item.text); }}
                        >{t("Repetir")}</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>

            <Card className="mb-5 border-[#e5e7eb] bg-[#ffffff] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Control de calidad")}</h3>
                <span className={`text-[11px] ${(data.qa?.total ?? 0) > 0 ? "text-red-600" : "text-emerald-600"}`}>
                  Últimas {data.qa?.hours ?? 72} h · {data.qa?.total ?? 0} casos
                </span>
              </div>
              <p className="mb-3 text-xs text-[#6b7280]">
                Conversaciones donde algo pudo salir mal: tema delicado con producto, venta a un cliente enojado, producto sin pedido o mensaje sin respuesta.
              </p>
              {(data.qa?.total ?? 0) === 0 ? (
                <p className="text-sm text-emerald-700">{t("Sin anomalías detectadas.")}</p>
              ) : (
                <>
                  <div className="mb-3 flex flex-wrap gap-2">
                    {Object.entries(data.qa?.counts ?? {}).map(([kind, count]) => (
                      <span key={kind} className="rounded-full bg-[#f9fafb] px-2.5 py-1 text-[11px] text-[#374151]">
                        {QA_LABELS[kind] ?? kind}: <strong>{count}</strong>
                      </span>
                    ))}
                  </div>
                  <div className="space-y-1.5">
                    {(data.qa?.issues ?? []).slice(0, 6).map((issue, index) => (
                      <div key={`${issue.kind}-${index}`} className="border-b border-[#f3f4f6] py-1.5 text-[12px] text-[#374151]">
                        <span className="font-semibold text-[#111111]">{QA_LABELS[issue.kind] ?? issue.kind}</span>
                        <span className="text-[#6b7280]"> · {formatDate(issue.at)}</span>
                        <div className="mt-0.5">Cliente: {issue.inbound || "—"}</div>
                        <div className="text-[11px] text-[#6b7280]">Bot: {issue.outbound || "sin respuesta"}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="border-[#e5e7eb] bg-[#ffffff] p-5">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Calidad de respuesta")}</h3>
                <p className="mb-3 text-xs text-[#6b7280]">{t("Indicadores de las últimas 24 horas.")}</p>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between border-b border-[#f3f4f6] py-2"><span>{t("Fallbacks / aclaraciones")}</span><strong>{data.quality.fallbacks_24h}</strong></div>
                  <div className="flex justify-between border-b border-[#f3f4f6] py-2"><span>{t("Llamadas a herramientas")}</span><strong>{data.quality.tools.calls}</strong></div>
                  <div className="flex justify-between py-2"><span>{t("Errores de herramientas")}</span><strong className={data.quality.tools.failures ? "text-red-600" : ""}>{data.quality.tools.failures}</strong></div>
                </div>
              </Card>

              <Card className="border-[#e5e7eb] bg-[#ffffff] p-5">
                <h3 className="font-serif text-lg font-semibold text-[#111111]">{t("Última sincronización")}</h3>
                <div className="mt-3 space-y-2 text-xs text-[#374151]">
                  <div><span className="font-semibold text-[#111111]">{t("Archivo:")}</span> {data.sync.file || "Sin log"}</div>
                  <div><span className="font-semibold text-[#111111]">{t("Resultado tarea:")}</span> {data.sync.task.last_result ?? "desconocido"}</div>
                  <div><span className="font-semibold text-[#111111]">{t("Próxima:")}</span> {data.sync.task.next_run || "—"}</div>
                  <div className="rounded-lg bg-[#f5f6f8] p-3 text-[11px] leading-relaxed">{data.sync.summary || "Sin resumen disponible."}</div>
                </div>
              </Card>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <Link to="/inbox" className="rounded-lg bg-[#e9082a] px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[#a90418]">{t("Atención al cliente")}</Link>
              <Link to="/rules" className="rounded-lg bg-[#e9082a] px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[#a90418]">{t("Reglas")}</Link>
              <Link to="/occasions" className="rounded-lg bg-[#e9082a] px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[#a90418]">{t("Ocasiones")}</Link>
              <Link to="/admin/center" className="rounded-lg bg-[#e9082a] px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[#a90418]">{t("Usuarios")}</Link>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
