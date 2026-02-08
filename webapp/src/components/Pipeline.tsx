import { useEffect, useMemo, useState } from 'react';
import { IconActivity, IconTool, IconMessage2, IconRefresh } from '@tabler/icons-react';

type PipelineEvent = {
  type: string;
  timestamp?: number;
  node_id?: string;
  state?: string;
  detail?: string;
  tool?: string;
  args?: Record<string, unknown>;
  text?: string;
};

type PipelineNode = {
  id: string;
  name: string;
  agent_type?: string;
  state: string;
  parent?: string | null;
  detail?: string;
  llm_text?: string;
  tool_calls?: Array<{ name: string; result_preview?: string }>;
};

type PipelinePayload = {
  run_id: string;
  events: PipelineEvent[];
  snapshot?: { nodes: PipelineNode[]; root: string | null };
};

function buildSnapshotFromEvents(events: PipelineEvent[]): PipelineNode[] {
  const nodes = new Map<string, PipelineNode>();
  for (const event of events) {
    if (event.type === 'add' && event.node_id) {
      nodes.set(event.node_id, {
        id: event.node_id,
        name: String((event as Record<string, unknown>).name ?? event.node_id),
        state: 'pending',
        parent: (event as Record<string, unknown>).parent_id as string | undefined,
        agent_type: (event as Record<string, unknown>).agent_type as string | undefined,
      });
    }
    if (event.type === 'state' && event.node_id) {
      const current = nodes.get(event.node_id);
      if (!current) continue;
      current.state = event.state || current.state;
      current.detail = event.detail || current.detail;
    }
    if (event.type === 'text' && event.node_id && event.text) {
      const current = nodes.get(event.node_id);
      if (!current) continue;
      current.llm_text = ((current.llm_text || '') + event.text).slice(-1000);
    }
    if (event.type === 'tool_call' && event.node_id && event.tool) {
      const current = nodes.get(event.node_id);
      if (!current) continue;
      current.tool_calls = current.tool_calls || [];
      current.tool_calls.push({
        name: event.tool,
        result_preview: String((event as Record<string, unknown>).result_preview || ''),
      });
      if (current.tool_calls.length > 5) {
        current.tool_calls = current.tool_calls.slice(-5);
      }
    }
  }
  return Array.from(nodes.values());
}

export default function Pipeline() {
  const [payload, setPayload] = useState<PipelinePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    fetch('/api/pipeline')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setPayload(data);
        setError(null);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, []);

  const nodes = useMemo(
    () => payload?.snapshot?.nodes || buildSnapshotFromEvents(payload?.events || []),
    [payload],
  );

  const counts = useMemo(() => {
    const events = payload?.events || [];
    return {
      total: events.length,
      llm: events.filter((e) => e.type === 'text').length,
      tools: events.filter((e) => e.type === 'tool_call').length,
    };
  }, [payload]);

  if (loading) return <div className="p-6 font-mono text-sm text-gray-500">Loading pipeline events...</div>;
  if (error) return <div className="p-6 font-mono text-sm text-red-600">Failed to load pipeline events: {error}</div>;
  if (!payload) return <div className="p-6 font-mono text-sm text-gray-500">No pipeline data available.</div>;

  return (
    <div className="h-full overflow-auto bg-gray-50">
      <div className="max-w-6xl mx-auto p-8 space-y-6">
        <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
          <div className="flex items-center gap-3">
            <IconActivity className="text-blue-600" />
            <h2 className="text-lg font-bold uppercase tracking-wide">Pipeline Logs</h2>
            <button onClick={load} className="ml-auto text-xs font-mono border border-black px-2 py-1 hover:bg-black hover:text-white">
              <span className="inline-flex items-center gap-1"><IconRefresh size={14} /> refresh</span>
            </button>
          </div>
          <div className="mt-3 text-sm font-mono text-gray-600">
            run: {payload.run_id} • events: {counts.total} • llm text: {counts.llm} • tool calls: {counts.tools}
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <div className="bg-white border border-black p-5 shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]">
            <h3 className="text-sm font-bold uppercase tracking-wide mb-3">Agent/Stage Nodes</h3>
            <div className="space-y-2 max-h-[520px] overflow-auto">
              {nodes.map((node) => (
                <div key={node.id} className="border border-gray-200 rounded p-3 bg-gray-50">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs bg-gray-200 px-1.5 py-0.5 rounded">{node.state}</span>
                    <span className="font-mono text-sm font-bold">{node.name}</span>
                    {node.agent_type && <span className="text-[10px] uppercase text-gray-500 ml-auto">{node.agent_type}</span>}
                  </div>
                  {node.detail && <div className="text-xs text-gray-700 mt-1">{node.detail}</div>}
                  {node.llm_text && (
                    <div className="mt-2 text-xs text-gray-700 border border-gray-200 bg-white p-2 rounded">
                      <div className="inline-flex items-center gap-1 font-semibold text-gray-500 mb-1"><IconMessage2 size={12} /> llm</div>
                      <div className="font-mono whitespace-pre-wrap">{node.llm_text.slice(-400)}</div>
                    </div>
                  )}
                  {node.tool_calls && node.tool_calls.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {node.tool_calls.map((tool, idx) => (
                        <div key={`${node.id}-${idx}`} className="text-xs border border-gray-200 bg-white rounded p-2">
                          <div className="inline-flex items-center gap-1 font-semibold"><IconTool size={12} /> {tool.name}</div>
                          {tool.result_preview && <div className="font-mono text-gray-600 mt-1">{tool.result_preview}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="bg-white border border-black p-5 shadow-[6px_6px_0px_0px_rgba(0,0,0,1)]">
            <h3 className="text-sm font-bold uppercase tracking-wide mb-3">Event Stream</h3>
            <div className="space-y-2 max-h-[520px] overflow-auto">
              {[...(payload.events || [])].reverse().slice(0, 250).map((event, idx) => (
                <div key={idx} className="border border-gray-200 rounded p-2 font-mono text-xs bg-gray-50">
                  <div className="text-gray-500">
                    {event.timestamp?.toFixed?.(2) ?? '0.00'}s • {event.type} • {event.node_id || '-'}
                  </div>
                  {event.state && <div>state: {event.state}</div>}
                  {event.tool && <div>tool: {event.tool}</div>}
                  {event.detail && <div>detail: {event.detail}</div>}
                  {event.text && <div className="whitespace-pre-wrap text-gray-700">{event.text.slice(0, 160)}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

