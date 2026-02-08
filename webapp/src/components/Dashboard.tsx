import { useEffect, useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { IconChartBar, IconFiles, IconCode, IconBook, IconCpu, IconChevronDown, IconChevronRight, IconCloud, IconDatabase, IconBrain, IconApi, IconArrowRight, IconGitCommit, IconHistory } from '@tabler/icons-react';
import Mermaid from './Mermaid';

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

interface ExternalNode {
  id: string;
  title: string;
  icon: string;
  matched_imports?: string[];
}

interface ExternalEdge {
  from: string;
  to: string;
  imports?: string[];
}

interface ScopeEdge {
  from: string;
  to: string;
}

interface GraphData {
  scopes: ScopeSummary[];
  scope_edges: ScopeEdge[];
  external_nodes: ExternalNode[];
  external_edges: ExternalEdge[];
}

interface HistorySnapshot {
  run_id: string;
  timestamp: string;
  commit_sha: string | null;
  commit_msg: string | null;
  scope_count: number;
  symbol_count: number;
  entrypoint_count: number;
}

const SERVICE_ICONS: Record<string, typeof IconCloud> = {
  db: IconDatabase,
  cloud: IconCloud,
  ai: IconBrain,
  api: IconApi,
};

const SERVICE_COLORS: Record<string, { bg: string; badge: string; border: string; text: string }> = {
  db: { bg: 'bg-emerald-50', badge: 'bg-emerald-100 text-emerald-700', border: 'border-emerald-200', text: 'text-emerald-700' },
  cloud: { bg: 'bg-sky-50', badge: 'bg-sky-100 text-sky-700', border: 'border-sky-200', text: 'text-sky-700' },
  ai: { bg: 'bg-violet-50', badge: 'bg-violet-100 text-violet-700', border: 'border-violet-200', text: 'text-violet-700' },
  api: { bg: 'bg-amber-50', badge: 'bg-amber-100 text-amber-700', border: 'border-amber-200', text: 'text-amber-700' },
};

const SERVICE_TYPE_LABELS: Record<string, string> = {
  db: 'Database',
  cloud: 'Cloud Storage',
  ai: 'AI / ML',
  api: 'External API',
  auth: 'Auth Provider',
};

const SERVICE_DESCRIPTIONS: Record<string, string> = {
  ext_mongodb: 'MongoDB is a NoSQL document database used for storing and querying application data as flexible JSON-like documents. Scopes using it likely handle data persistence, CRUD operations, and query logic.',
  ext_postgres: 'PostgreSQL is a relational database used for structured data storage with SQL queries, transactions, and strong consistency guarantees. Scopes using it handle core data models and business logic.',
  ext_redis: 'Redis is an in-memory key-value store commonly used for caching, session management, rate limiting, and pub/sub messaging to improve application performance.',
  ext_mysql: 'MySQL is a relational database used for structured data storage with SQL. Scopes using it manage persistent application state, user records, and transactional data.',
  ext_firebase: 'Firebase is a Google-backed platform providing real-time databases, authentication, hosting, and cloud functions. Scopes using it typically manage user auth, real-time data sync, or push notifications.',
  ext_supabase: 'Supabase is an open-source Firebase alternative built on PostgreSQL, providing a database, auth, real-time subscriptions, and storage APIs.',
  ext_aws_s3: 'AWS S3 (Simple Storage Service) is used for storing and serving files like images, videos, documents, and backups. Scopes using it handle file uploads, asset management, or static content.',
  ext_digitalocean: 'DigitalOcean Spaces or infrastructure is used for cloud hosting, object storage, or compute resources.',
  ext_gcs: 'Google Cloud Storage is used for storing and serving files, media assets, and data blobs in the Google Cloud ecosystem.',
  ext_openai: 'OpenAI provides GPT language models and APIs for text generation, embeddings, image generation, and other AI capabilities. Scopes using it handle AI-powered features like chat, summarization, or content generation.',
  ext_gemini: 'Google Gemini is a multimodal AI model used for text generation, reasoning, image understanding, and other intelligent processing tasks. Scopes using it integrate AI-driven analysis or generation features.',
  ext_anthropic: 'Anthropic provides the Claude family of AI models for text generation, analysis, and reasoning. Scopes using it power AI chat, content generation, or automated analysis features.',
  ext_openrouter: 'Backboard.io is a unified API with persistent memory/RAG that provides access to multiple LLM providers (OpenAI, Anthropic, Google, etc.). Scopes using it make LLM calls for text generation or analysis.',
  ext_auth0: 'Auth0 is an identity platform for authentication and authorization, handling user login, SSO, MFA, and access control.',
  ext_clerk: 'Clerk is a user authentication and management platform providing sign-in/sign-up flows, session management, and user profiles.',
  ext_stripe: 'Stripe is a payment processing platform used for handling credit card payments, subscriptions, invoices, and financial transactions.',
  ext_twilio: 'Twilio provides communication APIs for sending SMS messages, making phone calls, and handling real-time messaging in applications.',
  ext_sendgrid: 'SendGrid is an email delivery service used for sending transactional emails, marketing campaigns, and email notifications.',
  ext_selenium: 'Selenium is a browser automation framework used for web scraping, end-to-end testing, and automated interaction with web pages.',
  ext_playwright: 'Playwright is a browser automation library for web scraping, end-to-end testing, and rendering web pages programmatically across Chromium, Firefox, and WebKit.',
  ext_ffmpeg: 'FFmpeg is a multimedia processing toolkit used for video/audio encoding, decoding, transcoding, and format conversion. Scopes using it handle media processing pipelines.',
  ext_greenhouse: 'Greenhouse is a recruiting and applicant tracking system (ATS). Scopes using it integrate with hiring workflows, job postings, or candidate data.',
};

export default function Dashboard() {
  const [data, setData] = useState<IndexData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scopeDetails, setScopeDetails] = useState<Record<string, ScopeDetail>>({});
  const [expandedScopes, setExpandedScopes] = useState<Set<string>>(new Set());
  const [expandedSymbolScopes, setExpandedSymbolScopes] = useState<Set<string>>(new Set());
  const [expandedServices, setExpandedServices] = useState<Set<string>>(new Set());
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [historyData, setHistoryData] = useState<HistorySnapshot[] | null>(null);
  const [serviceDetails, setServiceDetails] = useState<Record<string, Record<string, string>>>({});
  const [serviceDetailsLoading, setServiceDetailsLoading] = useState(false);
  const [archAnalysis, setArchAnalysis] = useState<string | null>(null);
  const [archAnalysisLoading, setArchAnalysisLoading] = useState(false);

  useEffect(() => {
    fetch('/api/index')
      .then(res => res.json())
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));

    fetch('/api/graph')
      .then(res => res.json())
      .then(d => {
        if (d.scopes) {
          setGraphData(d);
          if (d.external_nodes?.length > 0) {
            setServiceDetailsLoading(true);
            fetch('/api/service-details')
              .then(r => r.json())
              .then(details => { if (details && typeof details === 'object') setServiceDetails(details); })
              .catch(console.error)
              .finally(() => setServiceDetailsLoading(false));
          }
        }
      })
      .catch(console.error);

    fetch('/api/history')
      .then(res => { if (res.ok) return res.json(); return null; })
      .then(d => { if (Array.isArray(d)) setHistoryData(d); })
      .catch(() => {});
  }, []);

  // Fetch architecture analysis on-the-fly if missing from index
  useEffect(() => {
    if (!data) return;
    if (data.cross_scope_analysis) {
      setArchAnalysis(data.cross_scope_analysis);
      return;
    }
    setArchAnalysisLoading(true);
    fetch('/api/architecture-analysis')
      .then(r => { if (r.ok) return r.json(); return null; })
      .then(d => { if (d?.analysis) setArchAnalysis(d.analysis); })
      .catch(() => {})
      .finally(() => setArchAnalysisLoading(false));
  }, [data]);

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

  const toggleService = (id: string) => {
    setExpandedServices(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Build external services → scope mapping with import details
  const serviceUsage = useMemo(() => {
    if (!graphData || !graphData.external_nodes) return [];
    return graphData.external_nodes.map(node => {
      const edges = (graphData.external_edges || []).filter(e => e.to === node.id);
      const usedBy = edges.map(e => {
        const scope = graphData.scopes.find(s => s.scope_id === e.from);
        return {
          scopeId: e.from,
          scopeTitle: scope?.title || e.from,
          imports: e.imports || [],
        };
      });
      return { ...node, usedBy };
    });
  }, [graphData]);

  // Build Mermaid diagram for scope dependencies
  const scopeDepsMermaid = useMemo(() => {
    if (!graphData || !graphData.scope_edges || graphData.scope_edges.length === 0) return null;
    const lines = ['graph LR'];
    const seen = new Set<string>();
    for (const edge of graphData.scope_edges) {
      const fromScope = graphData.scopes.find(s => s.scope_id === edge.from);
      const toScope = graphData.scopes.find(s => s.scope_id === edge.to);
      const fromLabel = fromScope?.title || edge.from;
      const toLabel = toScope?.title || edge.to;
      if (!seen.has(edge.from)) {
        lines.push(`    ${edge.from}["${fromLabel}"]`);
        seen.add(edge.from);
      }
      if (!seen.has(edge.to)) {
        lines.push(`    ${edge.to}["${toLabel}"]`);
        seen.add(edge.to);
      }
      lines.push(`    ${edge.from} --> ${edge.to}`);
    }
    return lines.join('\n');
  }, [graphData]);

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
                    <span>&middot;</span>
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

                {archAnalysis ? (
                    <div className="prose prose-sm max-w-none font-sans leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {archAnalysis}
                        </ReactMarkdown>
                    </div>
                ) : archAnalysisLoading ? (
                    <div className="flex items-center gap-2 text-gray-400 font-mono text-sm py-8 justify-center">
                        <IconCpu className="animate-spin" size={16} />
                        Generating architecture analysis...
                    </div>
                ) : (
                    <div className="text-gray-400 italic font-mono py-8 text-center border-2 border-dashed border-gray-200">
                        No architecture analysis available.
                    </div>
                )}
            </div>

            {/* External Services */}
            {serviceUsage.length > 0 && (
                <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                    <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                        <IconCloud className="text-sky-600" />
                        <h2 className="text-lg font-bold uppercase tracking-wide">External Services</h2>
                        <span className="text-sm text-gray-400 ml-auto font-mono">{serviceUsage.length} detected</span>
                    </div>
                    <p className="text-sm text-gray-500 mb-4">
                        Third-party services and infrastructure dependencies detected in the codebase.
                    </p>
                    <div className="space-y-3">
                        {serviceUsage.map(svc => {
                            const Icon = SERVICE_ICONS[svc.icon] || IconApi;
                            const colors = SERVICE_COLORS[svc.icon] || SERVICE_COLORS.api;
                            const typeLabel = SERVICE_TYPE_LABELS[svc.icon] || 'Service';
                            const isExpanded = expandedServices.has(svc.id);
                            return (
                                <div key={svc.id} className="border border-gray-200 rounded-lg overflow-hidden">
                                    <button
                                        onClick={() => toggleService(svc.id)}
                                        className="w-full p-4 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
                                    >
                                        {isExpanded
                                            ? <IconChevronDown size={16} className="text-gray-400 shrink-0" />
                                            : <IconChevronRight size={16} className="text-gray-400 shrink-0" />
                                        }
                                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${colors.bg} ${colors.text}`}>
                                            <Icon size={18} />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="font-mono text-sm font-bold">{svc.title}</div>
                                            <div className="text-xs text-gray-500 mt-0.5">
                                                {typeLabel} &middot; used by {svc.usedBy.length} scope{svc.usedBy.length !== 1 ? 's' : ''}
                                            </div>
                                        </div>
                                        <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${colors.badge}`}>
                                            {typeLabel}
                                        </span>
                                    </button>
                                    {isExpanded && (
                                        <div className={`border-t border-gray-200 p-4 ${colors.bg} space-y-4`}>
                                            <div className="text-sm text-gray-700 leading-relaxed">
                                                {SERVICE_DESCRIPTIONS[svc.id] || `${svc.title} is an external dependency integrated into this project.`}
                                            </div>
                                            <div>
                                                <div className="text-xs font-bold uppercase tracking-wide text-gray-400 mb-2">Usage by scope</div>
                                                <div className="space-y-2">
                                                    {svc.usedBy.map((usage, i) => {
                                                        const llmDesc = serviceDetails[svc.id]?.[usage.scopeId];
                                                        return (
                                                            <div key={i} className="bg-white/50 border border-gray-200 rounded-lg p-3">
                                                                <div className="flex items-center gap-2 text-sm font-bold font-mono">
                                                                    <IconArrowRight size={12} className="text-gray-400 shrink-0" />
                                                                    {usage.scopeTitle}
                                                                </div>
                                                                {llmDesc ? (
                                                                    <div className="ml-5 mt-1.5 text-sm text-gray-700 leading-relaxed">
                                                                        {llmDesc}
                                                                    </div>
                                                                ) : serviceDetailsLoading ? (
                                                                    <div className="ml-5 mt-1.5 text-xs text-gray-400 animate-pulse">
                                                                        Generating usage description...
                                                                    </div>
                                                                ) : null}
                                                                {usage.imports.length > 0 && (
                                                                    <div className="ml-5 mt-2 flex flex-wrap gap-1.5">
                                                                        {usage.imports.map(imp => (
                                                                            <code key={imp} className="text-[11px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                                                                                {imp}
                                                                            </code>
                                                                        ))}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Dependency Mini-Graph */}
            {scopeDepsMermaid && (
                <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                    <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                        <IconChartBar className="text-indigo-600" />
                        <h2 className="text-lg font-bold uppercase tracking-wide">Scope Dependencies</h2>
                    </div>
                    <p className="text-sm text-gray-500 mb-4">
                        How scopes depend on each other — arrows show import/usage direction.
                    </p>
                    <Mermaid chart={scopeDepsMermaid} />
                </div>
            )}

            {/* History Timeline */}
            {historyData && historyData.length > 0 && (
                <div className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
                    <div className="flex items-center gap-2 mb-6 border-b border-gray-100 pb-2">
                        <IconHistory className="text-teal-600" />
                        <h2 className="text-lg font-bold uppercase tracking-wide">Documentation History</h2>
                        <span className="text-sm text-gray-400 ml-auto font-mono">{historyData.length} snapshot{historyData.length !== 1 ? 's' : ''}</span>
                    </div>
                    <p className="text-sm text-gray-500 mb-4">
                        Past docbot runs showing how the codebase has evolved over time.
                    </p>
                    <div className="relative">
                        <div className="absolute left-[15px] top-4 bottom-4 w-px bg-gray-200" />
                        <div className="space-y-4">
                            {historyData.map((snap, i) => (
                                <div key={snap.run_id} className="flex gap-4 items-start relative">
                                    <div className={`w-[31px] h-[31px] rounded-full border-2 flex items-center justify-center shrink-0 z-10 ${
                                        i === 0
                                            ? 'border-teal-500 bg-teal-50 text-teal-600'
                                            : 'border-gray-300 bg-white text-gray-400'
                                    }`}>
                                        <IconGitCommit size={14} />
                                    </div>
                                    <div className={`flex-1 border rounded-lg p-3 ${i === 0 ? 'border-teal-200 bg-teal-50' : 'border-gray-200 bg-gray-50'}`}>
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="font-mono text-xs font-bold">
                                                {new Date(snap.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                                            </span>
                                            <span className="font-mono text-[10px] text-gray-400">
                                                {new Date(snap.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                                            </span>
                                            {i === 0 && (
                                                <span className="text-[10px] font-bold uppercase bg-teal-500 text-white px-1.5 py-0.5 rounded">Latest</span>
                                            )}
                                        </div>
                                        {snap.commit_msg && (
                                            <div className="text-sm text-gray-700 mb-1.5 truncate">{snap.commit_msg}</div>
                                        )}
                                        <div className="flex gap-4 text-xs font-mono text-gray-500">
                                            <span>{snap.scope_count} scopes</span>
                                            <span>{snap.symbol_count} symbols</span>
                                            <span>{snap.entrypoint_count} entrypoints</span>
                                            {snap.commit_sha && (
                                                <span className="text-gray-400">{snap.commit_sha.slice(0, 7)}</span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

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
                                            {' \u00b7 '}
                                            {scope.symbol_count} symbol{scope.symbol_count !== 1 ? 's' : ''}
                                            {scope.languages.length > 0 && (
                                                <> &middot; {scope.languages.join(', ')}</>
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
