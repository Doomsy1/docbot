import { useEffect, useState } from 'react';
import { IconRoute, IconChevronRight, IconChevronLeft, IconMap2, IconCircleCheck } from '@tabler/icons-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

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

  const startTour = (tour: Tour) => {
    setSelectedTour(tour);
    setCurrentStepIndex(0);
    const firstStep = tour.steps[0];
    if (firstStep?.citation) {
        onSelectFile?.(firstStep.citation.file);
    }
  };

  const nextStep = () => {
    if (!selectedTour) return;
    const nextIndex = Math.min(currentStepIndex + 1, selectedTour.steps.length - 1);
    setCurrentStepIndex(nextIndex);
    const nextStep = selectedTour.steps[nextIndex];
    if (nextStep?.citation) {
        onSelectFile?.(nextStep.citation.file);
    }
  };

  const prevStep = () => {
    if (!selectedTour) return;
    const prevIndex = Math.max(currentStepIndex - 1, 0);
    setCurrentStepIndex(prevIndex);
    const prevStep = selectedTour.steps[prevIndex];
    if (prevStep?.citation) {
        onSelectFile?.(prevStep.citation.file);
    }
  };

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
        <div className="p-4 border-b border-black flex justify-between items-center bg-gray-50">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-blue-600 mb-0.5 flex items-center gap-1">
                <IconRoute size={12} />
                Now Touring
            </div>
            <h2 className="text-lg font-bold font-mono">{selectedTour.title}</h2>
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

        {/* content */}
        <div className="flex-1 overflow-auto p-8 max-w-2xl mx-auto w-full space-y-6">
            <div className="space-y-4">
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full border border-black flex items-center justify-center font-bold text-sm bg-white shadow-[2px_2px_0px_0px_rgba(0,0,0,1)]">
                        {currentStepIndex + 1}
                    </div>
                    <h3 className="text-xl font-bold">{step.title}</h3>
                </div>
                
                <div className="prose prose-sm max-w-none font-sans leading-relaxed text-gray-800">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {step.description}
                    </ReactMarkdown>
                </div>

                {step.citation && (
                    <div className="p-3 bg-blue-50 border border-blue-100 font-mono text-xs text-blue-700 flex items-center gap-2">
                        <IconMap2 size={14} />
                        {step.citation.file}
                    </div>
                )}
            </div>

            {currentStepIndex === selectedTour.steps.length - 1 && (
                <div className="p-6 border-2 border-dashed border-green-200 bg-green-50 text-green-800 rounded-lg flex flex-col items-center gap-2 text-center">
                    <IconCircleCheck size={32} className="text-green-500" />
                    <div className="font-bold">Tour Complete!</div>
                    <div className="text-sm">You've reached the end of this walkthrough.</div>
                </div>
            )}
        </div>

        {/* Footer controls */}
        <div className="p-4 border-t border-black bg-white flex justify-between items-center">
            <button 
                onClick={prevStep}
                disabled={currentStepIndex === 0}
                className="flex items-center gap-1 text-sm font-bold border border-black px-4 py-2 hover:bg-gray-100 disabled:opacity-30 disabled:hover:bg-white"
            >
                <IconChevronLeft size={18} />
                Back
            </button>
            <div className="text-xs font-mono text-gray-500">
                Step {currentStepIndex + 1} of {selectedTour.steps.length}
            </div>
            {currentStepIndex < selectedTour.steps.length - 1 ? (
                <button 
                    onClick={nextStep}
                    className="flex items-center gap-1 text-sm font-bold border border-black px-6 py-2 bg-black text-white hover:bg-gray-800 shadow-[4px_4px_0px_0px_rgba(30,58,138,0.3)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none"
                >
                    Next
                    <IconChevronRight size={18} />
                </button>
            ) : (
                <button 
                    onClick={() => setSelectedTour(null)}
                    className="flex items-center gap-1 text-sm font-bold border border-black px-6 py-2 bg-black text-white"
                >
                    Finish
                </button>
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
