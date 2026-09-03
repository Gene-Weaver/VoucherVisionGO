"""Focused regression checks for response-aware URL image filenames.

Run manually with:
    python -m unittest tests.tests_url_filename_parser
"""

import unittest

from url_name_parser import resolve_filename_from_response


class ResponseFilenameTests(unittest.TestCase):
    def test_michigan_content_disposition_yields_catalog_number(self):
        url = (
            "https://quod.lib.umich.edu/cgi/i/image/api/image/"
            "herb00ic:1122841:MICH-V-1122841/full/res:0/0/native.jpg"
        )
        disposition = (
            'inline; filename="herb00ic_1122841_MICH-V-1122841_'
            'MICH-V-1122841_3753x5634.jpg"'
        )
        self.assertEqual(
            resolve_filename_from_response(
                url, content_disposition=disposition
            ),
            "MICH-V-1122841.jpg",
        )

    def test_iiif_path_identifier_is_used_without_a_header(self):
        url = (
            "https://quod.lib.umich.edu/cgi/i/image/api/image/"
            "herb00ic:1122841:MICH-V-1122841/full/res:0/0/native.jpg"
        )
        self.assertEqual(
            resolve_filename_from_response(url), "MICH-V-1122841.jpg"
        )

    def test_explicit_image_filename_remains_unchanged(self):
        url = "https://sweetgum.nybg.org/images3/521/802/01449954.jpg"
        self.assertEqual(
            resolve_filename_from_response(url), "01449954.jpg"
        )

    def test_case_insensitive_image_query_parameter_is_used(self):
        url = "https://rmh.uwyo.edu/images/jpeg.php?Image=RM0021232.jpg&Width=2000"
        self.assertEqual(
            resolve_filename_from_response(url), "RM0021232.jpg"
        )

    def test_rfc_5987_response_filename_is_supported_and_sanitized(self):
        self.assertEqual(
            resolve_filename_from_response(
                "https://example.org/native.jpg",
                content_disposition=(
                    "attachment; filename*=UTF-8''ABC%201234.jpg"
                ),
            ),
            "ABC_1234.jpg",
        )


if __name__ == "__main__":
    unittest.main()
