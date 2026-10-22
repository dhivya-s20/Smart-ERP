
import { useEffect, useMemo, useState } from "react";
import "./ExtractedData.css";

const formatLabel = (key) =>
  String(key)
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());

const isObject = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

function getCertificateType(certificate, result) {
  if (typeof certificate === "string") return certificate;

  return (
    certificate?.certificateType ||
    certificate?.name ||
    certificate?.type ||
    result?.doc_type ||
    result?.document_type ||
    "Certificate"
  );
}

function getCertificateImage(documentData) {
  if (!documentData) return "";

  const file = documentData.file;

  const possibleUrls = [
    documentData.imageUrl,
    documentData.image_url,
    documentData.previewUrl,
    documentData.preview_url,
    documentData.fileUrl,
    documentData.file_url,
    documentData.url,
    documentData.dataUrl,
    documentData.data_url,
    documentData.preview,
    documentData.image,
    documentData.fileDataUrl,
  ];

  const url = possibleUrls.find(
    (value) => typeof value === "string" && value.length > 0
  );

  if (url) return url;

  if (typeof file === "string") return file;

  if (typeof File !== "undefined" && file instanceof File) {
    return URL.createObjectURL(file);
  }

  return "";
}

function getFileName(documentData) {
  const file = documentData?.file;

  if (typeof File !== "undefined" && file instanceof File) {
    return file.name;
  }

  return (
    file?.name ||
    documentData?.fileName ||
    documentData?.filename ||
    documentData?.name ||
    "Uploaded certificate"
  );
}

function getInitialFields(result) {
  if (!result) return {};

  if (isObject(result.fields)) {
    return { ...result.fields };
  }

  if (Array.isArray(result.fields)) {
    return Object.fromEntries(
      result.fields.map((field, index) => [
        field.key || field.name || `field_${index + 1}`,
        field.value ?? "",
      ])
    );
  }

  if (isObject(result.extracted_fields)) {
    return { ...result.extracted_fields };
  }

  if (isObject(result.data)) {
    return { ...result.data };
  }

  const ignoredKeys = new Set([
    "doc_type",
    "document_type",
    "confidence",
    "success",
    "message",
    "raw_text",
    "text",
    "fields",
  ]);

  return Object.fromEntries(
    Object.entries(result).filter(
      ([key, value]) =>
        !ignoredKeys.has(key.toLowerCase()) &&
        !isObject(value) &&
        !Array.isArray(value)
    )
  );
}

export default function ExtractedData({
  certificate,
  documentData,
  onBack,
  onNext,
  onNavigate,
  saving = false,
}) {
  const ocrResult = documentData?.ocrResult || {};
  const validationWarnings = Array.isArray(ocrResult.warnings)
    ? ocrResult.warnings.filter(
        (warning) => typeof warning === "string" && warning.trim()
      )
    : [];

  const certificateType = getCertificateType(
    certificate,
    ocrResult
  );

  const [viewMode, setViewMode] = useState("table");
  const [fullScreen, setFullScreen] = useState(false);
  const [studentId, setStudentId] = useState("");
  const [feedback, setFeedback] = useState("");
  const [feedbackType, setFeedbackType] = useState("");
  const [editedFields, setEditedFields] = useState({});
  const [editingKey, setEditingKey] = useState(null);

  const initialFields = useMemo(
    () => getInitialFields(ocrResult),
    [ocrResult]
  );

  useEffect(() => {
    setEditedFields({ ...initialFields });
    setEditingKey(null);
    setFeedback("");
    setFeedbackType("");
  }, [initialFields]);

  useEffect(() => {
    if (!fullScreen) return undefined;

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setFullScreen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [fullScreen]);

  const imageUrl = getCertificateImage(documentData);
  const fileName = getFileName(documentData);

  const fields = Object.entries(editedFields).filter(
    ([key]) =>
      ![
        "raw_text",
        "text",
        "doc_type",
        "document_type",
      ].includes(key.toLowerCase())
  );

  const correctedResult = useMemo(() => {
    if (Array.isArray(ocrResult?.fields)) {
      const updatedArray = ocrResult.fields.map((field, index) => {
        const key =
          field.key || field.name || `field_${index + 1}`;

        return {
          ...field,
          value: editedFields[key] ?? field.value ?? "",
        };
      });

      return {
        ...ocrResult,
        fields: updatedArray,
      };
    }

    if (isObject(ocrResult?.fields)) {
      return {
        ...ocrResult,
        fields: { ...ocrResult.fields, ...editedFields },
      };
    }

    if (isObject(ocrResult?.extracted_fields)) {
      return {
        ...ocrResult,
        extracted_fields: {
          ...ocrResult.extracted_fields,
          ...editedFields,
        },
      };
    }

    if (isObject(ocrResult?.data)) {
      return {
        ...ocrResult,
        data: { ...ocrResult.data, ...editedFields },
      };
    }

    return {
      ...ocrResult,
      fields: { ...editedFields },
    };
  }, [ocrResult, editedFields]);

  const updateField = (key, value) => {
    setEditedFields((previous) => ({
      ...previous,
      [key]: value,
    }));
  };

  const handleSave = async () => {
    setFeedback("");
    setFeedbackType("");

    if (!studentId.trim()) {
      setFeedback(
        "Please enter the existing Student ID before saving."
      );
      setFeedbackType("error");
      return;
    }

    if (!fields.length) {
      setFeedback(
        "No extracted fields were found. Please check the OCR result."
      );
      setFeedbackType("error");
      return;
    }

    if (typeof onNext !== "function") {
      setFeedback("Save handler is not connected in App.jsx.");
      setFeedbackType("error");
      return;
    }

    try {
      await onNext({
        ...correctedResult,
        student_id: studentId.trim(),
      });
    } catch (error) {
      setFeedback(
        error?.message || "Unable to save the certificate."
      );
      setFeedbackType("error");
    }
  };

  const handleBack = () => {
    if (fullScreen) {
      setFullScreen(false);
      return;
    }

    if (typeof onBack === "function") {
      onBack();
    } else if (typeof onNavigate === "function") {
      onNavigate("upload");
    }
  };

  return (
    <main className="extracted-page">

      {/* PROFESSIONAL NAVY BLUE TOP HEADER */}
      <header className="extracted-topbar">
        <div className="extracted-brand">
          <div
            className="extracted-brand-logo"
            aria-hidden="true"
          >
            🎓
          </div>

          <div className="extracted-brand-text">
            <div className="extracted-brand-name">
              SMART ERP
            </div>

            <div className="extracted-brand-subtitle">
              Certificate Data Extraction &amp; Management System
            </div>
          </div>
        </div>

        <div className="extracted-user">
          <span
            className="extracted-user-icon"
            aria-hidden="true"
          >
            ♙
          </span>

          <span>Certificate Management</span>
        </div>
      </header>

      {/* CENTRE CONTENT — ORIGINAL DESIGN PRESERVED */}
      <div className="extracted-main">

        {/* Page title */}
        <section className="extracted-heading">
          <div
            className="extracted-heading-icon"
            aria-hidden="true"
          >
            ▤
          </div>

          <div className="extracted-heading-content">
            <h1>Extracted Certificate Data</h1>

            <p>
              Review and correct the extracted information before saving.
            </p>

            <div className="extracted-meta">
              <span>
                <strong>Certificate Category:</strong>{" "}
                {typeof certificate === "object"
                  ? certificate?.category || "Selected"
                  : "Selected"}
              </span>

              <span>
                <strong>Certificate Type:</strong>{" "}
                {certificateType}
              </span>
            </div>
          </div>

          <div className="extracted-ocr-status">
            <span className="extracted-status-dot" />
            OCR Processed
          </div>
        </section>

        {/* Student ID */}
        <section className="extracted-student-card">
          <label htmlFor="extracted-student-id">
            <span
              className="extracted-student-icon"
              aria-hidden="true"
            >
              ♙
            </span>

            Student ID
          </label>

          <input
            id="extracted-student-id"
            type="text"
            value={studentId}
            onChange={(event) => setStudentId(event.target.value)}
            placeholder="Enter existing student ID"
            autoComplete="off"
          />

          <small>
            Enter the ID of the student who owns this certificate.
          </small>
        </section>

        {validationWarnings.length > 0 && (
          <section
            className="extracted-validation-warnings"
            role="status"
            aria-label="OCR validation warnings"
          >
            <strong>Review these OCR checks before saving:</strong>
            <ul>
              {validationWarnings.map((warning, index) => (
                <li key={`${index}-${warning}`}>{warning}</li>
              ))}
            </ul>
            <span>Correct any inaccurate fields in the form below.</span>
          </section>
        )}

        {/* Certificate preview and extracted fields */}
        <section className="extracted-content-grid">

          {/* Certificate Preview */}
          <article className="extracted-panel extracted-preview-panel">
            <div className="extracted-panel-heading">
              <div className="extracted-panel-title">
                <span
                  className="extracted-panel-icon"
                  aria-hidden="true"
                >
                  ▧
                </span>

                <h2>Certificate Preview</h2>
              </div>

              {imageUrl && (
                <button
                  className="extracted-outline-button"
                  type="button"
                  onClick={() => setFullScreen(true)}
                >
                  ⛶ View Full Image
                </button>
              )}
            </div>

            <div className="extracted-preview-filebar">
              <span title={fileName}>{fileName}</span>

              {imageUrl && (
                <a
                  href={imageUrl}
                  target="_blank"
                  rel="noreferrer"
                  download={fileName}
                >
                  Open / Download
                </a>
              )}
            </div>

            <div className="extracted-preview-stage">
              {imageUrl ? (
                <button
                  type="button"
                  className="extracted-preview-image-button"
                  onClick={() => setFullScreen(true)}
                  aria-label="View certificate image full screen"
                >
                  <img
                    className="extracted-preview-image"
                    src={imageUrl}
                    alt="Uploaded certificate preview"
                  />
                </button>
              ) : (
                <div className="extracted-preview-empty">
                  <div className="extracted-empty-icon">▧</div>

                  <h3>Certificate preview unavailable</h3>

                  <p>
                    The uploaded file does not contain a preview URL.
                    Pass an image URL or preview URL from your upload page.
                  </p>
                </div>
              )}
            </div>
          </article>

          {/* Extracted Fields */}
          <article className="extracted-panel extracted-fields-panel">
            <div className="extracted-panel-heading extracted-fields-heading">
              <div className="extracted-panel-title">
                <span
                  className="extracted-panel-icon"
                  aria-hidden="true"
                >
                  ☷
                </span>

                <h2>Extracted Fields</h2>

                <span className="extracted-field-count">
                  {fields.length} fields
                </span>
              </div>

              <div className="extracted-view-switch">
                <button
                  type="button"
                  className={viewMode === "table" ? "active" : ""}
                  onClick={() => setViewMode("table")}
                >
                  ▦ Table View
                </button>

                <button
                  type="button"
                  className={viewMode === "form" ? "active" : ""}
                  onClick={() => setViewMode("form")}
                >
                  ☷ Form View
                </button>
              </div>
            </div>

            {fields.length === 0 ? (
              <div className="extracted-no-fields">
                <strong>No extracted fields available.</strong>

                <p>
                  Check that the OCR response contains a fields object.
                </p>
              </div>
            ) : viewMode === "table" ? (
              <div className="extracted-table-wrap">
                <div className="extracted-table-scroll">
                  <table className="extracted-table">
                    <thead>
                      <tr>
                        <th>Field Name</th>
                        <th>Extracted Value</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>

                    <tbody>
                      {fields.map(([key, value]) => (
                        <tr key={key}>
                          <td className="extracted-field-label">
                            {formatLabel(key)}
                          </td>

                          <td className="extracted-field-value">
                            {editingKey === key ? (
                              <input
                                type="text"
                                value={
                                  value === null || value === undefined
                                    ? ""
                                    : String(value)
                                }
                                onChange={(event) =>
                                  updateField(key, event.target.value)
                                }
                                autoFocus
                                aria-label={`Edit ${formatLabel(key)}`}
                              />
                            ) : (
                              String(value ?? "") || "—"
                            )}
                          </td>

                          <td>
                            <span className="extracted-field-status">
                              ✓ Extracted
                            </span>
                          </td>

                          <td>
                            <button
                              type="button"
                              className="extracted-edit-button"
                              title={
                                editingKey === key
                                  ? "Finish editing"
                                  : `Edit ${formatLabel(key)}`
                              }
                              aria-label={
                                editingKey === key
                                  ? `Finish editing ${formatLabel(key)}`
                                  : `Edit ${formatLabel(key)}`
                              }
                              onClick={() =>
                                setEditingKey((current) =>
                                  current === key ? null : key
                                )
                              }
                            >
                              {editingKey === key ? "✓" : "✎"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="extracted-review-note">
                  <span>ⓘ</span>
                  Select the edit icon to correct a value before saving.
                </div>
              </div>
            ) : (
              <div className="extracted-form-view">
                {fields.map(([key, value]) => (
                  <label className="extracted-form-field" key={key}>
                    <span>{formatLabel(key)}</span>

                    <input
                      type="text"
                      value={
                        value === null || value === undefined
                          ? ""
                          : String(value)
                      }
                      onChange={(event) =>
                        updateField(key, event.target.value)
                      }
                    />

                    <small>✓ Extracted</small>
                  </label>
                ))}
              </div>
            )}
          </article>
        </section>

        {/* Feedback messages */}
        {feedback && (
          <div
            className={`extracted-feedback ${feedbackType}`}
            role="status"
          >
            {feedback}
          </div>
        )}

        {/* UPDATED BOTTOM BRANDING */}
        <section className="extracted-bottom-brand">
          <div className="extracted-bottom-brand-info">
            <div
              className="extracted-bottom-logo"
              aria-hidden="true"
            >
              🎓
            </div>

            <div>
              <strong>SMART ERP</strong>

              <span>
                CERTIFICATE DATA EXTRACTION AND MANAGEMENT SYSTEM
              </span>
            </div>
          </div>

          {imageUrl && (
            <button
              type="button"
              className="extracted-bottom-thumbnail"
              onClick={() => setFullScreen(true)}
              aria-label="Open certificate preview"
            >
              <img
                src={imageUrl}
                alt="Certificate thumbnail"
              />
            </button>
          )}
        </section>

        {/* Bottom actions — original functionality */}
        <footer className="extracted-action-bar">
          <button
            type="button"
            className="extracted-cancel-button"
            onClick={handleBack}
            disabled={saving}
          >
            ← Cancel
          </button>

          <div className="extracted-action-right">
            <span>Review the values before saving.</span>

            <button
              type="button"
              className="extracted-save-button"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? "Saving..." : "✓ Save & Continue"}
            </button>
          </div>
        </footer>
      </div>

      {/* Full-screen certificate viewer — unchanged */}
      {fullScreen && imageUrl && (
        <div
          className="extracted-fullscreen"
          role="dialog"
          aria-modal="true"
          aria-label="Full-screen certificate preview"
        >
          <header className="extracted-fullscreen-header">
            <div>
              <strong>Certificate Preview</strong>
              <span>{fileName}</span>
            </div>

            <button
              type="button"
              className="extracted-fullscreen-close"
              onClick={() => setFullScreen(false)}
              aria-label="Close full-screen preview"
              title="Close (Esc)"
            >
              ✕
            </button>
          </header>

          <div className="extracted-fullscreen-body">
            <img
              className="extracted-fullscreen-image"
              src={imageUrl}
              alt="Full-screen certificate"
            />
          </div>

          <footer className="extracted-fullscreen-footer">
            <button
              type="button"
              className="extracted-outline-button"
              onClick={() => setFullScreen(false)}
            >
              ← Back to Extracted Data
            </button>

            <a
              href={imageUrl}
              target="_blank"
              rel="noreferrer"
              download={fileName}
            >
              Open / Download Certificate
            </a>
          </footer>
        </div>
      )}
    </main>
  );
}
