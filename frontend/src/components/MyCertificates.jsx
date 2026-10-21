
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  GraduationCap,
  FileText,
  ShieldCheck,
  Clock3,
  Search,
  ArrowLeft,
  RefreshCw,
  CircleAlert,
} from "lucide-react";
import { authenticatedFetch } from "../lib/authenticatedFetch";
import "./MyCertificates.css";

const API_BASE_URL = (
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "")
).replace(/\/+$/, "");

function getValue(record, keys, fallback = "") {
  for (const key of keys) {
    const value = record?.[key];
    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }
  return fallback;
}

function formatCertificateType(value) {
  const labels = {
    aadhaar_card: "Aadhaar Card",
    state_board_10th: "10th Marksheet",
    state_board_12th: "12th Marksheet",
    community_certificate: "Community Certificate",
    birth_certificate: "Birth Certificate",
    transfer_certificate: "Transfer Certificate",
    income_certificate: "Income Certificate",
    caste_certificate: "Caste Certificate",
    diploma_certificate: "Diploma Certificate",
  };

  const normalized = String(value || "Certificate")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");

  return labels[normalized] ||
    String(value || "Certificate")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDate(value) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);

  return date.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function normalizeStatus(record) {
  const status = String(
    getValue(record, ["verification_status", "status", "verification"], "")
  ).toLowerCase().trim();

  if (status === "verified") return "Verified";
  if (status === "rejected") return "Rejected";
  if (status === "pending") return "Pending";

  return "Extracted";
}

function normalizeCertificate(record, index) {
  const docType = getValue(record, [
    "doc_type",
    "certificate_type",
    "document_type",
  ]);

  const extracted = getValue(record, [
    "extracted_text",
    "extracted_details",
    "extracted_data",
    "ocr_text",
  ]);

  return {
    id: getValue(
      record,
      ["id", "certificate_id", "record_id"],
      `${docType || "certificate"}-${index}`
    ),
    studentName: getValue(
      record,
      ["candidate_name", "student_name", "holder_name", "name"],
      "Name not available"
    ),
    certificateType: formatCertificateType(
      docType || getValue(record, ["certificate_name"], "Certificate")
    ),
    date: formatDate(
      getValue(record, ["created_at", "uploaded_at", "issue_date", "issued_date"])
    ),
    status: normalizeStatus(record),
    studentId: getValue(record, ["student_id", "register_number", "registration_number"], "—"),
    extractedDetails:
      typeof extracted === "string"
        ? extracted
        : extracted
          ? JSON.stringify(extracted)
          : "",
  };
}

export default function MyCertificates({ onBack }) {
  const [records, setRecords] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchCertificates = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      if (!API_BASE_URL) {
        throw new Error(
          "The certificate service is not configured. Set VITE_API_URL for this deployment."
        );
      }

      const response = await authenticatedFetch(`${API_BASE_URL}/certificates/`);

      if (!response.ok) {
        let message = `Unable to load certificate records (${response.status}).`;

        try {
          const body = await response.json();
          if (body.detail) {
            message = typeof body.detail === "string"
              ? body.detail
              : JSON.stringify(body.detail);
          }
        } catch {
          // Keep the default message.
        }

        throw new Error(message);
      }

      const data = await response.json();
      const items = Array.isArray(data)
        ? data
        : Array.isArray(data.items)
          ? data.items
          : [];

      setRecords(items.map((record, index) => normalizeCertificate(record, index)));
    } catch (err) {
      setError(
        err.message ||
        "Unable to load certificate records. Check whether your FastAPI backend is running."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCertificates();
  }, [fetchCertificates]);

  const filteredRecords = useMemo(() => {
    const term = search.trim().toLowerCase();

    return records.filter((record) => {
      const matchesSearch = [
        record.studentName,
        record.certificateType,
        record.studentId,
        record.extractedDetails,
      ].some((value) => String(value).toLowerCase().includes(term));

      const matchesStatus =
        statusFilter === "All" || record.status === statusFilter;

      return matchesSearch && matchesStatus;
    });
  }, [records, search, statusFilter]);

  const verifiedCount = records.filter(
    (record) => record.status === "Verified"
  ).length;

  const pendingCount = records.filter(
    (record) => record.status === "Pending"
  ).length;

  return (
    <div className="cert-page">
      <header className="cert-topbar">
        <div className="cert-brand">
          <div className="cert-brand-icon">
            <GraduationCap size={25} />
          </div>
          <div>
            <h2>SMART ERP</h2>
            <p>Certificate Data Extraction &amp; Management System</p>
          </div>
        </div>

        <div className="cert-header-actions">
          <button className="cert-header-btn" onClick={onBack} type="button">
            <ArrowLeft size={15} />
            Back to Dashboard
          </button>
          <button
            className="cert-header-btn"
            onClick={fetchCertificates}
            disabled={loading}
            type="button"
          >
            <RefreshCw size={15} className={loading ? "cert-spin" : ""} />
            Refresh
          </button>
        </div>
      </header>

      <main className="cert-main">
        <section className="cert-page-heading">
          <div>
            <span className="cert-eyebrow">CERTIFICATE MANAGEMENT</span>
            <h1>My Certificates</h1>
            <p>View, search and manage your certificates saved in the database.</p>
          </div>

          <div className="cert-record-pill">
            <span />
            Certificate records
          </div>
        </section>

        <section className="cert-stats">
          <article className="cert-stat-card">
            <div className="cert-stat-icon cert-stat-blue">
              <FileText size={21} />
            </div>
            <div>
              <p>Total Certificates</p>
              <h2>{records.length}</h2>
            </div>
          </article>

          <article className="cert-stat-card">
            <div className="cert-stat-icon cert-stat-green">
              <ShieldCheck size={21} />
            </div>
            <div>
              <p>Verified</p>
              <h2>{verifiedCount}</h2>
            </div>
          </article>

          <article className="cert-stat-card">
            <div className="cert-stat-icon cert-stat-orange">
              <Clock3 size={21} />
            </div>
            <div>
              <p>Pending Review</p>
              <h2>{pendingCount}</h2>
            </div>
          </article>
        </section>

        <section className="cert-records-panel">
          <div className="cert-panel-heading">
            <div>
              <h2>Certificate Records</h2>
              <p>Search your saved certificates and view extracted information.</p>
            </div>
            <span className="cert-count-pill">
              {filteredRecords.length} records
            </span>
          </div>

          <div className="cert-toolbar">
            <div className="cert-search">
              <Search size={18} />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search student name, certificate or register number..."
                aria-label="Search certificate records"
              />
            </div>

            <select
              className="cert-filter"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              aria-label="Filter by status"
            >
              <option value="All">All Status</option>
              <option value="Extracted">Extracted</option>
              <option value="Verified">Verified</option>
              <option value="Pending">Pending</option>
              <option value="Rejected">Rejected</option>
            </select>
          </div>

          {error && (
            <div className="cert-error" role="alert">
              <CircleAlert size={23} />
              <div>
                <strong>Could not load records</strong>
                <p>{error}</p>
                <button type="button" onClick={fetchCertificates}>
                  Try Again
                </button>
              </div>
            </div>
          )}

          <div className="cert-table-scroll">
            <table className="cert-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Student Name</th>
                  <th>Certificate Type</th>
                  <th>Date</th>
                  <th>Status</th>
                  <th>Extracted Details</th>
                </tr>
              </thead>

              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan="6" className="cert-empty">
                      Loading certificate records...
                    </td>
                  </tr>
                ) : error ? (
                  <tr>
                    <td colSpan="6" className="cert-empty">
                      Certificate records could not be loaded.
                    </td>
                  </tr>
                ) : filteredRecords.length > 0 ? (
                  filteredRecords.map((record, index) => (
                    <tr key={record.id}>
                      <td>{index + 1}</td>
                      <td>
                        <strong>{record.studentName}</strong>
                      </td>
                      <td>{record.certificateType}</td>
                      <td>{record.date}</td>
                      <td>
                        <span
                          className={`cert-status cert-status-${record.status.toLowerCase()}`}
                        >
                          {record.status}
                        </span>
                      </td>
                      <td className="cert-extracted-cell">
                        {record.extractedDetails
                          ? record.extractedDetails.length > 100
                            ? `${record.extractedDetails.slice(0, 100)}…`
                            : record.extractedDetails
                          : "—"}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="6" className="cert-empty">
                      {records.length === 0
                        ? "No saved certificates found. Upload and save a certificate to see it here."
                        : "No certificates match your search or selected status."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="cert-table-footer">
            <span>
              Showing {filteredRecords.length} of {records.length} records
            </span>
            <span>SMART ERP · Certificate Management</span>
          </div>
        </section>
      </main>

      <footer className="cert-footer">
        <div className="cert-footer-brand">
          <GraduationCap size={17} />
          <strong>SMART ERP</strong>
          <span className="cert-footer-divider">|</span>
          <span>Certificate Data Extraction &amp; Management System</span>
        </div>
        <div className="cert-footer-links">Scan&nbsp; · &nbsp;Extract&nbsp; · &nbsp;Manage&nbsp; · &nbsp;Secure</div>
      </footer>
    </div>
  );
}
