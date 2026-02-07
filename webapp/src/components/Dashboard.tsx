import { useEffect, useState } from 'react';
import { IconChartBar, IconFiles, IconCode, IconBook, IconCpu } from '@tabler/icons-react';

interface IndexData {
  repo_path: string;
  generated_at: string;
  languages: string[];
  scope_count: number;
  public_api_count: number;
  entrypoints: string[];
  cross_scope_analysis: string | null;
}

export default function Dashboard() {
  const [data, setData] = useState<IndexData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/index')
      .then(res => res.json())
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center gap-2">
            <IconCpu className="animate-spin text-gray-400" size={32} />
            <span className="text-gray-400 font-mono">Loading analysis...</span>
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-8 text-red-500 font-mono">Failed to load index.</div>;

  return (
    <div className="h-full overflow-auto bg-gray-50">
        <div className="max-w-4xl mx-auto p-8 space-y-8">
            
            {/* Header */}
            <div className="border-b border-black pb-4">
                <h1 className="text-3xl font-bold font-mono selection:bg-black selection:text-white">
                    {data.repo_path.split('/').pop()}
                </h1>
                <div className="flex items-center gap-4 text-sm text-gray-500 mt-2 font-mono">
                    <span>Generated: {new Date(data.generated_at).toLocaleString()}</span>
                    <span>•</span>
                    <span className="uppercase">{data.languages.join(', ') || 'Unknown'}</span>
                </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-white border border-black p-4 flex items-center gap-3 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                    <IconBook size={24} className="text-blue-600" />
                    <div>
                        <div className="text-2xl font-bold font-mono">{data.scope_count}</div>
                        <div className="text-xs uppercase tracking-wide text-gray-500">Scopes</div>
                    </div>
                </div>
                <div className="bg-white border border-black p-4 flex items-center gap-3 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                    <IconCode size={24} className="text-green-600" />
                    <div>
                        <div className="text-2xl font-bold font-mono">{data.public_api_count}</div>
                        <div className="text-xs uppercase tracking-wide text-gray-500">Public Symbols</div>
                    </div>
                </div>
                <div className="bg-white border border-black p-4 flex items-center gap-3 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                    <IconFiles size={24} className="text-orange-600" />
                    <div>
                        <div className="text-2xl font-bold font-mono">{data.entrypoints.length}</div>
                        <div className="text-xs uppercase tracking-wide text-gray-500">Entrypoints</div>
                    </div>
                </div>
            </div>

            {/* Analysis Section */}
            <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                    <IconChartBar className="text-purple-600" />
                    <h2 className="text-lg font-bold uppercase tracking-wide">Architecture Analysis</h2>
                </div>
                
                {data.cross_scope_analysis ? (
                    <div className="prose prose-sm max-w-none font-sans leading-relaxed whitespace-pre-wrap">
                        {data.cross_scope_analysis}
                    </div>
                ) : (
                    <div className="text-gray-400 italic font-mono py-8 text-center border-2 border-dashed border-gray-200">
                        No architecture analysis found.<br/>
                        Run `docbot run` with an OPENROUTER_KEY to generate one.
                    </div>
                )}
            </div>

        </div>
    </div>
  );
}
