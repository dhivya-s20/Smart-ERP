
import { useRef, useState } from "react";
import "./UploadPage.css";

export default function UploadPage({ onBack, onNext }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const fileInputRef = useRef(null);

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];

    if (!file) return;

    const allowedTypes = [
      "image/jpeg",
      "image/png",
      "application/pdf",
    ];

    if (!allowedTypes.includes(file.type)) {
      alert("Please select a JPG, PNG, or PDF file.");
      event.target.value = "";
      return;
    }

    setSelectedFile(file);
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleContinue = () => {
    if (!selectedFile) {
      alert("Please choose a certificate document first.");
      return;
    }

    if (onNext) {
      onNext({
        file: selectedFile,
        source: "upload",
      });
    }
  };

  return (
    <div className="upload-page">
      {/* HEADER */}
      <header className="upload-header">
        <div className="upload-header-inner">
          <button
            type="button"
            className="upload-back-btn"
            onClick={onBack}
            aria-label="Go back"
          >
            <svg
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M19 12H5M12 19l-7-7 7-7"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>

          {/* HEADER TITLE ONLY */}
          <div className="upload-brand">
            SMART <span>ERP</span>
          </div>
        </div>
      </header>

      {/* CENTERED MAIN CONTENT */}
      <main className="upload-main">
        <section className="upload-card">
          <div className="upload-icon">
            <svg
              viewBox="0 0 64 64"
              width="48"
              height="48"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M32 42V10M20 22l12-12 12 12"
                stroke="currentColor"
                strokeWidth="3.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M12 38v13a4 4 0 004 4h32a4 4 0 004-4V38"
                stroke="currentColor"
                strokeWidth="3.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>

          <div className="upload-eyebrow">
            ACADEMIC DOCUMENTS
          </div>

          <h1>Upload Your Certificate</h1>

          <p className="upload-description">
            Select an educational certificate from your computer
            to begin the data extraction process.
          </p>

          <input
            ref={fileInputRef}
            className="upload-file-input"
            id="certificate-upload"
            name="certificate"
            type="file"
            accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
            onChange={handleFileChange}
            aria-label="Choose a certificate"
          />

          <button
            type="button"
            className="choose-certificate-btn"
            onClick={() => fileInputRef.current?.click()}
          >
            {selectedFile
              ? "Change Certificate"
              : "Choose Certificate"}
          </button>

          {selectedFile && (
            <div className="selected-file">
              <div className="selected-file-icon">
                <svg
                  viewBox="0 0 24 24"
                  width="22"
                  height="22"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M7 3.75h7l5 5V20a1 1 0 01-1 1H7a2 2 0 01-2-2V5.75a2 2 0 012-2z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M14 4v5h5M8.5 13h7M8.5 16.5h7"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
              </div>

              <div className="selected-file-info">
                <strong title={selectedFile.name}>
                  {selectedFile.name}
                </strong>
                <span>
                  {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB
                </span>
              </div>

              <button
                type="button"
                className="remove-file-btn"
                onClick={handleRemoveFile}
                aria-label="Remove selected file"
              >
                ×
              </button>
            </div>
          )}

          <div className="supported-formats">
            <svg
              viewBox="0 0 20 20"
              width="15"
              height="15"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M10 2.5l6 2.3v4.5c0 3.7-2.5 6.3-6 8.2-3.5-1.9-6-4.5-6-8.2V4.8L10 2.5z"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinejoin="round"
              />
              <path
                d="M7.5 9.5l1.7 1.7 3.4-3.5"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            JPG, PNG and PDF supported
          </div>

          {selectedFile && (
            <button
              type="button"
              className="upload-continue-btn"
              onClick={handleContinue}
            >
              Continue <span aria-hidden="true">→</span>
            </button>
          )}
        </section>
      </main>

      {/* FOOTER */}
      <footer className="upload-footer">
        <div className="upload-footer-content">
          <span className="upload-footer-logo" aria-hidden="true">
            🎓
          </span>
          <span>
            SMART ERP CERTIFICATE DATA EXTRACTION AND MANAGEMENT SYSTEM
          </span>
        </div>
      </footer>
    </div>
  );
}
