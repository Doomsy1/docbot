import { useEffect, useState } from 'react';
import Mermaid from './Mermaid';

interface IndexResponse {
  repo_path: string;
  generated_at: string;
  cross_scope_analysis: string | null;
}

interface GraphScope {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
  group: string;
}

interface GraphResponse {
  scopes: GraphScope[];
  scope_edges: Array<{ from: string; to: string }>;
  mermaid_graph: string | null;
}

export default function ArchitectureDev() {
  const [indexData, setIndexData] = useState<IndexResponse | null>(null);
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [indexRes, graphRes] = await Promise.all([
          fetch('/api/index'),
          fetch('/api/graph'),
        ]);

        if (!indexRes.ok) {
          throw new Error(`index request failed: ${indexRes.status}`);
        }
        if (!graphRes.ok) {
          throw new Error(`graph request failed: ${graphRes.status}`);
        }

        const indexJson = (await indexRes.json()) as IndexResponse;
        const graphJson = (await graphRes.json()) as GraphResponse;
        setIndexData(indexJson);
        setGraphData(graphJson);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  if (loading) {
    return <div className="h-full p-6 font-mono text-sm">Loading architecture debug data...</div>;
  }

  if (error) {
    return (
      <div className="h-full p-6">
        <div className="border border-red-600 bg-red-50 p-4 font-mono text-sm text-red-700">
          Failed to load architecture debug data: {error}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-gray-50">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        <div className="bg-white border border-black p-4">
          <h2 className="text-lg font-bold">Architecture Debug</h2>
          <div className="mt-2 text-sm text-gray-700">
            <div><span className="font-semibold">Repo:</span> {indexData?.repo_path}</div>
            <div><span className="font-semibold">Generated:</span> {indexData?.generated_at}</div>
            <div><span className="font-semibold">Scopes:</span> {graphData?.scopes.length ?? 0}</div>
            <div><span className="font-semibold">Edges:</span> {graphData?.scope_edges.length ?? 0}</div>
          </div>
        </div>

        <div className="bg-white border border-black p-4">
          <h3 className="font-bold mb-2">Cross-Scope Analysis (raw markdown)</h3>
          <pre className="text-xs whitespace-pre-wrap break-words bg-gray-100 p-3 border border-gray-200">
            {indexData?.cross_scope_analysis || '[empty]'}
          </pre>
        </div>

        <div className="bg-white border border-black p-4">
          <h3 className="font-bold mb-2">Mermaid Graph</h3>
          {graphData?.mermaid_graph ? (
            <>
              <Mermaid chart={graphData.mermaid_graph} />
              <h4 className="font-semibold mt-4 mb-2">Raw Mermaid Source</h4>
              <pre className="text-xs whitespace-pre-wrap break-words bg-gray-100 p-3 border border-gray-200">
                {graphData.mermaid_graph}
              </pre>
            </>
          ) : (
            <div className="text-sm text-gray-700 font-mono">[empty mermaid_graph]</div>
          )}
        </div>

        <div className="bg-white border border-black p-4">
          <h3 className="font-bold mb-2">Scopes and Edges JSON</h3>
          <pre className="text-xs whitespace-pre-wrap break-words bg-gray-100 p-3 border border-gray-200">
            {JSON.stringify(graphData, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
