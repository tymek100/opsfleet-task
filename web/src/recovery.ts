import {
  A2AClient,
  A2AError,
  isInterruptedTaskState,
  isTerminalTaskState,
  type A2AStreamEvent,
} from "@assistant-ui/react-a2a";
import type { ThreadHistoryAdapter } from "@assistant-ui/react";
import { api, ApiError } from "./api";

function transient(error: unknown) {
  if (error instanceof ApiError || error instanceof A2AError) {
    const status = error instanceof ApiError ? error.status : error.code;
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

export class RecoveringA2AClient extends A2AClient {
  override async *streamMessage(
    ...args: Parameters<A2AClient["streamMessage"]>
  ): AsyncGenerator<A2AStreamEvent> {
    const [message, , , signal] = args;
    // The gateway allows 180 seconds of execution; leave time for a final fetch.
    const deadline = Date.now() + 210_000;
    let taskId: string | undefined;
    let finished = false;
    try {
      for await (const event of super.streamMessage(...args)) {
        if (event.type === "task") {
          taskId = event.task.id;
          finished =
            isTerminalTaskState(event.task.status.state) ||
            isInterruptedTaskState(event.task.status.state);
        } else if (event.type === "statusUpdate") {
          taskId = event.event.taskId;
          finished =
            isTerminalTaskState(event.event.status.state) ||
            isInterruptedTaskState(event.event.status.state);
        } else if (event.type === "artifactUpdate") {
          taskId = event.event.taskId;
        } else if (event.type === "message") {
          finished = true;
        }
        yield event;
      }
    } catch (error) {
      signal?.throwIfAborted();
      if (finished) return;
      if (!taskId || !transient(error)) throw error;
    }
    signal?.throwIfAborted();
    if (finished) return;
    if (!taskId)
      throw new Error(
        "The connection ended before a task was received. The question was not resent.",
      );

    // An EOF without a terminal event is an interrupted stream, not an answer.
    while (Date.now() < deadline) {
      signal?.throwIfAborted();
      const timeout = AbortSignal.timeout(
        Math.max(1, Math.min(10_000, deadline - Date.now())),
      );
      let task;
      try {
        task = await this.getTask(
          taskId,
          undefined,
          signal ? AbortSignal.any([signal, timeout]) : timeout,
        );
      } catch (error) {
        signal?.throwIfAborted();
        if (!transient(error)) throw error;
        await pause(signal);
        continue;
      }
      if (task.contextId !== message.contextId)
        throw new Error("Recovered task belongs to a different conversation.");
      yield { type: "task", task };
      if (
        isTerminalTaskState(task.status.state) ||
        isInterruptedTaskState(task.status.state)
      )
        return;
      await pause(signal);
    }
    throw new Error(
      "The connection was interrupted and the task result could not be recovered in time. The question was not resent.",
    );
  }
}
