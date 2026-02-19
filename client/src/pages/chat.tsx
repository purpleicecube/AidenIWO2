import { useState, useRef, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Send, Bot, User, AlertCircle, Loader2 } from "lucide-react";
import { apiRequest } from "@/lib/queryClient";
import { usePageTitle } from "@/hooks/use-page-title";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export default function ChatPage() {
  usePageTitle("Chat with Aiden");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const chatMutation = useMutation({
    mutationFn: async (message: string) => {
      const history = messages.map(m => ({ role: m.role, content: m.content }));
      const res = await apiRequest("POST", "/api/chat", { message, history });
      return res.json();
    },
    onSuccess: (data) => {
      setMessages(prev => [
        ...prev,
        { role: "assistant", content: data.reply, timestamp: new Date() },
      ]);
    },
    onError: (error: any) => {
      let errorMsg = "Failed to get a response from Aiden.";
      try {
        const raw = error?.message || "";
        const jsonStart = raw.indexOf("{");
        if (jsonStart >= 0) {
          const parsed = JSON.parse(raw.slice(jsonStart));
          errorMsg = parsed.message || errorMsg;
        } else if (raw) {
          errorMsg = raw.replace(/^\d+:\s*/, "");
        }
      } catch {}
      setMessages(prev => [
        ...prev,
        { role: "assistant", content: `**Error:** ${errorMsg}`, timestamp: new Date() },
      ]);
    },
  });

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || chatMutation.isPending) return;
    setMessages(prev => [...prev, { role: "user", content: trimmed, timestamp: new Date() }]);
    setInput("");
    chatMutation.mutate(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full" data-testid="page-chat">
      <div className="flex items-center justify-between gap-4 p-6 pb-4 border-b flex-wrap">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-md bg-primary">
            <Bot className="w-5 h-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-xl font-semibold" data-testid="heading-chat">Chat with Aiden</h1>
            <p className="text-sm text-muted-foreground">Ask about work orders, system status, and operations</p>
          </div>
        </div>
        <Badge variant="outline" data-testid="badge-chat-status">
          {chatMutation.isPending ? "Thinking..." : "Online"}
        </Badge>
      </div>

      <div className="flex-1 overflow-auto p-6" data-testid="container-messages">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center gap-4">
            <div className="flex items-center justify-center w-16 h-16 rounded-full bg-muted">
              <Bot className="w-8 h-8 text-muted-foreground" />
            </div>
            <div>
              <h2 className="text-lg font-medium" data-testid="text-empty-state">Welcome! I'm Aiden.</h2>
              <p className="text-sm text-muted-foreground mt-1 max-w-md">
                Your Tier 1 orchestration manager. Ask me about work order statuses, sub-agent assignments, workflow progress, or any operational question.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 mt-4 justify-center">
              {[
                "What's the current system status?",
                "Show me pending work orders",
                "Which sub-agents are active?",
                "Summarize recent activity",
              ].map((suggestion) => (
                <Button
                  key={suggestion}
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setInput(suggestion);
                    textareaRef.current?.focus();
                  }}
                  data-testid={`button-suggestion-${suggestion.slice(0, 10).replace(/\s/g, "-").toLowerCase()}`}
                >
                  {suggestion}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4 max-w-3xl mx-auto">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                data-testid={`message-${msg.role}-${i}`}
              >
                {msg.role === "assistant" && (
                  <div className="flex-shrink-0 flex items-start pt-1">
                    <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary">
                      <Bot className="w-4 h-4 text-primary-foreground" />
                    </div>
                  </div>
                )}
                <Card
                  className={`px-4 py-3 max-w-[80%] ${
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : ""
                  }`}
                >
                  <div
                    className={`text-sm whitespace-pre-wrap break-words ${
                      msg.role === "user" ? "" : "prose prose-sm dark:prose-invert max-w-none"
                    }`}
                    data-testid={`text-message-content-${i}`}
                  >
                    {msg.content}
                  </div>
                  <div
                    className={`text-xs mt-2 ${
                      msg.role === "user" ? "text-primary-foreground/70" : "text-muted-foreground"
                    }`}
                  >
                    {msg.timestamp.toLocaleTimeString()}
                  </div>
                </Card>
                {msg.role === "user" && (
                  <div className="flex-shrink-0 flex items-start pt-1">
                    <div className="flex items-center justify-center w-8 h-8 rounded-md bg-muted">
                      <User className="w-4 h-4 text-muted-foreground" />
                    </div>
                  </div>
                )}
              </div>
            ))}
            {chatMutation.isPending && (
              <div className="flex gap-3 justify-start" data-testid="message-loading">
                <div className="flex-shrink-0 flex items-start pt-1">
                  <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary">
                    <Bot className="w-4 h-4 text-primary-foreground" />
                  </div>
                </div>
                <Card className="px-4 py-3">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Aiden is thinking...
                  </div>
                </Card>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <div className="border-t p-4" data-testid="container-input">
        <div className="flex gap-2 max-w-3xl mx-auto items-end">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask Aiden anything about your work orders and operations..."
            className="resize-none min-h-[44px] max-h-[120px] text-sm"
            rows={1}
            disabled={chatMutation.isPending}
            data-testid="input-chat-message"
          />
          <Button
            onClick={handleSend}
            disabled={!input.trim() || chatMutation.isPending}
            size="icon"
            data-testid="button-send-message"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
