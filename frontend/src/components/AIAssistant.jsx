
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Bot,
  Send,
  Sparkles,
  FileText,
  Search,
  Users,
  BarChart3,
  RotateCcw,
} from "lucide-react";

import { authenticatedFetch } from "../lib/authenticatedFetch";
import "./AIAssistant.css";

// Backend API URL
const API_BASE_URL = (
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://localhost:8000" : "")
).replace(/\/+$/, "");

const INITIAL_MESSAGE = {
  id: "welcome",
  sender: "ai",
  text: "Hello! 👋 Welcome to SMART ERP. I'm your AI Assistant. Ask me about OCR, certificates, student records, or your dashboard.",
};

const SUGGESTIONS = [
  {
    label: "How does OCR work?",
    question: "Explain OCR in simple words",
    icon: FileText,
  },
  {
    label: "Search certificates",
    question: "How can I search certificates?",
    icon: Search,
  },
  {
    label: "Manage students",
    question: "How do I manage student records?",
    icon: Users,
  },
  {
    label: "Explain reports",
    question: "Explain certificate reports in simple words",
    icon: BarChart3,
  },
];

export default function AIAssistant({ onBack }) {
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState("");

  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const requestControllerRef = useRef(null);

  // Automatically scroll to the latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, isTyping]);

  // Cancel pending requests when leaving the component
  useEffect(() => {
    return () => {
      requestControllerRef.current?.abort();
    };
  }, []);

  const handleSend = async (providedQuestion) => {
    const question = (
      typeof providedQuestion === "string"
        ? providedQuestion
        : input
    ).trim();

    if (!question || isTyping) return;

    setError("");

    const userMessage = {
      id: `${Date.now()}-user`,
      sender: "user",
      text: question,
    };

    // Use recent messages as conversation context
    const history = messages
      .filter(
        (message) =>
          message.id !== INITIAL_MESSAGE.id &&
          ["user", "ai"].includes(message.sender)
      )
      .slice(-10)
      .map((message) => ({
        role: message.sender === "ai" ? "assistant" : "user",
        content: message.text,
      }));

    setMessages((previous) => [...previous, userMessage]);
    setInput("");
    setIsTyping(true);

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    const controller = new AbortController();
    requestControllerRef.current = controller;

    try {
      const apiUrl = `${API_BASE_URL}/api/ai/chat`;

      if (!API_BASE_URL) {
        throw new Error(
          "AI backend is not configured. Set VITE_API_URL for this deployment."
        );
      }

      console.log("SMART ERP AI API:", apiUrl);
      console.log("User question:", question);

      const response = await authenticatedFetch(apiUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: question,
          history,
        }),
        signal: controller.signal,
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          data.detail ||
            `AI request failed with status ${response.status}`
        );
      }

      const answer = data.reply || data.response || data.answer;

      if (typeof answer !== "string" || !answer.trim()) {
        throw new Error("The AI returned an empty response.");
      }

      setMessages((previous) => [
        ...previous,
        {
          id: `${Date.now()}-ai`,
          sender: "ai",
          text: answer.trim(),
        },
      ]);
    } catch (err) {
      if (err.name === "AbortError") return;

      console.error("SMART ERP AI error:", err);

      let errorMessage;

      if (err instanceof TypeError) {
        errorMessage =
          "Cannot connect to the AI backend. Please check that FastAPI is running on port 8000 and that the frontend URL and CORS settings are correct.";
      } else {
        errorMessage =
          err.message || "Something went wrong. Please try again.";
      }

      setError(errorMessage);

      setMessages((previous) => [
        ...previous,
        {
          id: `${Date.now()}-error`,
          sender: "ai",
          text: `Sorry, ${errorMessage}`,
        },
      ]);
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
        setIsTyping(false);
      }
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const handleInputChange = (event) => {
    setInput(event.target.value);

    event.target.style.height = "auto";
    event.target.style.height = `${Math.min(
      event.target.scrollHeight,
      120
    )}px`;
  };

  const handleReset = () => {
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;

    setMessages([INITIAL_MESSAGE]);
    setInput("");
    setIsTyping(false);
    setError("");

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  return (
    <div className="ai-page">
      <div className="ai-container">
        <header className="ai-header">
          <button
            type="button"
            className="ai-back-btn"
            onClick={onBack}
          >
            <ArrowLeft size={17} />
            Back to Dashboard
          </button>

          <div className="ai-title-section">
            <div className="ai-title-icon">
              <Sparkles size={23} />
            </div>

            <div>
              <h1>AI Assistant</h1>
              <p>Your SMART ERP intelligent assistant</p>
            </div>
          </div>
        </header>

        <main className="ai-chat-card">
          <div className="ai-chat-header">
            <div className="ai-avatar">
              <Bot size={24} />
            </div>

            <div className="ai-chat-heading-text">
              <h2>SMART ERP Assistant</h2>

              <span className="ai-online">
                <span className="ai-online-dot" />
                {isTyping ? "Thinking..." : "Local AI Assistant"}
              </span>
            </div>

            <button
              type="button"
              className="ai-reset-btn"
              onClick={handleReset}
              title="Start a new conversation"
              aria-label="Start a new conversation"
            >
              <RotateCcw size={17} />
            </button>
          </div>

          <div
            className="ai-messages"
            role="log"
            aria-label="Chat messages"
            aria-live="polite"
          >
            {messages.map((message) => (
              <div
                key={message.id}
                className={`message-row ${
                  message.sender === "user"
                    ? "user-message-row"
                    : "ai-message-row"
                }`}
              >
                {message.sender !== "user" && (
                  <div className="message-avatar">
                    <Bot size={18} />
                  </div>
                )}

                <div
                  className={`message-bubble ${
                    message.sender === "user"
                      ? "user-bubble"
                      : "ai-bubble"
                  }`}
                >
                  {message.text}
                </div>
              </div>
            ))}

            {isTyping && (
              <div className="message-row ai-message-row">
                <div className="message-avatar">
                  <Bot size={18} />
                </div>

                <div
                  className="message-bubble ai-bubble ai-typing"
                  aria-label="Assistant is typing"
                >
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <div className="ai-suggestions">
            {SUGGESTIONS.map((suggestion) => {
              const Icon = suggestion.icon;

              return (
                <button
                  type="button"
                  key={suggestion.label}
                  onClick={() => handleSend(suggestion.question)}
                  disabled={isTyping}
                >
                  <Icon size={15} />
                  {suggestion.label}
                </button>
              );
            })}
          </div>

          <form
            className="ai-input-area"
            onSubmit={(event) => {
              event.preventDefault();
              handleSend();
            }}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask me anything about SMART ERP..."
              rows={1}
              aria-label="Message the SMART ERP Assistant"
            />

            <button
              type="submit"
              className="ai-send-btn"
              disabled={!input.trim() || isTyping}
              aria-label="Send message"
              title="Send message"
            >
              <Send size={18} />
            </button>
          </form>

          <p className="ai-footer-text">
            SMART ERP AI Assistant · Powered by local Ollama
          </p>
        </main>
      </div>
    </div>
  );
}
