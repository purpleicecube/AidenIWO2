import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Send,
  Bot,
  User,
  Loader2,
  Plus,
  MessageSquare,
  Trash2,
  GitBranch,
} from "lucide-react";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { usePageTitle } from "@/hooks/use-page-title";
import type { ChatSession, ChatMessage } from "@shared/schema";
import SplitPane from "@/components/split-pane";

type SessionWithMessages = ChatSession & { messages: ChatMessage[] };

export default function ChatPage() {
  usePageTitle("Chat with Aiden");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const sessionsQuery = useQuery<ChatSession[]>({
    queryKey: ["/api/chat/sessions"],
  });

  const activeSessionQuery = useQuery<SessionWithMessages>({
    queryKey: ["/api/chat/sessions", activeSessionId],
    enabled: !!activeSessionId,
  });

  const messages = activeSessionQuery.data?.messages || [];

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const deleteSessionMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiRequest("DELETE", `/api/chat/sessions/${id}`);
    },
    onSuccess: (_data, id) => {
      if (activeSessionId === id) {
        setActiveSessionId(null);
      }
      queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions"] });
    },
  });

  const chatMutation = useMutation({
    mutationFn: async (message: string) => {
      let sessionId = activeSessionId;
      if (!sessionId) {
        const res = await apiRequest("POST", "/api/chat/sessions", {});
        const newSession: ChatSession = await res.json();
        sessionId = newSession.id;
        setActiveSessionId(sessionId);
        queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions"] });
      }
      const res = await apiRequest("POST", `/api/chat/sessions/${sessionId}/messages`, { message });
      return res.json();
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions", activeSessionId || data.sessionId] });
      if (!activeSessionId && data.sessionId) {
        setActiveSessionId(data.sessionId);
      }
      queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions"] });
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions", activeSessionId] });
    },
  });

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || chatMutation.isPending) return;
    setInput("");
    chatMutation.mutate(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleNewChat = () => {
    setActiveSessionId(null);
  };

  const sessions = sessionsQuery.data || [];
  const activeSession = activeSessionQuery.data;
  const rawGcc = activeSession?.gccMemory as Record<string, unknown> | null;
  const gccMemory = rawGcc ? (
    rawGcc["gcc.project_id"] ? rawGcc : {
      "gcc.project_id": rawGcc.correlationId ? `aiden-chat-${String(rawGcc.correlationId).slice(0, 8)}` : null,
      "gcc.branch": "main",
      "gcc.tier": "tier1",
      "gcc.last_commit_id": null,
      "gcc.context_commit_count": 0,
      "gcc.last_action": rawGcc.lastAction || rawGcc["lastAction"] || "none",
      ...rawGcc,
    }
  ) : null;

  return (
    <div className="flex h-full" data-testid="page-chat">
      <SplitPane
        panes={[
          { defaultSize: 25, minSize: 15, maxSize: 40 },
          { defaultSize: 75, minSize: 50, maxSize: 85 },
        ]}
        storageKey="chat"
      >
      <div className="flex flex-col bg-muted/30 h-full">
        <div className="p-3 border-b flex items-center justify-between gap-2 flex-wrap">
          <span className="text-sm font-medium">History</span>
          <Button
            size="icon"
            variant="ghost"
            onClick={handleNewChat}
            data-testid="button-new-chat"
          >
            <Plus className="w-4 h-4" />
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {sessions.map((session) => (
              <div
                key={session.id}
                className={`group flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer text-sm transition-colors ${
                  activeSessionId === session.id
                    ? "bg-accent text-accent-foreground"
                    : "hover-elevate"
                }`}
                onClick={() => setActiveSessionId(session.id)}
                data-testid={`session-item-${session.id}`}
              >
                <MessageSquare className="w-3.5 h-3.5 flex-shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate">
                  {session.title || "New Conversation"}
                </span>
                <Button
                  size="icon"
                  variant="ghost"
                  className="invisible group-hover:visible h-6 w-6"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteSessionMutation.mutate(session.id);
                  }}
                  data-testid={`button-delete-session-${session.id}`}
                >
                  <Trash2 className="w-3 h-3" />
                </Button>
              </div>
            ))}
            {sessions.length === 0 && !sessionsQuery.isLoading && (
              <p className="text-xs text-muted-foreground text-center py-4">
                No conversations yet
              </p>
            )}
          </div>
        </ScrollArea>
        {gccMemory && activeSessionId && (
          <div className="border-t p-3 space-y-2" data-testid="container-gcc-memory">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <GitBranch className="w-3 h-3" />
              GCC Memory
            </div>
            <div className="text-xs text-muted-foreground space-y-1">
              <div className="truncate" title={String(gccMemory["gcc.project_id"] || "")} data-testid="text-gcc-project">
                Project: {String(gccMemory["gcc.project_id"] || "—")}
              </div>
              <div data-testid="text-gcc-branch">
                Branch: {String(gccMemory["gcc.branch"] || "main")}
              </div>
              <div data-testid="text-gcc-tier">
                Tier: {String(gccMemory["gcc.tier"] || "tier1")}
              </div>
              <div data-testid="text-gcc-last-commit">
                Last Commit: <span className="font-mono">{String(gccMemory["gcc.last_commit_id"] || "—")}</span>
              </div>
              <div data-testid="text-gcc-commit-count">
                Commits: {Number(gccMemory["gcc.context_commit_count"] || 0)}
              </div>
              <div data-testid="text-gcc-action">
                Action: {String(gccMemory["gcc.last_action"] || "none")}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col min-w-0 h-full">
        <div className="flex items-center justify-between gap-4 p-4 pb-3 border-b flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary">
              <Bot className="w-4 h-4 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-lg font-semibold" data-testid="heading-chat">Chat with Aiden</h1>
              <p className="text-xs text-muted-foreground">
                {activeSession
                  ? activeSession.title
                  : "Start a new conversation"}
              </p>
            </div>
          </div>
          <Badge variant="outline" data-testid="badge-chat-status">
            {chatMutation.isPending ? "Thinking..." : "Online"}
          </Badge>
        </div>

        <div className="flex-1 overflow-auto p-6" data-testid="container-messages">
          {!activeSessionId || messages.length === 0 ? (
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
                  key={msg.id}
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
                      {new Date(msg.createdAt).toLocaleTimeString()}
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
      </SplitPane>
    </div>
  );
}
