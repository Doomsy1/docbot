import { useEffect, useState } from 'react';

type Props = {
  filePath?: string;
  onSelectFile?: (path: string) => void;
};

export default function FileViewer({ filePath }: Props) {
  const [content, setContent] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!filePath) {
      setContent('');
      setError(null);
      return;
    }
    fetch(`/api/files/${filePath}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setContent(data.content || '');
        setError(null);
      })
      .catch((err) => setError(String(err)));
  }, [filePath]);

  if (!filePath) {
    return <div className="h-full p-4 font-mono text-sm text-gray-500">Select a file from Graph or Tours to view source.</div>;
  }

  if (error) {
    return <div className="h-full p-4 font-mono text-sm text-red-600">Failed to load {filePath}: {error}</div>;
  }

  return (
    <div className="h-full flex flex-col border border-black bg-white">
      <div className="border-b border-black px-3 py-2 font-mono text-xs bg-gray-50">{filePath}</div>
      <pre className="m-0 p-4 overflow-auto text-xs leading-5 font-mono whitespace-pre-wrap">{content}</pre>
    </div>
  );
}

