/**
 * Right-side detail panel showing a selected agent's streaming text,
 * tool calls, and notepad writes.
 */
import type { AgentNode } from './types';

interface Props {
  agent: AgentNode;
  onClose: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-green-500',
  done: 'bg-gray-400',
  error: 'bg-red-500',
};

export default function AgentDetail({ agent, onClose }: Props) {
  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-black flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_COLORS[agent.status] ?? 'bg-gray-300'}`} />
          <span className="font-mono text-sm font-bold truncate">{agent.agent_id}</span>
          <span className="text-xs text-gray-500">d={agent.depth}</span>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-black text-lg leading-none px-1"
          aria-label="Close"
        >
          x
        </button>
      </div>

      {/* Purpose */}
      <div className="px-3 py-2 border-b border-gray-200 bg-gray-50">
        <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Purpose</div>
        <div className="text-xs leading-relaxed">{agent.purpose || '(none)'}</div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        {/* Tool calls */}
        {agent.tools.length > 0 && (
          <div className="px-3 py-2 border-b border-gray-200">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
              Tools ({agent.tools.length})
            </div>
            <div className="space-y-1">
              {agent.tools.slice(-20).map((tool, i) => (
                <div key={i} className="text-xs font-mono">
                  <span className={tool.status === 'running' ? 'text-green-600' : 'text-gray-600'}>
                    {tool.tool}
                  </span>
                  <span className="text-gray-400 ml-1">
                    {tool.input.length > 60 ? tool.input.slice(0, 60) + '...' : tool.input}
                  </span>
                  {tool.output && (
                    <div className="text-gray-500 ml-2 mt-0.5 text-[11px] leading-tight">
                      {tool.output.length > 120 ? tool.output.slice(0, 120) + '...' : tool.output}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Streaming text */}
        <div className="px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            LLM Output
          </div>
          {agent.text ? (
            <pre className="text-xs font-mono whitespace-pre-wrap break-words leading-relaxed text-gray-800">
              {agent.text}
            </pre>
          ) : (
            <div className="text-xs text-gray-400 italic">Waiting for output...</div>
          )}
        </div>

        {/* Summary (when done) */}
        {agent.summary && (
          <div className="px-3 py-2 border-t border-gray-200 bg-gray-50">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Summary</div>
            <div className="text-xs leading-relaxed">{agent.summary}</div>
          </div>
        )}

        {/* Error (if any) */}
        {agent.error && (
          <div className="px-3 py-2 border-t border-red-200 bg-red-50">
            <div className="text-[10px] uppercase tracking-wider text-red-500 mb-1">Error</div>
            <div className="text-xs text-red-700 font-mono">{agent.error}</div>
          </div>
        )}
      </div>
    </div>
  );
}
