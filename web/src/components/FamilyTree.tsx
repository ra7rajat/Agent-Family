"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import { Users, Info } from "lucide-react";

interface FamilyTreeProps {
  onAgentSelect?: (agentName: string) => void;
}

export default function FamilyTree({ onAgentSelect }: FamilyTreeProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  const agents = [
    { id: "Clara", x: 60, y: 140, color: "#e5484d", role: "Governess" },
    { id: "Sebastian", x: 150, y: 50, color: "#5e6ad2", role: "Head Butler" },
    { id: "Arthur", x: 240, y: 140, color: "#3db874", role: "Footman" },
  ];

  return (
    <div className={`family-tree-wrapper ${isCollapsed ? "collapsed" : ""}`}>
      <div className="tree-header" onClick={() => setIsCollapsed(!isCollapsed)}>
        <Users size={16} />
        <span>Family Hierarchy</span>
        <div className="spacer" />
        <Info size={14} className="info-icon" />
      </div>

      {!isCollapsed && (
        <div className="tree-content">
          <svg 
            width="300" 
            height="220" 
            viewBox="0 0 300 220" 
            className="tree-svg"
            preserveAspectRatio="xMidYMid meet"
          >
            {/* Connections */}
            <motion.path
              d="M 150 50 L 60 140"
              stroke="var(--border)"
              strokeWidth="1.5"
              fill="none"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 1 }}
            />
            <motion.path
              d="M 150 50 L 240 140"
              stroke="var(--border)"
              strokeWidth="1.5"
              fill="none"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 1 }}
            />

            {/* Nodes */}
            {agents.map((agent) => (
              <g 
                key={agent.id} 
                className="agent-node" 
                onClick={() => onAgentSelect?.(agent.id)}
              >
                <motion.circle
                  cx={agent.x}
                  cy={agent.y}
                  r="24"
                  fill="var(--surface)"
                  stroke={agent.color}
                  strokeWidth="2"
                  whileHover={{ r: 28, strokeWidth: 4 }}
                  className="node-circle"
                />
                <text
                  x={agent.x}
                  y={agent.y + 40}
                  textAnchor="middle"
                  className="node-label"
                >
                  {agent.id}
                </text>
                <text
                  x={agent.x}
                  y={agent.y + 52}
                  textAnchor="middle"
                  className="node-role"
                >
                  {agent.role}
                </text>
                
                {/* Visual indicators */}
                <circle cx={agent.x} cy={agent.y} r="2" fill={agent.color} />
              </g>
            ))}
          </svg>
        </div>
      )}

      <style jsx>{`
        .family-tree-wrapper {
          width: 100%;
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 12px;
          overflow: hidden;
          transition: all 0.3s ease;
        }

        .tree-header {
          padding: 12px 16px;
          display: flex;
          align-items: center;
          gap: 10px;
          cursor: pointer;
          font-size: 13px;
          font-weight: 500;
          color: var(--muted);
          border-bottom: 1px solid transparent;
          user-select: none;
        }

        .family-tree-wrapper:not(.collapsed) .tree-header {
           border-bottom-color: var(--border);
           color: var(--foreground);
        }

        .spacer { flex: 1; }
        .info-icon { opacity: 0.5; }

        .tree-content {
          padding: 10px 20px 30px 20px;
          display: flex;
          justify-content: center;
          background: radial-gradient(circle at 150px 50px, rgba(94, 106, 210, 0.05) 0%, transparent 70%);
        }

        .tree-svg {
          filter: drop-shadow(0 0 10px rgba(0,0,0,0.5));
        }

        .agent-node {
          cursor: pointer;
        }

        .node-circle {
          transition: filter 0.2s;
        }

        .agent-node:hover .node-circle {
          filter: drop-shadow(0 0 8px currentColor);
        }

        .node-label {
          fill: var(--foreground);
          font-size: 11px;
          font-weight: 600;
          pointer-events: none;
        }

        .node-role {
          fill: var(--muted);
          font-size: 9px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          pointer-events: none;
        }
      `}</style>
    </div>
  );
}
