import { useState } from 'react';
import Graph from './components/Graph';
import Chat from './components/Chat';
import FileViewer from './components/FileViewer';

export default function App() {
  const [activeTab, setActiveTab] = useState<'graph' | 'chat' | 'files'>('graph');
  const [selectedFile, setSelectedFile] = useState<string | undefined>();

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-white text-black font-sans">
      <header className="border-b border-black p-4 flex justify-between items-center">
        <h1 className="text-xl font-bold tracking-tight">docbot</h1>
        <div className="flex gap-4 text-sm font-medium">
          <button 
            onClick={() => setActiveTab('graph')}
            className={`hover:underline ${activeTab === 'graph' ? 'underline decoration-2' : ''}`}
          >
            Graph
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
        </div>
      </header>
      
      <main className="flex-1 p-4 overflow-hidden relative">
        {activeTab === 'graph' && (
          <Graph onSelectFile={(path) => {
             setActiveTab('files');
             setSelectedFile(path);
          }} />
        )}
        {activeTab === 'chat' && (
          <div className="max-w-2xl mx-auto h-full">
            <Chat onSelectFile={(path) => {
              setActiveTab('files');
              setSelectedFile(path);
            }} />
          </div>
        )}
        {activeTab === 'files' && (
          <FileViewer 
            filePath={selectedFile} 
            onSelectFile={(path) => setSelectedFile(path)}
          />
        )}
      </main>
    </div>
  )
}
