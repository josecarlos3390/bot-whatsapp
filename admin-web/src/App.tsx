import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppShell,
  Avatar,
  Burger,
  Drawer,
  Group,
  Kbd,
  Modal,
  NavLink,
  Stack,
  Text,
  TextInput,
  UnstyledButton
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate
} from "react-router-dom";
import {
  IconChartBar,
  IconInbox,
  IconLogout,
  IconSearch,
  IconUsers
} from "@tabler/icons-react";
import {
  Bell,
  BarChart3,
  Check,
  Clock,
  Inbox as InboxIcon,
  LogOut,
  PanelRight,
  Paperclip,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  StickyNote,
  Users,
  X
} from "lucide-react";
import { api, onUnauthorized } from "./api";
import { Badge, Button, Card, Dialog, Input, Skeleton, Textarea, cn } from "./ui";
import type { Advisor, AdvisorMetric, Handoff, HandoffDetail } from "./types";

const dateFmt = new Intl.DateTimeFormat("es-BO", {
  hour: "2-digit",
  minute: "2-digit",
  day: "2-digit",
  month: "short"
});

function formatDate(value: string | null) {
  if (!value) return "";
  return dateFmt.format(new Date(value));
}

function StatusBadge({ handoff }: { handoff: Handoff }) {
  const labels: Record<string, string> = {
    pending: "Pendiente",
    taken: "En atención",
    resolved: "Resuelto",
    returned: "Devuelto",
    closed: "Cerrado"
  };
  const tone = handoff.status === "taken" ? "blue" : handoff.status === "resolved" ? "green" : handoff.status === "returned" ? "slate" : "amber";
  return <Badge tone={tone}>{labels[handoff.status] ?? handoff.status}</Badge>;
}

function ToastStack({ toasts }: { toasts: { id: number; text: string }[] }) {
  return (
    <div
      className="fixed right-4 top-20 z-50 flex w-80 flex-col gap-2"
      role="status"
      aria-live="polite"
    >
      {toasts.map((toast) => (
        <div key={toast.id} className="animate-toast rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-xl">
          {toast.text}
        </div>
      ))}
    </div>
  );
}

function loginRedirect(navigate: ReturnType<typeof useNavigate>) {
  navigate("/login", { replace: true });
}

function Login({ onLogin }: { onLogin: (me: Advisor) => void }) {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/advisor/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      const me = await api<Advisor>("/advisor/me");
      onLogin(me);
      navigate("/inbox", { replace: true });
    } catch {
      setError("Usuario o contraseña incorrectos.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-[radial-gradient(circle_at_top,#7f1d1d,#020617)] px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-2xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-red-600 font-black text-white">R</div>
          <div>
            <div className="text-xs font-bold uppercase tracking-[.2em] text-slate-400">ROHO Homecenter</div>
            <h1 className="text-xl font-bold text-slate-900">Consola de asesores</h1>
          </div>
        </div>
        <label htmlFor="advisor-username" className="mb-1 block text-sm font-medium text-slate-600">
          Usuario
        </label>
        <input
          id="advisor-username"
          className="mb-4 w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-600"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          autoFocus
          required
        />
        <label htmlFor="advisor-password" className="mb-1 block text-sm font-medium text-slate-600">
          Contraseña
        </label>
        <input
          id="advisor-password"
          className="mb-2 w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-600"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />
        {error && (
          <p role="alert" className="mb-2 text-sm text-red-600">
            {error}
          </p>
        )}
        <button
          disabled={busy}
          className="mt-3 w-full rounded-lg bg-red-600 px-4 py-2.5 font-semibold text-white hover:bg-red-700 disabled:opacity-50"
        >
          {busy ? "Ingresando…" : "Ingresar"}
        </button>
      </form>
    </div>
  );
}

function Header({
  me,
  duty,
  count,
  onNotify
}: {
  me: Advisor;
  duty: string[];
  count: number;
  onNotify: () => void;
}) {
  const location = useLocation();
  return (
    <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/95 text-white backdrop-blur">
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-3 px-4 py-3 lg:px-6">
        <div className="flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-red-600 text-sm font-black text-white">R</div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[.2em] text-slate-400">ROHO</div>
            <div className="text-sm font-semibold">Consola de asesores</div>
          </div>
        </div>
        <nav className="ml-4 flex items-center gap-1 text-sm">
          <Link
            to="/inbox"
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 ${location.pathname.startsWith("/inbox") ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5"}`}
          >
            <InboxIcon size={15} /> Bandeja
          </Link>
          {me.is_admin && (
            <Link
              to="/agents"
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 ${location.pathname.startsWith("/agents") ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5"}`}
            >
              <Users size={15} /> Agentes
            </Link>
          )}
          {(me.is_admin || me.role === "supervisor") && (
            <Link
              to="/metrics"
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 ${location.pathname.startsWith("/metrics") ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5"}`}
            >
              <BarChart3 size={15} /> Métricas
            </Link>
          )}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span className={`hidden items-center gap-1.5 rounded-full px-3 py-1 text-xs md:inline-flex ${duty.length ? "bg-blue-400/15 text-blue-300" : "bg-red-400/15 text-red-300"}`}>
            <ShieldCheck size={13} />
            {duty.length ? `Guardia: ${duty.join(", ")}` : "Sin guardia"}
          </span>
          <button onClick={onNotify} className="relative rounded-full border border-slate-700 p-2 text-slate-300 hover:bg-slate-800 hover:text-white" title="Notificaciones">
            <Bell size={16} />
            {count > 0 && (
              <span className="absolute -right-2 -top-2 rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">{count}</span>
            )}
          </button>
          <span className="hidden text-slate-300 sm:inline">{me.display_name}</span>
          <a href="/advisor/logout" className="inline-flex items-center gap-1.5 text-slate-400 hover:text-white">
            <LogOut size={14} /> Salir
          </a>
        </div>
      </div>
    </header>
  );
}

function ConsoleShell({
  me,
  children
}: {
  me: Advisor;
  children: React.ReactNode;
}) {
  const [opened, { toggle, close }] = useDisclosure();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const initials = me.display_name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  const links = [
    { to: "/inbox", label: "Bandeja", icon: IconInbox, visible: true },
    { to: "/agents", label: "Agentes", icon: IconUsers, visible: me.is_admin },
    {
      to: "/metrics",
      label: "Métricas",
      icon: IconChartBar,
      visible: me.is_admin || me.role === "supervisor"
    }
  ];

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const commands = [
    ...links
      .filter((item) => item.visible)
      .map((item) => ({
        label: `Ir a ${item.label}`,
        hint: item.to,
        run: () => navigate(item.to)
      })),
    {
      label: "Cerrar sesión",
      hint: "Salir de la consola",
      run: () => {
        window.location.href = "/advisor/logout";
      }
    }
  ].filter((command) =>
    command.label.toLowerCase().includes(paletteQuery.trim().toLowerCase())
  );

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{
        width: 238,
        breakpoint: "sm",
        collapsed: { mobile: !opened }
      }}
      padding={0}
    >
      <AppShell.Header className="border-b border-slate-800 bg-slate-950 text-white">
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              color="white"
              aria-label="Abrir navegación"
            />
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-red-600 text-sm font-black text-white">
              R
            </div>
            <div className="leading-tight">
              <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ letterSpacing: ".16em" }}>
                ROHO
              </Text>
              <Text size="sm" fw={600}>
                Consola de asesores
              </Text>
            </div>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <UnstyledButton
              onClick={() => setPaletteOpen(true)}
              className="hidden items-center gap-2 rounded-lg border border-white/15 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/10 hover:text-white sm:inline-flex"
              aria-label="Abrir comandos"
            >
              <IconSearch size={15} />
              <span>Buscar</span>
              <Kbd size="xs" className="bg-white/10 text-slate-300">
                Ctrl K
              </Kbd>
            </UnstyledButton>
            <Avatar color="red" radius="xl" size="sm">
              {initials || "A"}
            </Avatar>
            <div className="hidden leading-tight sm:block">
              <Text size="sm" fw={600}>
                {me.display_name}
              </Text>
              <Text size="xs" c="dimmed">
                {me.role}
              </Text>
            </div>
            <UnstyledButton
              component="a"
              href="/advisor/logout"
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-slate-400 hover:bg-white/10 hover:text-white"
              aria-label="Cerrar sesión"
            >
              <IconLogout size={16} />
              <span className="hidden sm:inline">Salir</span>
            </UnstyledButton>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" className="border-r border-slate-200 bg-white">
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" px="sm" py="xs" style={{ letterSpacing: ".12em" }}>
          Operación
        </Text>
        {links
          .filter((item) => item.visible)
          .map((item) => {
            const active = location.pathname.startsWith(item.to);
            return (
              <NavLink
                key={item.to}
                component={Link}
                to={item.to}
                label={item.label}
                active={active}
                onClick={close}
                leftSection={<item.icon size={18} stroke={1.7} />}
                styles={{
                  root: { borderRadius: 8, marginBottom: 2 },
                  label: { fontWeight: 600 }
                }}
              />
            );
          })}

        <div className="mt-auto border-t border-slate-100 px-2 pt-3">
          <Text size="xs" c="dimmed">
            ROHO Homecenter · SAP B1
          </Text>
          <Text size="xs" c="dimmed">
            {me.username}
          </Text>
        </div>
      </AppShell.Navbar>

      <AppShell.Main>
        <div className="min-h-[calc(100vh-60px)] bg-[#f4f6f8]">{children}</div>
      </AppShell.Main>

      <Modal
        opened={paletteOpen}
        onClose={() => {
          setPaletteOpen(false);
          setPaletteQuery("");
        }}
        title="Comandos"
        centered
        size="md"
      >
        <TextInput
          autoFocus
          value={paletteQuery}
          onChange={(event) => setPaletteQuery(event.currentTarget.value)}
          placeholder="Buscar una acción…"
          leftSection={<IconSearch size={16} />}
          aria-label="Buscar comando"
        />
        <Stack gap={4} mt="md">
          {commands.length ? (
            commands.map((command) => (
              <UnstyledButton
                key={command.label}
                onClick={() => {
                  command.run();
                  setPaletteOpen(false);
                  setPaletteQuery("");
                }}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100"
              >
                <span className="font-medium text-slate-800">{command.label}</span>
                <span className="text-xs text-slate-400">{command.hint}</span>
              </UnstyledButton>
            ))
          ) : (
            <Text size="sm" c="dimmed" ta="center" py="sm">
              Sin comandos para esa búsqueda.
            </Text>
          )}
        </Stack>
      </Modal>
    </AppShell>
  );
}

function HandoffCard({
  handoff,
  active,
  onClick
}: {
  handoff: Handoff;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full rounded-xl border p-3 text-left transition ${
        active
          ? "border-red-500 bg-white ring-1 ring-red-100"
          : "border-slate-200 bg-white/80 hover:border-blue-300 hover:bg-white"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {handoff.unread && <span className="h-2 w-2 shrink-0 rounded-full bg-red-500" />}
            <span className="truncate font-semibold text-slate-900">{handoff.contact}</span>
          </div>
          <div className="truncate text-xs text-slate-500">{handoff.reason || "Sin motivo"}</div>
        </div>
        <StatusBadge handoff={handoff} />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>{handoff.assigned_to ? `Asignado: ${handoff.assigned_to}` : "Sin asignar"}</span>
        <span className={handoff.overdue ? "font-semibold text-red-600" : ""}>
          {handoff.waiting_minutes} min {handoff.overdue ? "· SLA" : ""}
        </span>
      </div>
    </button>
  );
}

function ContextBox({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-400">{title}</div>
      <div className="text-sm text-slate-700">{children}</div>
    </div>
  );
}

const QUICK_TEMPLATES = [
  "Estoy revisando stock, dame un momento 🙌",
  "Te paso el link de pago 💳",
  "¿Me confirmás la dirección de entrega, por favor?",
  "Ya derivé el caso a logística; te confirmo apenas tenga novedad."
];

const RESOLUTION_CATEGORIES = [
  ["stock", "Stock"],
  ["precio", "Precio"],
  ["pago", "Pago"],
  ["entrega", "Entrega"],
  ["garantia", "Garantía"],
  ["otro", "Otro"]
] as const;

function ContextPanel({ detail }: { detail: HandoffDetail }) {
  return (
    <div className="space-y-2">
      <ContextBox title="Cliente">
        {detail.profile.city || "Sin ciudad"}
        <br />
        {detail.profile.preferred_store || "Sin tienda preferida"}
      </ContextBox>
      <ContextBox title="Carrito">
        {detail.cart ? `${detail.cart.count} ítems · Bs ${detail.cart.total}` : "Vacío"}
      </ContextBox>
      <ContextBox title="Pedidos">
        {detail.orders.length
          ? detail.orders.map((order) => `#${order.number} · ${order.status} · Bs ${order.total}`).join(" | ")
          : "Sin pedidos"}
      </ContextBox>
    </div>
  );
}

function DetailPanel({
  detail,
  onTake,
  onReply,
  onResolve,
  onNote,
  onAttach,
  onTransfer,
  onReturn,
  onReopen,
  onOpenContext
}: {
  detail: HandoffDetail;
  onTake: () => void;
  onReply: (text: string) => Promise<void>;
  onResolve: () => void;
  onNote: (text: string) => Promise<void>;
  onAttach: (file: File, caption: string) => Promise<void>;
  onTransfer: () => void;
  onReturn: () => void;
  onReopen: () => void;
  onOpenContext: () => void;
}) {
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [noteSending, setNoteSending] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail.id, detail.messages.length]);

  async function send() {
    const text = reply.trim();
    if (!text) return;
    setSending(true);
    setError("");
    try {
      await onReply(text);
      setReply("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo enviar.");
    } finally {
      setSending(false);
    }
  }

  async function sendNote() {
    const text = note.trim();
    if (!text) return;
    setNoteSending(true);
    setError("");
    try {
      await onNote(text);
      setNote("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo guardar la nota.");
    } finally {
      setNoteSending(false);
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    setAttaching(true);
    setError("");
    try {
      await onAttach(file, "");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo enviar el archivo.");
    } finally {
      setAttaching(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <section id="handoff-detail" className="flex min-h-[70vh] flex-col rounded-2xl border border-slate-200 bg-white shadow-sm lg:h-[calc(100vh-92px)] lg:min-h-[620px]">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 p-4">
        <div>
          <h2 className="text-lg font-bold text-slate-900">{detail.contact.name || detail.contact.wa_id}</h2>
          <p className="text-xs text-slate-500">
            {detail.contact.phone} · {detail.reason || "Sin motivo"} · {detail.waiting_minutes} min
            {detail.overdue ? " · SLA vencido" : ""}
            {detail.sla_paused ? " · En espera del cliente" : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {detail.can_take && (
            <Button onClick={onTake}>
              <Check size={15} /> Tomar
            </Button>
          )}
          {detail.can_transfer && (
            <Button variant="secondary" size="sm" onClick={onTransfer}>
              Transferir
            </Button>
          )}
          {detail.can_transfer && (
            <Button variant="secondary" size="sm" onClick={onReturn}>
              Devolver al bot
            </Button>
          )}
          {detail.can_resolve && (
            <Button variant="secondary" onClick={onResolve}>
              <Check size={15} /> Resolver
            </Button>
          )}
          {detail.can_reopen && (
            <Button onClick={onReopen}>Reabrir</Button>
          )}
        </div>
      </div>

      {!detail.can_reply && (
        <div className="border-b border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
          {detail.status === "pending"
            ? "Tomá el caso para habilitar la respuesta."
            : `Este caso está siendo atendido por ${detail.assigned_to || "otro asesor"}.`}
        </div>
      )}

      <div className="border-b border-slate-100 px-4 py-2 xl:hidden">
        <Button variant="secondary" size="sm" onClick={onOpenContext}>
          <PanelRight size={15} /> Ver contexto
        </Button>
      </div>

      <details className="border-b border-slate-100 px-4 py-2">
        <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">
          <StickyNote size={14} /> Notas internas ({detail.notes.length})
        </summary>
        <div className="mt-2 space-y-1.5">
          {detail.notes.map((item) => (
            <div key={item.id} className="rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-900">
              {item.text}
              <div className="mt-1 text-[10px] text-blue-700/60">{item.advisor} · {formatDate(item.created_at)}</div>
            </div>
          ))}
          <div className="flex gap-2 pt-1">
            <Input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void sendNote();
                }
              }}
              placeholder="Nota visible solo para el equipo…"
              className="text-xs"
            />
            <Button size="sm" variant="secondary" onClick={sendNote} disabled={noteSending || !note.trim()}>
              Guardar
            </Button>
          </div>
        </div>
      </details>

      <div className="scrollbar-thin min-h-0 flex-1 space-y-3 overflow-y-auto bg-slate-50/60 p-4">
        {detail.messages.map((message, index) => (
          <div key={`${message.created_at}-${index}`} className={`flex ${message.direction === "out" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${message.direction === "out" ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-800"}`}>
              {message.payload?.media?.media_id ? (
                message.type === "image" ? (
                  <a href={`/admin/handoffs/${detail.id}/messages/${message.id}/media`} target="_blank" rel="noreferrer">
                    <img
                      src={`/admin/handoffs/${detail.id}/messages/${message.id}/media`}
                      alt={message.payload.media.filename || "Imagen del cliente"}
                      className="max-h-56 rounded-lg"
                    />
                  </a>
                ) : (
                  <a
                    href={`/admin/handoffs/${detail.id}/messages/${message.id}/media`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 underline"
                  >
                    <Paperclip size={13} /> {message.payload.media.filename || message.text || message.type}
                  </a>
                )
              ) : message.type !== "text" && message.payload?.filename ? (
                <span>📎 {message.payload.filename}</span>
              ) : (
                message.text || `[${message.type}]`
              )}
              <div className={`mt-1 text-[10px] ${message.direction === "out" ? "text-slate-400" : "text-slate-400"}`}>{formatDate(message.created_at)}</div>
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <div className="border-t border-slate-100 p-3">
        {error && <div className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <div className="mb-2 flex gap-1.5 overflow-x-auto pb-1">
          {QUICK_TEMPLATES.map((template) => (
            <button
              key={template}
              onClick={() => setReply(template)}
              disabled={!detail.can_reply}
              className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600 hover:border-blue-400 hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {template.length > 34 ? template.slice(0, 32) + "…" : template}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            accept="image/*,.pdf,.doc,.docx,.xls,.xlsx"
            onChange={(event) => void upload(event.target.files?.[0])}
          />
          <Button
            variant="secondary"
            size="sm"
            className="self-end"
            onClick={() => fileInput.current?.click()}
            disabled={attaching || !detail.can_reply}
            title="Adjuntar imagen o documento"
          >
            <Paperclip size={15} /> {attaching ? "…" : ""}
          </Button>
          <Textarea
            value={reply}
            onChange={(event) => setReply(event.target.value)}
            disabled={!detail.can_reply}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            rows={2}
            placeholder={detail.can_reply ? "Escribí la respuesta… (Enter envía, Shift+Enter salto de línea)" : "Tomá el caso para escribir…"}
            className="min-h-[46px] flex-1 disabled:cursor-not-allowed disabled:bg-slate-100"
          />
          <Button
            onClick={send}
            disabled={sending || !reply.trim() || !detail.can_reply}
            variant="gold"
            className="self-end"
          >
            <Send size={14} /> {sending ? "Enviando…" : "Enviar"}
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400">
          <span>Auditoría:</span>
          {detail.events.length ? detail.events.map((event, index) => (
            <span key={index}>{event.advisor || "sistema"} · {event.action}</span>
          )) : <span>sin eventos</span>}
        </div>
      </div>
    </section>
  );
}

function Inbox({ me }: { me: Advisor }) {
  const navigate = useNavigate();
  const [handoffs, setHandoffs] = useState<Handoff[]>([]);
  const [selected, setSelected] = useState<Handoff | null>(null);
  const [detail, setDetail] = useState<HandoffDetail | null>(null);
  const [duty, setDuty] = useState<string[]>([]);
  const [toasts, setToasts] = useState<{ id: number; text: string }[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "pending" | "taken" | "overdue" | "closed">("all");
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveNote, setResolveNote] = useState("");
  const [resolveCategory, setResolveCategory] = useState("stock");
  const [transferOpen, setTransferOpen] = useState(false);
  const [team, setTeam] = useState<{ display_name: string; username: string }[]>([]);
  const [transferTo, setTransferTo] = useState("");
  const [returnOpen, setReturnOpen] = useState(false);
  const [returnReason, setReturnReason] = useState("El asesor devolvió el caso al bot.");
  const [contextOpen, setContextOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const known = useRef<Set<string> | null>(null);
  const selectedId = selected?.id;

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return handoffs.filter((handoff) => {
      const isOpen = handoff.status === "pending" || handoff.status === "taken";
      if (filter === "closed") {
        if (isOpen) return false;
      } else if (!isOpen) {
        return false;
      }
      if (filter === "overdue" && !handoff.overdue) return false;
      if (filter !== "all" && filter !== "overdue" && filter !== "closed" && handoff.status !== filter) return false;
      if (!needle) return true;
      return `${handoff.contact} ${handoff.wa_id} ${handoff.reason ?? ""}`.toLowerCase().includes(needle);
    });
  }, [handoffs, query, filter]);

  const counts = useMemo(
    () => ({
      all: handoffs.filter((handoff) => handoff.status === "pending" || handoff.status === "taken").length,
      pending: handoffs.filter((handoff) => handoff.status === "pending").length,
      taken: handoffs.filter((handoff) => handoff.status === "taken").length,
      overdue: handoffs.filter((handoff) => handoff.overdue && (handoff.status === "pending" || handoff.status === "taken")).length,
      closed: handoffs.filter((handoff) => handoff.status === "resolved" || handoff.status === "returned").length
    }),
    [handoffs]
  );

  const addToast = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, text }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 6000);
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("Nuevo handoff", { body: text });
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const [data, dutyData] = await Promise.all([
        api<{ handoffs: Handoff[] }>("/admin/handoffs?status=all"),
        api<{ on_duty: { display_name: string }[] }>("/advisor/duty")
      ]);
      const ids = new Set(data.handoffs.map((handoff) => handoff.id));
      if (known.current === null) {
        known.current = ids;
      } else {
        data.handoffs.forEach((handoff) => {
          if (!known.current?.has(handoff.id) && handoff.status === "pending") {
            addToast(`${handoff.contact} pidió un asesor · ${handoff.reason || ""}`);
          }
        });
        known.current = ids;
      }
      setHandoffs(data.handoffs);
      setDuty(dutyData.on_duty.map((advisor) => advisor.display_name));
      setSelected((current) => {
        if (current) return data.handoffs.find((handoff) => handoff.id === current.id) ?? current;
        return data.handoffs[0] ?? null;
      });
      setLoading(false);
    } catch {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    const source = new EventSource("/advisor/events");
    source.addEventListener("refresh", () => void load());
    return () => source.close();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    api<{ handoff: HandoffDetail }>(`/admin/handoffs/${selectedId}`)
      .then((data) => setDetail(data.handoff))
      .catch(() => setDetail(null));
  }, [selectedId, handoffs]);

  useEffect(() => {
    if (!selectedId) return;
    if (!window.matchMedia("(max-width: 1023px)").matches) return;
    const timer = window.setTimeout(() => {
      document
        .getElementById("handoff-detail")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [selectedId]);

  async function take() {
    if (!detail) return;
    try {
      await api(`/admin/handoffs/${detail.id}/take`, { method: "POST" });
      await load();
    } catch (exception) {
      addToast(exception instanceof Error ? exception.message : "No se pudo tomar el caso.");
    }
  }

  async function resolve() {
    if (!detail) return;
    setResolveNote("");
    setResolveCategory("stock");
    setResolveOpen(true);
  }

  async function confirmResolve() {
    if (!detail || !resolveNote.trim()) return;
    try {
      await api(`/admin/handoffs/${detail.id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ text: resolveNote, category: resolveCategory })
      });
      setResolveOpen(false);
      await load();
    } catch (exception) {
      addToast(exception instanceof Error ? exception.message : "No se pudo resolver.");
    }
  }

  async function openTransfer() {
    if (!detail) return;
    const data = await api<{ advisors: { display_name: string; username: string }[] }>("/advisor/team");
    setTeam(data.advisors.filter((advisor) => advisor.display_name !== detail.assigned_to));
    setTransferTo(data.advisors[0]?.display_name ?? "");
    setTransferOpen(true);
  }

  async function confirmTransfer() {
    if (!detail || !transferTo) return;
    try {
      await api(`/admin/handoffs/${detail.id}/transfer`, {
        method: "POST",
        body: JSON.stringify({ to: transferTo })
      });
      setTransferOpen(false);
      await load();
    } catch (exception) {
      addToast(exception instanceof Error ? exception.message : "No se pudo transferir.");
    }
  }

  async function confirmReturn() {
    if (!detail) return;
    try {
      await api(`/admin/handoffs/${detail.id}/return-to-bot`, {
        method: "POST",
        body: JSON.stringify({ reason: returnReason })
      });
      setReturnOpen(false);
      await load();
    } catch (exception) {
      addToast(exception instanceof Error ? exception.message : "No se pudo devolver al bot.");
    }
  }

  async function reopen() {
    if (!detail) return;
    try {
      await api(`/admin/handoffs/${detail.id}/reopen`, { method: "POST" });
      await load();
    } catch (exception) {
      addToast(exception instanceof Error ? exception.message : "No se pudo reabrir.");
    }
  }

  async function reply(text: string) {
    if (!detail) return;
    await api(`/admin/handoffs/${detail.id}/reply`, {
      method: "POST",
      body: JSON.stringify({ text })
    });
    const data = await api<{ handoff: HandoffDetail }>(`/admin/handoffs/${detail.id}`);
    setDetail(data.handoff);
    await load();
  }

  async function note(text: string) {
    if (!detail) return;
    await api(`/admin/handoffs/${detail.id}/notes`, {
      method: "POST",
      body: JSON.stringify({ text })
    });
    const data = await api<{ handoff: HandoffDetail }>(`/admin/handoffs/${detail.id}`);
    setDetail(data.handoff);
  }

  async function attach(file: File, caption: string) {
    if (!detail) return;
    const form = new FormData();
    form.append("file", file);
    form.append("caption", caption);
    const response = await fetch(`/admin/handoffs/${detail.id}/attachment`, {
      method: "POST",
      body: form,
      credentials: "same-origin"
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const data = await api<{ handoff: HandoffDetail }>(`/admin/handoffs/${detail.id}`);
    setDetail(data.handoff);
  }

  function notify() {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }

  return (
    <>
      <ToastStack toasts={toasts} />
      <div className="mx-auto grid max-w-[1600px] gap-4 p-4 xl:grid-cols-[360px_minmax(0,1fr)_300px] xl:p-6">
        <aside className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <div>
              <h1 className="text-lg font-bold text-slate-900">Handoffs abiertos</h1>
              <p className="text-xs text-slate-500">
                Tiempo real + respaldo cada 30 s
              </p>
              <p className={`mt-1 text-[11px] font-semibold ${duty.length ? "text-blue-700" : "text-red-600"}`}>
                {duty.length ? `Guardia: ${duty.join(", ")}` : "Sin guardia"}
              </p>
            </div>
            <button onClick={load} className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold hover:bg-slate-50">
              Actualizar
            </button>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
            <div className="relative mb-2">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Buscar por nombre, número o motivo…"
                aria-label="Buscar handoffs"
                className="pl-9"
              />
            </div>
            <div className="flex gap-1 overflow-x-auto">
              {([
                ["all", "Todos"],
                ["pending", "Pendientes"],
                ["taken", "Tomados"],
                ["overdue", "SLA"],
                ["closed", "Cerrados"]
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setFilter(key)}
                  className={`shrink-0 rounded-lg px-2.5 py-1.5 text-xs font-semibold ${filter === key ? "bg-red-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}
                >
                  {label} <span className={filter === key ? "text-slate-300" : "text-slate-400"}>{counts[key]}</span>
                </button>
              ))}
            </div>
          </div>
          {loading && (
            <div className="space-y-2">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </div>
          )}
          {!loading && !filtered.length && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              <InboxIcon className="mx-auto mb-2 text-slate-300" size={28} />
              {handoffs.length ? "No hay casos con ese filtro." : "No hay handoffs abiertos"}
            </div>
          )}
          {filtered.map((handoff) => (
            <HandoffCard
              key={handoff.id}
              handoff={handoff}
              active={selected?.id === handoff.id}
              onClick={() => setSelected(handoff)}
            />
          ))}
        </aside>
        {detail ? (
          <DetailPanel
            detail={detail}
            onTake={take}
            onReply={reply}
            onResolve={resolve}
            onNote={note}
            onAttach={attach}
            onTransfer={openTransfer}
            onReturn={() => setReturnOpen(true)}
            onReopen={reopen}
            onOpenContext={() => setContextOpen(true)}
          />
        ) : (
          <div className="grid min-h-[50vh] place-items-center rounded-2xl border border-dashed border-slate-300 bg-white/60 text-sm text-slate-500">
            Elegí un handoff para ver la conversación
          </div>
        )}
        {detail && (
          <aside className="hidden xl:block">
            <div className="sticky top-[76px] rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
              <div className="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-400">
                Contexto del cliente
              </div>
              <ContextPanel detail={detail} />
            </div>
          </aside>
        )}
      </div>

      <Drawer
        opened={contextOpen}
        onClose={() => setContextOpen(false)}
        title="Contexto del cliente"
        position="right"
        size="sm"
      >
        {detail && <ContextPanel detail={detail} />}
      </Drawer>
      <Dialog
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
        title="Resolver handoff"
        description="Indicá qué solución aplicaste. El bot volverá a atender al cliente."
      >
        <div className="mt-3 grid grid-cols-2 gap-2">
          {RESOLUTION_CATEGORIES.map(([value, label]) => (
            <button
              key={value}
              onClick={() => setResolveCategory(value)}
              className={`rounded-lg border px-3 py-2 text-sm font-semibold ${resolveCategory === value ? "border-red-500 bg-red-50 text-red-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <Textarea
          value={resolveNote}
          onChange={(event) => setResolveNote(event.target.value)}
          rows={3}
          placeholder="Ej: se confirmó stock y se pasó el link de pago"
          className="mt-3"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setResolveOpen(false)}>Cancelar</Button>
          <Button onClick={confirmResolve} disabled={!resolveNote.trim()}>
            <Check size={14} /> Resolver
          </Button>
        </div>
      </Dialog>
      <Dialog
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        title="Transferir caso"
        description="El nuevo asesor podrá responder desde su consola."
      >
        <select
          value={transferTo}
          onChange={(event) => setTransferTo(event.target.value)}
          className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        >
          {team.map((member) => (
            <option key={member.username} value={member.display_name}>{member.display_name}</option>
          ))}
        </select>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setTransferOpen(false)}>Cancelar</Button>
          <Button onClick={confirmTransfer} disabled={!transferTo}>Transferir</Button>
        </div>
      </Dialog>
      <Dialog
        open={returnOpen}
        onClose={() => setReturnOpen(false)}
        title="Devolver al bot"
        description="El bot retomará la conversación sin marcar el caso como resuelto."
      >
        <Textarea
          value={returnReason}
          onChange={(event) => setReturnReason(event.target.value)}
          rows={3}
          className="mt-3"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setReturnOpen(false)}>Cancelar</Button>
          <Button onClick={confirmReturn} disabled={!returnReason.trim()}>Devolver al bot</Button>
        </div>
      </Dialog>
    </>
  );
}

function Agents({ me }: { me: Advisor }) {
  const navigate = useNavigate();
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [metrics, setMetrics] = useState<AdvisorMetric[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "agent", on_duty: true });

  const load = useCallback(async () => {
    try {
      const [data, metricData] = await Promise.all([
        api<{ advisors: Advisor[] }>("/admin/advisors"),
        api<{ advisors: AdvisorMetric[] }>("/admin/metrics?days=30")
      ]);
      setAdvisors(data.advisors);
      setMetrics(metricData.advisors);
    } catch {
      setError("No se pudieron cargar los agentes.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/admin/advisors", { method: "POST", body: JSON.stringify(form) });
      setForm({ username: "", display_name: "", password: "", role: "agent", on_duty: true });
      await load();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "No se pudo crear.");
    }
  }

  async function patch(id: string, body: Record<string, unknown>) {
    await api(`/admin/advisors/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    await load();
  }

  return (
    <>
      <div className="mx-auto max-w-[1100px] p-4 lg:p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Agentes</h1>
            <p className="text-sm text-slate-500">Usuarios, guardia y permisos.</p>
          </div>
          <button onClick={() => navigate("/inbox")} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold hover:bg-slate-50">
            Volver a bandeja
          </button>
        </div>
        {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <form onSubmit={create} className="mb-4 grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-5">
          <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="usuario" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required />
          <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="nombre visible" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} required />
          <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" type="password" placeholder="contraseña" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required />
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })} className="rounded-lg border border-slate-300 px-2 py-1.5">
              <option value="agent">Agente</option>
              <option value="supervisor">Supervisor</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          <div className="flex gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={form.on_duty} onChange={(event) => setForm({ ...form, on_duty: event.target.checked })} /> guardia</label>
            <button className="ml-auto rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white hover:bg-red-700">Crear</button>
          </div>
        </form>
        <Card className="mb-4 overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-3">
            <h2 className="text-sm font-bold text-slate-900">Métricas · últimos 30 días</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2">Asesor</th>
                  <th className="px-3 py-2">Tomados</th>
                  <th className="px-3 py-2">Resueltos</th>
                  <th className="px-3 py-2">Reabiertos</th>
                  <th className="px-3 py-2">1ª respuesta</th>
                  <th className="px-3 py-2">Resolución</th>
                </tr>
              </thead>
              <tbody>
                {metrics.length ? metrics.map((row) => (
                  <tr key={row.username} className="border-t border-slate-100">
                    <td className="px-4 py-2 font-semibold">{row.advisor}</td>
                    <td className="px-3 py-2">{row.taken}</td>
                    <td className="px-3 py-2">{row.resolved}</td>
                    <td className="px-3 py-2">{row.reopened}</td>
                    <td className="px-3 py-2">{row.avg_response_minutes == null ? "—" : `${row.avg_response_minutes} min`}</td>
                    <td className="px-3 py-2">{row.avg_resolution_minutes == null ? "—" : `${row.avg_resolution_minutes} min`}</td>
                  </tr>
                )) : (
                  <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">Sin actividad todavía.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
        <div className="space-y-2">
          {advisors.map((advisor) => (
            <div key={advisor.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="min-w-[180px] flex-1">
                <div className="font-semibold text-slate-900">{advisor.display_name}</div>
                <div className="text-xs text-slate-500">{advisor.username}</div>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${advisor.on_duty ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{advisor.on_duty ? "de guardia" : "fuera"}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-bold text-slate-600">{advisor.role || (advisor.is_admin ? "admin" : "agente")}</span>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${advisor.active ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>{advisor.active ? "activo" : "inactivo"}</span>
              <div className="flex gap-2">
                <button onClick={() => patch(advisor.id!, { on_duty: !advisor.on_duty })} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold hover:bg-slate-50">{advisor.on_duty ? "Quitar guardia" : "Poner guardia"}</button>
                <button onClick={() => patch(advisor.id!, { active: !advisor.active })} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold hover:bg-slate-50">{advisor.active ? "Desactivar" : "Activar"}</button>
                <button onClick={() => patch(advisor.id!, { role: advisor.role === "admin" ? "supervisor" : advisor.role === "supervisor" ? "agent" : "admin" })} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold hover:bg-slate-50">Cambiar rol</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function MetricsPage({ me }: { me: Advisor }) {
  const [metrics, setMetrics] = useState<AdvisorMetric[]>([]);
  const load = useCallback(async () => {
    const data = await api<{ advisors: AdvisorMetric[] }>("/admin/metrics?days=30");
    setMetrics(data.advisors);
  }, []);
  useEffect(() => { void load(); }, [load]);
  return (
    <>
      <div className="mx-auto max-w-[1100px] p-4 lg:p-6">
        <h1 className="mb-1 text-xl font-bold text-slate-900">Métricas de atención</h1>
        <p className="mb-4 text-sm text-slate-500">Últimos 30 días.</p>
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Asesor</th>
                  <th className="px-3 py-3">Tomados</th>
                  <th className="px-3 py-3">Resueltos</th>
                  <th className="px-3 py-3">Reabiertos</th>
                  <th className="px-3 py-3">1ª respuesta</th>
                  <th className="px-3 py-3">Resolución</th>
                </tr>
              </thead>
              <tbody>
                {metrics.length ? metrics.map((row) => (
                  <tr key={row.username} className="border-t border-slate-100">
                    <td className="px-4 py-3 font-semibold">{row.advisor}</td>
                    <td className="px-3 py-3">{row.taken}</td>
                    <td className="px-3 py-3">{row.resolved}</td>
                    <td className="px-3 py-3">{row.reopened}</td>
                    <td className="px-3 py-3">{row.avg_response_minutes == null ? "—" : `${row.avg_response_minutes} min`}</td>
                    <td className="px-3 py-3">{row.avg_resolution_minutes == null ? "—" : `${row.avg_resolution_minutes} min`}</td>
                  </tr>
                )) : (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">Sin actividad todavía.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}

export default function App() {
  const [me, setMe] = useState<Advisor | null>(null);
  const [checking, setChecking] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    onUnauthorized(() => {
      setMe(null);
      setChecking(false);
      loginRedirect(navigate);
    });
    api<Advisor>("/advisor/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setChecking(false));
  }, [navigate]);

  if (checking) {
    return <div className="grid min-h-screen place-items-center text-sm text-slate-500">Cargando consola…</div>;
  }

  return (
    <Routes>
      <Route path="/login" element={me ? <Navigate to="/inbox" replace /> : <Login onLogin={setMe} />} />
      <Route path="/inbox" element={me ? <ConsoleShell me={me}><Inbox me={me} /></ConsoleShell> : <Navigate to="/login" replace />} />
      <Route path="/agents" element={me?.is_admin ? <ConsoleShell me={me}><Agents me={me} /></ConsoleShell> : <Navigate to="/inbox" replace />} />
      <Route path="/metrics" element={me && (me.is_admin || me.role === "supervisor") ? <ConsoleShell me={me}><MetricsPage me={me} /></ConsoleShell> : <Navigate to="/inbox" replace />} />
      <Route path="*" element={<Navigate to={me ? "/inbox" : "/login"} replace />} />
    </Routes>
  );
}
