import { useEffect, useState, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { IconGitCompare, IconPlus, IconMinus, IconEdit, IconChartBar, IconCpu, IconChevronDown, IconChevronRight, IconSend, IconMessageCircle, IconFileDescription, IconTopologyRing } from '@tabler/icons-react';
import DiffGraph from './DiffGraph';

interface HistorySnapshot {
  run_id: string;
  timestamp: string;
  commit_sha: string | null;
  scope_count: number;
  symbol_count: number;
}

interface ModifiedScope {
  scope_id: string;
  added_files: string[];
  removed_files: string[];
  added_symbols: string[];
  removed_symbols: string[];
  summary_changed: boolean;
}

interface DiffReport {
  from_id: string;
  to_id: string;
  from_timestamp: string;
  to_timestamp: string;
  added_scopes: string[];
  removed_scopes: string[];
  modified_scopes: ModifiedScope[];
  graph_changed: boolean;
  stats_delta: {
    total_files: number;
    total_scopes: number;
    total_symbols: number;
  };
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export default function DiffViewer() {
  const [snapshots, setSnapshots] = useState<HistorySnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [fromId, setFromId] = useState<string>('');
  const [toId, setToId] = useState<string>('');
  const [diff, setDiff] = useState<DiffReport | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [expandedMods, setExpandedMods] = useState<Set<string>>(new Set());
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch('/api/history')
      .then(res => {
        if (!res.ok) throw new Error(`Failed to load history: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        // Ensure data is an array
        const snapshotList = Array.isArray(data) ? data : [];
        setSnapshots(snapshotList);
        if (snapshotList.length >= 2) {
          setFromId(snapshotList[1].run_id);
          setToId(snapshotList[0].run_id);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!fromId || !toId || fromId === toId) {
      setDiff(null);
      return;
    }
    setDiffLoading(true);
    setDiffError(null);
    fetch(`/api/changes?from_id=${encodeURIComponent(fromId)}&to_id=${encodeURIComponent(toId)}`)
      .then(res => {
        if (!res.ok) throw new Error(`Failed to load diff: ${res.status}`);
        return res.json();
      })
      .then(d => {
        setDiff(d);
        // Fetch LLM summary for this diff
        setSummary(null);
        setSummaryLoading(true);
        fetch(`/api/diff-summary?from_id=${encodeURIComponent(fromId)}&to_id=${encodeURIComponent(toId)}`)
          .then(r => { if (r.ok) return r.json(); return null; })
          .then(data => { if (data?.summary) setSummary(data.summary); })
          .catch(() => {})
          .finally(() => setSummaryLoading(false));
      })
      .catch(err => setDiffError(err.message))
      .finally(() => setDiffLoading(false));
  }, [fromId, toId]);

  // Scroll chat to bottom when new messages arrive
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  const sendMessage = async () => {
    if (!chatInput.trim() || !diff || chatLoading) return;
    
    const userMsg: ChatMessage = { role: 'user', content: chatInput.trim() };
    setChatMessages(prev => [...prev, userMsg]);
    setChatInput('');
    setChatLoading(true);

    try {
      const res = await fetch('/api/diff-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: userMsg.content,
          diff_context: diff,
        }),
      });
      if (!res.ok) throw new Error(`Error: ${res.status}`);
      const data = await res.json();
      setChatMessages(prev => [...prev, { role: 'assistant', content: data.answer }]);
    } catch (err) {
      setChatMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err instanceof Error ? err.message : 'Failed to get response'}` }]);
    } finally {
      setChatLoading(false);
    }
  };

  const toggleMod = (id: string) => {
    setExpandedMods(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const formatDate = (ts: string) => {
    const d = new Date(ts);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) +
      ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  };

  const formatDelta = (n: number) => {
    if (n > 0) return `+${n}`;
    return String(n);
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center gap-2">
          <IconCpu className="animate-spin text-gray-400" size={32} />
          <span className="text-gray-400 font-mono">Loading snapshots...</span>
        </div>
      </div>
    );
  }

  if (snapshots.length < 2) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="text-center max-w-md">
          <IconGitCompare size={48} className="mx-auto text-gray-300 mb-4" />
          <h2 className="text-xl font-bold mb-2">No History Available</h2>
          <p className="text-gray-500">
            At least 2 documentation snapshots are required to compare changes.
            Run <code className="bg-gray-100 px-1 rounded">docbot generate</code> multiple times to create history.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex bg-gray-50">
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-auto">
          <div className="max-w-4xl mx-auto p-8 space-y-6">
        {/* Header */}
        <div className="border-b border-black pb-4">
          <h1 className="text-2xl font-bold font-mono flex items-center gap-3">
            <IconGitCompare size={28} />
            Compare Snapshots
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Select two snapshots to see what changed between them.
          </p>
        </div>

        {/* Snapshot Selectors */}
        <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-xs font-bold uppercase tracking-wide text-gray-500 mb-2">
                From (Older)
              </label>
              <select
                value={fromId}
                onChange={e => setFromId(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-black"
              >
                {snapshots.map(s => (
                  <option key={s.run_id} value={s.run_id}>
                    {formatDate(s.timestamp)} — {s.scope_count} scopes
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold uppercase tracking-wide text-gray-500 mb-2">
                To (Newer)
              </label>
              <select
                value={toId}
                onChange={e => setToId(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-black"
              >
                {snapshots.map(s => (
                  <option key={s.run_id} value={s.run_id}>
                    {formatDate(s.timestamp)} — {s.scope_count} scopes
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Loading / Error State */}
        {diffLoading && (
          <div className="flex items-center justify-center py-12">
            <IconCpu className="animate-spin text-gray-400" size={24} />
            <span className="ml-2 text-gray-400 font-mono">Computing diff...</span>
          </div>
        )}

        {diffError && (
          <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded">
            {diffError}
          </div>
        )}

        {/* Diff Results */}
        {diff && !diffLoading && (
          <>
            {/* Stats Summary */}
            <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
              <div className="flex items-center gap-2 mb-4 border-b border-gray-100 pb-2">
                <IconChartBar className="text-indigo-600" />
                <h2 className="text-lg font-bold uppercase tracking-wide">Summary</h2>
              </div>
              <div className="grid grid-cols-4 gap-4">
                <div className="text-center">
                  <div className={`text-2xl font-bold font-mono ${diff.stats_delta.total_scopes >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {formatDelta(diff.stats_delta.total_scopes)}
                  </div>
                  <div className="text-xs uppercase text-gray-500">Scopes</div>
                </div>
                <div className="text-center">
                  <div className={`text-2xl font-bold font-mono ${diff.stats_delta.total_files >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {formatDelta(diff.stats_delta.total_files)}
                  </div>
                  <div className="text-xs uppercase text-gray-500">Files</div>
                </div>
                <div className="text-center">
                  <div className={`text-2xl font-bold font-mono ${diff.stats_delta.total_symbols >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {formatDelta(diff.stats_delta.total_symbols)}
                  </div>
                  <div className="text-xs uppercase text-gray-500">Symbols</div>
                </div>
                <div className="text-center">
                  <div className={`text-2xl font-bold font-mono ${diff.graph_changed ? 'text-yellow-600' : 'text-gray-400'}`}>
                    {diff.graph_changed ? 'Yes' : 'No'}
                  </div>
                  <div className="text-xs uppercase text-gray-500">Graph Changed</div>
                </div>
              </div>
            </div>

            {/* Visual Graph */}
            <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
              <div className="flex items-center gap-2 mb-4 border-b border-gray-100 pb-2">
                <IconTopologyRing className="text-purple-600" />
                <h2 className="text-lg font-bold uppercase tracking-wide">Change Graph</h2>
              </div>
              <DiffGraph diff={diff} />
            </div>

            {/* Narrative Summary */}
            <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
              <div className="flex items-center gap-2 mb-4 border-b border-gray-100 pb-2">
                <IconFileDescription className="text-blue-600" />
                <h2 className="text-lg font-bold uppercase tracking-wide">What Changed</h2>
              </div>
              {summaryLoading ? (
                <div className="flex items-center gap-2 text-gray-400 font-mono text-sm py-4">
                  <IconCpu className="animate-spin" size={16} />
                  Generating summary...
                </div>
              ) : summary ? (
                <div className="prose prose-sm max-w-none font-sans leading-relaxed text-gray-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {summary}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="text-gray-400 italic font-mono text-sm py-4">
                  Summary unavailable — LLM may not be configured.
                </div>
              )}
            </div>

            {/* Added Scopes */}
            {diff.added_scopes.length > 0 && (
              <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-4 border-b border-gray-100 pb-2">
                  <IconPlus className="text-green-600" />
                  <h2 className="text-lg font-bold uppercase tracking-wide text-green-700">Added Scopes</h2>
                  <span className="text-sm text-gray-400 ml-auto font-mono">{diff.added_scopes.length}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {diff.added_scopes.map(id => (
                    <span key={id} className="bg-green-100 text-green-800 px-3 py-1 rounded-full text-sm font-mono">
                      {id}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Removed Scopes */}
            {diff.removed_scopes.length > 0 && (
              <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-4 border-b border-gray-100 pb-2">
                  <IconMinus className="text-red-600" />
                  <h2 className="text-lg font-bold uppercase tracking-wide text-red-700">Removed Scopes</h2>
                  <span className="text-sm text-gray-400 ml-auto font-mono">{diff.removed_scopes.length}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {diff.removed_scopes.map(id => (
                    <span key={id} className="bg-red-100 text-red-800 px-3 py-1 rounded-full text-sm font-mono">
                      {id}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Modified Scopes */}
            {diff.modified_scopes.length > 0 && (
              <div className="bg-white border border-black p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
                <div className="flex items-center gap-2 mb-4 border-b border-gray-100 pb-2">
                  <IconEdit className="text-yellow-600" />
                  <h2 className="text-lg font-bold uppercase tracking-wide text-yellow-700">Modified Scopes</h2>
                  <span className="text-sm text-gray-400 ml-auto font-mono">{diff.modified_scopes.length}</span>
                </div>
                <div className="space-y-2">
                  {diff.modified_scopes.map(mod => {
                    const isExpanded = expandedMods.has(mod.scope_id);
                    const hasDetails = mod.added_files.length > 0 || mod.removed_files.length > 0 ||
                      mod.added_symbols.length > 0 || mod.removed_symbols.length > 0;
                    return (
                      <div key={mod.scope_id} className="border border-gray-200 rounded-lg overflow-hidden">
                        <button
                          onClick={() => toggleMod(mod.scope_id)}
                          className="w-full p-3 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
                        >
                          {hasDetails ? (
                            isExpanded
                              ? <IconChevronDown size={16} className="text-gray-400 shrink-0" />
                              : <IconChevronRight size={16} className="text-gray-400 shrink-0" />
                          ) : (
                            <div className="w-4" />
                          )}
                          <span className="font-mono text-sm font-bold">{mod.scope_id}</span>
                          <div className="flex gap-2 ml-auto">
                            {mod.summary_changed && (
                              <span className="text-[10px] bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
                                Summary Changed
                              </span>
                            )}
                            {mod.added_files.length > 0 && (
                              <span className="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                                +{mod.added_files.length} files
                              </span>
                            )}
                            {mod.removed_files.length > 0 && (
                              <span className="text-[10px] bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
                                -{mod.removed_files.length} files
                              </span>
                            )}
                          </div>
                        </button>
                        {isExpanded && hasDetails && (
                          <div className="border-t border-gray-200 p-3 bg-gray-50 text-sm space-y-2">
                            {mod.added_files.length > 0 && (
                              <div>
                                <span className="text-green-700 font-bold">+ Files:</span>
                                <span className="font-mono text-gray-600 ml-2">{mod.added_files.join(', ')}</span>
                              </div>
                            )}
                            {mod.removed_files.length > 0 && (
                              <div>
                                <span className="text-red-700 font-bold">- Files:</span>
                                <span className="font-mono text-gray-600 ml-2">{mod.removed_files.join(', ')}</span>
                              </div>
                            )}
                            {mod.added_symbols.length > 0 && (
                              <div>
                                <span className="text-green-700 font-bold">+ Symbols:</span>
                                <span className="font-mono text-gray-600 ml-2">{mod.added_symbols.slice(0, 10).join(', ')}{mod.added_symbols.length > 10 ? '...' : ''}</span>
                              </div>
                            )}
                            {mod.removed_symbols.length > 0 && (
                              <div>
                                <span className="text-red-700 font-bold">- Symbols:</span>
                                <span className="font-mono text-gray-600 ml-2">{mod.removed_symbols.slice(0, 10).join(', ')}{mod.removed_symbols.length > 10 ? '...' : ''}</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* No Changes */}
            {diff.added_scopes.length === 0 && diff.removed_scopes.length === 0 && diff.modified_scopes.length === 0 && (
              <div className="bg-white border border-black p-8 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] text-center">
                <div className="text-gray-400 text-lg">No scope changes detected between these snapshots.</div>
              </div>
            )}
          </>
        )}
          </div>
        </div>
      </div>

      {diff && (
        <div className="w-[570px] shrink-0 border-l border-black bg-white flex flex-col">
          <div className="p-3 border-b border-black text-xs font-bold uppercase tracking-widest bg-gray-50">
            Diff Chat
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-white">
            {chatMessages.length === 0 && !chatLoading && (
              <div className="text-xs text-gray-400 italic">No messages yet.</div>
            )}
            {chatMessages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] px-4 py-2 text-sm border border-black ${
                  msg.role === 'user'
                    ? 'bg-gray-100'
                    : 'bg-white text-gray-800'
                }`}>
                  {msg.role === 'assistant' ? (
                    <div className="prose prose-sm max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            ))}
            {chatLoading && (
              <div className="flex justify-start">
                <div className="bg-white border border-black px-4 py-2 text-sm text-gray-500">
                  <IconCpu className="inline animate-spin mr-2" size={14} />
                  Thinking...
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
          <div className="border-t border-black p-4 flex gap-3 items-center bg-white">
            <IconMessageCircle className="text-gray-400 shrink-0" size={20} />
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
              placeholder="Ask about the changes..."
              className="flex-1 border border-black px-3 py-2 text-sm font-mono bg-white focus:ring-2 focus:ring-blue-500/10"
              disabled={chatLoading}
            />
            <button
              onClick={sendMessage}
              disabled={chatLoading || !chatInput.trim()}
              className="p-3 border border-black bg-white hover:bg-black hover:text-white transition-all disabled:opacity-50 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none"
            >
              {chatLoading ? <IconCpu className="animate-spin" size={18} /> : <IconSend size={18} />}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
