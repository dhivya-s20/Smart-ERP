"""Authorization checks for privileged certificate API routes."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class CertificateAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_document_types_reject_missing_bearer_token(self):
        response = self.client.get("/doc-types")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    @patch.object(main, "get_sb")
    def test_invalid_or_expired_supabase_token_returns_safe_401(self, get_sb):
        auth_error = RuntimeError("invalid JWT")
        auth_error.message = "invalid JWT"
        get_sb.return_value.auth.get_user.side_effect = auth_error

        response = self.client.get(
            "/doc-types",
            headers={"Authorization": "Bearer redacted-test-token"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid or expired session", response.json()["detail"])
        self.assertNotIn("redacted-test-token", response.text)

    @patch.object(main, "get_sb")
    def test_supabase_auth_service_failure_is_not_misreported_as_bad_user_session(
        self, get_sb
    ):
        get_sb.return_value.auth.get_user.side_effect = RuntimeError(
            "upstream connection unavailable"
        )

        response = self.client.get(
            "/doc-types",
            headers={"Authorization": "Bearer valid-format-token"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("backend Supabase project configuration", response.json()["detail"])

    def test_cors_allows_the_frontend_bearer_preflight_without_cookie_credentials(self):
        response = self.client.options(
            "/doc-types",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )
        self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_cors_allows_the_deployed_vercel_origin_for_certificate_uploads(self):
        response = self.client.options(
            "/extract/state_board_10th",
            headers={
                "Origin": "https://smart-erp-five-umber.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://smart-erp-five-umber.vercel.app",
        )
        self.assertIn("POST", response.headers.get("access-control-allow-methods", ""))

    @patch.object(main, "run_ocr")
    @patch.object(main, "get_sb")
    def test_extract_returns_fields_and_validation_warnings(self, get_sb, run_ocr):
        admin_id = "verified-admin"
        get_sb.return_value.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id=admin_id)
        )
        run_ocr.return_value = (
            "sample OCR text",
            {"candidate_name": "Sample Student"},
        )

        with (
            patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {admin_id}),
            patch.object(main, "validate_document", return_value=["Date is missing."]) as validate,
        ):
            response = self.client.post(
                "/extract/state_board_10th",
                headers={"Authorization": "Bearer valid-admin-token"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"]["candidate_name"], "Sample Student")
        self.assertEqual(response.json()["warnings"], ["Date is missing."])
        validate.assert_called_once()

    @patch.object(main, "run_ocr")
    @patch.object(main, "get_sb")
    def test_extract_rejects_invalid_session_before_running_ocr(self, get_sb, run_ocr):
        get_sb.return_value.auth.get_user.side_effect = ValueError("invalid token")

        response = self.client.post(
            "/extract/state_board_10th",
            headers={"Authorization": "Bearer invalid-token"},
            files={"file": ("certificate.pdf", b"test document", "application/pdf")},
        )

        self.assertEqual(response.status_code, 401)
        run_ocr.assert_not_called()

    @patch.object(main, "run_ocr")
    @patch.object(main, "read_upload", return_value=b"test document")
    @patch.object(main, "get_sb")
    def test_upload_saves_document_and_file_for_authorized_admin(
        self, get_sb, read_upload, run_ocr
    ):
        admin_id = "verified-admin"
        sb = get_sb.return_value
        sb.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id=admin_id)
        )
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"student_id": 42}]
        )
        saved_row = {"student_id": 42, "candidate_name": "Sample Student"}
        sb.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(
            data=[saved_row]
        )
        run_ocr.return_value = ("sample OCR text", {"candidate_name": "Sample Student"})

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {admin_id}):
            response = self.client.post(
                "/upload/state_board_10th",
                headers={"Authorization": "Bearer valid-admin-token"},
                data={"student_id": "42"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["saved"])
        self.assertEqual(response.json()["record"]["student_id"], 42)
        read_upload.assert_called_once()
        run_ocr.assert_called_once()
        sb.storage.from_().upload.assert_called_once()
        sb.table.return_value.insert.assert_called_once()

    @patch.object(main, "run_ocr")
    @patch.object(main, "read_upload", return_value=b"test document")
    @patch.object(main, "get_sb")
    def test_upload_returns_422_for_ocr_failure_without_storage_or_database_writes(
        self, get_sb, read_upload, run_ocr
    ):
        admin_id = "verified-admin"
        sb = get_sb.return_value
        sb.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id=admin_id)
        )
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"student_id": 42}]
        )
        run_ocr.side_effect = main.HTTPException(status_code=422, detail="OCR failed.")

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {admin_id}):
            response = self.client.post(
                "/upload/state_board_10th",
                headers={"Authorization": "Bearer valid-admin-token"},
                data={"student_id": "42"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "OCR failed.")
        sb.storage.from_().upload.assert_not_called()
        sb.table.return_value.insert.assert_not_called()

    @patch.object(main, "run_ocr")
    @patch.object(main, "get_sb")
    def test_upload_rejects_authenticated_user_outside_admin_allowlist(
        self, get_sb, run_ocr
    ):
        sb = get_sb.return_value
        sb.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id="regular-user")
        )

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {"verified-admin"}):
            response = self.client.post(
                "/upload/state_board_10th",
                headers={"Authorization": "Bearer valid-user-token"},
                data={"student_id": "42"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 403)
        run_ocr.assert_not_called()
        sb.table.assert_not_called()

    @patch.object(main, "run_ocr", return_value=("sample OCR text", {"candidate_name": "Sample Student"}))
    @patch.object(main, "read_upload", return_value=b"test document")
    @patch.object(main, "get_sb")
    def test_upload_reports_storage_failure_without_database_insert(
        self, get_sb, read_upload, run_ocr
    ):
        admin_id = "verified-admin"
        sb = get_sb.return_value
        sb.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id=admin_id)
        )
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"student_id": 42}]
        )
        sb.storage.from_.return_value.upload.side_effect = RuntimeError(
            "storage unavailable"
        )

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {admin_id}):
            response = self.client.post(
                "/upload/state_board_10th",
                headers={"Authorization": "Bearer valid-admin-token"},
                data={"student_id": "42"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["detail"],
            "Certificate file upload to Supabase Storage failed.",
        )
        sb.table.return_value.insert.assert_not_called()

    @patch.object(main, "run_ocr", return_value=("sample OCR text", {"candidate_name": "Sample Student"}))
    @patch.object(main, "read_upload", return_value=b"test document")
    @patch.object(main, "get_sb")
    def test_upload_cleans_up_storage_and_reports_database_save_failure(
        self, get_sb, read_upload, run_ocr
    ):
        admin_id = "verified-admin"
        sb = get_sb.return_value
        sb.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id=admin_id)
        )
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"student_id": 42}]
        )
        sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError(
            "database unavailable"
        )

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {admin_id}):
            response = self.client.post(
                "/upload/state_board_10th",
                headers={"Authorization": "Bearer valid-admin-token"},
                data={"student_id": "42"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("could not be saved", response.json()["detail"])
        sb.storage.from_().remove.assert_called_once()

    @patch.object(main, "run_ocr", return_value=("sample OCR text", {"candidate_name": "Sample Student"}))
    @patch.object(main, "read_upload", return_value=b"test document")
    @patch.object(main, "get_sb")
    def test_upload_does_not_claim_storage_cleanup_when_removal_fails(
        self, get_sb, read_upload, run_ocr
    ):
        admin_id = "verified-admin"
        sb = get_sb.return_value
        sb.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id=admin_id)
        )
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{"student_id": 42}]
        )
        sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError(
            "database unavailable"
        )
        sb.storage.from_.return_value.remove.side_effect = RuntimeError(
            "storage cleanup unavailable"
        )

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {admin_id}):
            response = self.client.post(
                "/upload/state_board_10th",
                headers={"Authorization": "Bearer valid-admin-token"},
                data={"student_id": "42"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("cleanup could not be confirmed", response.json()["detail"])
        self.assertNotIn("The uploaded file was removed.", response.json()["detail"])

    @patch.object(main, "get_sb")
    def test_invalid_token_cannot_access_certificate_records(self, get_sb):
        get_sb.return_value.auth.get_user.side_effect = ValueError("invalid token")

        response = self.client.get(
            "/certificates/",
            headers={"Authorization": "Bearer invalid-token"},
        )

        self.assertEqual(response.status_code, 401)
        get_sb.return_value.table.assert_not_called()

    @patch.object(main, "get_sb")
    def test_authenticated_non_admin_cannot_access_certificate_records(self, get_sb):
        get_sb.return_value.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id="regular-user")
        )

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {"erp-admin"}):
            response = self.client.get(
                "/certificates/",
                headers={"Authorization": "Bearer valid-user-token"},
            )

        self.assertEqual(response.status_code, 403)
        get_sb.return_value.table.assert_not_called()

    @patch.object(main, "get_sb")
    def test_valid_student_session_is_not_granted_certificate_admin_access(self, get_sb):
        get_sb.return_value.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id="verified-student")
        )

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {"erp-admin"}):
            response = self.client.post(
                "/extract/state_board_10th",
                headers={"Authorization": "Bearer valid-student-token"},
                files={"file": ("certificate.pdf", b"test document", "application/pdf")},
            )

        self.assertEqual(response.status_code, 403)
        get_sb.return_value.auth.get_user.assert_called_once_with("valid-student-token")

    @patch.object(main, "get_sb")
    def test_verification_identity_comes_from_verified_token(self, get_sb):
        admin_id = "verified-admin"
        get_sb.return_value.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id=admin_id)
        )
        result = SimpleNamespace(data=[{"id": 12, "verified_by": admin_id}])
        query = get_sb.return_value.table.return_value.update.return_value
        query.eq.return_value.execute.return_value = result

        with patch.object(main, "CERTIFICATE_ADMIN_USER_IDS", {admin_id}):
            response = self.client.patch(
                "/verify/cbse_10th_marksheet/12",
                headers={"Authorization": "Bearer valid-admin-token"},
                json={"status": "verified", "verified_by": "forged-user"},
            )

        self.assertEqual(response.status_code, 200)
        update = get_sb.return_value.table.return_value.update.call_args.args[0]
        self.assertEqual(update["verified_by"], admin_id)


if __name__ == "__main__":
    unittest.main()
