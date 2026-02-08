/**
 * SSE hook that manages agent state from the /api/agent-stream endpoint.
 *
 * Maintains a reactive map of agents, links between them, and notepad
 * entries. Components subscribe to the returned state to render the
 * force graph and detail panels.
 */
import { useState, useEffect, useRef } from 'react';
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
}

export function useAgentStream(): AgentStreamState {
  const [agents, setAgents] = useState<Map<string, AgentNode>>(new Map());
  const [notepads, setNotepads] = useState<Map<string, NoteEntry[]>>(new Map());
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isDone, setIsDone] = useState(false);

  // Use a ref to avoid stale closure issues in event handlers.
  const agentsRef = useRef(agents);
  agentsRef.current = agents;
  const notepadsRef = useRef(notepads);
  notepadsRef.current = notepads;

  useEffect(() => {
    let es: EventSource | null = null;

    const connect = () => {
      es = new EventSource('/api/agent-stream');

      es.onopen = () => setIsConnected(true);
      es.onerror = () => {
        setIsConnected(false);
        // Try to reconnect after a delay if not done.
        if (!isDone) {
          setTimeout(connect, 3000);
        }
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
              tools: [...agent.tools, newTool],
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

      es.addEventListener('done', () => {
        setIsDone(true);
        es?.close();
      });

      // Ignore pings (keep-alive).
      es.addEventListener('ping', () => {});
    };

    connect();

    return () => {
      es?.close();
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Derive graph nodes and links from agents map.
  const graphNodes: GraphNode[] = [];
  const graphLinks: GraphLink[] = [];

  for (const [id, agent] of agents) {
    graphNodes.push({
      id,
      name: id,
      status: agent.status,
      depth: agent.depth,
      val: agent.status === 'running' ? 8 : 4,
    });
    if (agent.parent_id && agents.has(agent.parent_id)) {
      graphLinks.push({
        source: agent.parent_id,
        target: id,
      });
    }
  }

  return {
    agents,
    graphNodes,
    graphLinks,
    notepads,
    selectedAgent,
    setSelectedAgent,
    isConnected,
    isDone,
  };
}
