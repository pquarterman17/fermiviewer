import { record } from "../macro";

interface ValidationIssue {
  loc?: Array<string | number>;
  msg?: string;
}

/** Turn FastAPI's string or validation-array `detail` into a useful message. */
export function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const issues = detail
      .map((item: unknown) => {
        if (!item || typeof item !== "object") return String(item);
        const issue = item as ValidationIssue;
        const field = issue.loc?.filter((part) => part !== "body").join(".");
        return [field, issue.msg].filter(Boolean).join(": ");
      })
      .filter(Boolean);
    if (issues.length > 0) return issues.join("; ");
  }
  return fallback;
}

/** Shared response decoder for domain API modules; intentionally not public. */
export async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = formatApiDetail(body.detail, detail);
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
