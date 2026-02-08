import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { IconArrowLeft, IconArrowRight, IconLoader2, IconSend } from '@tabler/icons-react';
import AdaptiveMixedGraph from './AdaptiveMixedGraph';
import type { MixedEdge, MixedNode } from './AdaptiveMixedGraph';

type ViewLevel = 'scope' | 'module' | 'file' | 'entity';

interface Message {
  id: string;
  sender: 'user' | 'bot';
  text: string;
}

interface GraphState {
  view: ViewLevel;
  focus_scope_id: string | null;
  focus_module_id: string | null;
  focus_file_id: string | null;
}

interface GraphScene {
  state: GraphState;
  nodes: MixedNode[];
  edges: MixedEdge[];
  highlighted_node_id?: string | null;
  metrics: {
    node_count: number;
    edge_count: number;
    scope_nodes: number;
    module_nodes: number;
    file_nodes: number;
    entity_nodes: number;
  };
}

interface RoutingInfo {
  router: string;
  reason: string;
  latency_ms: number;
  query?: string;
}

interface ExploreResponse {
  answer_markdown: string;
  scene: GraphScene;
  routing: RoutingInfo;
  debug?: Record<string, unknown>;
}

interface TransitionResponse {
  scene: GraphScene;
  routing: RoutingInfo;
}

interface GraphHistoryItem {
  scene: GraphScene;
  routing: RoutingInfo;
}

export default function DynamicGraphChat() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [scene, setScene] = useState<GraphScene | null>(null);
  const [routing, setRouting] = useState<RoutingInfo | null>(null);
  const [debugInfo, setDebugInfo] = useState<Record<string, unknown> | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    { id: 'intro', sender: 'bot', text: 'Ask a question and I will adapt the graph depth and scope automatically.' },
  ]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isolatedEntityId, setIsolatedEntityId] = useState<string | null>(null);

  const [history, setHistory] = useState<GraphHistoryItem[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const historyIndexRef = useRef(-1);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    historyIndexRef.current = historyIndex;
  }, [historyIndex]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const commitScene = (nextScene: GraphScene, nextRouting: RoutingInfo) => {
    setScene(nextScene);
    setRouting(nextRouting);
    setIsolatedEntityId(null);
    setHistory((prev) => {
      const idx = historyIndexRef.current;
      const head = idx >= 0 ? prev.slice(0, idx + 1) : prev;
      const last = head.length ? head[head.length - 1] : null;
      if (last && JSON.stringify(last.scene.state) === JSON.stringify(nextScene.state) && last.scene.nodes.length === nextScene.nodes.length) {
        return head;
      }
      const updated = [...head, { scene: nextScene, routing: nextRouting }];
      const nextIndex = updated.length - 1;
      historyIndexRef.current = nextIndex;
      setHistoryIndex(nextIndex);
      return updated;
    });
  };

  const loadInitial = async () => {
    const res = await fetch('/api/graph/initial');
    if (!res.ok) throw new Error(`initial graph failed: ${res.status}`);
    const data = (await res.json()) as TransitionResponse;
    commitScene(data.scene, data.routing);
  };

  useEffect(() => {
    loadInitial().catch((e) => {
      setMessages((prev) => [...prev, { id: `${Date.now()}-initerr`, sender: 'bot', text: `Failed to load graph: ${e}` }]);
    });
  }, []);

  const send = async () => {
    const query = input.trim();
    if (!query || loading || !scene) return;
    setLoading(true);
    setMessages((prev) => [...prev, { id: `${Date.now()}-u`, sender: 'user', text: query }]);
    setInput('');

    try {
      const res = await fetch('/api/explore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, state: scene.state }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `explore failed: ${res.status}`);
      }
      const data = (await res.json()) as ExploreResponse;
      commitScene(data.scene, data.routing);
      setDebugInfo(data.debug ?? null);
      setSelectedNodeId(data.scene.highlighted_node_id ?? null);
      setMessages((prev) => [...prev, { id: `${Date.now()}-b`, sender: 'bot', text: data.answer_markdown }]);
    } catch (e) {
      setMessages((prev) => [...prev, { id: `${Date.now()}-err`, sender: 'bot', text: `Explore failed: ${e}` }]);
    } finally {
      setLoading(false);
    }
  };

  const transitionByClick = useCallback(async (node: MixedNode) => {
    if (!scene || loading) return;
    setSelectedNodeId(node.id);
    if (node.kind === 'entity') {
      setIsolatedEntityId((prev) => (prev === node.id ? null : node.id));
      return;
    }
    setIsolatedEntityId(null);
    try {
      const res = await fetch('/api/graph/transition', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: scene.state, node_id: node.id, node_kind: node.kind }),
      });
      if (!res.ok) throw new Error(`transition failed: ${res.status}`);
      const data = (await res.json()) as TransitionResponse;
      commitScene(data.scene, data.routing);
      setMessages((prev) => [...prev, { id: `${Date.now()}-t`, sender: 'bot', text: data.routing.reason }]);
    } catch (e) {
      setMessages((prev) => [...prev, { id: `${Date.now()}-terr`, sender: 'bot', text: `Transition failed: ${e}` }]);
    }
  }, [scene, loading]);

  const handleGraphInteract = useCallback(() => {
    if (isolatedEntityId) setIsolatedEntityId(null);
  }, [isolatedEntityId]);

  const goBack = () => {
    if (historyIndex <= 0) return;
    setIsolatedEntityId(null);
    const nextIndex = historyIndex - 1;
    const item = history[nextIndex];
    setHistoryIndex(nextIndex);
    historyIndexRef.current = nextIndex;
    setScene(item.scene);
    setRouting(item.routing);
    setSelectedNodeId(item.scene.highlighted_node_id ?? null);
  };

  const goForward = () => {
    if (historyIndex < 0 || historyIndex >= history.length - 1) return;
    setIsolatedEntityId(null);
    const nextIndex = historyIndex + 1;
    const item = history[nextIndex];
    setHistoryIndex(nextIndex);
    historyIndexRef.current = nextIndex;
    setScene(item.scene);
    setRouting(item.routing);
    setSelectedNodeId(item.scene.highlighted_node_id ?? null);
  };

  return (
    <div className="h-full grid grid-cols-12 gap-4 p-4 bg-gray-50">
      <div className="col-span-8 border border-black bg-white p-3 overflow-hidden flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-bold uppercase tracking-wide">Adaptive Graph</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={goBack}
              disabled={historyIndex <= 0 || loading}
              className="inline-flex items-center justify-center h-7 w-7 border border-black bg-white hover:bg-black hover:text-white disabled:opacity-40"
              aria-label="Graph back"
              title="Back"
            >
              <IconArrowLeft size={14} />
            </button>
            <button
              onClick={goForward}
              disabled={historyIndex < 0 || historyIndex >= history.length - 1 || loading}
              className="inline-flex items-center justify-center h-7 w-7 border border-black bg-white hover:bg-black hover:text-white disabled:opacity-40"
              aria-label="Graph forward"
              title="Forward"
            >
              <IconArrowRight size={14} />
            </button>
            {loading && (
              <span className="text-xs text-gray-500 flex items-center gap-1">
                <IconLoader2 size={12} className="animate-spin" /> updating
              </span>
            )}
          </div>
        </div>

        <div className="mb-2 border border-gray-300 bg-gray-50 p-2 text-xs text-gray-700">
          {routing && (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <div><span className="font-semibold">View:</span> {scene?.state.view}</div>
              <div><span className="font-semibold">Router:</span> {routing.router}</div>
              <div><span className="font-semibold">Reason:</span> {routing.reason}</div>
              <div><span className="font-semibold">Latency:</span> {routing.latency_ms}ms</div>
              {scene && <div><span className="font-semibold">Nodes/Edges:</span> {scene.metrics.node_count}/{scene.metrics.edge_count}</div>}
            </div>
          )}
        </div>

        <div className="flex-1 min-h-0">
          {scene ? (
            <AdaptiveMixedGraph
              nodes={scene.nodes}
              edges={scene.edges}
              highlightedNodeId={scene.highlighted_node_id ?? null}
              selectedNodeId={selectedNodeId}
              isolatedEntityId={isolatedEntityId}
              onNodeClick={transitionByClick}
              onGraphInteract={handleGraphInteract}
              fitTargetId={scene.highlighted_node_id ?? scene.state.focus_file_id ?? scene.state.focus_module_id ?? scene.state.focus_scope_id ?? null}
            />
          ) : (
            <div className="h-full border border-gray-300 bg-gray-100 flex items-center justify-center text-gray-500 text-sm">
              No graph loaded.
            </div>
          )}
        </div>
      </div>

      <div className="col-span-4 border border-black bg-white flex flex-col min-h-0">
        <div ref={scrollRef} className="flex-1 overflow-auto p-4 space-y-4">
          {messages.map((m) => (
            <div key={m.id} className={m.sender === 'user' ? 'text-right' : 'text-left'}>
              <div className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">{m.sender}</div>
              <div className={`inline-block text-left max-w-[96%] p-3 border ${m.sender === 'user' ? 'bg-gray-100' : 'bg-white'}`}>
                <div className="prose prose-sm max-w-none">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ children }) => <p className="mb-2 last:mb-0 leading-6">{children}</p>,
                      ul: ({ children }) => <ul className="my-2 list-disc pl-5 space-y-1">{children}</ul>,
                      ol: ({ children }) => <ol className="my-2 list-decimal pl-5 space-y-1">{children}</ol>,
                      li: ({ children }) => <li className="leading-6">{children}</li>,
                      code: ({ children }) => <code className="font-mono text-[12px] bg-gray-100 px-1 py-0.5">{children}</code>,
                    }}
                  >
                    {m.text}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="border-t border-black p-3 bg-gray-50">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
              placeholder="Ask anything about the codebase"
              className="flex-1 border border-black px-3 py-2 text-sm font-mono"
              disabled={loading || !scene}
            />
            <button
              onClick={send}
              disabled={loading || !input.trim() || !scene}
              className="p-3 border border-black bg-white hover:bg-black hover:text-white transition-all disabled:opacity-50 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none"
            >
              {loading ? <IconLoader2 className="animate-spin" size={18} /> : <IconSend size={18} />}
            </button>
          </div>
          {debugInfo && (
            <div className="mt-2 text-[10px] text-gray-500 break-all">
              debug: {Object.entries(debugInfo).slice(0, 4).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
