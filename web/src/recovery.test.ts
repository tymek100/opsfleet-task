import { afterEach, describe, expect, it, vi } from "vitest";
import { saveHistoryEntry } from "./recovery";
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
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
