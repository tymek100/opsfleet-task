import { afterEach, describe, expect, it, vi } from "vitest";
import { A2AClient, A2AError, type A2ATask } from "@assistant-ui/react-a2a";
import { RecoveringA2AClient, saveHistoryEntry } from "./recovery";

const message = {
  messageId: "user-1",
  contextId: "chat-1",
  role: "user" as const,
  parts: [{ text: "Compare sales and stock" }],
};
const working: A2ATask = {
  id: "task-1",
  contextId: "chat-1",
  status: { state: "working" },
};
const completed: A2ATask = {
  ...working,
  status: { state: "completed" },
  artifacts: [
    {
      artifactId: "answer-1",
      name: "Reviewed answer",
      parts: [{ text: "Verified result" }],
    },
  ],
};
const client = () =>
  new RecoveringA2AClient({
    baseUrl: "http://localhost:8080/api/agents/coordinator",
  });
async function collect<T>(events: AsyncIterable<T>) {
  const result: T[] = [];
  for await (const event of events) result.push(event);
  return result;
}
function interruptedStream(error = false) {
  return vi
    .spyOn(A2AClient.prototype, "streamMessage")
    .mockImplementation(async function* () {
      yield { type: "task", task: working };
      if (error) throw new TypeError("Failed to fetch");
    });
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("A2A connection recovery", () => {
  it.each([false, true])(
    "recovers existing task after interrupted stream (network error: %s)",
    async (networkError) => {
      vi.useFakeTimers();
      const send = interruptedStream(networkError);
      const get = vi
        .spyOn(A2AClient.prototype, "getTask")
        .mockRejectedValueOnce(
          new A2AError({
            code: 502,
            status: "UNAVAILABLE",
            message: "Restarting",
          }),
        )
        .mockResolvedValueOnce(working)
        .mockResolvedValue(completed);
      const result = collect(client().streamMessage(message));
      await vi.advanceTimersByTimeAsync(2000);
      expect((await result).at(-1)).toEqual({ type: "task", task: completed });
      expect(send).toHaveBeenCalledTimes(1);
      expect(get).toHaveBeenCalledTimes(3);
      expect(get.mock.calls.every(([id]) => id === "task-1")).toBe(true);
    },
  );

  it.each(["completed", "failed", "canceled", "input_required"] as const)(
    "does not retry %s tasks",
    async (state) => {
      vi.spyOn(A2AClient.prototype, "streamMessage").mockImplementation(
        async function* () {
          yield { type: "task", task: { ...working, status: { state } } };
        },
      );
      const get = vi.spyOn(A2AClient.prototype, "getTask");
      await collect(client().streamMessage(message));
      expect(get).not.toHaveBeenCalled();
    },
  );

  it("never resends a request when disconnected before receiving a task ID", async () => {
    const send = vi
      .spyOn(A2AClient.prototype, "streamMessage")
      .mockImplementation(async function* () {
        throw new TypeError("Failed to fetch");
      });
    const get = vi.spyOn(A2AClient.prototype, "getTask");
    await expect(collect(client().streamMessage(message))).rejects.toThrow(
      "Failed to fetch",
    );
    expect(send).toHaveBeenCalledTimes(1);
    expect(get).not.toHaveBeenCalled();
  });

  it("stops polling immediately when the user cancels", async () => {
    vi.useFakeTimers();
    interruptedStream();
    const get = vi
      .spyOn(A2AClient.prototype, "getTask")
      .mockResolvedValue(working);
    const controller = new AbortController();
    const result = expect(
      collect(
        client().streamMessage(
          message,
          undefined,
          undefined,
          controller.signal,
        ),
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await result;
    await vi.advanceTimersByTimeAsync(5000);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("rejects a task from a different conversation", async () => {
    interruptedStream();
    vi.spyOn(A2AClient.prototype, "getTask").mockResolvedValue({
      ...completed,
      contextId: "other-chat",
    });
    await expect(collect(client().streamMessage(message))).rejects.toThrow(
      "different conversation",
    );
  });

  it("does not retry missing or unauthorized tasks", async () => {
    interruptedStream();
    const get = vi
      .spyOn(A2AClient.prototype, "getTask")
      .mockRejectedValue(
        new A2AError({
          code: 404,
          status: "NOT_FOUND",
          message: "Task not found",
        }),
      );
    await expect(collect(client().streamMessage(message))).rejects.toThrow(
      "Task not found",
    );
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("bounds polling when the service stays unavailable", async () => {
    vi.useFakeTimers();
    const send = interruptedStream();
    vi.spyOn(A2AClient.prototype, "getTask").mockRejectedValue(
      new TypeError("Failed to fetch"),
    );
    const result = expect(
      collect(client().streamMessage(message)),
    ).rejects.toThrow("could not be recovered in time");
    await vi.advanceTimersByTimeAsync(210_000);
    await result;
    expect(send).toHaveBeenCalledTimes(1);
  });
});

describe("history save retry", () => {
  const entry = {
    parentId: null,
    message: {
      id: "user-1",
      role: "user" as const,
      content: [{ type: "text" as const, text: "Question" }],
      createdAt: new Date(),
      attachments: [],
      metadata: { custom: {} },
    },
  };

  it("retries the same idempotent save after network and server errors", async () => {
    vi.useFakeTimers();
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockResolvedValueOnce(new Response('{"saved":true}'));
    vi.stubGlobal("fetch", fetch);
    const result = saveHistoryEntry("/api/conversations/chat-1", entry);
    await vi.advanceTimersByTimeAsync(2000);
    await result;
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(new Set(fetch.mock.calls.map(([, init]) => init.body)).size).toBe(1);
  });

  it("does not retry a deleted conversation", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response('{"error":"Conversation not found."}', { status: 404 }),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(
      saveHistoryEntry("/api/conversations/chat-1", entry),
    ).rejects.toThrow("Conversation not found");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("gives up on saving after a bounded retry window", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    const result = expect(
      saveHistoryEntry("/api/conversations/chat-1", entry),
    ).rejects.toThrow("Failed to fetch");
    await vi.advanceTimersByTimeAsync(30_000);
    await result;
  });
});
