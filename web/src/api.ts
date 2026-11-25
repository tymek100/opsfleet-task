export type Agent = {
  id: string;
  name: string;
  description: string;
  url: string;
};
export type Conversation = { id: string; role: string; title: string };
export type Catalog = { profile: string; backend: string; agents: Agent[] };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Request failed (${response.status}).`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function conversationForAgent(
  conversations: Conversation[],
  role: string,
) {
  return conversations.find((conversation) => conversation.role === role);
}
