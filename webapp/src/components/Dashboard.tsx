import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { IconChartBar, IconFiles, IconCode, IconBook, IconCpu, IconChevronDown, IconChevronRight } from '@tabler/icons-react';

interface ScopeSummary {
  scope_id: string;
  title: string;
  file_count: number;
  symbol_count: number;
  languages: string[];
}

interface PublicSymbolItem {
  name: string;
  kind: string;
  signature: string;
  docstring: string | null;
  file: string;
  line: number;
}

interface ScopeDetail {
  scope_id: string;
  title: string;
  summary: string;
  paths: string[];
  public_api: PublicSymbolItem[];
  entrypoints: string[];
}

interface IndexData {
  repo_path: string;
  generated_at: string;
  languages: string[];
  scope_count: number;
  public_api_count: number;
  entrypoints: string[];
  cross_scope_analysis: string | null;
  scopes: ScopeSummary[];
  public_api_by_scope: Record<string, PublicSymbolItem[]>;
  entrypoint_groups: Record<string, string[]>;
}

export default function Dashboard() {
  const [data, setData] = useState<IndexData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scopeDetails, setScopeDetails] = useState<Record<string, ScopeDetail>>({});
  const [expandedScopes, setExpandedScopes] = useState<Set<string>>(new Set());
  const [expandedSymbolScopes, setExpandedSymbolScopes] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetch('/api/index')
      .then(res => res.json())
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Fetch scope details for all scopes once we have the index
  useEffect(() => {
    if (!data) return;
    for (const scope of data.scopes) {
      fetch(`/api/scopes/${scope.scope_id}`)
        .then(res => res.json())
        .then(detail => {
          setScopeDetails(prev => ({ ...prev, [scope.scope_id]: detail }));
        })
        .catch(console.error);
    }
  }, [data]);

  const toggleScope = (id: string) => {
    setExpandedScopes(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSymbolScope = (key: string) => {
    setExpandedSymbolScopes(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

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
                    {data.repo_path.split(/[/\\]/).pop()}
                </h1>
                <div className="flex items-center gap-4 text-sm text-gray-500 mt-2 font-mono">
                    <span>Generated: {new Date(data.generated_at).toLocaleString()}</span>
                    <span>·</span>
                    <span className="uppercase">{data.languages.join(', ') || 'Unknown'}</span>
                </div>
            </div>

            {/* Stats Row */}
            <div className="grid grid-cols-3 gap-4">
                <div className="bg-white border border-black p-4 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                    <div className="flex items-center gap-3">
                        <IconBook size={24} className="text-blue-600" />
                        <div>
                            <div className="text-2xl font-bold font-mono">{data.scope_count}</div>
                            <div className="text-xs uppercase tracking-wide text-gray-500">Scopes</div>
                        </div>
                    </div>
                </div>
                <div className="bg-white border border-black p-4 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                    <div className="flex items-center gap-3">
                        <IconCode size={24} className="text-green-600" />
                        <div>
                            <div className="text-2xl font-bold font-mono">{data.public_api_count}</div>
                            <div className="text-xs uppercase tracking-wide text-gray-500">Public Symbols</div>
                        </div>
                    </div>
                </div>
                <div className="bg-white border border-black p-4 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                    <div className="flex items-center gap-3">
                        <IconFiles size={24} className="text-orange-600" />
                        <div>
                            <div className="text-2xl font-bold font-mono">{data.entrypoints.length}</div>
                            <div className="text-xs uppercase tracking-wide text-gray-500">Entrypoints</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Architecture Analysis */}
            <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                    <IconChartBar className="text-purple-600" />
                    <h2 className="text-lg font-bold uppercase tracking-wide">Architecture Analysis</h2>
                </div>

                {data.cross_scope_analysis ? (
                    <div className="prose prose-sm max-w-none font-sans leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {data.cross_scope_analysis}
                        </ReactMarkdown>
                    </div>
                ) : (
                    <div className="text-gray-400 italic font-mono py-8 text-center border-2 border-dashed border-gray-200">
                        No architecture analysis found.<br/>
                        Run docbot with an OPENROUTER_KEY to generate one.
                    </div>
                )}
            </div>

            {/* Scopes Section */}
            <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                    <IconBook className="text-blue-600" />
                    <h2 className="text-lg font-bold uppercase tracking-wide">Scopes</h2>
                    <span className="text-sm text-gray-400 ml-auto font-mono">{data.scope_count} total</span>
                </div>
                <p className="text-sm text-gray-500 mb-4">
                    Each scope groups related files into a logical module. Click a scope to see its summary and files.
                </p>
                <div className="space-y-3">
                    {(data.scopes || []).map(scope => {
                        const detail = scopeDetails[scope.scope_id];
                        const isExpanded = expandedScopes.has(scope.scope_id);
                        return (
                            <div key={scope.scope_id} className="border border-gray-200 rounded-lg overflow-hidden">
                                <button
                                    onClick={() => toggleScope(scope.scope_id)}
                                    className="w-full p-4 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
                                >
                                    {isExpanded
                                        ? <IconChevronDown size={16} className="text-gray-400 shrink-0" />
                                        : <IconChevronRight size={16} className="text-gray-400 shrink-0" />
                                    }
                                    <div className="flex-1 min-w-0">
                                        <div className="font-mono text-sm font-bold">{scope.title}</div>
                                        <div className="text-xs text-gray-500 mt-0.5">
                                            {scope.file_count} file{scope.file_count !== 1 ? 's' : ''}
                                            {' · '}
                                            {scope.symbol_count} symbol{scope.symbol_count !== 1 ? 's' : ''}
                                            {scope.languages.length > 0 && (
                                                <> · {scope.languages.join(', ')}</>
                                            )}
                                        </div>
                                    </div>
                                </button>
                                {isExpanded && (
                                    <div className="border-t border-gray-200 p-4 bg-gray-50 space-y-4">
                                        {detail ? (
                                            <>
                                                <div className="prose prose-sm max-w-none text-gray-700">
                                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                        {detail.summary || 'No summary available.'}
                                                    </ReactMarkdown>
                                                </div>
                                                {detail.paths.length > 0 && (
                                                    <div>
                                                        <div className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">Files</div>
                                                        <div className="grid grid-cols-2 gap-1">
                                                            {detail.paths.map(path => (
                                                                <div key={path} className="font-mono text-xs text-gray-600 truncate py-0.5">
                                                                    {path}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </>
                                        ) : (
                                            <div className="animate-pulse text-gray-400 font-mono text-sm">Loading...</div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Public Symbols Section */}
            <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                    <IconCode className="text-green-600" />
                    <h2 className="text-lg font-bold uppercase tracking-wide">Public Symbols</h2>
                    <span className="text-sm text-gray-400 ml-auto font-mono">{data.public_api_count} total</span>
                </div>
                <p className="text-sm text-gray-500 mb-4">
                    Functions and classes exported from each scope that form the public API of this codebase.
                </p>
                <div className="space-y-3">
                    {Object.entries(data.public_api_by_scope || {}).map(([scopeTitle, symbols]) => {
                        const isExpanded = expandedSymbolScopes.has(scopeTitle);
                        return (
                            <div key={scopeTitle} className="border border-gray-200 rounded-lg overflow-hidden">
                                <button
                                    onClick={() => toggleSymbolScope(scopeTitle)}
                                    className="w-full p-4 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
                                >
                                    {isExpanded
                                        ? <IconChevronDown size={16} className="text-gray-400 shrink-0" />
                                        : <IconChevronRight size={16} className="text-gray-400 shrink-0" />
                                    }
                                    <div className="flex-1 min-w-0">
                                        <div className="font-mono text-sm font-bold">{scopeTitle}</div>
                                        <div className="text-xs text-gray-500 mt-0.5">
                                            {symbols.length} symbol{symbols.length !== 1 ? 's' : ''}
                                        </div>
                                    </div>
                                </button>
                                {isExpanded && (
                                    <div className="border-t border-gray-200 p-4 bg-gray-50 max-h-96 overflow-auto">
                                        <div className="space-y-2">
                                            {symbols.map((sym, i) => (
                                                <div key={i} className="py-1.5 border-b border-gray-100 last:border-0">
                                                    <div className="flex items-center gap-2">
                                                        <span className={`inline-block px-1.5 py-0.5 text-[10px] font-mono font-bold uppercase rounded ${
                                                            sym.kind === 'class' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                                                        }`}>
                                                            {sym.kind === 'class' ? 'cls' : 'fn'}
                                                        </span>
                                                        <span className="font-mono text-sm font-medium">{sym.name}</span>
                                                        <span className="font-mono text-xs text-gray-400 ml-auto truncate max-w-[200px]">{sym.file}:{sym.line}</span>
                                                    </div>
                                                    {sym.signature && (
                                                        <div className="font-mono text-xs text-gray-500 mt-1 ml-8 truncate">{sym.signature}</div>
                                                    )}
                                                    {sym.docstring && (
                                                        <div className="text-xs text-gray-600 mt-1 ml-8">{sym.docstring}</div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Entrypoints Section */}
            <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                    <IconFiles className="text-orange-600" />
                    <h2 className="text-lg font-bold uppercase tracking-wide">Entrypoints</h2>
                    <span className="text-sm text-gray-400 ml-auto font-mono">{data.entrypoints.length} total</span>
                </div>
                <p className="text-sm text-gray-500 mb-4">
                    Files that serve as entry points to the application — main scripts, server starts, and CLI commands.
                </p>
                <div className="space-y-3">
                    {Object.entries(data.entrypoint_groups || {}).map(([group, paths]) => (
                        <div key={group} className="border border-gray-200 rounded-lg p-4">
                            <div className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">{group}/</div>
                            <div className="space-y-1">
                                {paths.map(ep => (
                                    <div key={ep} className="font-mono text-sm text-gray-700 py-0.5 flex items-center gap-2">
                                        <IconFiles size={14} className="text-orange-400 shrink-0" />
                                        <span className="truncate">{ep}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

        </div>
    </div>
  );
}
