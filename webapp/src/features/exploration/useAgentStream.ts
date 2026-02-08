/**
 * SSE hook that manages agent state from the /api/agent-stream endpoint.
 *
 * Maintains a reactive map of agents, links between them, and notepad
 * entries. Components subscribe to the returned state to render the
 * force graph and detail panels.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { AgentNode, ToolCall, NoteEntry, AgentEvent, GraphNode, GraphLink } from './types';

interface AgentStreamState {
  agents: Map<string, AgentNode>;
  graphNodes: GraphNode[];
  graphLinks: GraphLink[];
  notepads: Map<string, NoteEntry[]>;
  selectedAgent: string | null;
  setSelectedAgent: (id: string | null) => void;
  isConnected: boolean;
  isDone: boolean;
  noAgents: boolean;
  retry: () => void;
}

/** Compute depth-based node size: root largest, deeper nodes smaller. */
function nodeSize(depth: number, status: string): number {
  if (depth === 0) return 12;
  if (depth === 1) return 8;
  // depth 2+ get a small bump while running
  return status === 'running' ? 5 : 4;
}

export function useAgentStream(): AgentStreamState {
  const [agents, setAgents] = useState<Map<string, AgentNode>>(new Map());
  const [notepads, setNotepads] = useState<Map<string, NoteEntry[]>>(new Map());
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const [noAgents, setNoAgents] = useState(false);
  const isDoneRef = useRef(false);
  const noAgentsRef = useRef(false);
  const failureCountRef = useRef(0);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);

  /** Load notepad entries from REST endpoints (works for completed runs). */
  const loadNotepadsFromRest = async () => {
    try {
      const topicsRes = await fetch('/api/notepad');
      if (!topicsRes.ok) return;
      const topicsList = await topicsRes.json() as { topic: string; count: number }[];
      if (!Array.isArray(topicsList) || topicsList.length === 0) return;

      const fetches = topicsList.map(async ({ topic }): Promise<[string, NoteEntry[]]> => {
        try {
          const res = await fetch(`/api/notepad/${encodeURIComponent(topic)}`);
          if (!res.ok) return [topic, []];
          const entries = await res.json() as NoteEntry[];
          return [topic, entries];
        } catch {
          return [topic, []];
        }
      });

      const results = await Promise.all(fetches);
      setNotepads(prev => {
        const next = new Map(prev);
        for (const [topic, entries] of results) {
          // Only add if we don't already have entries from SSE
          if (!next.has(topic) || (next.get(topic)?.length ?? 0) === 0) {
            next.set(topic, entries);
          }
        }
        return next;
      });
    } catch {
      // Notepad REST loading is best-effort
    }
  };

  const connect = useCallback(() => {
    if (cancelledRef.current || isDoneRef.current || noAgentsRef.current) {
      return;
    }
    const es = new EventSource('/api/agent-stream');
    esRef.current = es;

    es.onopen = () => {
      setIsConnected(true);
      failureCountRef.current = 0;
    };

    es.onerror = () => {
      setIsConnected(false);
      es.close();
      if (cancelledRef.current || isDoneRef.current || noAgentsRef.current) {
        return;
      }
      failureCountRef.current += 1;
      if (failureCountRef.current >= 3) {
        // Don't set isDone -- exploration may still be running.
        // The retry button will appear since isConnected=false and isDone=false.
        return;
      }
      reconnectTimerRef.current = setTimeout(connect, 3000);
    };

    es.addEventListener('agent_spawned', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      setAgents(prev => {
        const next = new Map(prev);
        next.set(data.agent_id!, {
          agent_id: data.agent_id!,
          parent_id: data.parent_id ?? null,
          purpose: data.purpose ?? '',
          depth: data.depth ?? 0,
          status: 'running',
          text: '',
          tools: [],
          scope_root: data.scope_root,
        });
        return next;
      });
    });

    es.addEventListener('agent_finished', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      setAgents(prev => {
        const next = new Map(prev);
        const agent = next.get(data.agent_id!);
        if (agent) {
          next.set(data.agent_id!, {
            ...agent,
            status: 'done',
            summary: data.summary,
          });
        }
        return next;
      });
    });

    es.addEventListener('agent_error', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      setAgents(prev => {
        const next = new Map(prev);
        const agent = next.get(data.agent_id!);
        if (agent) {
          next.set(data.agent_id!, {
            ...agent,
            status: 'error',
            error: data.error,
          });
        }
        return next;
      });
    });

    es.addEventListener('llm_token', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      setAgents(prev => {
        const next = new Map(prev);
        const agent = next.get(data.agent_id!);
        if (agent) {
          const newText = agent.text + (data.token ?? '');
          next.set(data.agent_id!, {
            ...agent,
            text: newText.length > 5000 ? newText.slice(-5000) : newText,
          });
        }
        return next;
      });
    });

    es.addEventListener('tool_start', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      setAgents(prev => {
        const next = new Map(prev);
        const agent = next.get(data.agent_id!);
        if (agent) {
          const newTool: ToolCall = {
            tool: data.tool ?? '',
            input: data.input ?? '',
            status: 'running',
          };
          next.set(data.agent_id!, {
            ...agent,
            tools: [...agent.tools.slice(-49), newTool],
          });
        }
        return next;
      });
    });

    es.addEventListener('tool_end', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      setAgents(prev => {
        const next = new Map(prev);
        const agent = next.get(data.agent_id!);
        if (agent) {
          const tools = [...agent.tools];
          let lastRunning = -1;
          for (let i = tools.length - 1; i >= 0; i--) {
            if (tools[i].status === 'running') { lastRunning = i; break; }
          }
          if (lastRunning >= 0) {
            tools[lastRunning] = {
              ...tools[lastRunning],
              status: 'done',
              output: data.output,
            };
          }
          next.set(data.agent_id!, { ...agent, tools });
        }
        return next;
      });
    });

    es.addEventListener('notepad_write', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      const topic = data.topic ?? '';
      setNotepads(prev => {
        const next = new Map(prev);
        const entries = next.get(topic) ?? [];
        next.set(topic, [...entries, {
          content: data.content ?? '',
          author: data.author ?? '',
        }]);
        return next;
      });
    });

    es.addEventListener('notepad_created', (e: MessageEvent) => {
      const data: AgentEvent = JSON.parse(e.data);
      const topic = data.topic ?? '';
      setNotepads(prev => {
        const next = new Map(prev);
        if (!next.has(topic)) {
          next.set(topic, []);
        }
        return next;
      });
    });

    es.addEventListener('done', (e: MessageEvent) => {
      let payload: { no_agents?: boolean } = {};
      try {
        payload = JSON.parse(e.data || '{}');
      } catch {
        payload = {};
      }
      if (payload.no_agents) {
        setNoAgents(true);
        noAgentsRef.current = true;
      }
      setIsDone(true);
      isDoneRef.current = true;
      setIsConnected(false);
      es.close();
    });

    // Ignore pings (keep-alive).
    es.addEventListener('ping', () => {});
  }, []);

  /** Retry connection after failures. */
  const retry = useCallback(() => {
    failureCountRef.current = 0;
    isDoneRef.current = false;
    setIsDone(false);
    connect();
  }, [connect]);

  useEffect(() => {
    cancelledRef.current = false;

    const loadPersistedState = async (): Promise<boolean> => {
      try {
        const response = await fetch('/api/agent-state');
        if (!response.ok) {
          return false;
        }
        const payload = await response.json() as {
          agents?: Record<string, AgentNode>;
          notepads?: Record<string, NoteEntry[]>;
        };
        const persistedAgents = payload.agents ?? {};
        const persistedNotepads = payload.notepads ?? {};
        if (Object.keys(persistedAgents).length === 0) {
          return false;
        }
        setAgents(new Map(Object.entries(persistedAgents)));
        setNotepads(new Map(Object.entries(persistedNotepads)));
        setNoAgents(false);
        noAgentsRef.current = false;

        // Check if any agents are still running -- if so, connect SSE
        const hasRunning = Object.values(persistedAgents).some(a => a.status === 'running');
        if (hasRunning) {
          setIsDone(false);
          isDoneRef.current = false;
          return false; // Signal caller to proceed with SSE connection
        }

        setIsDone(true);
        isDoneRef.current = true;

        // Load notepads from REST endpoints for completed runs
        await loadNotepadsFromRest();

        return true;
      } catch {
        return false;
      }
    };

    loadPersistedState().then((hasPersisted) => {
      if (!hasPersisted) {
        connect();
      }
    });

    return () => {
      cancelledRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      esRef.current?.close();
    };
  }, [connect]);

  // Build a fingerprint of graph-structural state so we only recompute
  // nodes/links when IDs, statuses, parents, depths, or scope_roots change
  // -- not on high-frequency llm_token or tool events.
  const graphFingerprint = useMemo(() => {
    const parts: string[] = [];
    for (const [id, agent] of agents) {
      parts.push(`${id}:${agent.status}:${agent.parent_id ?? ''}:${agent.depth}:${agent.scope_root ?? ''}`);
    }
    return parts.join('|');
  }, [agents]);

  // Derive graph nodes and links, memoized on structural changes only.
  const { graphNodes, graphLinks } = useMemo(() => {
    const nodes: GraphNode[] = [];
    const links: GraphLink[] = [];

    for (const [id, agent] of agents) {
      const label = agent.scope_root
        ? agent.scope_root.replace(/\/+$/, '').split('/').pop() || agent.scope_root
        : id;
      nodes.push({
        id,
        name: label,
        status: agent.status,
        depth: agent.depth,
        val: nodeSize(agent.depth, agent.status),
        scope_root: agent.scope_root,
      });
      if (agent.parent_id && agents.has(agent.parent_id)) {
        links.push({
          source: agent.parent_id,
          target: id,
        });
      }
    }

    return { graphNodes: nodes, graphLinks: links };
  }, [graphFingerprint]); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    agents,
    graphNodes,
    graphLinks,
    notepads,
    selectedAgent,
    setSelectedAgent,
    isConnected,
    isDone,
    noAgents,
    retry,
  };
}
