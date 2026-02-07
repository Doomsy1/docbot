import { useState } from 'react';

interface Message {
  id: string;
  sender: 'user' | 'bot';
  text: string;
  results?: SearchResult[];
}

interface SearchResult {
  citation: {
    file: string;
    line_start: number;
    symbol?: string;
  };
  score: number;
  match_context: string;
}

interface ChatProps {
  onSelectFile?: (path: string) => void;
}

export default function Chat({ onSelectFile }: ChatProps) {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'bot', text: 'Hello. I am docbot. Ask me about your codebase.' }
  ]);
  const [loading, setLoading] = useState(false);

  const send = async () => {
    if (!input.trim()) return;
    
    const userMsg: Message = { id: Date.now().toString(), sender: 'user', text: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(input)}`);
      const data: SearchResult[] = await res.json();
      
      const botMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'bot',
        text: data.length > 0 ? `Found ${data.length} results:` : 'No results found.',
        results: data
      };
      setMessages(prev => [...prev, botMsg]);
    } catch (e) {
      setMessages(prev => [...prev, { id: Date.now().toString(), sender: 'bot', text: 'Error fetching results.' }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full border border-black p-4 space-y-4">
      <div className="flex-1 overflow-y-auto space-y-4">
        {messages.map(m => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] p-2 border border-black ${m.sender === 'user' ? 'bg-black text-white' : 'bg-white text-black'}`}>
              <p className="text-sm font-mono mb-1">{m.sender.toUpperCase()}:</p>
              <p className="whitespace-pre-wrap">{m.text}</p>
              {m.results && (
                <div className="mt-2 space-y-2 border-t border-gray-300 pt-2">
                  {m.results.map((r, i) => (
                    <div key={i} className="text-sm">
                      <div className="font-bold">{r.match_context}</div>
                      <div 
                        className="text-xs opacity-75 cursor-pointer hover:underline"
                        onClick={() => onSelectFile?.(r.citation.file)}
                      >
                        {r.citation.file}:{r.citation.line_start}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && <div className="text-sm animate-pulse">Searching...</div>}
      </div>
      <div className="flex gap-2">
        <input 
          className="flex-1 border border-black p-2 outline-none font-mono text-sm"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()}
          placeholder="Type a query..."
          disabled={loading}
        />
        <button 
          onClick={send}
          disabled={loading}
          className="px-4 py-2 border border-black hover:bg-black hover:text-white transition-colors font-bold uppercase text-sm disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
