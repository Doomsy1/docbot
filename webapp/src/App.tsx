import { useState } from 'react';
import Graph from './components/Graph';
import Chat from './components/Chat';
import FileViewer from './components/FileViewer';
import Dashboard from './components/Dashboard';
import TourViewer from './components/TourViewer';
import ArchitectureDev from './components/ArchitectureDev';
import Pipeline from './components/Pipeline';
import AgentExplorer from './features/exploration/AgentExplorer';

export default function App() {
  const [activeTab, setActiveTab] = useState<'pipeline' | 'exploration' | 'dashboard' | 'graph' | 'files' | 'tours' | 'dev-arch'>('pipeline');
  const [selectedFile, setSelectedFile] = useState<string | undefined>();

  const selectFile = (path: string) => {
    setActiveTab('files');
    setSelectedFile(path);
  };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-white text-black font-sans">
      <header className="border-b border-black p-4 flex justify-between items-center">
        <h1 className="text-xl font-bold tracking-tight">docbot</h1>
        <div className="flex gap-4 text-sm font-medium">
          <button
            onClick={() => setActiveTab('pipeline')}
            className={`hover:underline ${activeTab === 'pipeline' ? 'underline decoration-2' : ''}`}
          >
            Pipeline
          </button>
          <button
            onClick={() => setActiveTab('exploration')}
            className={`hover:underline ${activeTab === 'exploration' ? 'underline decoration-2' : ''}`}
          >
            Exploration
          </button>
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`hover:underline ${activeTab === 'dashboard' ? 'underline decoration-2' : ''}`}
          >
            Dashboard
          </button>
          <button
            onClick={() => setActiveTab('graph')}
            className={`hover:underline ${activeTab === 'graph' ? 'underline decoration-2' : ''}`}
          >
            Graph
          </button>
          <button
            onClick={() => setActiveTab('tours')}
            className={`hover:underline ${activeTab === 'tours' ? 'underline decoration-2' : ''}`}
          >
            Tours
          </button>
          <button
            onClick={() => setActiveTab('files')}
            className={`hover:underline ${activeTab === 'files' ? 'underline decoration-2' : ''}`}
          >
            Files
          </button>
          <button
            onClick={() => setActiveTab('dev-arch')}
            className={`hover:underline ${activeTab === 'dev-arch' ? 'underline decoration-2' : ''}`}
          >
            Dev Arch
          </button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Main content area */}
        <main className="flex-1 overflow-hidden relative">
          {activeTab === 'pipeline' && <Pipeline />}
          {activeTab === 'exploration' && <AgentExplorer />}
          {activeTab === 'dashboard' && <Dashboard />}
          {activeTab === 'tours' && (
            <TourViewer onSelectFile={selectFile} />
          )}
          {activeTab === 'graph' && (
            <Graph onSelectFile={selectFile} />
          )}
          {activeTab === 'files' && (
            <div className="h-full p-4">
              <FileViewer
                filePath={selectedFile}
                onSelectFile={(path) => setSelectedFile(path)}
              />
            </div>
          )}
          {activeTab === 'dev-arch' && <ArchitectureDev />}
        </main>

        {/* Chat sidebar - always visible */}
        <div className="w-[570px] shrink-0 border-l border-black h-full">
          <Chat onSelectFile={selectFile} />
        </div>
      </div>
    </div>
  )
}
