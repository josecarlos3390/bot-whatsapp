import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/**
 * Traducción ligera del panel.
 *
 * La clave es el texto en español: si una cadena todavía no está traducida, se
 * muestra tal cual. Así se puede ir traduciendo por partes sin romper nada.
 */
export type Lang = "es" | "en";

const EN: Record<string, string> = {
  // Navegación y cabecera
  "Bandeja": "Inbox",
  "Agentes": "Agents",
  "Métricas": "Metrics",
  "Operación": "Operations",
  "Administración": "Administration",
  "Reglas": "Rules",
  "Ocasiones": "Occasions",
  "Consola de asesores": "Advisor console",
  "Portal de áreas": "Area portal",
  "Notificaciones": "Notifications",
  "Guardia": "On duty",
  "Sin guardia": "No one on duty",
  "Cerrar sesión": "Sign out",
  "Tema": "Theme",
  // Login
  "Consola": "Console",
  "Área": "Area",
  "Usuario": "Username",
  "Contraseña": "Password",
  "Ingresar": "Sign in",
  "Usuario o contraseña incorrectos.": "Wrong username or password.",
  "ROHO HOMECENTER": "ROHO HOMECENTER",
  // Tablero
  "Centro de operación": "Operations center",
  "¿Cómo está el bot hoy?": "How is the bot doing today?",
  "Bot WhatsApp": "WhatsApp bot",
  "API de integración": "Integration API",
  "Sincronización VTEX": "VTEX sync",
  "Embudo de venta": "Sales funnel",
  "Búsquedas sin resultados": "Searches with no results",
  "Consumo del modelo": "Model usage",
  "Latencia de respuesta": "Response latency",
  "Probar el bot": "Test the bot",
  "Control de calidad": "Quality control",
  "Calidad de respuesta": "Response quality",
  "Última sincronización": "Last sync",
  "No envía nada ni ensucia las métricas": "Sends nothing and keeps metrics clean",
  "Escribí como si fueras un cliente y mirá exactamente qué respondería el bot.":
    "Type as a customer would and see exactly what the bot would answer.",
  "Respondió en": "Answered in",
  "camino": "path",
  "Últimas pruebas": "Recent tests",
  "Repetir": "Run again",
  "Probando…": "Testing…",
  "Probar": "Test",
  "Mediana": "Median",
  "p95": "p95",
  "Máxima": "Max",
  "Lentas": "Slow",
  "Entrada / llamada": "Input / call",
  "Salida / llamada": "Output / call",
  "Cacheado": "Cached",
  "Total tokens": "Total tokens",
  "Sin anomalías detectadas.": "No anomalies detected.",
  "Casos": "Cases",
};

type I18nValue = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (text: string) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

function idiomaInicial(): Lang {
  const guardado = window.localStorage.getItem("roho-lang");
  if (guardado === "es" || guardado === "en") return guardado;
  return navigator.language.toLowerCase().startsWith("en") ? "en" : "es";
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>(idiomaInicial);

  useEffect(() => {
    window.localStorage.setItem("roho-lang", lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const t = useCallback(
    (text: string) => (lang === "en" ? EN[text] ?? text : text),
    [lang]
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n debe usarse dentro de I18nProvider");
  return value;
}

export function LanguageToggle() {
  const { lang, setLang } = useI18n();
  return (
    <div className="flex items-center rounded-full border border-slate-700 bg-slate-900/60 p-0.5 text-[11px] font-semibold">
      {(["es", "en"] as Lang[]).map((opcion) => (
        <button
          key={opcion}
          type="button"
          onClick={() => setLang(opcion)}
          className={`rounded-full px-2 py-1 uppercase transition ${
            lang === opcion ? "bg-[#e9082a] text-white" : "text-slate-300 hover:text-white"
          }`}
          title={opcion === "es" ? "Español" : "English"}
        >
          {opcion}
        </button>
      ))}
    </div>
  );
}
