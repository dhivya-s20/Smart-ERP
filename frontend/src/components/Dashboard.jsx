
import { useCallback, useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  FilePlus2,
  Files,
  Users,
  Search,
  ChartColumn,
  Bot,
  Settings,
  LogOut,
  Box,
  Bell,
  GraduationCap,
  TreeDeciduous,
  Clock3,
  FileCheck,
  Plus,
  MessageCircle,
  Send,
  X,
  ArrowUpRight,
  RefreshCw,
  FileText,
  ShieldCheck,
  Menu,
} from "lucide-react";

import { supabase } from "../lib/supabase";
import { authenticatedFetch } from "../lib/authenticatedFetch";
import ReactMarkdown from "react-markdown";
import "./Dashboard.css";

// FastAPI + Ollama backend
const API_BASE_URL = (
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://localhost:8000" : "")
).replace(/\/+$/, "");

// Fix escaped Markdown characters returned by the AI
function cleanReply(text) {
  return String(text || "")
    .replace(/\\([*_#])/g, "$1")
    .trim();
}

const menuItems = [
  { label: "Dashboard", icon: LayoutDashboard, page: "dashboard" },
  { label: "Add Certificate", icon: FilePlus2, page: "certificateType" },
  { label: "Extracted Data", icon: FileText, page: "extractedDataMenu" },
  { label: "My Certificates", icon: Files, page: "myCertificates" },
  { label: "Students", icon: Users, page: "students" },
  { label: "Search", icon: Search, page: "search" },
  { label: "Reports", icon: ChartColumn, page: "reports" },
  { label: "AI Assistant", icon: Bot, page: "aiAssistant" },
  { label: "Settings", icon: Settings, page: "settings" },
];

const formatDate = (value) => {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleDateString("en-GB");
};

const statusClass = (status) => {
  const value = String(status || "pending").toLowerCase();

  if (value.includes("verif") || value.includes("approved")) {
    return "verified";
  }

  if (value.includes("extract") || value.includes("process")) {
    return "extracted";
  }

  if (value.includes("reject") || value.includes("fail")) {
    return "rejected";
  }

  return "pending";
};

// Answer questions that can be calculated from loaded dashboard data
function getDashboardAnswer(question, stats, displayName) {
  const q = question.toLowerCase().trim();

  const asksPendingCount =
    /\b(how many|count|number|total|show|list)\b/.test(q) &&
    /\b(pending|unverified|awaiting verification)\b/.test(q);

  const asksStudentCount =
    /\b(how many|count|number|total)\b/.test(q) &&
    /\b(students|student names)\b/.test(q);

  const asksCertificateCount =
    /\b(how many|count|number|total)\b/.test(q) &&
    /\b(certificates|certificate records)\b/.test(q);

  const asksTodayUploads =
    /\b(today|today's|uploaded today)\b/.test(q) &&
    /\b(upload|uploads|uploaded|certificate)\b/.test(q);

  if (asksPendingCount) {
    return `There are ${stats.pendingCount} pending certificate records in the currently loaded dashboard data.`;
  }

  if (asksStudentCount) {
    return `There are ${stats.uniqueStudents} unique student names in the currently loaded certificate records.`;
  }

  if (asksCertificateCount) {
    return `There are ${stats.totalCertificates} certificate records currently loaded from Supabase.`;
  }

  if (asksTodayUploads) {
    return `Today's upload count is ${stats.todayUploads}, based on the available certificate date fields.`;
  }

  if (/^(hi|hello|hey)\b[!. ]*$/.test(q)) {
    return `Hello ${displayName}! How can I help you with SMART ERP today?`;
  }

  return null;
}

export default function Dashboard({
  user,
  onNavigate = () => {},
  onUpload = () => {},
  onLogout = () => {},
}) {
  const [certificates, setCertificates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const [chatOpen, setChatOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Hi! Welcome to SMART ERP. 👋 Ask me about OCR, certificates, students, or your dashboard.",
    },
  ]);

  const chatEndRef = useRef(null);
  const chatInputRef = useRef(null);
  const requestControllerRef = useRef(null);

  // Load certificate records from Supabase
  const loadCertificates = useCallback(async () => {
    setLoading(true);
    setErrorMessage("");

    try {
      if (!supabase) {
        throw new Error(
          "Supabase credentials missing. Check your frontend/.env file."
        );
      }

      const { data, error } = await supabase
        .from("certificates")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(500);

      if (error) throw error;

      setCertificates(data || []);
    } catch (error) {
      console.error("Supabase certificate loading error:", error);

      setErrorMessage(
        error.message || "Unable to load certificate records."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCertificates();
  }, [loadCertificates]);

  // Scroll to the latest chatbot message
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, chatOpen, chatBusy]);

  // Cancel an active request when Dashboard unmounts
  useEffect(() => {
    return () => {
      requestControllerRef.current?.abort();
    };
  }, []);

  const displayName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "Student";

  const roleName = user?.user_metadata?.role || "Student";

  const today = new Date();

  const todayKey = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");

  const todayUploads = certificates.filter((certificate) => {
    const value = certificate.created_at || certificate.date_extracted;

    if (!value) return false;

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) return false;

    const key = [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");

    return key === todayKey;
  }).length;

  const uniqueStudents = new Set(
    certificates
      .map((certificate) => certificate.student_name?.trim())
      .filter(Boolean)
  ).size;

  const pendingCount = certificates.filter((certificate) => {
    const status = String(certificate.status || "").toLowerCase();

    return [
      "pending",
      "processing",
      "under review",
      "pending verification",
    ].includes(status);
  }).length;

  const stats = [
    {
      title: "Total Students",
      value: uniqueStudents,
      icon: GraduationCap,
      tone: "blue",
    },
    {
      title: "Total Certificates",
      value: certificates.length,
      icon: TreeDeciduous,
      tone: "green",
    },
    {
      title: "Pending Verification",
      value: pendingCount,
      icon: Clock3,
      tone: "orange",
    },
    {
      title: "Today's Uploads",
      value: todayUploads,
      icon: FileCheck,
      tone: "purple",
    },
  ];

  const navigateTo = (page) => {
    setMobileMenuOpen(false);

    if (page === "dashboard") return;

    if (page === "certificateType") {
      onUpload();
      return;
    }

    if (page === "aiAssistant") {
      setChatOpen(true);
      return;
    }

    onNavigate(page);
  };

  // Send messages to the local Ollama AI through FastAPI
  const sendMessage = async (event) => {
    event.preventDefault();

    const question = chatInput.trim();

    if (!question || chatBusy) return;

    const history = messages.slice(-10).map((message) => ({
      role: message.role === "assistant" ? "assistant" : "user",
      content: message.text,
    }));

    setMessages((previous) => [
      ...previous,
      { role: "user", text: question },
    ]);

    setChatInput("");
    setChatBusy(true);

    const controller = new AbortController();
    requestControllerRef.current = controller;

    try {
      // Answer simple count questions using loaded Supabase data
      const dashboardAnswer = getDashboardAnswer(
        question,
        {
          pendingCount,
          uniqueStudents,
          totalCertificates: certificates.length,
          todayUploads,
        },
        displayName
      );

      let answer = dashboardAnswer;

      // Send other questions to the local AI
      if (!answer) {
        if (!API_BASE_URL) {
          throw new Error(
            "AI backend is not configured. Set VITE_API_URL for this deployment."
          );
        }

        const apiUrl = `${API_BASE_URL}/api/ai/chat`;

        console.log("SMART ERP chatbot API:", apiUrl);
        console.log("Chat question:", question);

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

        answer = cleanReply(
          data.reply || data.response || data.answer || ""
        );

        if (!answer) {
          throw new Error("The AI returned an empty response.");
        }
      }

      if (controller.signal.aborted) return;

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          text: cleanReply(answer),
        },
      ]);
    } catch (error) {
      if (error.name === "AbortError") return;

      console.error("SMART ERP chatbot error:", error);

      let errorText;

      if (error instanceof TypeError) {
        errorText =
          "Cannot connect to the AI backend. Check that FastAPI is running on port 8000 and verify the backend CORS settings.";
      } else {
        errorText =
          error.message || "Something went wrong. Please try again.";
      }

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          text: `Sorry, ${errorText}`,
        },
      ]);
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
        setChatBusy(false);
      }
    }
  };

  const closeChat = () => {
    requestControllerRef.current?.abort();
    requestControllerRef.current = null;

    setChatBusy(false);
    setChatOpen(false);
  };

  return (
    <div className="erp-app">
      {mobileMenuOpen && (
        <button
          className="erp-mobile-overlay"
          type="button"
          aria-label="Close sidebar"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      <aside
        className={`erp-sidebar ${mobileMenuOpen ? "is-open" : ""}`}
      >
        <div className="erp-brand">
          <div className="erp-brand-mark">
            <Box size={25} />
          </div>
          <span>SMART ERP</span>
        </div>

        <div className="erp-profile">
          <div className="erp-avatar">
            {displayName.slice(0, 2).toUpperCase()}
          </div>

          <div className="erp-profile-info">
            <strong>{displayName}</strong>
            <span>{roleName}</span>
          </div>
        </div>

        <nav className="erp-navigation">
          {menuItems.map(({ label, icon: Icon, page }) => (
            <button
              type="button"
              key={page}
              className={`erp-nav-item ${
                page === "dashboard" ? "active" : ""
              }`}
              onClick={() => navigateTo(page)}
            >
              <Icon size={19} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <button
          type="button"
          className="erp-nav-item erp-logout"
          onClick={onLogout}
        >
          <LogOut size={19} />
          <span>Logout</span>
        </button>
      </aside>

      <main className="erp-main">
        <header className="erp-topbar">
          <button
            type="button"
            className="erp-mobile-menu"
            aria-label="Open sidebar"
            onClick={() => setMobileMenuOpen(true)}
          >
            <Menu size={22} />
          </button>

          <button
            type="button"
            className="erp-global-search"
            onClick={() => navigateTo("search")}
          >
            <Search size={19} />
            <span>Search certificates, students...</span>
          </button>

          <div className="erp-topbar-right">
            <button
              type="button"
              className="erp-icon-button"
              aria-label="Notifications"
              onClick={() =>
                window.alert("You have no new notifications.")
              }
            >
              <Bell size={19} />
            </button>

            <div className="erp-top-avatar">
              {displayName.slice(0, 2).toUpperCase()}
            </div>

            <div className="erp-top-user">
              <strong>{displayName}</strong>
              <span>{roleName}</span>
            </div>
          </div>
        </header>

        <div className="erp-content">
          <div className="erp-page-heading">
            <div>
              <h1>Dashboard</h1>
              <p>
                Overview of your certificate data and system activity
              </p>
            </div>

            <button
              type="button"
              className="erp-refresh-button"
              onClick={loadCertificates}
              disabled={loading}
            >
              <RefreshCw
                size={16}
                className={loading ? "erp-spin" : ""}
              />
              Refresh
            </button>
          </div>

          {errorMessage && (
            <div className="erp-error-banner">
              <span>Supabase error: {errorMessage}</span>
              <button type="button" onClick={loadCertificates}>
                Retry
              </button>
            </div>
          )}

          <section className="erp-stats-grid">
            {stats.map(({ title, value, icon: Icon, tone }) => (
              <article className="erp-stat-card" key={title}>
                <div className={`erp-stat-icon ${tone}`}>
                  <Icon size={23} />
                </div>

                <div className="erp-stat-details">
                  <span>{title}</span>
                  <strong>
                    {loading ? "—" : value.toLocaleString()}
                  </strong>
                  <small>Live dashboard records</small>
                </div>
              </article>
            ))}
          </section>

          <section className="erp-dashboard-grid">
            <article className="erp-panel erp-recent-panel">
              <div className="erp-panel-heading">
                <h2>Recent Uploads</h2>

                <button
                  type="button"
                  onClick={() => navigateTo("myCertificates")}
                >
                  View All <ArrowUpRight size={15} />
                </button>
              </div>

              <div className="erp-table-wrap">
                <table className="erp-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Student Name</th>
                      <th>Certificate Type</th>
                      <th>Date</th>
                      <th>Status</th>
                    </tr>
                  </thead>

                  <tbody>
                    {loading ? (
                      <tr>
                        <td colSpan={5} className="erp-empty-state">
                          Loading Supabase records...
                        </td>
                      </tr>
                    ) : certificates.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="erp-empty-state">
                          No certificate records found.
                        </td>
                      </tr>
                    ) : (
                      certificates.slice(0, 7).map((certificate, index) => (
                        <tr
                          key={
                            certificate.id ??
                            `${certificate.student_name}-${index}`
                          }
                        >
                          <td>{index + 1}</td>

                          <td className="erp-student-cell">
                            {certificate.student_name || "—"}
                          </td>

                          <td>
                            {certificate.certificate_type || "—"}
                          </td>

                          <td>
                            {formatDate(
                              certificate.date_extracted ||
                                certificate.created_at
                            )}
                          </td>

                          <td>
                            <span
                              className={`erp-status ${statusClass(
                                certificate.status
                              )}`}
                            >
                              {certificate.status || "Pending"}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </article>

            <div className="erp-right-column">
              <article className="erp-panel erp-quick-panel">
                <div className="erp-panel-heading">
                  <h2>Quick Actions</h2>
                </div>

                <div className="erp-quick-actions">
                  <button
                    type="button"
                    className="erp-action-primary"
                    onClick={onUpload}
                  >
                    <Plus size={19} />
                    Add Certificate
                  </button>

                  <button
                    type="button"
                    onClick={() => navigateTo("myCertificates")}
                  >
                    <Files size={17} />
                    View All Certificates
                  </button>

                  <button
                    type="button"
                    onClick={() => navigateTo("search")}
                  >
                    <Search size={17} />
                    Search Student
                  </button>

                  <button
                    type="button"
                    onClick={() => navigateTo("reports")}
                  >
                    <ChartColumn size={17} />
                    Generate Report
                  </button>
                </div>
              </article>

              <article className="erp-panel erp-documents-panel">
                <div className="erp-panel-heading">
                  <h2>Document Types Supported</h2>
                </div>

                <div className="erp-document-grid">
                  {[
                    ["10th/12th Marksheet", "blue", FileText],
                    ["TC Certificate", "red", Files],
                    ["Community Certificate", "purple", ShieldCheck],
                    ["Income Certificate", "green", FileCheck],
                    ["Aadhaar", "purple", Users],
                    ["Birth Certificate", "blue", GraduationCap],
                    ["Diploma", "purple", FileCheck],
                  ].map(([label, tone, Icon]) => (
                    <button
                      type="button"
                      className="erp-document-type"
                      key={label}
                      onClick={onUpload}
                    >
                      <span className={`erp-document-icon ${tone}`}>
                        <Icon size={21} />
                      </span>
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              </article>
            </div>
          </section>
        </div>

        <footer className="erp-footer">
          <Box size={19} />
          <span>
            SMART ERP CERTIFICATE DATA EXTRACTION AND MANAGEMENT SYSTEM
          </span>
        </footer>
      </main>

      <button
        type="button"
        className={`erp-chat-launcher ${chatOpen ? "is-hidden" : ""}`}
        onClick={() => setChatOpen(true)}
        aria-label="Open AI Assistant"
      >
        <MessageCircle size={22} />
        <span>AI Assistant</span>
      </button>

      {chatOpen && (
        <section
          className="erp-chat-window"
          aria-label="AI Assistant chat"
        >
          <header className="erp-chat-header">
            <div className="erp-chat-heading-icon">
              <Bot size={22} />
            </div>

            <div>
              <strong>SMART ERP Assistant</strong>
              <span>
                <i />
                {chatBusy ? "Thinking..." : "Local AI Assistant"}
              </span>
            </div>

            <button
              type="button"
              className="erp-chat-close"
              onClick={closeChat}
              aria-label="Close chat"
            >
              <X size={20} />
            </button>
          </header>

          <div className="erp-chat-messages">
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={`erp-chat-message ${message.role}`}
              >
                {message.role === "assistant" ? (
                  <ReactMarkdown>{cleanReply(message.text)}</ReactMarkdown>
                ) : (
                  message.text
                )}
              </div>
            ))}

            {chatBusy && (
              <div className="erp-chat-message assistant">
                Thinking...
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          <form className="erp-chat-form" onSubmit={sendMessage}>
            <input
              ref={chatInputRef}
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder="Ask me anything about SMART ERP..."
              aria-label="Message the assistant"
              disabled={chatBusy}
            />

            <button
              type="submit"
              disabled={!chatInput.trim() || chatBusy}
              aria-label="Send message"
            >
              <Send size={18} />
            </button>
          </form>

          <p className="erp-chat-disclaimer">
            SMART ERP Assistant · Powered by local Ollama
          </p>
        </section>
      )}
    </div>
  );
}
