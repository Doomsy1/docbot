import { useEffect, useRef } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: true,
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

export default function Mermaid({ chart }: MermaidProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) {
        // Clear previous content
        ref.current.removeAttribute('data-processed');
        ref.current.innerHTML = chart;
        mermaid.contentLoaded();
    }
  }, [chart]);

  return (
    <div className="mermaid my-4 flex justify-center bg-white border border-black p-4 overflow-x-auto shadow-[4px_4px_0px_0px_rgba(0,0,0,0.1)]" ref={ref}>
      {chart}
    </div>
  );
}
