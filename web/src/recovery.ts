import type { ThreadHistoryAdapter } from "@assistant-ui/react";
import { api, ApiError } from "./api";

function transient(error: unknown) {
  if (error instanceof ApiError) {
    const status = error.status;
    return status === 408 || status === 429 || status >= 500;
  }
  return (
    error instanceof TypeError ||
    (error instanceof DOMException && error.name === "TimeoutError")
  );
}

function pause(signal?: AbortSignal) {
  signal?.throwIfAborted();
  return new Promise<void>((resolve, reject) => {
    const aborted = () => {
      clearTimeout(timer);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", aborted);
      resolve();
    }, 1000);
    signal?.addEventListener("abort", aborted, { once: true });
  });
}

// Only retry the idempotent history upsert. Never replay a model request.
export async function saveHistoryEntry(
  path: string,
  entry: Parameters<ThreadHistoryAdapter["append"]>[0],
) {
  const deadline = Date.now() + 30_000;
  const body = JSON.stringify(entry);
  while (true) {
    try {
      await api(path, {
        method: "POST",
        body,
        signal: AbortSignal.timeout(
          Math.max(1, Math.min(5000, deadline - Date.now())),
        ),
      });
      return;
    } catch (error) {
      if (!transient(error) || Date.now() >= deadline) throw error;
      await pause();
    }
  }
}
