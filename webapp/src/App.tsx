import { useState } from 'react';
import Graph from './components/Graph';
import Chat from './components/Chat';
import FileViewer from './components/FileViewer';
import Dashboard from './components/Dashboard';
import TourViewer from './components/TourViewer';
import ArchitectureDev from './components/ArchitectureDev';
import DynamicGraphChat from './components/DynamicGraphChat';

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'graph' | 'chat' | 'files' | 'tours' | 'dev-arch' | 'explore'>('dashboard');
  const [selectedFile, setSelectedFile] = useState<string | undefined>();

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-white text-black font-sans">
      <header className="border-b border-black p-4 flex justify-between items-center">
        <h1 className="text-xl font-bold tracking-tight">docbot</h1>
        <div className="flex gap-4 text-sm font-medium">
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
            onClick={() => setActiveTab('chat')}
            className={`hover:underline ${activeTab === 'chat' ? 'underline decoration-2' : ''}`}
          >
            Chat
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
          <button
            onClick={() => setActiveTab('explore')}
            className={`hover:underline ${activeTab === 'explore' ? 'underline decoration-2' : ''}`}
          >
            Explore
          </button>
        </div>
      </header>
      
      <main className="flex-1 overflow-hidden relative">
        {activeTab === 'dashboard' && <Dashboard />}
        {activeTab === 'tours' && (
          <TourViewer onSelectFile={(path) => {
             setActiveTab('files');
             setSelectedFile(path);
          }} />
        )}
        {activeTab === 'graph' && (
          <Graph onSelectFile={(path) => {
             setActiveTab('files');
             setSelectedFile(path);
          }} />
        )}
        {activeTab === 'chat' && (
          <div className="max-w-2xl mx-auto h-full p-4">
            <Chat onSelectFile={(path) => {
              setActiveTab('files');
              setSelectedFile(path);
            }} />
          </div>
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
        {activeTab === 'explore' && <DynamicGraphChat />}
      </main>
    </div>
  )
}
