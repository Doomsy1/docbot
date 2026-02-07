import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { IconSend, IconLoader2, IconQuote } from '@tabler/icons-react';

interface Citation {
  file: string;
  line_start: number;
  symbol?: string;
}

interface Message {
  id: string;
  sender: 'user' | 'bot';
  text: string;
  citations?: Citation[];
}

interface ChatProps {
  onSelectFile?: (path: string) => void;
}

export default function Chat({ onSelectFile }: ChatProps) {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'bot', text: 'Hello! I am docbot. Ask me anything about this codebase, e.g., "What does the server do?" or "How do I add a new API endpoint?"' }
  ]);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    
    const userMsg: Message = { id: Date.now().toString(), sender: 'user', text: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: input })
      });
      
      if (!res.ok) throw new Error("Chat failed");
      
      const data = await res.json();
      
      const botMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'bot',
        text: data.answer,
        citations: data.citations
      };
      setMessages(prev => [...prev, botMsg]);
    } catch (e) {
      setMessages(prev => [...prev, { id: Date.now().toString(), sender: 'bot', text: 'Sorry, I encountered an error while processing your request.' }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white border border-black shadow-[8px_8px_0px_0px_rgba(0,0,0,1)]">
      {/* Message List */}
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-6 space-y-6 selection:bg-black selection:text-white"
      >
        {messages.map(m => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] space-y-2`}>
              <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-gray-400 mb-1">
                <span className={m.sender === 'user' ? 'order-2' : ''}>{m.sender}</span>
                <div className="h-[1px] flex-1 bg-gray-100"></div>
              </div>
              
              <div className={`p-4 border border-black ${m.sender === 'user' ? 'bg-gray-50' : 'bg-white shadow-[4px_4px_0px_0px_rgba(30,58,138,0.1)]'}`}>
                <div className="prose prose-sm max-w-none font-sans leading-relaxed text-gray-800">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {m.text}
                  </ReactMarkdown>
                </div>

                {m.citations && m.citations.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-100 space-y-2">
                    <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                      <IconQuote size={10} />
                      Sources
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {m.citations.map((c, i) => (
                        <button 
                          key={i}
                          onClick={() => onSelectFile?.(c.file)}
                          className="text-[11px] font-mono bg-blue-50 text-blue-700 px-2 py-1 hover:bg-blue-100 transition-colors border border-blue-100 truncate max-w-[200px]"
                          title={c.file}
                        >
                          {c.file.split('/').pop()}:{c.line_start}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 text-gray-400 font-mono text-xs italic p-4 border border-dashed border-gray-200">
              <IconLoader2 className="animate-spin" size={14} />
              docbot is thinking...
            </div>
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="p-4 border-t border-black bg-gray-50">
        <div className="flex gap-2">
          <input 
            className="flex-1 border border-black p-3 outline-none font-mono text-sm bg-white focus:ring-2 focus:ring-blue-500/10 transition-shadow"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && send()}
            placeholder="Ask about the architecture, logic, or specific files..."
            disabled={loading}
          />
          <button 
            onClick={send}
            disabled={loading || !input.trim()}
            className="px-6 py-3 border border-black bg-white hover:bg-black hover:text-white transition-all font-bold uppercase text-xs flex items-center gap-2 disabled:opacity-50 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none"
          >
            {loading ? <IconLoader2 className="animate-spin" size={16} /> : <IconSend size={16} />}
            Ask
          </button>
        </div>
      </div>
    </div>
  );
}
