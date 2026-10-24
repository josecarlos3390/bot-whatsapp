import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { AreaHeader } from "./areas";
import { Badge, Button, Card } from "./ui";

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
  alerts: { level: "critical" | "warning"; title: string; detail: string }[];
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
    <div className="rounded-2xl border border-[#e5d4bf] bg-[#fffdf9] p-4 shadow-sm">
      <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#a8792f]">{label}</div>
      <div className="mt-1 font-serif text-3xl font-semibold text-[#3d1a17]">{value}</div>
      {hint && <div className="mt-1 text-[11px] text-[#8b6d59]">{hint}</div>}
    </div>
  );
}

export function OverviewPage({ onLogout }: { onLogout: () => void }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const result = await api<Overview>("/admin/overview");
      setData(result);
      setError("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo cargar el estado");
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
    <div className="min-h-screen bg-[#f7f2eb] text-[#2a1710]">
      <AreaHeader title="Operación" subtitle="Estado consolidado del bot" onLogout={onLogout} />
      <main className="mx-auto max-w-[1180px] px-4 py-6 lg:px-6">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-[.28em] text-[#a8792f]">Centro de operación</div>
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-[#3d1a17]">¿Cómo está el bot hoy?</h1>
            <p className="mt-1 text-sm text-[#765b4b]">
              Una sola vista para revisar datos, sincronización, conversaciones y reglas.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => void load()}>Actualizar</Button>
            <Link to="/inbox" className="rounded-lg bg-[#6b1d2b] px-3 py-2 text-sm font-semibold text-[#fffaf3]">Ir a atención</Link>
          </div>
        </div>

        {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

        <Card className="mb-5 overflow-hidden border-[#e5d4bf] bg-[#fffdf9]">
          <div className="flex flex-wrap items-center gap-4 p-5">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#3d1a17] font-serif text-lg font-semibold text-[#e2bf7d]">R</div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-serif text-xl font-semibold text-[#3d1a17]">{overallLabel}</h2>
                <Badge tone={overallTone as "green" | "amber" | "red"}>{overall}</Badge>
              </div>
              <p className="text-xs text-[#8b6d59]">Actualizado {formatDate(data?.generated_at)} · refresco automático cada 30 s</p>
            </div>
            <div className="ml-auto text-xs text-[#8b6d59]">
              {data?.alerts?.length ? `${data.alerts.length} alerta(s)` : "Sin alertas activas"}
            </div>
          </div>
          {data?.alerts?.length ? (
            <div className="border-t border-[#efe2d2] bg-[#fff8ee] px-5 py-3">
              {data.alerts.map((alert, index) => (
                <div key={`${alert.title}-${index}`} className="flex items-start gap-2 py-1 text-xs">
                  <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${alert.level === "critical" ? "bg-red-500" : "bg-amber-500"}`} />
                  <span><strong className="text-[#3d1a17]">{alert.title}:</strong> <span className="text-[#765b4b]">{alert.detail}</span></span>
                </div>
              ))}
            </div>
          ) : null}
        </Card>

        {loading && !data ? <div className="text-sm text-[#765b4b]">Cargando estado…</div> : null}

        {data && (
          <>
            <div className="mb-5 grid gap-3 md:grid-cols-3">
              <Card className="border-[#e5d4bf] bg-[#fffdf9] p-4">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#a8792f]">Bot WhatsApp</div>
                  <StatusDot ok={data.bot.ok} />
                </div>
                <div className="mt-2 text-lg font-semibold text-[#3d1a17]">{data.bot.ok ? "Escuchando" : "Sin respuesta"}</div>
                <div className="mt-1 text-xs text-[#765b4b]">{data.bot.whatsapp_number || "Número no configurado"} · {data.bot.mode}</div>
              </Card>
              <Card className="border-[#e5d4bf] bg-[#fffdf9] p-4">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#a8792f]">API de integración</div>
                  <StatusDot ok={data.api.ok} />
                </div>
                <div className="mt-2 text-lg font-semibold text-[#3d1a17]">{data.api.ok ? "Disponible" : "No responde"}</div>
                <div className="mt-1 truncate text-xs text-[#765b4b]">{data.api.detail || "Sin detalle"}</div>
              </Card>
              <Card className="border-[#e5d4bf] bg-[#fffdf9] p-4">
                <div className="flex items-center justify-between">
                  <div className="text-[10px] font-bold uppercase tracking-[.2em] text-[#a8792f]">Sincronización VTEX</div>
                  <StatusDot ok={!data.sync.failed} />
                </div>
                <div className="mt-2 text-lg font-semibold text-[#3d1a17]">{data.sync.failed ? "Con error" : "Al día"}</div>
                <div className="mt-1 text-xs text-[#765b4b]">Última: {formatDate(data.sync.at)}</div>
              </Card>
            </div>

            <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric label="Conversaciones" value={data.counts.conversations} hint={`${data.counts.contacts} contactos`} />
              <Metric label="Mensajes 24 h" value={data.counts.messages_24h} hint={`${data.counts.active_flows} flujos activos`} />
              <Metric label="Handoffs abiertos" value={data.counts.handoffs_open} hint="Pendientes o en atención" />
              <Metric label="Reglas publicadas" value={data.counts.rules_published} hint={`${data.counts.occasions_published} ocasiones`} />
            </div>

            <Card className="mb-5 border-[#e5d4bf] bg-[#fffdf9] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#3d1a17]">Embudo de venta</h3>
                <span className="text-[11px] text-[#8b6d59]">
                  Últimos {data.funnel.days} días · {data.funnel.revenue} Bs cobrados
                </span>
              </div>
              <p className="mb-3 text-xs text-[#8b6d59]">
                Contactos únicos que llegaron a cada paso. La conversión compara con el paso anterior.
              </p>
              <div className="space-y-1.5">
                {data.funnel.steps.map((row) => {
                  const max = Math.max(...data.funnel.steps.map((item) => item.contacts), 1);
                  const width = Math.round((row.contacts / max) * 100);
                  return (
                    <div key={row.step} className="flex items-center gap-3">
                      <div className="w-40 shrink-0 text-xs text-[#5d463b]">{row.label}</div>
                      <div className="h-6 flex-1 overflow-hidden rounded-md bg-[#f3ece1]">
                        <div
                          className="flex h-6 items-center justify-end rounded-md bg-[#c99a52] px-2 text-[11px] font-semibold text-white"
                          style={{ width: `${Math.max(width, row.contacts ? 8 : 0)}%` }}
                        >
                          {row.contacts}
                        </div>
                      </div>
                      <div className="w-16 shrink-0 text-right text-[11px] text-[#8b6d59]">
                        {row.conversion === null ? "—" : `${row.conversion}%`}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>

            <Card className="mb-5 border-[#e5d4bf] bg-[#fffdf9] p-5">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-serif text-lg font-semibold text-[#3d1a17]">Búsquedas sin resultados</h3>
                <span className="text-[11px] text-[#8b6d59]">
                  Últimos 30 días · {(data.search_gaps ?? []).reduce((total, row) => total + row.count, 0)} casos
                </span>
              </div>
              <p className="mb-3 text-xs text-[#8b6d59]">
                Consultas que no encontraron nada: sirven para detectar artículos que faltan o sinónimos por agregar.
              </p>
              {(data.search_gaps ?? []).length === 0 ? (
                <p className="text-sm text-[#8b6d59]">Ninguna registrada.</p>
              ) : (
                <div className="space-y-1.5">
                  {(data.search_gaps ?? []).slice(0, 8).map((row) => (
                    <div key={row.query} className="flex items-center justify-between border-b border-[#f1e6d6] py-1.5 text-sm">
                      <span className="text-[#3d1a17]">{row.query}</span>
                      <span className="text-[11px] text-[#8b6d59]">
                        {row.count}× · {formatDate(row.last_seen)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="border-[#e5d4bf] bg-[#fffdf9] p-5">
                <h3 className="font-serif text-lg font-semibold text-[#3d1a17]">Calidad de respuesta</h3>
                <p className="mb-3 text-xs text-[#8b6d59]">Indicadores de las últimas 24 horas.</p>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between border-b border-[#f1e6d6] py-2"><span>Fallbacks / aclaraciones</span><strong>{data.quality.fallbacks_24h}</strong></div>
                  <div className="flex justify-between border-b border-[#f1e6d6] py-2"><span>Llamadas a herramientas</span><strong>{data.quality.tools.calls}</strong></div>
                  <div className="flex justify-between py-2"><span>Errores de herramientas</span><strong className={data.quality.tools.failures ? "text-red-600" : ""}>{data.quality.tools.failures}</strong></div>
                </div>
              </Card>

              <Card className="border-[#e5d4bf] bg-[#fffdf9] p-5">
                <h3 className="font-serif text-lg font-semibold text-[#3d1a17]">Última sincronización</h3>
                <div className="mt-3 space-y-2 text-xs text-[#5d463b]">
                  <div><span className="font-semibold text-[#3d1a17]">Archivo:</span> {data.sync.file || "Sin log"}</div>
                  <div><span className="font-semibold text-[#3d1a17]">Resultado tarea:</span> {data.sync.task.last_result ?? "desconocido"}</div>
                  <div><span className="font-semibold text-[#3d1a17]">Próxima:</span> {data.sync.task.next_run || "—"}</div>
                  <div className="rounded-lg bg-[#f7f2eb] p-3 text-[11px] leading-relaxed">{data.sync.summary || "Sin resumen disponible."}</div>
                </div>
              </Card>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <Link to="/inbox" className="rounded-lg border border-[#d9c3aa] bg-white px-3 py-2 text-sm font-semibold text-[#5b3323]">Atención al cliente</Link>
              <Link to="/rules" className="rounded-lg border border-[#d9c3aa] bg-white px-3 py-2 text-sm font-semibold text-[#5b3323]">Reglas</Link>
              <Link to="/occasions" className="rounded-lg border border-[#d9c3aa] bg-white px-3 py-2 text-sm font-semibold text-[#5b3323]">Ocasiones</Link>
              <Link to="/admin/center" className="rounded-lg border border-[#d9c3aa] bg-white px-3 py-2 text-sm font-semibold text-[#5b3323]">Usuarios</Link>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
