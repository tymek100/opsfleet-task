import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  type ThreadHistoryAdapter,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { useLocalRuntime, type ChatModelAdapter } from "@assistant-ui/react";
import {
  ArrowUp,
  Boxes,
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  Copy,
  GitBranch,
  Info,
  Menu,
  MessageSquare,
  Plus,
  Square,
  Trash2,
  Truck,
  X,
} from "lucide-react";
import {
  api,
  conversationForAgent,
  type Agent,
  type Catalog,
  type Conversation,
} from "./api";
import { Markdown } from "./Markdown";
import { saveHistoryEntry } from "./recovery";

const icons = {
  coordinator: GitBranch,
  retail: ChartNoAxesCombined,
  inventory: Boxes,
  distribution: Truck,
};
const suggestions: Record<string, string[]> = {
  coordinator: [
    "Compare our Q1 2026 sales with current inventory. Which categories deserve a closer look?",
    "Which distribution centers hold the most unsold inventory, and how does that compare with demand?",
  ],
  retail: [
    "Show our top five products by revenue and, separately, by distinct customers in Q1 2026. Use two compact tables.",
    "Compare Q1 2026 with Q4 2025: revenue, customers, orders and average order value.",
  ],
  inventory: [
    "Which product categories have the most unsold inventory? Show units and inventory cost.",
    "Show the oldest unsold stock and explain the limitations of this inventory model.",
  ],
  distribution: [
    "Compare unsold units and inventory cost across distribution centers.",
    "Which distribution centers have the largest share of aging inventory?",
  ],
};

export default function App() {
  const [catalog, setCatalog] = useState<Catalog>();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<Conversation>();
  const [role, setRole] = useState("coordinator");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const [deleting, setDeleting] = useState<Conversation>();
  const [deleteError, setDeleteError] = useState("");
  const refresh = useCallback(
    async () =>
      setConversations(await api<Conversation[]>("/api/conversations")),
    [],
  );
  useEffect(() => {
    (async () => {
      const configuration = await api<Catalog>("/api/catalog");
      setCatalog(configuration);
      const saved = await api<Conversation[]>("/api/conversations");
      setConversations(saved);
      const selected = conversationForAgent(saved, "coordinator");
      if (selected) setActive(selected);
      else {
        const created = await api<Conversation>("/api/conversations", {
          method: "POST",
          body: JSON.stringify({ role: "coordinator" }),
        });
        setActive(created);
        setConversations((items) => [created, ...items]);
      }
    })().catch((e) => setError(e.message));
  }, []);

  async function choose(nextRole: string, forceNew = false) {
    if (running || busy) return;
    setBusy(true);
    setError("");
    try {
      const previous = forceNew
        ? undefined
        : conversationForAgent(conversations, nextRole);
      const next =
        previous ||
        (await api<Conversation>("/api/conversations", {
          method: "POST",
          body: JSON.stringify({ role: nextRole }),
        }));
      setRole(nextRole);
      setActive(next);
      setSidebar(false);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteConversation() {
    if (!deleting || busy || running) return;
    setBusy(true);
    setDeleteError("");
    try {
      await api(`/api/conversations/${deleting.id}`, { method: "DELETE" });
    } catch (e) {
      setDeleteError(
        `Could not delete this conversation. ${(e as Error).message}`,
      );
      setBusy(false);
      return;
    }

    const remaining = conversations.filter((item) => item.id !== deleting.id);
    setConversations(remaining);
    try {
      if (active?.id === deleting.id) {
        setActive(undefined);
        const previous = conversationForAgent(remaining, role);
        const next =
          previous ||
          (await api<Conversation>("/api/conversations", {
            method: "POST",
            body: JSON.stringify({ role }),
          }));
        setActive(next);
        if (!previous) setConversations((items) => [next, ...items]);
        setSidebar(false);
      }
    } catch (e) {
      setError(
        `Conversation deleted, but a new chat could not be opened. ${(e as Error).message}`,
      );
    } finally {
      setDeleting(undefined);
      setBusy(false);
    }
  }
  const agent = catalog?.agents.find((item) => item.id === role);
  return (
    <div className="app-shell">
      <aside
        className={`sidebar ${sidebar ? "open" : ""}`}
        aria-label="Workspace navigation"
      >
        <a className="brand" href="/">
          <span className="brand-icon">
            <ChartNoAxesCombined size={22} />
          </span>
          <span>
            Retail Insight<small>Agent workspace</small>
          </span>
        </a>
        <button
          className="new-chat"
          disabled={busy || running}
          onClick={() => choose(role, true)}
        >
          <Plus size={18} />
          New conversation
        </button>
        <div className="section-label">
          YOUR AGENTS <span>4</span>
        </div>
        <nav className="agent-list" aria-label="Choose an agent">
          {catalog?.agents.map((item) => {
            const Icon = icons[item.id as keyof typeof icons];
            return (
              <button
                key={item.id}
                aria-pressed={role === item.id}
                className={`agent-button ${role === item.id ? "active" : ""}`}
                disabled={busy || running}
                onClick={() => choose(item.id)}
              >
                <Icon size={20} />
                <span>
                  {item.name}
                  <small>
                    {item.id === "coordinator"
                      ? "Works across your agents"
                      : item.id === "retail"
                        ? "Sales & customers"
                        : item.id === "inventory"
                          ? "Stock & aging"
                          : "Centers & allocation"}
                  </small>
                </span>
                {role === item.id && <ChevronRight size={16} />}
              </button>
            );
          })}
        </nav>
        <div className="section-label history-label">RECENT CONVERSATIONS</div>
        <nav className="history-list" aria-label="Conversation history">
          {conversations
            .filter(
              (item) => item.role === role && item.title !== "New conversation",
            )
            .map((item) => (
              <div
                key={item.id}
                className={`history-item ${active?.id === item.id ? "selected" : ""}`}
              >
                <button
                  className="history-open"
                  aria-current={active?.id === item.id ? "true" : undefined}
                  title={item.title}
                  disabled={running || busy}
                  onClick={() => {
                    setActive(item);
                    setSidebar(false);
                  }}
                >
                  <MessageSquare size={15} />
                  <span>{item.title}</span>
                </button>
                <button
                  className="history-delete"
                  aria-label={`Delete conversation: ${item.title}`}
                  title={
                    running
                      ? "Stop generation before deleting a conversation"
                      : "Delete conversation"
                  }
                  disabled={running || busy}
                  onClick={() => {
                    setDeleteError("");
                    setDeleting(item);
                  }}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          {!conversations.some(
            (item) => item.role === role && item.title !== "New conversation",
          ) && <p>Your conversations will appear here.</p>}
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" />
          <div>
            Local workspace
            <small>
              {catalog?.backend === "bigquery"
                ? "BigQuery · all brands"
                : "Fixture data · all brands"}
            </small>
          </div>
          <a href="https://ai.azure.com" target="_blank" rel="noreferrer">
            Foundry ↗
          </a>
        </div>
      </aside>
      {sidebar && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setSidebar(false)}
        />
      )}
      <main className="main">
        <button
          className="mobile-menu"
          aria-label="Open navigation"
          onClick={() => setSidebar(true)}
        >
          <Menu size={20} />
        </button>
        {error && (
          <div className="app-error" role="alert">
            {error}{" "}
            <button onClick={() => window.location.reload()}>Reconnect</button>
          </div>
        )}
        {agent && active ? (
          <Chat
            key={`${catalog?.profile}:${role}:${active.id}`}
            agent={agent}
            conversation={active}
            onSaved={refresh}
            onRunning={setRunning}
          />
        ) : (
          <div className="connecting">Connecting to your workspace…</div>
        )}
      </main>
      {deleting && (
        <DeleteConversationDialog
          conversation={deleting}
          busy={busy}
          error={deleteError}
          onCancel={() => setDeleting(undefined)}
          onDelete={deleteConversation}
        />
      )}
    </div>
  );
}

function DeleteConversationDialog({
  conversation,
  busy,
  error,
  onCancel,
  onDelete,
}: {
  conversation: Conversation;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const opener = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="delete-dialog"
      aria-labelledby="delete-title"
      aria-describedby="delete-description"
      aria-busy={busy}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <h2 id="delete-title">Delete conversation?</h2>
      <p className="delete-conversation-title">{conversation.title}</p>
      <p id="delete-description">
        This removes the chat and its saved messages from this workspace. This
        can't be undone.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="delete-dialog-actions">
        <button disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button className="confirm-delete" disabled={busy} onClick={onDelete}>
          {busy ? "Deleting…" : "Delete conversation"}
        </button>
      </div>
    </dialog>
  );
}

function Chat({
  agent,
  conversation,
  onSaved,
  onRunning,
}: {
  agent: Agent;
  conversation: Conversation;
  onSaved: () => Promise<void>;
  onRunning: (running: boolean) => void;
}) {
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const adapter = useMemo<ChatModelAdapter>(() => ({
    async *run({ messages, abortSignal }) {
      setError("");
      const question = messages.filter(m => m.role === "user").at(-1)?.content
        .filter(p => p.type === "text").map(p => p.text).join("\n") || "";
      const response = await fetch(`${agent.url}/chat`, {
        method: "POST", signal: abortSignal,
        headers: { "Content-Type": "application/json", "x-retail-conversation": conversation.id },
        body: JSON.stringify({ question }),
      });
      if (!response.ok || !response.body) throw new Error("The agent could not accept this request.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let newline;
          while ((newline = buffer.indexOf("\n")) >= 0) {
            const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "error") throw new Error(event.message);
            if (event.type === "result") {
              finished = true;
              yield { content: [{ type: "text", text: event.result.markdown }],
                metadata: { custom: { result: event.result } } };
            }
          }
        }
        if (!finished) throw new Error("The connection ended before a reviewed result arrived. The request was not resent.");
      } catch (failure) {
        if (!abortSignal.aborted) setError(failure instanceof Error ? failure.message : "The investigation could not complete.");
        throw failure;
      } finally { reader.releaseLock(); }
    },
  }), [agent.url, conversation.id]);
  const history = useMemo<ThreadHistoryAdapter>(() => {
    const path = `/api/conversations/${conversation.id}`;
    const save: ThreadHistoryAdapter["append"] = async (entry) => {
      try {
        await saveHistoryEntry(path, entry);
        setSaveError("");
      } catch (e) {
        setSaveError("Conversation could not be saved. Keep this tab open.");
        throw e;
      }
      // A failed sidebar refresh does not mean the message failed to save.
      await onSaved().catch(() => undefined);
    };
    return {
      load: async () => {
        const repo =
          await api<Awaited<ReturnType<ThreadHistoryAdapter["load"]>>>(path);
        return {
          ...repo,
          messages: repo.messages.map((item) => ({
            ...item,
            message: {
              ...item.message,
              createdAt: new Date(item.message.createdAt),
            },
          })),
        };
      },
      append: save,
      update: save,
    };
  }, [conversation.id, onSaved]);
  const runtime = useLocalRuntime(adapter, { adapters: { history } });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ChatThread
        agent={agent}
        error={saveError || error}
        onRunning={onRunning}
      />
    </AssistantRuntimeProvider>
  );
}

function ChatThread({
  agent,
  error,
  onRunning,
}: {
  agent: Agent;
  error: string;
  onRunning: (running: boolean) => void;
}) {
  const running = useAuiState((s) => s.thread.isRunning);
  const loading = useAuiState((s) => s.thread.isLoading);
  const [details, setDetails] = useState(false);
  const [card, setCard] = useState<{name:string;description:string;skills:{id:string;name:string;description:string}[]} | null>(null);
  useEffect(() => { api<typeof card>(`${agent.url}/agent-card.json`).then(setCard).catch(() => setCard(null)); }, [agent.url]);
  useEffect(() => {
    onRunning(running);
  }, [running]);
  useEffect(() => () => onRunning(false), [onRunning]);
  const Icon = icons[agent.id as keyof typeof icons];
  return (
    <ThreadPrimitive.Root className="thread">
      <header className="chat-header">
        <div>
          <span className="header-icon">
            <Icon size={22} />
          </span>
          <div>
            <h1>{agent.name}</h1>
            <p>{agent.description}</p>
          </div>
        </div>
        <button
          className="icon-button"
          aria-label="Agent details"
          aria-expanded={details}
          onClick={() => setDetails(!details)}
        >
          <Info size={20} />
        </button>
      </header>
      {details && (
        <section className="agent-details" aria-label="Agent card">
          <div>
            <strong>{card?.name || agent.name}</strong>
            <button
              className="icon-button"
              aria-label="Close agent details"
              onClick={() => setDetails(false)}
            >
              <X size={18} />
            </button>
          </div>
          <p>{card?.description || agent.description}</p>
          <p>
            LangGraph · Reviewed answers · Streaming progress
          </p>
          {card?.skills.map((skill) => (
            <p key={skill.id}>
              <strong>{skill.name}</strong> — {skill.description}
            </p>
          ))}
          <a
            href={`${agent.url}/agent-card.json`}
            target="_blank"
            rel="noreferrer"
          >
            View Agent Card ↗
          </a>
        </section>
      )}
      <ThreadPrimitive.Viewport className="viewport">
        <ThreadPrimitive.Empty>
          <section className="welcome">
            <div className="welcome-icon">
              <Icon size={30} />
            </div>
            <div className="eyebrow">YOUR DATA, IN CONVERSATION</div>
            <h2>
              {agent.id === "coordinator"
                ? "Ask a bigger question."
                : `Explore ${agent.id === "retail" ? "your retail performance" : agent.id === "inventory" ? "your inventory" : "your distribution network"}.`}
            </h2>
            <p>
              {agent.id === "coordinator"
                ? "Bring sales, inventory and distribution together. Your coordinator finds the right agents and connects the evidence."
                : agent.description}
            </p>
            <div className="suggestions">
              {suggestions[agent.id].map((prompt) => (
                <ThreadPrimitive.Suggestion
                  key={prompt}
                  prompt={prompt}
                  method="replace"
                  autoSend={false}
                  className="suggestion"
                >
                  <span>{prompt}</span>
                  <ChevronRight size={18} />
                </ThreadPrimitive.Suggestion>
              ))}
            </div>
          </section>
        </ThreadPrimitive.Empty>
        <div className="messages">
          <ThreadPrimitive.Messages
            components={{ UserMessage, AssistantMessage }}
          />
        </div>
        {running && <Thinking />}
        {loading && (
          <p className="loading-history" role="status">
            Loading conversation…
          </p>
        )}
      </ThreadPrimitive.Viewport>
      <div className="composer-area">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <ComposerPrimitive.Root className="composer">
          <ComposerPrimitive.Input
            className="composer-input"
            placeholder={`Ask the ${agent.name.toLowerCase()}…`}
            aria-label="Message"
            rows={2}
            disabled={loading}
          />
          <div className="composer-bottom">
            <span>
              {running
                ? "Working on your question"
                : "Enter to send · Shift + Enter for a new line"}
            </span>
            {running ? (
              <ComposerPrimitive.Cancel
                className="send-button stop"
                aria-label="Stop generation"
              >
                <Square size={16} fill="currentColor" />
              </ComposerPrimitive.Cancel>
            ) : (
              <ComposerPrimitive.Send
                className="send-button"
                aria-label="Send message"
              >
                <ArrowUp size={20} />
              </ComposerPrimitive.Send>
            )}
          </div>
        </ComposerPrimitive.Root>
        <p className="composer-note">
          Answers are reviewed against evidence. Check important decisions
          against the source data.
        </p>
      </div>
    </ThreadPrimitive.Root>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user-message">
      <div className="message-label">You</div>
      <MessagePrimitive.Parts
        components={{ Text: () => <MarkdownTextPrimitive smooth={false} /> }}
      />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  const message = useAuiState((s) => s.message);
  const [copied, setCopied] = useState(false);
  const result = message.metadata.custom.result as { status?: string; contains_ephemeral_evidence?: boolean; usage?: {accounted_usd?: number}; trace_id?: string; evidence?: unknown[] } | undefined;
  const fallback = message.content
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("\n");
  const text = message.status?.type === "running" ? "" : fallback;
  if (!text && message.status?.type === "running") return null;
  return (
    <MessagePrimitive.Root className="message assistant-message">
      <div className="message-label">
        <span className="small-spark">
          <GitBranch size={14} />
        </span>
        Retail Insight
      </div>
      <Markdown
        text={text || "No reviewed answer was returned. Please try again."}
      />
      {message.status?.type === "incomplete" && (
        <p className="outcome-note">
          {message.status.reason === "cancelled"
            ? "Stopped. No unfinished answer was published."
            : "This request did not complete successfully."}
        </p>
      )}
      {result?.contains_ephemeral_evidence && (
        <p className="outcome-note">
          Maps content is temporary and will not be saved.
        </p>
      )}
      <div className="answer-actions">
        <button
          aria-label="Copy answer"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy answer"}
        </button>
        {result && (
          <details>
            <summary>Run details</summary>
            <p>
              Outcome: {result.status}
              {typeof result.usage?.accounted_usd === "number"
                ? ` · Accounted cost: $${result.usage.accounted_usd.toFixed(4)}`
                : ""}
            </p>
            {result.trace_id && (
              <p>
                Trace: <code>{result.trace_id}</code> ·{" "}
                <a
                  href="https://ai.azure.com"
                  target="_blank"
                  rel="noreferrer"
                >
                  Open Foundry ↗
                </a>
              </p>
            )}
            {!!result.evidence?.length && (
              <details className="evidence-details">
                <summary>Evidence ({result.evidence.length})</summary>
                <pre>{JSON.stringify(result.evidence, null, 2)}</pre>
              </details>
            )}
          </details>
        )}
      </div>
    </MessagePrimitive.Root>
  );
}

function Thinking() {
  const [started] = useState(() => performance.now());
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(
      () => setSeconds(Math.floor((performance.now() - started) / 1000)),
      250,
    );
    return () => clearInterval(timer);
  }, [started]);
  return (
    <div className="thinking" role="status">
      <span className="thinking-spinner" />
      <span>
        Thinking
        <span className="thinking-dots">{".".repeat((seconds % 3) + 1)}</span>
      </span>
      <span className="elapsed">{seconds}s</span>
    </div>
  );
}
