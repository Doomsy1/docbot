import { useEffect, useState } from 'react';
import { codeToHtml } from 'shiki';
import { IconFolder, IconFile, IconChevronRight, IconChevronDown } from '@tabler/icons-react';

interface FileViewerProps {
  filePath?: string;
  onSelectFile?: (path: string) => void;
}

interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: FileNode[];
}

const FileTreeNode = ({ node, onSelect, selectedPath }: { 
  node: FileNode; 
  onSelect: (path: string) => void;
  selectedPath?: string;
}) => {
  const [expanded, setExpanded] = useState(false);
  
  if (node.type === 'file') {
    return (
      <div 
        className={`flex items-center gap-1 cursor-pointer py-0.5 px-2 hover:bg-gray-100 ${selectedPath === node.path ? 'bg-gray-200 font-medium' : ''}`}
        onClick={() => onSelect(node.path)}
      >
        <IconFile size={14} className="text-gray-500" />
        <span>{node.name}</span>
      </div>
    );
  }

  return (
    <div>
      <div 
        className="flex items-center gap-1 cursor-pointer py-0.5 px-2 hover:bg-gray-100 font-medium"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
        <IconFolder size={14} className="text-blue-500" />
        <span>{node.name}</span>
      </div>
      {expanded && node.children && (
        <div className="pl-4 border-l border-gray-200 ml-2">
          {node.children.map((child) => (
            <FileTreeNode 
              key={child.path} 
              node={child} 
              onSelect={onSelect} 
              selectedPath={selectedPath}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default function FileViewer({ filePath, onSelectFile }: FileViewerProps) {
  const [html, setHtml] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);

  // Fetch Tree on mount
  useEffect(() => {
    fetch('/api/fs')
      .then(res => res.json())
      .then(data => setFileTree(data))
      .catch(err => console.error("Failed to load fs", err));
  }, []);

  // Fetch File Content when filePath changes
  useEffect(() => {
    if (!filePath) {
      setHtml('');
      setContent('');
      return;
    }

    async function loadFile() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/files/${filePath}`);
        if (!res.ok) throw new Error(`Status ${res.status}`);
        const data = await res.json();
        setContent(data.content);

        // Highlight
        const lang = filePath?.split('.').pop() || 'txt';
        const out = await codeToHtml(data.content, {
          lang,
          theme: 'min-light' 
        });
        setHtml(out);
      } catch (err) {
        console.error(err);
        setError("Failed to load file.");
      } finally {
        setLoading(false);
      }
    }
    loadFile();
  }, [filePath]);

  const handleSelect = (path: string) => {
    if (onSelectFile) {
      onSelectFile(path);
    }
  };

  return (
    <div className="h-full flex border border-black overflow-hidden">
      {/* Sidebar */}
      <div className="w-1/4 min-w-[200px] border-r border-black overflow-auto bg-gray-50 text-xs p-2">
        <div className="font-bold mb-2 uppercase tracking-wide text-gray-400">Explorer</div>
        {fileTree.map(node => (
          <FileTreeNode 
            key={node.path} 
            node={node} 
            onSelect={handleSelect} 
            selectedPath={filePath}
          />
        ))}
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="border-b border-black p-2 bg-gray-100 flex justify-between items-center">
          <span className="font-mono text-sm truncate">{filePath || 'No file selected'}</span>
          {loading && <span className="text-xs animate-pulse">Loading...</span>}
        </div>
        {error ? (
           <div className="p-4 text-red-600 font-mono">{error}</div>
        ) : filePath ? (
          <div 
            className="flex-1 p-4 overflow-auto font-mono text-sm [&>pre]:!bg-transparent"
            dangerouslySetInnerHTML={{ __html: html || `<pre>${content}</pre>` }}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-gray-400 font-mono">
            Select a file from the explorer.
          </div>
        )}
      </div>
    </div>
  );
}
