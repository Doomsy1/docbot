import { useEffect, useState } from 'react';
import Mermaid from './Mermaid';
import ModuleGraph from './ModuleGraph';
import RawScopeGraph from './RawScopeGraph';

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

interface FileNode {
  id: string;
  path: string;
  scope_id: string;
  scope_title: string;
  symbol_count: number;
  import_count: number;
  language: string;
  group: string;
}

interface ScopeGroup {
  scope_id: string;
  title: string;
  file_count: number;
  group: string;
}

interface DetailedGraphResponse {
  file_nodes: FileNode[];
  file_edges: Array<{ from: string; to: string }>;
  scope_groups: ScopeGroup[];
  scope_edges: Array<{ from: string; to: string }>;
}

interface ModuleNode {
  id: string;
  label: string;
  scope_id: string;
  scope_title: string;
  file_count: number;
  symbol_count: number;
  import_count: number;
  languages: string[];
  group: string;
}

interface ModuleGraphResponse {
  module_nodes: ModuleNode[];
  module_edges: Array<{ from: string; to: string; weight: number }>;
  scope_groups: ScopeGroup[];
}

export default function ArchitectureDev() {
  const [indexData, setIndexData] = useState<IndexResponse | null>(null);
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [moduleData, setModuleData] = useState<ModuleGraphResponse | null>(null);
  const [detailedData, setDetailedData] = useState<DetailedGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [indexRes, graphRes, moduleRes, detailedRes] = await Promise.all([
          fetch('/api/index'),
          fetch('/api/graph'),
          fetch('/api/graph/modules'),
          fetch('/api/graph/detailed'),
        ]);

        if (!indexRes.ok) {
          throw new Error(`index request failed: ${indexRes.status}`);
        }
        if (!graphRes.ok) {
          throw new Error(`graph request failed: ${graphRes.status}`);
        }
        if (!moduleRes.ok) {
          throw new Error(`module graph request failed: ${moduleRes.status}`);
        }
        if (!detailedRes.ok) {
          throw new Error(`detailed graph request failed: ${detailedRes.status}`);
        }

        const indexJson = (await indexRes.json()) as IndexResponse;
        const graphJson = (await graphRes.json()) as GraphResponse;
        const moduleJson = (await moduleRes.json()) as ModuleGraphResponse;
        const detailedJson = (await detailedRes.json()) as DetailedGraphResponse;
        setIndexData(indexJson);
        setGraphData(graphJson);
        setModuleData(moduleJson);
        setDetailedData(detailedJson);
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
          <h3 className="font-bold mb-2">Module Graph</h3>
          <p className="text-xs text-gray-500 mb-3">
            Directory-level modules grouped by scope with weighted module-to-module import edges.
          </p>
          {moduleData && moduleData.module_nodes.length > 0 ? (
            <ModuleGraph
              moduleNodes={moduleData.module_nodes}
              moduleEdges={moduleData.module_edges}
              scopeGroups={moduleData.scope_groups}
            />
          ) : (
            <div className="text-sm text-gray-700 font-mono">[no module-level data]</div>
          )}
        </div>

        <div className="bg-white border border-black p-4">
          <h3 className="font-bold mb-2">File-Level Graph</h3>
          <p className="text-xs text-gray-500 mb-3">
            File nodes grouped by scope with file-to-file import edges — shows what the agents actually explored.
          </p>
          {detailedData && detailedData.file_nodes.length > 0 ? (
            <RawScopeGraph
              fileNodes={detailedData.file_nodes}
              fileEdges={detailedData.file_edges}
              scopeGroups={detailedData.scope_groups}
              scopeEdges={detailedData.scope_edges}
            />
          ) : (
            <div className="text-sm text-gray-700 font-mono">[no file-level data]</div>
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
