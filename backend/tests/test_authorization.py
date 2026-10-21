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
