import { useState } from 'react';

interface Message {
  id: string;
  sender: 'user' | 'bot';
  text: string;
}

export default function Chat() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'bot', text: 'Hello. I am docbot. Ask me about your codebase.' }
  ]);

  const send = () => {
    if (!input.trim()) return;
    setMessages(prev => [
      ...prev, 
      { id: Date.now().toString(), sender: 'user', text: input },
      { id: (Date.now() + 1).toString(), sender: 'bot', text: `Echo: ${input}` } // Mock response
    ]);
    setInput('');
  };

  return (
    <div className="flex flex-col h-full border border-black p-4 space-y-4">
      <div className="flex-1 overflow-y-auto space-y-4">
        {messages.map(m => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[70%] p-2 border border-black ${m.sender === 'user' ? 'bg-black text-white' : 'bg-white text-black'}`}>
              <p className="text-sm font-mono">{m.sender.toUpperCase()}:</p>
              <p className="whitespace-pre-wrap">{m.text}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input 
          className="flex-1 border border-black p-2 outline-none font-mono text-sm"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()}
          placeholder="Type a query..."
        />
        <button 
          onClick={send}
          className="px-4 py-2 border border-black hover:bg-black hover:text-white transition-colors font-bold uppercase text-sm"
        >
          Send
        </button>
      </div>
    </div>
  );
}
