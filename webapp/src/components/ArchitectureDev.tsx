import { useEffect, useState } from 'react';
import Mermaid from './Mermaid';
import { IconChartLine, IconCode, IconBox } from '@tabler/icons-react';

export default function ArchitectureDev() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    fetch('/api/index')
      .then(res => res.json())
      .then(setData)
      .catch(console.error);
  }, []);

  const mermaidChart = `graph TD
  A[Scanner] --> B[Planner]
  B --> C[Explorer]
  C --> D[Reducer]
  D --> E[Renderer]
`;

  return (
    <div className="h-full overflow-auto p-8 bg-gray-50 font-sans">
      <div className="max-w-4xl mx-auto space-y-6">
        <header className="border-b border-black pb-4 mb-8">
          <h1 className="text-2xl font-bold font-mono">Development Architecture Viewer</h1>
          <p className="text-sm text-gray-500 mt-1">Internal view for debugging docbot pipeline and graph state.</p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
            <div className="flex items-center gap-2 mb-4">
              <IconChartLine size={20} className="text-blue-600" />
              <h2 className="text-lg font-bold uppercase tracking-tight">Pipeline Flow</h2>
            </div>
            <Mermaid chart={mermaidChart} />
          </div>

          <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
            <div className="flex items-center gap-2 mb-4">
              <IconBox size={20} className="text-green-600" />
              <h2 className="text-lg font-bold uppercase tracking-tight">Project Stats</h2>
            </div>
            {data ? (
              <div className="space-y-4">
                <div className="flex justify-between items-center border-b border-gray-100 pb-2">
                  <span className="text-xs font-bold text-gray-400">SCOPES</span>
                  <span className="font-mono text-sm">{data.scope_count}</span>
                </div>
                <div className="flex justify-between items-center border-b border-gray-100 pb-2">
                  <span className="text-xs font-bold text-gray-400">PUBLIC SYMBOLS</span>
                  <span className="font-mono text-sm">{data.public_api_count}</span>
                </div>
                <div className="flex justify-between items-center border-b border-gray-100 pb-2">
                  <span className="text-xs font-bold text-gray-400">ENTRYPOINTS</span>
                  <span className="font-mono text-sm">{data.entrypoints?.length || 0}</span>
                </div>
              </div>
            ) : (
              <div className="animate-pulse text-gray-400 font-mono text-center py-8">Loading stats...</div>
            )}
          </div>
        </div>

        <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(30,58,138,0.1)]">
          <div className="flex items-center gap-2 mb-4">
            <IconCode size={20} className="text-purple-600" />
            <h2 className="text-lg font-bold uppercase tracking-tight">Raw Index Metadata</h2>
          </div>
          <pre className="text-[10px] bg-gray-50 p-4 border border-gray-100 overflow-auto max-h-[400px] font-mono">
            {data ? JSON.stringify(data, null, 2) : 'Loading...'}
          </pre>
        </div>
      </div>
    </div>
  );
}
