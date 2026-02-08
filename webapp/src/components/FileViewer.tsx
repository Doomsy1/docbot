import { useState, useEffect } from 'react';
import { IconFile, IconFolder, IconChevronDown, IconChevronRight } from '@tabler/icons-react';

interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  children?: FileNode[];
}

interface FileViewerProps {
  filePath?: string;
  onSelectFile: (path: string) => void;
}

export default function FileViewer({ filePath, onSelectFile }: FileViewerProps) {
  const [fs, setFs] = useState<FileNode | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(['.']));

  useEffect(() => {
    fetch('/api/fs')
      .then(res => res.json())
      .then(setFs)
      .catch(console.error);
  }, []);

  useEffect(() => {
    if (filePath) {
      setLoading(true);
      fetch(`/api/files/${encodeURIComponent(filePath)}`)
        .then(res => res.json())
        .then(data => setContent(data.content))
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [filePath]);

  const toggleFolder = (path: string) => {
    setExpandedFolders(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const renderTree = (node: FileNode, depth = 0) => {
    const isExpanded = expandedFolders.has(node.path);
    const isSelected = filePath === node.path;

    return (
      <div key={node.path}>
        <div
          className={`flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-gray-100 text-sm ${isSelected ? 'bg-blue-50 border-l-2 border-blue-500' : ''}`}
          style={{ paddingLeft: `${depth * 1.5 + 0.5}rem` }}
          onClick={() => {
            if (node.isDir) toggleFolder(node.path);
            else onSelectFile(node.path);
          }}
        >
          {node.isDir ? (
            <>
              {isExpanded ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
              <IconFolder size={16} className="text-blue-400" />
            </>
          ) : (
            <>
              <div className="w-3.5" />
              <IconFile size={16} className="text-gray-400" />
            </>
          )}
          <span className="truncate">{node.name}</span>
        </div>
        {node.isDir && isExpanded && node.children?.map(child => renderTree(child, depth + 1))}
      </div>
    );
  };

  return (
    <div className="flex h-full border border-black overflow-hidden bg-white">
      {/* File Tree */}
      <div className="w-64 border-r border-black overflow-y-auto shrink-0 bg-gray-50">
        <div className="p-2 border-b border-black text-xs font-bold uppercase tracking-widest bg-white">
          Explorer
        </div>
        <div className="py-2">
          {fs ? renderTree(fs) : <div className="p-4 text-xs text-gray-400 animate-pulse">Loading tree...</div>}
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="p-2 border-b border-black bg-gray-50 flex items-center justify-between text-xs">
          <span className="font-mono truncate">{filePath || 'Select a file to view'}</span>
          {loading && <span className="animate-pulse text-blue-600">Loading...</span>}
        </div>
        <div className="flex-1 overflow-auto p-4 font-mono text-sm">
          {content ? (
            <pre className="whitespace-pre-wrap">{content}</pre>
          ) : (
            <div className="h-full flex items-center justify-center text-gray-300 italic">
              {filePath ? 'Loading content...' : 'No file selected'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
