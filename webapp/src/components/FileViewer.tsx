import { useEffect, useState } from 'react';
import { codeToHtml } from 'shiki';

export default function FileViewer() {
  const [html, setHtml] = useState('');
  const code = `
def hello():
    print("Hello, docbot world!")

# This is a sample file viewer
class Docbot:
    pass
`;

  useEffect(() => {
    async function highlight() {
      const out = await codeToHtml(code, {
        lang: 'python',
        theme: 'min-light' 
      });
      setHtml(out);
    }
    highlight();
  }, []);

  return (
    <div className="h-full flex flex-col border border-black">
      <div className="border-b border-black p-2 bg-gray-100">
        <span className="font-mono text-sm">src/docbot/example.py</span>
      </div>
      <div 
        className="flex-1 p-4 overflow-auto font-mono text-sm [&>pre]:!bg-transparent"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
