"use client";

import { AnimatePresence, motion } from "framer-motion";
import { BrainCircuit, Calendar, CheckSquare } from "lucide-react";
import { useEffect, useRef } from "react";
import { useAuth } from "../context/AuthContext";

const AGENT_ENTRIES = [
  {
    Icon: BrainCircuit,
    label: "Sebastian",
    message: "Master Rajat, I have arrived. Shall we attend to the household duties?",
    delay: 0,
  },
  {
    Icon: Calendar,
    label: "Clara",
    message: "The sanctity of time must be observed. I am ready to manage your schedule.",
    delay: 0.5,
  },
  {
    Icon: CheckSquare,
    label: "Arthur",
    message: "Right away, Master Rajat! Consideration it done!",
    delay: 1.0,
  },
  {
    Icon: BrainCircuit,
    label: "Sebastian",
    message:
      "To begin, I require your permission to access the Google records. Pray tell, will you sign in?",
    delay: 1.5,
  },
];

export default function SignInPrompt() {
  const { signIn } = useAuth();
  const btnRef = useRef<HTMLButtonElement>(null);

  // Focus the sign-in button after the last card animates in
  useEffect(() => {
    const timer = setTimeout(() => btnRef.current?.focus(), 2200);
    return () => clearTimeout(timer);
  }, []);

  // Keyboard focus trap inside the prompt region
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      // nothing to close — prompt is the whole page
    }
  };

  return (
    <div
      className="signin-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="signin-title"
      onKeyDown={handleKeyDown}
    >
      <div className="signin-scroll-area">
        <AnimatePresence>
          {AGENT_ENTRIES.map((entry, i) => (
            <motion.div
              key={i}
              className="message agent"
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.4, delay: entry.delay, ease: [0.23, 1, 0.32, 1] }}
              aria-live="polite"
            >
              <div className="message-avatar" aria-hidden="true">
                <entry.Icon size={18} />
              </div>
              <div className="message-content">
                <div className="message-header">
                  <span>{entry.label}</span>
                </div>
                <div className="message-bubble">
                  <p>{entry.message}</p>
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <div className="signin-action">
        <button
          id="signin-title"
          ref={btnRef}
          className="signin-btn"
          onClick={signIn}
          aria-label="Sign in with Google to connect your Calendar and Tasks"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 48 48"
            aria-hidden="true"
            focusable="false"
          >
            <path
              fill="#EA4335"
              d="M24 9.5c3.5 0 6.6 1.2 9.1 3.2l6.8-6.8C35.7 2.5 30.2 0 24 0 14.8 0 7 5.4 3.2 13.3l7.9 6.1C13 13.7 18.1 9.5 24 9.5z"
            />
            <path
              fill="#4285F4"
              d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.4c-.5 2.8-2.1 5.2-4.5 6.8l7 5.4c4.1-3.8 6.5-9.4 6.5-16.2z"
            />
            <path
              fill="#FBBC05"
              d="M11.1 28.6A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.1.7-4.6L2.3 13.3A24 24 0 0 0 0 24c0 3.8.9 7.3 2.5 10.4l8.6-5.8z"
            />
            <path
              fill="#34A853"
              d="M24 48c6.2 0 11.4-2 15.2-5.5l-7-5.4c-2 1.4-4.6 2.2-8.2 2.2-5.9 0-10.9-4-12.7-9.4l-8 6.2C7 43.3 14.9 48 24 48z"
            />
          </svg>
          Connect Google Account
        </button>
      </div>
    </div>
  );
}
