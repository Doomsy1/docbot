import { useEffect, useState } from 'react';
import { IconFile } from '@tabler/icons-react';
import Mermaid from './Mermaid';

interface ScopeMeta {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
  group: string;
}

interface ScopeDetail {
  scope_id: string;
  title: string;
  summary: string;
  paths: string[];
}

interface GraphProps {
  onSelectFile?: (path: string) => void;
}

interface GraphResponse {
  scopes: ScopeMeta[];
  scope_edges: Array<{ from: string; to: string }>;
  mermaid_graph: string | null;
}

export default function Graph({ onSelectFile }: GraphProps) {
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [selectedScopeId, setSelectedScopeId] = useState<string | null>(null);
  const [scopeDetail, setScopeDetail] = useState<ScopeDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/graph');
        const data = await res.json();
        setGraphData({
          scopes: data.scopes || [],
          scope_edges: data.scope_edges || [],
          mermaid_graph: data.mermaid_graph || null,
        });
      } catch (err) {
        console.error('Failed to fetch graph', err);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  useEffect(() => {
    if (!selectedScopeId) {
      setScopeDetail(null);
      return;
    }
    async function fetchDetail() {
      try {
        const res = await fetch(`/api/scopes/${selectedScopeId}`);
        if (!res.ok) {
          throw new Error('Failed to fetch scope');
        }
        setScopeDetail(await res.json());
      } catch (err) {
        console.error(err);
      }
    }
    fetchDetail();
  }, [selectedScopeId]);

  if (loading) {
    return <div className="h-full p-4 font-mono text-sm">Loading graph data...</div>;
  }

  if (!graphData) {
    return <div className="h-full p-4 font-mono text-sm text-red-600">Failed to load graph data.</div>;
  }

  return (
    <div className="h-full w-full border border-black relative flex overflow-hidden">
      <div className="w-[40%] min-w-[320px] border-r border-black bg-white overflow-auto">
        <div className="p-3 border-b border-black bg-gray-50">
          <h2 className="text-xs font-bold uppercase tracking-wide">Scopes</h2>
        </div>
        <div className="p-2">
          {graphData.scopes.map((scope) => (
            <button
              key={scope.scope_id}
              onClick={() => setSelectedScopeId(scope.scope_id)}
              className={`w-full text-left p-2 border mb-2 ${
                selectedScopeId === scope.scope_id ? 'border-black bg-gray-100' : 'border-gray-200 bg-white'
              }`}
            >
              <div className="font-semibold text-sm">{scope.title}</div>
              <div className="text-xs text-gray-600">
                {scope.file_count} files · {scope.symbol_count} entities · {scope.languages.join(', ') || 'unknown'}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-gray-50 p-4 space-y-4">
        <div className="bg-white border border-black p-3">
          <h2 className="text-xs font-bold uppercase tracking-wide mb-2">Architecture Diagram</h2>
          {graphData.mermaid_graph ? (
            <Mermaid chart={graphData.mermaid_graph} />
          ) : (
            <div className="font-mono text-sm text-gray-600">No mermaid graph available.</div>
          )}
        </div>

        <div className="bg-white border border-black p-3">
          <h2 className="text-xs font-bold uppercase tracking-wide mb-2">Dependencies</h2>
          <pre className="text-xs bg-gray-100 border border-gray-200 p-2 whitespace-pre-wrap break-words">
            {JSON.stringify(graphData.scope_edges, null, 2)}
          </pre>
        </div>
      </div>

      <div className="w-[32%] min-w-[320px] border-l border-black bg-white overflow-auto">
        <div className="p-3 border-b border-black bg-gray-50">
          <h2 className="text-xs font-bold uppercase tracking-wide">Selected Scope</h2>
        </div>
        <div className="p-3">
          {!selectedScopeId && (
            <div className="text-sm text-gray-600">Select a scope to inspect details.</div>
          )}
          {selectedScopeId && !scopeDetail && (
            <div className="text-sm text-gray-600">Loading scope details...</div>
          )}
          {scopeDetail && (
            <div className="space-y-4">
              <div>
                <div className="font-semibold">{scopeDetail.title}</div>
                <div className="text-xs text-gray-500 font-mono">{scopeDetail.scope_id}</div>
              </div>
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wide mb-1">Summary</h3>
                <p className="text-sm text-gray-800">{scopeDetail.summary || 'No summary available.'}</p>
              </div>
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wide mb-1">Files</h3>
                <div className="space-y-1">
                  {scopeDetail.paths.map((path) => (
                    <button
                      key={path}
                      className="w-full text-left flex items-center gap-2 text-sm p-1 hover:bg-gray-100 font-mono text-blue-700"
                      onClick={() => onSelectFile?.(path)}
                    >
                      <IconFile size={14} className="shrink-0 text-gray-500" />
                      <span className="truncate">{path}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
