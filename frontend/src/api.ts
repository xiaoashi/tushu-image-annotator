let token = "";
export function setToken(value: string) {
  token = value;
}
export async function api<T = any>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    headers: {
      ...(method === "GET" ? {} : { "X-Tushu-Client": token }),
      ...(data instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
    },
    body:
      data === undefined
        ? undefined
        : data instanceof FormData
          ? data
          : JSON.stringify(data),
  });
  if (!response.ok) {
    let message = "操作未完成，请重试";
    try {
      const body = await response.json();
      message =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
export function imageUrl(id: string, hash: string, thumbnail = false) {
  return `/api/assets/${id}/image?v=${hash}${thumbnail ? "&thumbnail=true" : ""}`;
}
