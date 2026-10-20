let unauthorizedHandler: (() => void) | null = null;

export function onUnauthorized(handler: () => void) {
  unauthorizedHandler = handler;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {})
    }
  });
  if (response.status === 401) {
    unauthorizedHandler?.();
    throw new Error("Sesión vencida");
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Error ${response.status}`);
  }
  return (await response.json()) as T;
}
