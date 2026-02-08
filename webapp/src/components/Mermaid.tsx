import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    primaryColor: '#ffffff',
    primaryTextColor: '#000000',
    primaryBorderColor: '#000000',
    lineColor: '#000000',
    secondaryColor: '#f3f4f6',
    tertiaryColor: '#ffffff',
  }
});

interface MermaidProps {
  chart: string;
}

// Fix common LLM-generated Mermaid syntax issues
function sanitizeMermaid(src: string): string {
  return src
    // Strip inline %% comments (Mermaid only supports whole-line comments)
    .replace(/^(.+?)\s+%%.*$/gm, '$1')
    // Fix node labels with unquoted parentheses: A[Compose Video (and audio)] -> A["Compose Video (and audio)"]
    .replace(/(\[)([^\]"]*\([^\]]*\))(\])/g, '$1"$2"$3')
    // Fix edge labels with spaces inside pipes: -->| "label" | -> -->|label|
    .replace(/-->\|\s*"?([^"|]*)"?\s*\|/g, '-->|$1|');
}

export default function Mermaid({ chart }: MermaidProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function renderChart() {
        if (!ref.current || !chart) return;

        setError(null);
        const sanitized = sanitizeMermaid(chart);
        try {
            // Uniq ID for each render to avoid collisions
            const id = 'mermaid-' + Math.random().toString(36).substring(2, 9);
            const { svg } = await mermaid.render(id, sanitized);
            ref.current.innerHTML = svg;
        } catch (err: any) {
            console.error("Mermaid Render Error:", err);
            setError(err.message || "Failed to parse Mermaid syntax.");
        }
    }
    renderChart();
  }, [chart]);

  if (error) {
    return (
        <div className="my-4 p-6 border-2 border-dashed border-red-200 bg-red-50 rounded-lg">
            <h3 className="text-red-800 font-bold mb-2 flex items-center gap-2">
                ⚠️ Mermaid Syntax Error
            </h3>
            <pre className="text-xs text-red-600 bg-white p-4 border border-red-100 overflow-auto max-h-60 font-mono">
                {error}
            </pre>
            <div className="mt-4 text-[10px] text-gray-400 font-mono uppercase">
                Raw Chart Data:
                <pre className="mt-1 opacity-50 bg-gray-50 p-2 truncate">{chart}</pre>
            </div>
        </div>
    );
  }

  return (
    <div
        className="mermaid-container my-4 flex justify-center bg-white border border-black p-4 overflow-x-auto shadow-[4px_4px_0px_0px_rgba(0,0,0,0.1)]"
        ref={ref}
    />
  );
}
