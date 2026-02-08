/**
 * Notepad topic browser strip shown below the force graph.
 *
 * Displays topic chips that can be clicked to expand and show entries.
 */
import { useState } from 'react';
import type { NoteEntry } from './types';

interface Props {
  notepads: Map<string, NoteEntry[]>;
}

export default function NotepadViewer({ notepads }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const topics = Array.from(notepads.keys()).sort();

  if (topics.length === 0) {
    return null;
  }

  return (
    <div className="px-3 py-2">
      {/* Topic chips */}
      <div className="flex items-center gap-1 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-gray-500 mr-1">
          Notepad
        </span>
        {topics.map((topic) => {
          const count = notepads.get(topic)?.length ?? 0;
          const isActive = expanded === topic;
          return (
            <button
              key={topic}
              onClick={() => setExpanded(isActive ? null : topic)}
              className={`text-xs px-2 py-0.5 border rounded font-mono transition-colors ${
                isActive
                  ? 'bg-black text-white border-black'
                  : 'bg-white text-black border-gray-300 hover:border-black'
              }`}
            >
              {topic}
              <span className="text-[10px] ml-1 opacity-60">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Expanded topic entries */}
      {expanded && notepads.has(expanded) && (
        <div className="mt-2 border border-gray-200 rounded bg-gray-50 p-2 max-h-48 overflow-y-auto">
          <div className="text-xs font-mono font-bold mb-1">{expanded}</div>
          {(notepads.get(expanded) ?? []).map((entry, i) => (
            <div key={i} className="text-xs leading-relaxed mb-1">
              <span className="text-gray-500">[{entry.author}]</span>{' '}
              <span>{entry.content}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
