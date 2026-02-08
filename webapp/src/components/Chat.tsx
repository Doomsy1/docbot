import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { IconSend, IconLoader2, IconQuote, IconSparkles } from '@tabler/icons-react';
import Mermaid from './Mermaid';

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
    { id: '1', sender: 'bot', text: 'Hello! I am docbot. Ask me anything about this codebase.' }
  ]);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Generate suggested questions from index data
  useEffect(() => {
    fetch('/api/index')
      .then(r => r.json())
      .then(data => {
        const qs: string[] = [];
        qs.push('What is the overall architecture of this project?');
        if (data.scopes?.length > 0) {
          const scope = data.scopes[Math.floor(Math.random() * data.scopes.length)];
          qs.push(`What does the ${scope.title} scope do?`);
        }
        if (data.entrypoints?.length > 0) {
          qs.push('What are the main entrypoints and how do they work?');
        }
        if (data.public_api_count > 0) {
          const scopeKeys = Object.keys(data.public_api_by_scope || {});
          if (scopeKeys.length > 0) {
            const key = scopeKeys[Math.floor(Math.random() * scopeKeys.length)];
            qs.push(`What are the key functions in ${key}?`);
          }
        }
        qs.push('How do the different modules depend on each other?');
        setSuggestions(qs.slice(0, 4));
      })
      .catch(() => {
        setSuggestions([
          'What is the overall architecture of this project?',
          'What are the main entrypoints?',
          'How do the modules depend on each other?',
        ]);
      });
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, suggestions]);

  const send = async (overrideText?: string) => {
    const text = overrideText ?? input;
    if (!text.trim() || loading) return;

    const userMsg: Message = { id: Date.now().toString(), sender: 'user', text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setSuggestions([]); // Hide suggestions after first question
    setLoading(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text })
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
      // Update suggestions from server response
      if (data.suggestions?.length > 0) {
        setSuggestions(data.suggestions);
      } else {
        setSuggestions([]);
      }
    } catch (e) {
      setMessages(prev => [...prev, { id: Date.now().toString(), sender: 'bot', text: 'Sorry, I encountered an error while processing your request.' }]);
      setSuggestions([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Message List */}
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-6 space-y-6 selection:bg-black selection:text-white"
      >
        {messages.map(m => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className="max-w-full space-y-2 min-w-0">
              <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-gray-400 mb-1">
                <span className={m.sender === 'user' ? 'order-2' : ''}>{m.sender}</span>
                <div className="h-[1px] flex-1 bg-gray-100"></div>
              </div>
              
              <div className={`p-4 border border-black overflow-hidden ${m.sender === 'user' ? 'bg-gray-50' : 'bg-white shadow-[4px_4px_0px_0px_rgba(30,58,138,0.1)]'}`}>
                <div className="prose prose-sm max-w-none font-sans leading-relaxed text-gray-800 break-words overflow-hidden [&_pre]:overflow-x-auto [&_code]:break-all">
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    components={{
                        code({ node, inline, className, children, ...props }: any) {
                          const match = /language-mermaid/.exec(className || '');
                          const value = String(children).replace(/\n$/, '');
                          
                          if (!inline && match) {
                            return <Mermaid chart={value} />;
                          }
                          
                          return (
                            <code className={className} {...props}>
                              {children}
                            </code>
                          );
                        }
                    }}
                  >
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
        {/* Suggested questions */}
        {suggestions.length > 0 && !loading && (
          <div className="space-y-2 pt-2">
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-gray-400">
              <IconSparkles size={10} />
              {messages.length <= 1 ? 'Suggested questions' : 'Follow-up questions'}
            </div>
            <div className="flex flex-col gap-1.5">
              {suggestions.map((q, i) => (
                <button
                  key={i}
                  onClick={() => send(q)}
                  className="text-left text-sm font-mono px-3 py-2 border border-gray-200 bg-white hover:border-black hover:shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] transition-all text-gray-700"
                >
                  {q}
                </button>
              ))}
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
            onClick={() => send()}
            disabled={loading || !input.trim()}
            className="p-3 border border-black bg-white hover:bg-black hover:text-white transition-all disabled:opacity-50 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none"
          >
            {loading ? <IconLoader2 className="animate-spin" size={18} /> : <IconSend size={18} />}
          </button>
        </div>
      </div>
    </div>
  );
}
