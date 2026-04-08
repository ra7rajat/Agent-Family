"use client";

import { motion } from "framer-motion";
import { User, ShieldCheck, Activity, Zap, BrainCircuit } from "lucide-react";
import { ReactNode } from "react";

export type MessageState = "thinking" | "completed" | "error" | "internal_monologue";

export interface MessageProps {
  id: string;
  agent: string; // "User", "Sebastian", "Clara", "Arthur"
  state: MessageState;
  message: string;
  delayIndex?: number;
}

const AGENT_META: Record<string, { icon: any, label: string, color: string, portrait: string }> = {
  "Sebastian": { icon: ShieldCheck, label: "Sebastian", color: "#5e6ad2", portrait: "/portraits/sebastian.png" },
  "Clara": { icon: Activity, label: "Clara", color: "#e5484d", portrait: "/portraits/clara.png" },
  "Arthur": { icon: Zap, label: "Arthur", color: "#3db874", portrait: "/portraits/arthur.png" },
  "MasterAgent": { icon: BrainCircuit, label: "Sebastian", color: "#5e6ad2", portrait: "/portraits/sebastian.png" },
  "CalendarAgent": { icon: Activity, label: "Clara", color: "#e5484d", portrait: "/portraits/clara.png" },
  "TaskAgent": { icon: Zap, label: "Arthur", color: "#3db874", portrait: "/portraits/arthur.png" },
};

export default function MessageCard({ agent, state, message, delayIndex = 0 }: MessageProps) {
  const isUser = agent === "User";
  const meta = AGENT_META[agent] || { icon: BrainCircuit, label: agent, color: "var(--accent)", portrait: "" };
  
  const Icon = meta.icon;
  const label = meta.label;

  const renderContent = () => {
    if (state === "thinking") {
      return <p>Thinking...</p>;
    }
    
    return message.split("\n").map((line, i) => (
      <p key={i}>{line}</p>
    ));
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={`message ${isUser ? "user" : "agent"} ${state === "internal_monologue" ? "internal-monologue" : ""} ${state}`}
    >
      <div className={`message-avatar ${isUser ? "user-avatar" : ""}`} style={{ borderColor: isUser ? "var(--accent)" : meta.color }}>
        {isUser ? (
          <User size={18} />
        ) : meta.portrait ? (
          <img src={meta.portrait} alt={agent} className="avatar-img" />
        ) : (
          <Icon size={18} />
        )}
      </div>
      
      <div className="message-content">
        {!isUser && (
          <div className="message-header" style={{ color: meta.color }}>
             <span>{label}</span>
             {state === "internal_monologue" && <span className="monologue-tag">— Internal Coordination</span>}
          </div>
        )}
        <div className="message-bubble">
           {renderContent()}
        </div>
      </div>

      <style jsx>{`
        .avatar-img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          border-radius: inherit;
        }

        .monologue-tag {
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 1px;
          opacity: 0.5;
          margin-left: 4px;
        }
      `}</style>
    </motion.div>
  );
}
