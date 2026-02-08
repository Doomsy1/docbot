/** TypeScript types for the agent exploration visualization. */

export interface AgentNode {
  agent_id: string;
  parent_id: string | null;
  purpose: string;
  depth: number;
  status: 'running' | 'done' | 'error';
  text: string;
  tools: ToolCall[];
  summary?: string;
  error?: string;
}

export interface ToolCall {
  tool: string;
  input: string;
  status: 'running' | 'done';
  output?: string;
}

export interface NoteEntry {
  content: string;
  author: string;
}

export interface AgentEvent {
  type: string;
  agent_id?: string;
  parent_id?: string;
  purpose?: string;
  depth?: number;
  token?: string;
  tool?: string;
  input?: string;
  output?: string;
  summary?: string;
  error?: string;
  topic?: string;
  content?: string;
  author?: string;
}

export interface GraphNode {
  id: string;
  name: string;
  status: 'running' | 'done' | 'error';
  depth: number;
  val: number;
}

export interface GraphLink {
  source: string;
  target: string;
}
