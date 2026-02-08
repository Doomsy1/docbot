import { useEffect, useState, useCallback, useRef } from 'react';
import { IconRoute, IconChevronRight, IconChevronLeft, IconCircleCheck, IconCircleFilled } from '@tabler/icons-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface TourStep {
  title: string;
  description: string;
  scope_id?: string | null;
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

// Simple vertical step graph component
function TourStepGraph({ steps, currentIndex }: { steps: TourStep[]; currentIndex: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const currentNodeRef = useRef<HTMLDivElement>(null);

  // Scroll to keep current step visible
  useEffect(() => {
    if (currentNodeRef.current && containerRef.current) {
      const container = containerRef.current;
      const node = currentNodeRef.current;
      // Center the current node in the container
      const scrollTop = node.offsetTop - container.clientHeight / 2 + node.clientHeight / 2;
      container.scrollTo({ top: scrollTop, behavior: 'smooth' });
    }
  }, [currentIndex]);

  return (
    <div ref={containerRef} className="h-full overflow-auto p-6">
      <div className="flex flex-col items-center">
        {steps.map((step, index) => {
          const isCompleted = index < currentIndex;
          const isCurrent = index === currentIndex;

          return (
            <div key={index} className="flex flex-col items-center" ref={isCurrent ? currentNodeRef : undefined}>
              {/* Node */}
              <div
                className={`
                  relative flex items-center justify-center w-10 h-10 rounded-full border-2
                  transition-all duration-300 shrink-0
                  ${isCurrent 
                    ? 'bg-blue-600 border-blue-600 text-white scale-110 shadow-lg' 
                    : isCompleted 
                      ? 'bg-green-500 border-green-500 text-white' 
                      : 'bg-white border-gray-300 text-gray-400'
                  }
                `}
              >
                {isCompleted ? (
                  <IconCircleCheck size={20} />
                ) : isCurrent ? (
                  <IconCircleFilled size={20} />
                ) : (
                  <span className="text-sm font-bold">{index + 1}</span>
                )}
              </div>

              {/* Step title */}
              <div
                className={`
                  mt-2 text-center max-w-[180px] text-sm font-medium transition-all duration-300
                  ${isCurrent 
                    ? 'text-blue-600 font-bold' 
                    : isCompleted 
                      ? 'text-green-600' 
                      : 'text-gray-400'
                  }
                `}
              >
                {step.title}
              </div>

              {/* Connector line (except for last node) */}
              {index < steps.length - 1 && (
                <div className="flex flex-col items-center my-2">
                  <div
                    className={`
                      w-0.5 h-12 transition-all duration-300
                      ${index < currentIndex ? 'bg-green-500' : 'bg-gray-200'}
                    `}
                  />
                  <svg
                    className={`w-3 h-3 -mt-1 ${index < currentIndex ? 'text-green-500' : 'text-gray-200'}`}
                    viewBox="0 0 10 10"
                    fill="currentColor"
                  >
                    <polygon points="5,10 0,0 10,0" />
                  </svg>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function TourViewer({ onSelectFile }: TourViewerProps) {
  const [tours, setTours] = useState<Tour[]>([]);
  const [selectedTour, setSelectedTour] = useState<Tour | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [loading, setLoading] = useState(true);

  // Fetch tours
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

        {/* Split view: step graph left, description right */}
        <div className="flex-1 flex overflow-hidden">
          {/* Step graph */}
          <div className="w-64 shrink-0 border-r border-black bg-gray-50">
            <TourStepGraph steps={selectedTour.steps} currentIndex={currentStepIndex} />
          </div>

          {/* Tour step content */}
          <div className="flex-1 flex flex-col">
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
                  <span className="truncate">{step.citation.file}:{step.citation.line_start}-{step.citation.line_end}</span>
                  <span className="ml-auto text-blue-400 text-[10px] shrink-0">Open in Files</span>
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
