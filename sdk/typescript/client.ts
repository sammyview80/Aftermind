/**
 * TypeScript SDK for Aftermind's REST API — the same four operations as
 * the Python SDK, MCP tools, and the core facade: observe, recall,
 * checkpoint, search. Uses the global `fetch` (Node 18+ or browser), no
 * dependency on Aftermind's Python internals.
 */

export interface Scope {
  [level: string]: string;
}

export interface ObserveResult {
  created: boolean;
  memory_id?: string;
  content?: string;
}

export interface MemorySummary {
  memory_id: string;
  content: string;
  memory_type: string;
  confidence: number;
}

export interface RecallResult {
  context: string;
  memories: MemorySummary[];
  related_entities: string[];
}

export interface SearchResult {
  memories: MemorySummary[];
}

export interface CheckpointResult {
  found: boolean;
  checkpoint_id?: string;
  version?: number;
  goal?: string;
  current?: string;
  completed?: string[];
  blockers?: string[];
  next_steps?: string[];
}

export interface AftermindClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

const DEFAULT_BASE_URL = "http://localhost:8000";

export class AftermindClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AftermindClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, "");
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private async post<T>(path: string, body: Record<string, unknown>): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(`Aftermind API error ${response.status}: ${await response.text()}`);
    }
    return (await response.json()) as T;
  }

  /** Learn from one turn of agent experience. */
  async observe(
    scope: Scope,
    options: { input?: string; output?: string; eventType?: string } = {}
  ): Promise<ObserveResult> {
    return this.post<ObserveResult>("/observe", {
      scope: { levels: scope },
      input: options.input ?? "",
      output: options.output ?? "",
      event_type: options.eventType ?? "agent_message",
    });
  }

  /** Reconstruct context (checkpoint + relevant memories) for a request. */
  async recall(scope: Scope, text: string, limit = 10): Promise<RecallResult> {
    return this.post<RecallResult>("/recall", { scope: { levels: scope }, text, limit });
  }

  /** Explicitly record a checkpoint of where the agent's work stands. */
  async checkpoint(
    scope: Scope,
    options: {
      goal?: string;
      current?: string;
      completed?: string[];
      blockers?: string[];
      nextSteps?: string[];
      memoryIds?: string[];
    } = {}
  ): Promise<CheckpointResult> {
    return this.post<CheckpointResult>("/checkpoint", {
      scope: { levels: scope },
      goal: options.goal ?? "",
      current: options.current ?? "",
      completed: options.completed ?? [],
      blockers: options.blockers ?? [],
      next_steps: options.nextSteps ?? [],
      memory_ids: options.memoryIds ?? [],
    });
  }

  async latestCheckpoint(scope: Scope): Promise<CheckpointResult> {
    return this.post<CheckpointResult>("/checkpoint/latest", { scope: { levels: scope } });
  }

  /** Direct memory search, no checkpoint or context compression. */
  async search(scope: Scope, query: string, limit = 5): Promise<SearchResult> {
    return this.post<SearchResult>("/search", { scope: { levels: scope }, query, limit });
  }
}
