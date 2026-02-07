import { useEffect, useState } from 'react';
import { codeToHtml } from 'shiki';

interface FileViewerProps {
  filePath?: string;
}

export default function FileViewer({ filePath }: FileViewerProps) {
  const [html, setHtml] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  if (!filePath) {
    return (
      <div className="h-full flex items-center justify-center border border-black text-gray-500 font-mono">
        Select a file to view content.
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col border border-black">
      <div className="border-b border-black p-2 bg-gray-100 flex justify-between items-center">
        <span className="font-mono text-sm">{filePath}</span>
        {loading && <span className="text-xs animate-pulse">Loading...</span>}
      </div>
      {error ? (
         <div className="p-4 text-red-600 font-mono">{error}</div>
      ) : (
        <div 
          className="flex-1 p-4 overflow-auto font-mono text-sm [&>pre]:!bg-transparent"
          dangerouslySetInnerHTML={{ __html: html || `<pre>${content}</pre>` }}
        />
      )}
    </div>
  );
}
