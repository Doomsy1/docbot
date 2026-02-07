import { useEffect, useState, useCallback } from 'react';
import { IconRoute, IconChevronRight, IconChevronLeft, IconMap2, IconCircleCheck } from '@tabler/icons-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { codeToHtml } from 'shiki';

interface TourStep {
  title: string;
  description: string;
  citation?: {
    file: string;
    line_start: number;
    line_end: number;
  };
}

interface Tour {
  tour_id: string;
  title: string;
  description: string;
  steps: TourStep[];
}

interface TourViewerProps {
  onSelectFile?: (path: string) => void;
}

function CodePanel({ file, lineStart, lineEnd }: { file: string; lineStart: number; lineEnd: number }) {
  const [html, setHtml] = useState<string>('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/files/${file}`)
      .then(res => res.json())
      .then(async (data) => {
        const lines = (data.content as string).split('\n');
        // Show context: 5 lines before to 5 lines after the citation range
        const start = Math.max(0, lineStart - 6);
        const end = Math.min(lines.length, lineEnd + 5);
        const snippet = lines.slice(start, end).join('\n');

        // Detect language from file extension
        const ext = file.split('.').pop() || '';
        const langMap: Record<string, string> = {
          py: 'python', ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx',
          go: 'go', rs: 'rust', java: 'java', kt: 'kotlin', cs: 'csharp',
          swift: 'swift', rb: 'ruby', md: 'markdown', json: 'json', toml: 'toml',
          yaml: 'yaml', yml: 'yaml', css: 'css', html: 'html',
        };
        const lang = langMap[ext] || 'text';

        const highlighted = await codeToHtml(snippet, {
          lang,
          theme: 'github-light',
        });

        // Inject line numbers starting from actual file line
        const lineNumbered = highlighted.replace(
          /(<pre[^>]*><code[^>]*>)([\s\S]*?)(<\/code><\/pre>)/,
          (_match, pre, code, post) => {
            const codeLines = code.split('\n');
            const numbered = codeLines.map((line: string, i: number) => {
              const lineNum = start + i + 1;
              const isHighlighted = lineNum >= lineStart && lineNum <= lineEnd;
              return `<span class="line-row ${isHighlighted ? 'bg-yellow-100' : ''}"><span class="line-num text-gray-400 select-none pr-4 inline-block w-12 text-right text-xs">${lineNum}</span>${line}</span>`;
            }).join('\n');
            return `${pre}${numbered}${post}`;
          }
        );

        setHtml(lineNumbered);
      })
      .catch(() => setHtml('<div class="p-4 text-red-500 font-mono text-sm">Failed to load file.</div>'))
      .finally(() => setLoading(false));
  }, [file, lineStart, lineEnd]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 font-mono text-sm animate-pulse">
        Loading {file}...
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 font-mono text-xs text-gray-600 flex items-center gap-2">
        <IconMap2 size={12} />
        {file}
        <span className="text-gray-400">lines {lineStart}-{lineEnd}</span>
      </div>
      <div
        className="flex-1 overflow-auto text-sm [&_pre]:!bg-white [&_pre]:!m-0 [&_pre]:!p-4 [&_.line-row]:block [&_.line-row]:leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

export default function TourViewer({ onSelectFile }: TourViewerProps) {
  const [tours, setTours] = useState<Tour[]>([]);
  const [selectedTour, setSelectedTour] = useState<Tour | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/tours')
      .then(res => res.json())
      .then(setTours)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const startTour = useCallback((tour: Tour) => {
    setSelectedTour(tour);
    setCurrentStepIndex(0);
  }, []);

  const nextStep = useCallback(() => {
    if (!selectedTour) return;
    setCurrentStepIndex(prev => Math.min(prev + 1, selectedTour.steps.length - 1));
  }, [selectedTour]);

  const prevStep = useCallback(() => {
    setCurrentStepIndex(prev => Math.max(prev - 1, 0));
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center font-mono text-gray-400">
        Loading tours...
      </div>
    );
  }

  if (selectedTour) {
    const step = selectedTour.steps[currentStepIndex];
    const progress = ((currentStepIndex + 1) / selectedTour.steps.length) * 100;
    const hasCitation = step.citation && step.citation.file;

    return (
      <div className="h-full flex flex-col bg-white">
        {/* Tour Header */}
        <div className="p-3 border-b border-black flex justify-between items-center bg-gray-50">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-blue-600 mb-0.5 flex items-center gap-1">
                <IconRoute size={12} />
                Now Touring
            </div>
            <h2 className="text-base font-bold font-mono">{selectedTour.title}</h2>
          </div>
          <button
            onClick={() => setSelectedTour(null)}
            className="text-xs font-bold border border-black px-2 py-1 hover:bg-black hover:text-white transition-colors"
          >
            QUIT TOUR
          </button>
        </div>

        {/* Progress Bar */}
        <div className="h-1 bg-gray-100 w-full overflow-hidden">
            <div
                className="h-full bg-blue-600 transition-all duration-300"
                style={{ width: `${progress}%` }}
            />
        </div>

        {/* Split view: tour step left, code right */}
        <div className="flex-1 flex overflow-hidden">
          {/* Tour step content */}
          <div className={`${hasCitation ? 'w-2/5' : 'w-full'} flex flex-col border-r border-gray-200`}>
            <div className="flex-1 overflow-auto p-6 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-full border border-black flex items-center justify-center font-bold text-xs bg-white shadow-[2px_2px_0px_0px_rgba(0,0,0,1)]">
                  {currentStepIndex + 1}
                </div>
                <h3 className="text-lg font-bold">{step.title}</h3>
              </div>

              <div className="prose prose-sm max-w-none font-sans leading-relaxed text-gray-800">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {step.description}
                </ReactMarkdown>
              </div>

              {step.citation && (
                <button
                  onClick={() => onSelectFile?.(step.citation!.file)}
                  className="p-2 bg-blue-50 border border-blue-100 font-mono text-xs text-blue-700 flex items-center gap-2 hover:bg-blue-100 transition-colors w-full"
                >
                  <IconMap2 size={14} />
                  {step.citation.file}:{step.citation.line_start}-{step.citation.line_end}
                  <span className="ml-auto text-blue-400 text-[10px]">Open in Files</span>
                </button>
              )}

              {currentStepIndex === selectedTour.steps.length - 1 && (
                <div className="p-4 border-2 border-dashed border-green-200 bg-green-50 text-green-800 rounded-lg flex flex-col items-center gap-2 text-center">
                  <IconCircleCheck size={28} className="text-green-500" />
                  <div className="font-bold text-sm">Tour Complete!</div>
                  <div className="text-xs">You've reached the end of this walkthrough.</div>
                </div>
              )}
            </div>

            {/* Footer controls */}
            <div className="p-3 border-t border-black bg-white flex justify-between items-center">
              <button
                onClick={prevStep}
                disabled={currentStepIndex === 0}
                className="flex items-center gap-1 text-xs font-bold border border-black px-3 py-1.5 hover:bg-gray-100 disabled:opacity-30 disabled:hover:bg-white"
              >
                <IconChevronLeft size={16} />
                Back
              </button>
              <div className="text-xs font-mono text-gray-500">
                {currentStepIndex + 1} / {selectedTour.steps.length}
              </div>
              {currentStepIndex < selectedTour.steps.length - 1 ? (
                <button
                  onClick={nextStep}
                  className="flex items-center gap-1 text-xs font-bold border border-black px-4 py-1.5 bg-black text-white hover:bg-gray-800 shadow-[3px_3px_0px_0px_rgba(30,58,138,0.3)] active:translate-x-[1px] active:translate-y-[1px] active:shadow-none"
                >
                  Next
                  <IconChevronRight size={16} />
                </button>
              ) : (
                <button
                  onClick={() => setSelectedTour(null)}
                  className="flex items-center gap-1 text-xs font-bold border border-black px-4 py-1.5 bg-black text-white"
                >
                  Finish
                </button>
              )}
            </div>
          </div>

          {/* Code panel */}
          {hasCitation && (
            <div className="w-3/5 h-full">
              <CodePanel
                file={step.citation!.file}
                lineStart={step.citation!.line_start}
                lineEnd={step.citation!.line_end}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-gray-50 p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div className="border-b border-black pb-4">
            <h1 className="text-3xl font-bold font-mono">Guided Tours</h1>
            <p className="text-gray-500 font-mono text-sm mt-2 uppercase tracking-wide">
                Interactive walkthroughs of the codebase architecture and logic.
            </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {tours.map(tour => (
                <div
                    key={tour.tour_id}
                    className="bg-white border border-black p-6 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)] hover:-translate-y-1 hover:-translate-x-1 hover:shadow-[12px_12px_0px_0px_rgba(0,0,0,1)] transition-all flex flex-col h-full"
                >
                    <div className="flex-1 space-y-4">
                        <div className="font-mono text-[10px] text-blue-600 font-bold uppercase tracking-widest flex items-center gap-1.5">
                            <IconRoute size={14} />
                            {tour.steps.length} Steps
                        </div>
                        <h2 className="text-xl font-bold">{tour.title}</h2>
                        <p className="text-sm text-gray-600 leading-relaxed font-sans">
                            {tour.description}
                        </p>
                    </div>
                    <button
                        onClick={() => startTour(tour)}
                        className="mt-8 w-full border border-black font-bold uppercase py-2 bg-black text-white hover:bg-gray-800 transition-colors"
                    >
                        Start Walkthrough
                    </button>
                </div>
            ))}
            {tours.length === 0 && (
                <div className="col-span-full py-12 text-center border-2 border-dashed border-gray-200 text-gray-400 font-mono">
                    No tours available for this run.
                </div>
            )}
        </div>
      </div>
    </div>
  );
}
