import { record } from "../macro";

/** Shared response decoder for domain API modules; intentionally not public. */
export async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

/** JSON POST transport plus macro capture; intentionally not public. */
export async function post<T>(url: string, body: unknown): Promise<T> {
  record(url, body as Record<string, unknown>); // no-op unless recording
  return json(
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}
