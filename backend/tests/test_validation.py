import unittest
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from pydantic import ValidationError

from app.models import ChatRequest, ResetRequest
from app.validation import (
    handle_validation_error,
    safe_dict_get,
    validate_archive_safety,
    validate_content_type,
    validate_extension_mime_policy,
    validate_filename,
    validate_file_size,
    validate_file_signature,
    validate_message,
    validate_user_id,
)


class ValidationHelpersTests(unittest.TestCase):
    def test_validate_user_id_accepts_trimmed_value(self) -> None:
        self.assertEqual(validate_user_id("  user-1  "), "user-1")

    def test_validate_user_id_rejects_whitespace(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_user_id("   ")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_user_id_rejects_too_long(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_user_id("x" * 257)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_message_accepts_trimmed_value(self) -> None:
        self.assertEqual(validate_message("  hello world  "), "hello world")

    def test_validate_message_rejects_whitespace(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_message("   ")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_message_rejects_too_long(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_message("x" * 8001)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_content_type_accepts_allowed(self) -> None:
        allowed = {"application/json", "text/plain"}
        self.assertEqual(validate_content_type("application/json; charset=utf-8", allowed), "application/json")

    def test_validate_content_type_rejects_unsupported(self) -> None:
        allowed = {"application/json"}
        with self.assertRaises(HTTPException) as ctx:
            validate_content_type("text/plain", allowed)
        self.assertEqual(ctx.exception.status_code, 415)

    def test_validate_file_size_rejects_oversized_file(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_file_size(size=11, max_bytes=10, filename="doc.txt")
        self.assertEqual(ctx.exception.status_code, 413)

    def test_validate_filename_rejects_path_traversal(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_filename("../secret.txt")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_filename_accepts_normal_name(self) -> None:
        self.assertEqual(validate_filename("report-final.pdf"), "report-final.pdf")

    def test_validate_file_signature_accepts_pdf_magic(self) -> None:
        validate_file_signature("application/pdf", b"%PDF-1.7\nabc", "report.pdf")

    def test_validate_file_signature_rejects_mime_mismatch(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_file_signature("application/pdf", b"not-a-pdf", "report.pdf")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_file_signature_rejects_non_utf8_text_payload(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_file_signature("text/plain", b"\xff\xfe\x00\x00", "notes.txt")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_extension_mime_policy_accepts_matching_extension(self) -> None:
        validate_extension_mime_policy("application/pdf", "report.pdf")

    def test_validate_extension_mime_policy_rejects_mismatch(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_extension_mime_policy("application/pdf", "report.txt")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_extension_mime_policy_allows_no_extension(self) -> None:
        validate_extension_mime_policy("text/plain", "README")

    def test_validate_archive_safety_accepts_small_docx_like_zip(self) -> None:
        payload = BytesIO()
        with ZipFile(payload, "w") as zf:
            zf.writestr("[Content_Types].xml", "<types></types>")
            zf.writestr("word/document.xml", "<doc>Hello</doc>")
        validate_archive_safety(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload.getvalue(),
            "doc.docx",
        )

    def test_validate_archive_safety_rejects_zip_slip_path(self) -> None:
        payload = BytesIO()
        with ZipFile(payload, "w") as zf:
            zf.writestr("../evil.txt", "x")
        with self.assertRaises(HTTPException) as ctx:
            validate_archive_safety(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload.getvalue(),
                "doc.docx",
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_archive_safety_rejects_suspicious_compression_ratio(self) -> None:
        payload = BytesIO()
        with ZipFile(payload, "w", compression=ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr("word/document.xml", "A" * (4 * 1024 * 1024))
        with self.assertRaises(HTTPException) as ctx:
            validate_archive_safety(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload.getvalue(),
                "doc.docx",
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_safe_dict_get_defaults_for_non_dict(self) -> None:
        self.assertEqual(safe_dict_get(None, "x", "default"), "default")
        self.assertEqual(safe_dict_get({"x": 1}, "x", "default"), 1)


class PydanticModelValidationTests(unittest.TestCase):
    def test_chat_request_rejects_empty_user_id(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(user_id="   ", message="hello")

    def test_chat_request_rejects_empty_message(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(user_id="u1", message="   ")

    def test_reset_request_rejects_empty_user_id(self) -> None:
        with self.assertRaises(ValidationError):
            ResetRequest(user_id="   ")

    def test_handle_validation_error_maps_to_http_422(self) -> None:
        try:
            ChatRequest(user_id="", message="ok")
        except ValidationError as err:
            with self.assertRaises(HTTPException) as ctx:
                handle_validation_error(err, context="chat request")
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("chat request", str(ctx.exception.detail))
        else:
            self.fail("Expected ValidationError")


if __name__ == "__main__":
    unittest.main()
