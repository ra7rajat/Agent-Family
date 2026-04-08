"use client";

import { useState, useRef, useEffect } from "react";
import { Send } from "lucide-react";
import MessageCard, { MessageProps } from "./MessageCard";
import { AnimatePresence } from "framer-motion";
import { useAuth } from "../context/AuthContext";
import FamilySwiper from "./FamilySwiper";
import FamilyTree from "./FamilyTree";

const API = "http://localhost:8000";

let msgCounter = 0;
function newId() {
  return `msg-${Date.now()}-${++msgCounter}`;
}

export default function ChatInterface() {
  const { signIn } = useAuth();
  const [messages, setMessages] = useState<MessageProps[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleAgentSummon = (agentName: string) => {
    // Smoothly focus input and prefix with the agent's name
    const input = document.getElementById("chat-input") as HTMLInputElement;
    if (input) {
      input.focus();
      setInput(`@${agentName} `);
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    // Push user message immediately
    const userMsg: MessageProps = {
      id: newId(),
      agent: "User",
      state: "completed",
      message: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    try {
      const response = await fetch(`${API}/api/v1/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text }),
      });

      // If session expired, trigger re-auth
      if (response.status === 401) {
        setMessages((prev) => [
          ...prev,
          {
            id: newId(),
            agent: "Sebastian",
            state: "completed" as const,
            message: "Master Rajat, your session has expired. Pray tell, shall we sign you in again?",
          },
        ]);
        setTimeout(() => signIn(), 1800);
        return;
      }

      if (!response.body) throw new Error("No readable stream from server");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE messages are terminated by \n\n
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;

          try {
            const event = JSON.parse(line.slice(6));

            if (event.type === "done") {
              setMessages((prev) => prev.filter((m) => m.state !== "thinking"));
              setIsStreaming(false);
              continue;
            }

            setMessages((prev) => {
              // Internal monologues are unique entries usually
              if (event.type === "internal_monologue") {
                 return [
                   ...prev,
                   {
                     id: newId(),
                     agent: event.agent as string,
                     state: "internal_monologue" as const,
                     message: event.message as string,
                     delayIndex: prev.length,
                   }
                 ];
              }

              // If we already have a "thinking" card for this agent, update it
              const idx = prev.findIndex(
                (m) => m.agent === event.agent && m.state === "thinking"
              );

              if (idx >= 0) {
                const updated = [...prev];
                updated[idx] = {
                  ...updated[idx],
                  state: event.type === "completed" ? "completed" : "thinking",
                  message: event.message,
                };
                return updated;
              }

              // Otherwise add a new card
              return [
                ...prev,
                {
                  id: newId(),
                  agent: event.agent as string,
                  state: (event.type === "completed" ? "completed" : "thinking") as "completed" | "thinking",
                  message: event.message as string,
                  delayIndex: prev.length,
                },
              ];
            });
          } catch {
            // Ignore malformed SSE frames
          }
        }
      }
    } catch (err) {
      console.error("Chat error:", err);
      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          agent: "Sebastian",
          state: "error" as "completed",
          message: `⚠️ Master Rajat, the household systems are temporarily unresponsive. Error: ${err}`,
        },
      ]);
    } finally {
      setIsStreaming(false);
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <>
      {/* Message list */}
      <div
        className="chat-scroll-area"
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label="Agent conversation"
      >
        <div className="chat-top-layout">
          <aside className="chat-top-left">
            <FamilyTree onAgentSelect={handleAgentSummon} />
          </aside>
          <section className="chat-top-main">
            <FamilySwiper />
          </section>
        </div>
        
        <AnimatePresence>
          {messages.map((msg) => (
            <MessageCard key={msg.id} {...msg} />
          ))}
        </AnimatePresence>

        {isStreaming && (
          <div className="status-indicator" aria-live="assertive" role="status">
            <div className="spinner" aria-hidden="true" />
            The household is coordinating…
          </div>
        )}
      </div>

      {/* Input bar */}
      <div className="input-container">
        <form onSubmit={handleFormSubmit} className="input-form">
          <input
            id="chat-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder="e.g. Schedule a sync tomorrow at 3pm and add a todo to review slides…"
            className="chat-input"
            aria-label="Type your request"
            autoComplete="off"
          />
          <button
            type="submit"
            className="send-btn"
            disabled={isStreaming || !input.trim()}
            aria-label="Send message"
          >
            <Send size={18} aria-hidden="true" />
          </button>
        </form>
      </div>
    </>
  );
}
