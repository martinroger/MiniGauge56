"""Unit and integration tests for MiniGauge BMWP2000 LID Composer (tools/lid_composer.py)."""

import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

# Ensure workspace root and tools dir are on sys.path
TEST_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TEST_DIR.parent
REPO_ROOT = TOOLS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import lid_composer
from lid_composer import (
    parse_arguments,
    validate_cids,
    validate_lids,
    create_backup,
    generate_unique_cid_key,
    LIDComposerHandler,
)


class TestLIDComposerLogic(unittest.TestCase):
    """Unit tests for argument parsing, validation logic, and backup creation."""

    def test_cli_argument_defaults(self):
        args = parse_arguments([])
        self.assertEqual(args.port, 8092)
        self.assertFalse(args.no_browser)
        self.assertFalse(args.verbose)
        self.assertIn("cids.json", args.cids)
        self.assertIn("lids.json", args.lids)

    def test_cli_custom_arguments(self):
        args = parse_arguments([
            "--cids", "custom/cids.json",
            "--lids", "custom/lids.json",
            "--port", "8190",
            "--no-browser",
            "--verbose"
        ])
        self.assertEqual(args.port, 8190)
        self.assertTrue(args.no_browser)
        self.assertTrue(args.verbose)
        self.assertEqual(args.dids if hasattr(args, "dids") else args.cids, "custom/cids.json")
        self.assertEqual(args.ddlis if hasattr(args, "ddlis") else args.lids, "custom/lids.json")

    def test_validate_cids_valid(self):
        sample_cids = {
            "_schema_guide": {"description": "Guide"},
            "RPM": {
                "id": "0x580C",
                "memory_size": 1,
                "position": 1,
                "mul": 40,
                "div": 1,
                "add": 0,
                "unit": "RPM"
            },
            "Oil_Pressure": {
                "id": "0x58F0",
                "memory_size": 2,
                "position": 1,
                "signed": False,
                "mul": 0.0390625,
                "div": 1.0,
                "add": 0.0,
                "unit": "Bar",
                "description": "Oil Pressure"
            }
        }
        valid, err = validate_cids(sample_cids)
        self.assertTrue(valid, f"Validation should succeed: {err}")
        self.assertEqual(err, "")

    def test_validate_cids_invalid_types_and_values(self):
        # Non-dict
        valid, err = validate_cids(["not", "a", "dict"])
        self.assertFalse(valid)
        self.assertIn("must be a JSON object", err)

        # Invalid hex
        valid, err = validate_cids({"RPM": {"id": "580C", "memory_size": 1, "position": 1, "mul": 1, "div": 1, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("invalid hex id", err)

        # Invalid memory_size
        valid, err = validate_cids({"RPM": {"id": "0x580C", "memory_size": 3, "position": 1, "mul": 1, "div": 1, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("memory_size must be 1, 2, or 4", err)

        # Divisor is zero
        valid, err = validate_cids({"RPM": {"id": "0x580C", "memory_size": 1, "position": 1, "mul": 1, "div": 0, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("divisor 'div' must be a non-zero number", err)

        # Position < 1
        valid, err = validate_cids({"RPM": {"id": "0x580C", "memory_size": 1, "position": 0, "mul": 1, "div": 1, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("position must be a positive integer", err)

        # Invalid signed type
        valid, err = validate_cids({"RPM": {"id": "0x580C", "memory_size": 1, "position": 1, "mul": 1, "div": 1, "add": 0, "signed": "yes"}})
        self.assertFalse(valid)
        self.assertIn("'signed' field must be a boolean", err)

    def test_generate_unique_cid_key(self):
        keys = {"rpm", "oilTemp", "oilTemp_1", "oilTemp_2", "boost"}
        self.assertEqual(generate_unique_cid_key("lambda", keys), "lambda")
        self.assertEqual(generate_unique_cid_key("rpm", keys), "rpm_1")
        self.assertEqual(generate_unique_cid_key("oilTemp", keys), "oilTemp_3")
        self.assertEqual(generate_unique_cid_key("oilTemp_1", keys), "oilTemp_3")

    def test_production_json_files_pass_validation(self):
        cids_file = REPO_ROOT / "config" / "cids.json"
        lids_file = REPO_ROOT / "config" / "lids.json"
        self.assertTrue(cids_file.is_file(), "config/cids.json must exist")
        self.assertTrue(lids_file.is_file(), "config/lids.json must exist")

        cids = json.loads(cids_file.read_text(encoding="utf-8"))
        lids = json.loads(lids_file.read_text(encoding="utf-8"))

        valid_cids, err_cids = validate_cids(cids)
        self.assertTrue(valid_cids, f"Production config/cids.json failed validation: {err_cids}")

        valid_lids, err_lids = validate_lids(lids)
        self.assertTrue(valid_lids, f"Production config/lids.json failed validation: {err_lids}")

    def test_validate_lids_valid(self):
        sample_lids = [
            {"_schema_guide": {"description": "Guide"}},
            {
                "local_id": "0xF0",
                "name": "Engine_Core_Metrics",
                "transmission_mode": "fast",
                "cids": ["RPM", "HPFP_Pressure"]
            },
            {
                "local_id": "0xF1",
                "name": "Transmission_Metrics",
                "transmission_mode": "single",
                "cids": ["Gear"]
            }
        ]
        valid, err = validate_lids(sample_lids)
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_validate_lids_invalid_types_and_values(self):
        # Non-list
        valid, err = validate_lids({"not": "a list"})
        self.assertFalse(valid)
        self.assertIn("must be a JSON array", err)

        # Invalid local_id format
        valid, err = validate_lids([{"local_id": "F0", "name": "A", "transmission_mode": "fast", "cids": []}])
        self.assertFalse(valid)
        self.assertIn("invalid local_id", err)

        # Duplicate local_id
        valid, err = validate_lids([
            {"local_id": "0xF0", "name": "A", "transmission_mode": "fast", "cids": []},
            {"local_id": "0xF0", "name": "B", "transmission_mode": "slow", "cids": []}
        ])
        self.assertFalse(valid)
        self.assertIn("Duplicate local_id", err)

        # Invalid transmission_mode
        valid, err = validate_lids([{"local_id": "0xF0", "name": "A", "transmission_mode": "ultra_fast", "cids": []}])
        self.assertFalse(valid)
        self.assertIn("invalid transmission_mode", err)

        # cids is not a list
        valid, err = validate_lids([{"local_id": "0xF0", "name": "A", "transmission_mode": "fast", "cids": "RPM"}])
        self.assertFalse(valid)
        self.assertIn("must be a list of CID keys", err)

    def test_create_backup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = Path(tmp_dir) / "test_config.json"
            test_file.write_text('{"key": "initial_value"}\n', encoding="utf-8")

            # Non-existent file
            no_file = Path(tmp_dir) / "does_not_exist.json"
            self.assertIsNone(create_backup(no_file))

            # Existing file
            backup_path = create_backup(test_file)
            self.assertIsNotNone(backup_path)
            self.assertTrue(backup_path.is_file())
            self.assertIn(".bak_", backup_path.name)
            self.assertEqual(backup_path.read_text(encoding="utf-8"), test_file.read_text(encoding="utf-8"))


class TestLIDComposerServerEndpoints(unittest.TestCase):
    """In-memory integration test suite for HTTP routing, template rendering, and REST endpoints."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lid_test_")
        self.tmp_path = Path(self.tmp_dir)

        self.test_cids_path = self.tmp_path / "cids.json"
        self.test_lids_path = self.tmp_path / "lids.json"

        # Initialize with sample content
        self.test_cids_path.write_text(json.dumps({
            "_schema_guide": {"description": "Guide"},
            "RPM": {
                "id": "0x580C",
                "memory_size": 1,
                "position": 1,
                "mul": 40,
                "div": 1,
                "add": 0,
                "unit": "RPM"
            }
        }, indent=2), encoding="utf-8")

        self.test_lids_path.write_text(json.dumps([
            {"_schema_guide": {"description": "Guide"}},
            {
                "local_id": "0xF0",
                "name": "Engine_Core_Metrics",
                "transmission_mode": "fast",
                "cids": ["RPM"]
            }
        ], indent=2), encoding="utf-8")

        lid_composer.CIDS_FILE_PATH = self.test_cids_path
        lid_composer.LIDS_FILE_PATH = self.test_lids_path

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_mock_handler(self, path: str, method: str = "GET", body: bytes = None):
        class DummyHandler(LIDComposerHandler):
            def __init__(self):
                self.command = method
                self.path = path
                self.headers = {
                    "Content-Length": str(len(body)) if body else "0",
                    "Content-Type": "application/json",
                }
                self.rfile = io.BytesIO(body or b"")
                self.wfile = io.BytesIO()
                self.status_code = 200
                self.headers_sent = []

            def send_response(self, code, message=None):
                self.status_code = code

            def send_header(self, keyword, value):
                self.headers_sent.append((keyword, value))

            def end_headers(self):
                pass

            def send_error(self, code, message=None, explain=None):
                self.status_code = code

        return DummyHandler()

    def test_01_template_and_static_files_exist(self):
        template = TOOLS_DIR / "web" / "templates" / "lid_composer.html"
        self.assertTrue(template.is_file(), "lid_composer.html must exist")

        css = TOOLS_DIR / "web" / "static" / "css" / "lid_composer.css"
        self.assertTrue(css.is_file(), "lid_composer.css must exist")

        js = TOOLS_DIR / "web" / "static" / "js" / "lid_composer.js"
        self.assertTrue(js.is_file(), "lid_composer.js must exist")

    def test_02_http_get_index_and_dom_elements(self):
        h = self._create_mock_handler("/")
        h.do_GET()
        self.assertEqual(h.status_code, 200)
        body = h.wfile.getvalue().decode("utf-8")

        required_ids = [
            "tab-btn-composer",
            "tab-btn-cids",
            "tab-composer",
            "tab-cids",
            "badge-lids-file",
            "badge-cids-file",
            "theme-toggle-btn",
            "select-lid-train",
            "btn-new-train",
            "btn-delete-train",
            "btn-save-lids",
            "input-train-local-id",
            "input-train-name",
            "select-train-mode",
            "metric-cid-count",
            "metric-payload-bytes",
            "metric-response-bytes",
            "metric-framing",
            "metric-frame-count",
            "search-palette",
            "palette-cid-list",
            "active-sequence-list",
            "search-cids",
            "btn-add-cid",
            "btn-save-cids",
            "table-cids",
            "tbody-cids",
            "modal-cid",
            "form-cid",
        ]
        for elem_id in required_ids:
            self.assertIn(f'id="{elem_id}"', body, f"Missing DOM id: {elem_id}")

    def test_03_http_get_favicon_and_static_assets(self):
        # Favicon
        h = self._create_mock_handler("/favicon.ico")
        h.do_GET()
        self.assertEqual(h.status_code, 200)

        # Static assets
        assets = [
            "/static/css/lid_composer.css",
            "/static/js/lid_composer.js",
            "/static/css/theme.css",
            "/static/css/components.css",
            "/static/js/toast.js",
            "/static/js/theme.js",
        ]
        for path in assets:
            h_asset = self._create_mock_handler(path)
            h_asset.do_GET()
            self.assertEqual(h_asset.status_code, 200, f"Failed asset {path}")

    def test_04_api_config_get(self):
        h = self._create_mock_handler("/api/config")
        h.do_GET()
        self.assertEqual(h.status_code, 200)
        data = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertIn("cids", data)
        self.assertIn("lids", data)
        self.assertIn("RPM", data["cids"])
        self.assertEqual(len(data["lids"]), 2)

    def test_05_api_post_lids_validation_and_persistence(self):
        # 1. Invalid payload (missing lids)
        h_bad = self._create_mock_handler(
            "/api/lids",
            method="POST",
            body=json.dumps({"invalid_key": []}).encode("utf-8")
        )
        h_bad.do_POST()
        self.assertEqual(h_bad.status_code, 400)

        # 2. Invalid train data (duplicate local_id)
        bad_trains = [
            {"local_id": "0xF0", "name": "Train1", "transmission_mode": "fast", "cids": ["RPM"]},
            {"local_id": "0xF0", "name": "Train2", "transmission_mode": "fast", "cids": []},
        ]
        h_dup = self._create_mock_handler(
            "/api/lids",
            method="POST",
            body=json.dumps({"lids": bad_trains}).encode("utf-8")
        )
        h_dup.do_POST()
        self.assertEqual(h_dup.status_code, 400)

        # 3. Valid update
        good_trains = [
            {"_schema_guide": {"description": "Guide"}},
            {
                "local_id": "0xF0",
                "name": "Engine_Core_Metrics",
                "transmission_mode": "fast",
                "cids": ["RPM"]
            },
            {
                "local_id": "0xF1",
                "name": "Custom_Metrics",
                "transmission_mode": "medium",
                "cids": ["RPM"]
            }
        ]
        h_good = self._create_mock_handler(
            "/api/lids",
            method="POST",
            body=json.dumps({"lids": good_trains}).encode("utf-8")
        )
        h_good.do_POST()
        self.assertEqual(h_good.status_code, 200)
        res = json.loads(h_good.wfile.getvalue().decode("utf-8"))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["count"], 3)
        self.assertIsNotNone(res["backup"])

        # Check disk update
        updated_file_data = json.loads(self.test_lids_path.read_text(encoding="utf-8"))
        self.assertEqual(len(updated_file_data), 3)
        self.assertEqual(updated_file_data[2]["local_id"], "0xF1")

    def test_06_api_post_cids_validation_and_persistence(self):
        # 1. Invalid payload (missing cids)
        h_bad = self._create_mock_handler(
            "/api/cids",
            method="POST",
            body=json.dumps({"bad": 123}).encode("utf-8")
        )
        h_bad.do_POST()
        self.assertEqual(h_bad.status_code, 400)

        # 2. Invalid CID data (div=0)
        bad_cids = {
            "RPM": {"id": "0x580C", "memory_size": 1, "position": 1, "mul": 1, "div": 0, "add": 0}
        }
        h_zero = self._create_mock_handler(
            "/api/cids",
            method="POST",
            body=json.dumps({"cids": bad_cids}).encode("utf-8")
        )
        h_zero.do_POST()
        self.assertEqual(h_zero.status_code, 400)

        # 3. Valid update
        good_cids = {
            "_schema_guide": {"description": "Guide"},
            "RPM": {
                "id": "0x580C",
                "memory_size": 1,
                "position": 1,
                "mul": 40,
                "div": 1,
                "add": 0,
                "unit": "RPM"
            },
            "IAT": {
                "id": "0x580F",
                "memory_size": 1,
                "position": 1,
                "mul": 3,
                "div": 4,
                "add": -48,
                "unit": "°C"
            }
        }
        h_good = self._create_mock_handler(
            "/api/cids",
            method="POST",
            body=json.dumps({"cids": good_cids}).encode("utf-8")
        )
        h_good.do_POST()
        self.assertEqual(h_good.status_code, 200)
        res = json.loads(h_good.wfile.getvalue().decode("utf-8"))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["count"], 3)
        self.assertIsNotNone(res["backup"])

        # Check disk contents
        disk_data = json.loads(self.test_cids_path.read_text(encoding="utf-8"))
        self.assertIn("IAT", disk_data)
        self.assertEqual(disk_data["IAT"]["unit"], "°C")

    def test_07_http_404_routes(self):
        h1 = self._create_mock_handler("/api/unknown_endpoint")
        h1.do_GET()
        self.assertEqual(h1.status_code, 404)

        h2 = self._create_mock_handler("/static/css/does_not_exist_xyz.css")
        h2.do_GET()
        self.assertEqual(h2.status_code, 404)


if __name__ == "__main__":
    unittest.main()
