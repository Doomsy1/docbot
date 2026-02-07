function App() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-8">
      <div className="max-w-md w-full border border-gray-200 p-8 space-y-6">
        <div className="space-y-2 text-center">
          <h1 className="text-2xl font-bold">docbot</h1>
          <p className="text-sm text-gray-500">Minimal documentation browser.</p>
        </div>
        
        <div className="grid gap-4">
          <button className="w-full py-2 px-4 border border-black hover:bg-black hover:text-white transition-colors text-sm font-medium">
            Browse Scopes
          </button>
          <button className="w-full py-2 px-4 border border-black hover:bg-black hover:text-white transition-colors text-sm font-medium">
            View Graph
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
