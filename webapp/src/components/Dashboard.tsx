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

interface ExpandableCardProps {
  icon: React.ReactNode;
  count: number;
  label: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function ExpandableCard({ icon, count, label, expanded, onToggle, children }: ExpandableCardProps) {
  return (
    <div className="bg-white border border-black shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-center gap-3 cursor-pointer hover:bg-gray-50 transition-colors"
      >
        {icon}
        <div className="text-left flex-1">
          <div className="text-2xl font-bold font-mono">{count}</div>
          <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
        </div>
        {expanded
          ? <IconChevronDown size={18} className="text-gray-400" />
          : <IconChevronRight size={18} className="text-gray-400" />
        }
      </button>
      {expanded && (
        <div className="border-t border-gray-200 p-4 max-h-80 overflow-auto">
          {children}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<IndexData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedCards, setExpandedCards] = useState<Set<string>>(new Set());

  const toggleCard = (card: string) => {
    setExpandedCards(prev => {
      const next = new Set(prev);
      if (next.has(card)) next.delete(card);
      else next.add(card);
      return next;
    });
  };

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
                {/* Scopes */}
                <ExpandableCard
                  icon={<IconBook size={24} className="text-blue-600" />}
                  count={data.scope_count}
                  label="Scopes"
                  expanded={expandedCards.has('scopes')}
                  onToggle={() => toggleCard('scopes')}
                >
                  <div className="space-y-2">
                    {(data.scopes || []).map(scope => (
                      <div key={scope.scope_id} className="flex items-start gap-2 py-1.5 border-b border-gray-100 last:border-0">
                        <div className="flex-1 min-w-0">
                          <div className="font-mono text-sm font-medium truncate">{scope.title}</div>
                          <div className="text-xs text-gray-500">
                            {scope.file_count} file{scope.file_count !== 1 ? 's' : ''}
                            {' · '}
                            {scope.symbol_count} entit{scope.symbol_count !== 1 ? 'ies' : 'y'}
                            {scope.languages.length > 0 && (
                              <> · {scope.languages.join(', ')}</>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </ExpandableCard>

                {/* Public API */}
                <ExpandableCard
                  icon={<IconCode size={24} className="text-green-600" />}
                  count={data.public_api_count}
                  label="Public API"
                  expanded={expandedCards.has('symbols')}
                  onToggle={() => toggleCard('symbols')}
                >
                  <div className="space-y-4">
                    {Object.entries(data.public_api_by_scope || {}).map(([scopeTitle, symbols]) => (
                      <div key={scopeTitle}>
                        <div className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-1.5">{scopeTitle}</div>
                        <div className="space-y-1">
                          {symbols.map((sym, i) => (
                            <div key={i} className="py-1 border-b border-gray-100 last:border-0">
                              <div className="flex items-center gap-1.5">
                                <span className={`inline-block px-1 py-0.5 text-[10px] font-mono font-bold uppercase rounded ${
                                  sym.kind === 'class' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                                }`}>
                                  {sym.kind === 'class' ? 'cls' : 'fn'}
                                </span>
                                <span className="font-mono text-sm truncate">{sym.name}</span>
                              </div>
                              {sym.docstring && (
                                <div className="text-xs text-gray-500 ml-7 truncate">{sym.docstring}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </ExpandableCard>

                {/* Entrypoints */}
                <ExpandableCard
                  icon={<IconFiles size={24} className="text-orange-600" />}
                  count={data.entrypoints.length}
                  label="Entrypoints"
                  expanded={expandedCards.has('entrypoints')}
                  onToggle={() => toggleCard('entrypoints')}
                >
                  <div className="space-y-3">
                    {Object.entries(data.entrypoint_groups || {}).map(([group, paths]) => (
                      <div key={group}>
                        <div className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-1">{group}/</div>
                        <div className="space-y-0.5">
                          {paths.map(ep => (
                            <div key={ep} className="font-mono text-sm text-gray-700 py-0.5 truncate">
                              {ep}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </ExpandableCard>
            </div>

            {/* Analysis Section */}
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
                        Run `docbot run` with an OPENROUTER_KEY to generate one.
                    </div>
                )}
            </div>

        </div>
    </div>
  );
}
