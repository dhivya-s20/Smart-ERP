
import { useEffect, useRef, useState } from "react";
import { authenticatedFetch } from "../lib/authenticatedFetch";
import "./Processing.css";

const API_BASE_URL = (
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "")
).replace(/\/+$/, "");

function getDocType(certificate) {
  const name = (
    certificate?.certificateType ||
    certificate?.certificate_name ||
    certificate?.name ||
    certificate ||
    ""
  )
    .toString()
    .toLowerCase()
    .replace(/[-_/]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (name.includes("aadhaar") || name.includes("aadhar")) {
    return "aadhaar_card";
  }

  if (name.includes("community")) return "community_certificate";
  if (name.includes("income")) return "income_certificate";
  if (name.includes("nativity")) return "nativity_certificate";
  if (name.includes("birth")) return "birth_certificate";

  if (name.includes("diploma") && name.includes("semester")) {
    return "diploma_semester_marksheet";
  }

  if (name.includes("diploma") && name.includes("marksheet")) {
    return "diploma_semester_marksheet";
  }

  if (name.includes("diploma")) return "diploma_certificate";
  if (name.includes("degree") && name.includes("marksheet")) {
    return "degree_marksheet";
  }

  if (name.includes("degree")) return "degree_certificate";

  if (
    name.includes("transfer certificate") ||
    name === "tc" ||
    name.includes(" tc")
  ) {
    if (name.includes("cbse") && name.includes("10")) {
      return "cbse_10th_tc";
    }

    if (name.includes("cbse") && name.includes("12")) {
      return "cbse_12th_tc";
    }

    if (name.includes("10")) return "state_board_10th_tc";
    if (name.includes("12")) return "state_board_12th_tc";

    return "transfer_certificate";
  }

  if (name.includes("cbse") && name.includes("10")) {
    return "cbse_10th_marksheet";
  }

  if (name.includes("cbse") && name.includes("12")) {
    return "cbse_12th_marksheet";
  }

  if (name.includes("state board") && name.includes("10")) {
    return "state_board_10th";
  }

  if (name.includes("state board") && name.includes("12")) {
    return "state_board_12th";
  }

  return null;
}

export default function Processing({
  certificate,
  documentData,
  onBack,
  onNext,
}) {
  const [progress, setProgress] = useState(0);
  const [activeStep, setActiveStep] = useState(0);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(
    "Connecting to the OCR backend..."
  );

  const onNextRef = useRef(onNext);

  useEffect(() => {
    onNextRef.current = onNext;
  }, [onNext]);

  const steps = [
    "Image Preprocessing",
    "OCR Processing",
    "Document Classification",
    "Data Extraction",
    "Validation",
  ];

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let navigationTimer = null;

    const controller = new AbortController();

    async function extractCertificate() {
      try {
        setError("");
        setProgress(5);
        setActiveStep(0);
        setStatus("Connecting to the OCR backend...");

        const file = documentData?.file;

        if (!file) {
          throw new Error(
            "Certificate file missing. Please go back and upload it again."
          );
        }

        const docType = getDocType(certificate);

        if (!docType) {
          throw new Error(
            "Unsupported certificate type. Please go back and select the certificate again."
          );
        }

        if (!API_BASE_URL) {
          throw new Error(
            "OCR backend is not configured. Set VITE_API_URL for this deployment."
          );
        }

        setStatus("Uploading document for OCR processing...");

        timer = setInterval(() => {
          setProgress((previous) => Math.min(previous + 2, 90));
        }, 300);

        const formData = new FormData();
        formData.append("file", file);

        const response = await authenticatedFetch(
          `${API_BASE_URL}/extract/${encodeURIComponent(docType)}`,
          {
            method: "POST",
            body: formData,
            signal: controller.signal,
          }
        );

        const responseText = await response.text();
        let result;

        try {
          result = JSON.parse(responseText);
        } catch {
          throw new Error(
            `Backend returned an invalid response (HTTP ${response.status}). Check the backend terminal.`
          );
        }

        if (!response.ok) {
          const detail =
            typeof result.detail === "string"
              ? result.detail
              : JSON.stringify(result.detail || result);

          throw new Error(
            detail || `OCR request failed (${response.status}).`
          );
        }

        if (cancelled) return;

        clearInterval(timer);
        timer = null;

        setProgress(100);
        setActiveStep(4);
        setStatus("Certificate data extracted successfully!");

        navigationTimer = setTimeout(() => {
          if (!cancelled) {
            onNextRef.current?.(result);
          }
        }, 400);
      } catch (err) {
        if (cancelled || err.name === "AbortError") return;

        if (timer) {
          clearInterval(timer);
          timer = null;
        }

        const message = err.message || "Unable to process the certificate.";
        setError(
          message === "Failed to fetch"
            ? "Could not reach the OCR backend. Check that the backend is online, VITE_API_URL points to it, and its CORS settings allow this website."
            : message
        );

        setStatus("Processing failed");
      }
    }

    extractCertificate();

    return () => {
      cancelled = true;
      controller.abort();

      if (timer) clearInterval(timer);
      if (navigationTimer) clearTimeout(navigationTimer);
    };
  }, [certificate, documentData]);

  useEffect(() => {
    if (error) return;

    if (progress >= 100) {
      setActiveStep(4);
    } else if (progress < 20) {
      setActiveStep(0);
    } else if (progress < 40) {
      setActiveStep(1);
    } else if (progress < 60) {
      setActiveStep(2);
    } else if (progress < 80) {
      setActiveStep(3);
    } else {
      setActiveStep(4);
    }
  }, [progress, error]);

  return (
    <div className="processing-page">

      {/* BLUE HEADER: LOGO AND TITLE ON THE LEFT */}
      <header className="processing-header">
        <div className="processing-brand">
          <div className="processing-brand-icon">
            <svg
              viewBox="0 0 24 24"
              width="30"
              height="30"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <path d="M14 2v6h6" />
              <path d="M8 13h8" />
              <path d="M8 17h8" />
              <path d="M8 9h2" />
            </svg>
          </div>

          <div className="processing-brand-text">
            <h2>SMART ERP</h2>
            <p>
              Certificate Data Extraction and Management System
            </p>
          </div>
        </div>
      </header>

      {/* CENTERED PROCESSING CONTENT */}
      <main className="processing-container">
        <div className="processing-step-label">
          STEP 3 OF 3
        </div>

        <h1>Processing Document</h1>

        <p className="processing-status">{status}</p>

        <div className="process-steps">
          {steps.map((step, index) => (
            <div className="process-step" key={step}>
              <div
                className={
                  index < activeStep
                    ? "step-icon completed"
                    : index === activeStep
                    ? "step-icon active"
                    : "step-icon"
                }
              >
                {index < activeStep ? "✓" : index + 1}
              </div>

              <span>{step}</span>
            </div>
          ))}
        </div>

        <div
          className={`loader-ring ${error ? "loader-error" : ""}`}
          aria-label={error ? "Processing failed" : "Processing"}
        />

        <h2>{error ? "Processing Error" : steps[activeStep]}</h2>

        <div
          className="progress-wrapper"
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="progress-fill"
            style={{ width: `${progress}%` }}
          />
        </div>

        <div className="progress-value">{progress}%</div>

        {error && (
          <div className="processing-error" role="alert">
            <p>{error}</p>

            <button
              type="button"
              className="processing-back-btn"
              onClick={onBack}
            >
              ← Go Back
            </button>
          </div>
        )}
      </main>

      {/* BLUE FOOTER */}
      <footer className="processing-footer">
        <div className="processing-footer-content">
          <span
            className="processing-footer-logo"
            aria-label="Graduation cap"
          >
            🎓
          </span>

          <p className="processing-footer-title">
            SMART ERP CERTIFICATE DATA EXTRACTION AND MANAGEMENT SYSTEM
          </p>
        </div>
      </footer>
    </div>
  );
}
