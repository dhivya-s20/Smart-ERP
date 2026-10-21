
import { useState, useEffect, useCallback } from "react";
import { supabase } from "./lib/supabase";

/* MAIN PAGES */
import WelcomePage from "./components/welcomePage";
import LoginPage from "./components/LoginPage";
import Dashboard from "./components/Dashboard";

/* CERTIFICATE CATEGORY AND TYPE */
import CertificateCategory from "./components/CertificateCategory";
import CertificateType from "./components/CertificateType";

/* CERTIFICATE PROCESSING */
import ChooseMethod from "./components/ChooseMethod";
import ScanUpload from "./components/ScanUpload";
import UploadPage from "./components/UploadPage";
import Processing from "./components/Processing";
import ExtractedData from "./components/ExtractedData";
import CertificateDatabase from "./components/CertificateDatabase";

/* DASHBOARD MENU PAGES */
import MyCertificates from "./components/MyCertificates";
import Students from "./components/Students";
import Search from "./components/Search";
import Reports from "./components/Reports";
import AIAssistant from "./components/AIAssistant";
import Settings from "./components/Settings";

/* PAGE CONSTANTS */
const PAGES = {
  WELCOME: "welcome",
  LOGIN: "login",
  DASHBOARD: "dashboard",
  CERTIFICATE_CATEGORY: "certificateCategory",
  CERTIFICATE_TYPE: "certificateType",
  CHOOSE_METHOD: "chooseMethod",
  SCAN_UPLOAD: "scanUpload",
  UPLOAD: "upload",
  PROCESSING: "processing",
  EXTRACTED_DATA: "extractedData",
  EXTRACTED_DATA_MENU: "extractedDataMenu",
  CERTIFICATE_DATABASE: "certificateDatabase",
  MY_CERTIFICATES: "myCertificates",
  STUDENTS: "students",
  SEARCH: "search",
  REPORTS: "reports",
  AI_ASSISTANT: "aiAssistant",
  SETTINGS: "settings",
};

const VALID_PAGES = new Set(Object.values(PAGES));

/* CERTIFICATE TYPE HELPER */
const getCertificateType = (certificate, ocrResult) => {
  if (typeof certificate === "string") {
    return certificate;
  }

  return (
    certificate?.certificateType ||
    certificate?.name ||
    certificate?.type ||
    ocrResult?.doc_type ||
    "Unknown"
  );
};

/* STUDENT NAME HELPER */
const getStudentName = (ocrResult) => {
  const fields = ocrResult?.fields || {};

  return (
    fields.student_name ||
    fields.candidate_name ||
    fields.studentName ||
    fields.candidateName ||
    fields.name ||
    ""
  );
};

/* FILE NAME HELPER */
const getCertificateName = (documentData) => {
  const fileName =
    documentData?.file?.name ||
    documentData?.fileName ||
    documentData?.filename ||
    documentData?.name;

  return typeof fileName === "string" && fileName.trim()
    ? fileName
    : "Certificate";
};

export default function App() {
  /* APPLICATION STATE */
  const [currentPage, setCurrentPage] = useState(PAGES.WELCOME);
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [savingCertificate, setSavingCertificate] = useState(false);

  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedCertificate, setSelectedCertificate] = useState(null);
  const [documentData, setDocumentData] = useState(null);

  /* RESET CERTIFICATE WORKFLOW */
  const resetCertificateData = useCallback(() => {
    setSelectedCategory(null);
    setSelectedCertificate(null);
    setDocumentData(null);
  }, []);

  /* RESTORE AND MONITOR AUTH SESSION */
  useEffect(() => {
    if (!supabase) {
      setAuthLoading(false);
      return undefined;
    }

    let active = true;

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (!active) return;

      setUser(session?.user ?? null);

      if (event === "SIGNED_IN" && session?.user) {
        setCurrentPage(PAGES.DASHBOARD);
      }

      if (event === "SIGNED_OUT") {
        resetCertificateData();
        setCurrentPage(PAGES.WELCOME);
      }
    });

    const restoreSession = async () => {
      try {
        const {
          data: { session },
          error,
        } = await supabase.auth.getSession();

        if (!active) return;

        if (error) {
          console.error("Session restore failed:", error.message);
          return;
        }

        if (session?.user) {
          setUser(session.user);
          setCurrentPage(PAGES.DASHBOARD);
        } else {
          setUser(null);
          setCurrentPage(PAGES.WELCOME);
        }
      } catch (error) {
        console.error("Session error:", error);
      } finally {
        if (active) {
          setAuthLoading(false);
        }
      }
    };

    restoreSession();

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, [resetCertificateData]);

  /* NAVIGATION */
  const navigate = useCallback((page) => {
    if (!VALID_PAGES.has(page)) {
      console.warn("Invalid page navigation:", page);
      return;
    }

    setCurrentPage(page);
  }, []);

  /* START NEW CERTIFICATE WORKFLOW */
  const startCertificateWorkflow = useCallback(() => {
    resetCertificateData();
    navigate(PAGES.CERTIFICATE_CATEGORY);
  }, [navigate, resetCertificateData]);

  /* HOME NAVIGATION */
  const goHome = useCallback(() => {
    navigate(PAGES.WELCOME);
  }, [navigate]);

  /* DASHBOARD NAVIGATION */
  const goDashboard = useCallback(() => {
    navigate(PAGES.DASHBOARD);
  }, [navigate]);

  /* LOGIN */
  const handleLogin = useCallback(
    async (sessionOrUser) => {
      if (!supabase) {
        alert("Supabase is not configured. Check your .env file.");
        return;
      }

      try {
        let authenticatedUser =
          sessionOrUser?.user || sessionOrUser || null;

        if (!authenticatedUser?.id) {
          const {
            data: { user: currentUser },
            error,
          } = await supabase.auth.getUser();

          if (error || !currentUser?.id) {
            alert("Unable to verify your login. Please try again.");
            return;
          }

          authenticatedUser = currentUser;
        }

        setUser(authenticatedUser);
        resetCertificateData();
        navigate(PAGES.DASHBOARD);
      } catch (error) {
        console.error("Login failed:", error);
        alert("Login failed. Please try again.");
      }
    },
    [navigate, resetCertificateData]
  );

  /* LOGOUT */
  const handleLogout = useCallback(async () => {
    if (!supabase) return;

    try {
      const { error } = await supabase.auth.signOut();

      if (error) {
        console.error("Logout failed:", error.message);
        alert(`Logout failed: ${error.message}`);
        return;
      }

      setUser(null);
      resetCertificateData();
      navigate(PAGES.WELCOME);
    } catch (error) {
      console.error("Logout error:", error);
      alert("Unable to log out. Please try again.");
    }
  }, [navigate, resetCertificateData]);

  /* SELECT CERTIFICATE CATEGORY */
  const handleCategoryNext = useCallback(
    (category) => {
      if (!category) {
        alert("Please select a certificate category.");
        return;
      }

      setSelectedCategory(category);
      setSelectedCertificate(null);
      setDocumentData(null);
      navigate(PAGES.CERTIFICATE_TYPE);
    },
    [navigate]
  );

  /* SELECT CERTIFICATE TYPE */
  const handleCertificateTypeNext = useCallback(
    (documentType) => {
      if (!documentType) {
        alert("Please select a certificate type.");
        return;
      }

      setSelectedCertificate(documentType);
      setDocumentData(null);
      navigate(PAGES.CHOOSE_METHOD);
    },
    [navigate]
  );

  /* SAVE EXTRACTED CERTIFICATE */
  const handleSaveCertificate = useCallback(
    async (correctedResult) => {
      if (savingCertificate) return;

      if (!supabase) {
        alert("Supabase is not configured. Check your .env file.");
        return;
      }

      if (!correctedResult) {
        alert("No extracted certificate data is available.");
        return;
      }

      setSavingCertificate(true);

      try {
        const {
          data: { user: authenticatedUser },
          error: authError,
        } = await supabase.auth.getUser();

        if (authError || !authenticatedUser?.id) {
          alert("Your session has expired. Please log in again.");
          return;
        }

        const certificateType = getCertificateType(
          selectedCertificate,
          correctedResult
        );

        const studentName = getStudentName(correctedResult);
        const certificateName = getCertificateName(documentData);

        const recordToSave = {
          user_id: authenticatedUser.id,
          student_name: studentName,
          certificate_type: certificateType,
          certificate_name: certificateName,
          date_extracted: new Date().toISOString().slice(0, 10),
          status: "Extracted",
          ocr_result: correctedResult,
        };

        const { error: insertError } = await supabase
          .from("certificates")
          .insert(recordToSave);

        if (insertError) {
          console.error("Certificate save failed:", insertError);
          alert(`Could not save certificate:\n${insertError.message}`);
          return;
        }

        setDocumentData((previous) => ({
          ...(previous || {}),
          ocrResult: correctedResult,
        }));

        navigate(PAGES.CERTIFICATE_DATABASE);
      } catch (error) {
        console.error("Unexpected save error:", error);
        alert(error?.message || "Unable to save certificate.");
      } finally {
        setSavingCertificate(false);
      }
    },
    [
      savingCertificate,
      selectedCertificate,
      documentData,
      navigate,
    ]
  );

  /* SUPABASE CONFIGURATION CHECK */
  if (!supabase) {
    return (
      <main
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: 24,
          fontFamily: "Arial, sans-serif",
          background: "#f3f7fd",
          color: "#153d6b",
        }}
      >
        <section>
          <h2>Supabase Configuration Missing</h2>
          <p>
            Add VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
            to frontend/.env, then restart the development server.
          </p>
        </section>
      </main>
    );
  }

  /* SESSION LOADING */
  if (authLoading) {
    return (
      <main
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          fontFamily: "Arial, sans-serif",
          color: "#153d6b",
          background: "#f3f7fd",
        }}
      >
        Checking your session...
      </main>
    );
  }

  /* WELCOME */
  if (currentPage === PAGES.WELCOME) {
    return <WelcomePage onStart={() => navigate(PAGES.LOGIN)} />;
  }

  /* LOGIN */
  if (currentPage === PAGES.LOGIN) {
    return (
      <LoginPage
        onLogin={handleLogin}
        onBack={goHome}
      />
    );
  }

  /* DASHBOARD */
  if (currentPage === PAGES.DASHBOARD) {
    return (
      <Dashboard
        user={user}
        onNavigate={navigate}
        onUpload={startCertificateWorkflow}
        onLogout={handleLogout}
      />
    );
  }

  /* CERTIFICATE CATEGORY */
  if (currentPage === PAGES.CERTIFICATE_CATEGORY) {
    return (
      <CertificateCategory
        onBack={goDashboard}
        onHome={goHome}
        onNavigate={navigate}
        onNext={handleCategoryNext}
      />
    );
  }

  /* CERTIFICATE TYPE */
  if (currentPage === PAGES.CERTIFICATE_TYPE) {
    return (
      <CertificateType
        certificate={selectedCategory}
        onBack={() => navigate(PAGES.CERTIFICATE_CATEGORY)}
        onNext={handleCertificateTypeNext}
        onNavigate={navigate}
      />
    );
  }

  /* CHOOSE SCAN OR UPLOAD */
  if (currentPage === PAGES.CHOOSE_METHOD) {
    return (
      <ChooseMethod
        certificate={selectedCertificate}
        onBack={() => navigate(PAGES.CERTIFICATE_TYPE)}
        onNext={() => {
          setDocumentData(null);
          navigate(PAGES.SCAN_UPLOAD);
        }}
        onNavigate={(page) => {
          if (
            page === PAGES.UPLOAD ||
            page === PAGES.SCAN_UPLOAD
          ) {
            setDocumentData(null);
          }

          navigate(page);
        }}
      />
    );
  }

  /* CAMERA / SCAN */
  if (currentPage === PAGES.SCAN_UPLOAD) {
    return (
      <ScanUpload
        certificate={selectedCertificate}
        onBack={() => navigate(PAGES.CHOOSE_METHOD)}
        onNext={(scanData) => {
          if (!scanData) {
            alert("No scanned document data was received.");
            return;
          }

          setDocumentData({
            ...scanData,
            source: "camera",
          });

          navigate(PAGES.PROCESSING);
        }}
        onNavigate={navigate}
      />
    );
  }

  /* FILE UPLOAD */
  if (currentPage === PAGES.UPLOAD) {
    return (
      <UploadPage
        certificate={selectedCertificate}
        onBack={() => navigate(PAGES.CHOOSE_METHOD)}
        onNext={(uploadData) => {
          if (!uploadData) {
            alert("Please select a file first.");
            return;
          }

          setDocumentData({
            ...uploadData,
            source: "upload",
          });

          navigate(PAGES.PROCESSING);
        }}
        onNavigate={navigate}
      />
    );
  }

  /* OCR PROCESSING */
  if (currentPage === PAGES.PROCESSING) {
    return (
      <Processing
        certificate={selectedCertificate}
        documentData={documentData}
        onBack={() =>
          navigate(
            documentData?.source === "upload"
              ? PAGES.UPLOAD
              : PAGES.SCAN_UPLOAD
          )
        }
        onNext={(ocrResult) => {
          if (!ocrResult) {
            alert("No extracted data was received.");
            return;
          }

          setDocumentData((previous) => ({
            ...(previous || {}),
            ocrResult,
          }));

          navigate(PAGES.EXTRACTED_DATA);
        }}
        onNavigate={navigate}
      />
    );
  }

  /* EXTRACTED CERTIFICATE REVIEW */
  if (currentPage === PAGES.EXTRACTED_DATA) {
    return (
      <ExtractedData
        certificate={selectedCertificate}
        documentData={documentData}
        onBack={() =>
          navigate(
            documentData?.source === "upload"
              ? PAGES.UPLOAD
              : PAGES.SCAN_UPLOAD
          )
        }
        onNext={handleSaveCertificate}
        onNavigate={navigate}
        saving={savingCertificate}
      />
    );
  }

  /* CERTIFICATE DATABASE */
  if (currentPage === PAGES.CERTIFICATE_DATABASE) {
    return (
      <CertificateDatabase
        supabase={supabase}
        user={user}
        documentData={documentData}
        certificate={selectedCertificate}
        onBack={() => navigate(PAGES.EXTRACTED_DATA)}
        onNavigate={navigate}
      />
    );
  }

  /* DASHBOARD MENU PAGES */
  const menuPages = {
    [PAGES.EXTRACTED_DATA_MENU]: CertificateDatabase,
    [PAGES.MY_CERTIFICATES]: MyCertificates,
    [PAGES.STUDENTS]: Students,
    [PAGES.SEARCH]: Search,
    [PAGES.REPORTS]: Reports,
    [PAGES.AI_ASSISTANT]: AIAssistant,
    [PAGES.SETTINGS]: Settings,
  };

  const PageComponent = menuPages[currentPage];

  if (PageComponent) {
    return (
      <PageComponent
        supabase={supabase}
        user={user}
        documentData={documentData}
        certificate={selectedCertificate}
        onBack={goDashboard}
        onNavigate={navigate}
      />
    );
  }

  /* FALLBACK */
  return <WelcomePage onStart={() => navigate(PAGES.LOGIN)} />;
}
