"""Unit and integration tests for MiniGauge BMWP2000 DDLI Composer (tools/ddli_composer.py)."""

import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

# Ensure workspace root and tools dir are on sys.path
TEST_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TEST_DIR.parent
REPO_ROOT = TOOLS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import ddli_composer
from ddli_composer import (
    parse_arguments,
    validate_dids,
    validate_ddlis,
    create_backup,
    DDLIComposerHandler,
)
from common.http_server import ThreadingHTTPServer


class TestDDLIComposerLogic(unittest.TestCase):
    """Unit tests for argument parsing, validation logic, and backup creation."""

    def test_cli_argument_defaults(self):
        args = parse_arguments([])
        self.assertEqual(args.port, 8092)
        self.assertFalse(args.no_browser)
        self.assertFalse(args.verbose)
        self.assertIn("dids.json", args.dids)
        self.assertIn("ddlis.json", args.ddlis)

    def test_cli_custom_arguments(self):
        args = parse_arguments([
            "--dids", "custom/dids.json",
            "--ddlis", "custom/ddlis.json",
            "--port", "8190",
            "--no-browser",
            "--verbose"
        ])
        self.assertEqual(args.port, 8190)
        self.assertTrue(args.no_browser)
        self.assertTrue(args.verbose)
        self.assertEqual(args.dids, "custom/dids.json")
        self.assertEqual(args.ddlis, "custom/ddlis.json")

    def test_validate_dids_valid(self):
        sample_dids = {
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
                "mul": 1,
                "div": 2000,
                "add": 0,
                "unit": "Bar"
            }
        }
        valid, err = validate_dids(sample_dids)
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_validate_dids_invalid_types_and_values(self):
        # Non-dict
        valid, err = validate_dids(["not", "a", "dict"])
        self.assertFalse(valid)
        self.assertIn("must be a JSON object", err)

        # Invalid hex
        valid, err = validate_dids({"RPM": {"id": "580C", "memory_size": 1, "position": 1, "mul": 1, "div": 1, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("invalid hex id", err)

        # Invalid memory_size
        valid, err = validate_dids({"RPM": {"id": "0x580C", "memory_size": 3, "position": 1, "mul": 1, "div": 1, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("memory_size must be 1, 2, or 4", err)

        # Divisor is zero
        valid, err = validate_dids({"RPM": {"id": "0x580C", "memory_size": 1, "position": 1, "mul": 1, "div": 0, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("divisor 'div' must be a non-zero integer", err)

        # Position < 1
        valid, err = validate_dids({"RPM": {"id": "0x580C", "memory_size": 1, "position": 0, "mul": 1, "div": 1, "add": 0}})
        self.assertFalse(valid)
        self.assertIn("position must be a positive integer", err)

    def test_validate_ddlis_valid(self):
        sample_ddlis = [
            {"_schema_guide": {"description": "Guide"}},
            {
                "local_id": "0xF0",
                "name": "Engine_Core_Metrics",
                "transmission_mode": "fast",
                "dids": ["RPM", "HPFP_Pressure"]
            },
            {
                "local_id": "0xF1",
                "name": "Transmission_Metrics",
                "transmission_mode": "single",
                "dids": ["Gear"]
            }
        ]
        valid, err = validate_ddlis(sample_ddlis)
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_validate_ddlis_invalid_types_and_values(self):
        # Non-list
        valid, err = validate_ddlis({"not": "a list"})
        self.assertFalse(valid)
        self.assertIn("must be a JSON array", err)

        # Invalid local_id format
        valid, err = validate_ddlis([{"local_id": "F0", "name": "A", "transmission_mode": "fast", "dids": []}])
        self.assertFalse(valid)
        self.assertIn("invalid local_id", err)

        # Duplicate local_id
        valid, err = validate_ddlis([
            {"local_id": "0xF0", "name": "A", "transmission_mode": "fast", "dids": []},
            {"local_id": "0xF0", "name": "B", "transmission_mode": "slow", "dids": []}
        ])
        self.assertFalse(valid)
        self.assertIn("Duplicate local_id", err)

        # Invalid transmission_mode
        valid, err = validate_ddlis([{"local_id": "0xF0", "name": "A", "transmission_mode": "ultra_fast", "dids": []}])
        self.assertFalse(valid)
        self.assertIn("invalid transmission_mode", err)

        # dids is not a list
        valid, err = validate_ddlis([{"local_id": "0xF0", "name": "A", "transmission_mode": "fast", "dids": "RPM"}])
        self.assertFalse(valid)
        self.assertIn("must be a list of DID keys", err)

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


class TestDDLIComposerServerEndpoints(unittest.TestCase):
    """Integration test suite for HTTP routing, template rendering, and REST endpoints."""

    @classmethod
    def setUpClass(cls):
        # Create isolated temporary directory for test configuration files
        cls.tmp_dir = tempfile.mkdtemp(prefix="ddli_test_")
        cls.tmp_path = Path(cls.tmp_dir)

        cls.test_dids_path = cls.tmp_path / "dids.json"
        cls.test_ddlis_path = cls.tmp_path / "ddlis.json"

        # Initialize with sample content
        cls.test_dids_path.write_text(json.dumps({
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

        cls.test_ddlis_path.write_text(json.dumps([
            {"_schema_guide": {"description": "Guide"}},
            {
                "local_id": "0xF0",
                "name": "Engine_Core_Metrics",
                "transmission_mode": "fast",
                "dids": ["RPM"]
            }
        ], indent=2), encoding="utf-8")

        # Point module globals to test paths
        ddli_composer.DIDS_FILE_PATH = cls.test_dids_path
        ddli_composer.DDLIS_FILE_PATH = cls.test_ddlis_path

        # Start ThreadingHTTPServer on an ephemeral port
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DDLIComposerHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_01_template_and_static_files_exist(self):
        template = TOOLS_DIR / "web" / "templates" / "ddli_composer.html"
        self.assertTrue(template.is_file(), "ddli_composer.html must exist")

        css = TOOLS_DIR / "web" / "static" / "css" / "ddli_composer.css"
        self.assertTrue(css.is_file(), "ddli_composer.css must exist")

        js = TOOLS_DIR / "web" / "static" / "js" / "ddli_composer.js"
        self.assertTrue(js.is_file(), "ddli_composer.js must exist")

    def test_02_http_get_index_and_dom_elements(self):
        req = urllib.request.Request(f"{self.base_url}/")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")

            # Check core DOM IDs and controls
            required_ids = [
                "tab-btn-composer",
                "tab-btn-dids",
                "tab-composer",
                "tab-dids",
                "badge-ddlis-file",
                "badge-dids-file",
                "theme-toggle-btn",
                "select-ddli-train",
                "btn-new-train",
                "btn-delete-train",
                "btn-save-ddlis",
                "input-train-local-id",
                "input-train-name",
                "select-train-mode",
                "metric-did-count",
                "metric-payload-bytes",
                "metric-response-bytes",
                "metric-framing",
                "metric-frame-count",
                "search-palette",
                "palette-did-list",
                "active-sequence-list",
                "search-dids",
                "btn-add-did",
                "btn-save-dids",
                "table-dids",
                "tbody-dids",
                "modal-did",
                "form-did",
            ]
            for elem_id in required_ids:
                self.assertIn(f'id="{elem_id}"', body, f"Missing DOM id: {elem_id}")

    def test_03_http_get_favicon_and_static_assets(self):
        # Favicon
        with urllib.request.urlopen(f"{self.base_url}/favicon.ico") as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("image/svg+xml", resp.headers.get("Content-Type", ""))

        # Static assets
        assets = [
            ("/static/css/ddli_composer.css", "text/css"),
            ("/static/js/ddli_composer.js", "javascript"),
            ("/static/css/theme.css", "text/css"),
            ("/static/css/components.css", "text/css"),
            ("/static/js/toast.js", "javascript"),
            ("/static/js/theme.js", "javascript"),
        ]
        for path, mime in assets:
            with urllib.request.urlopen(f"{self.base_url}{path}") as resp:
                self.assertEqual(resp.status, 200, f"Failed asset {path}")
                ct = resp.headers.get("Content-Type", "")
                self.assertIn(mime, ct, f"MIME mismatch for {path}: {ct}")

    def test_04_api_config_get(self):
        req = urllib.request.Request(f"{self.base_url}/api/config")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("dids", data)
            self.assertIn("ddlis", data)
            self.assertIn("RPM", data["dids"])
            self.assertEqual(len(data["ddlis"]), 2)  # schema_guide + train

    def test_05_api_post_ddlis_validation_and_persistence(self):
        # 1. Invalid payload (missing ddlis)
        req_bad = urllib.request.Request(
            f"{self.base_url}/api/ddlis",
            data=json.dumps({"invalid_key": []}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_bad)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

        # 2. Invalid train data (duplicate local_id)
        bad_trains = [
            {"local_id": "0xF0", "name": "Train1", "transmission_mode": "fast", "dids": ["RPM"]},
            {"local_id": "0xF0", "name": "Train2", "transmission_mode": "fast", "dids": []},
        ]
        req_dup = urllib.request.Request(
            f"{self.base_url}/api/ddlis",
            data=json.dumps({"ddlis": bad_trains}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_dup)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

        # 3. Valid update
        good_trains = [
            {"_schema_guide": {"description": "Guide"}},
            {
                "local_id": "0xF0",
                "name": "Engine_Core_Metrics",
                "transmission_mode": "fast",
                "dids": ["RPM"]
            },
            {
                "local_id": "0xF1",
                "name": "Custom_Metrics",
                "transmission_mode": "medium",
                "dids": ["RPM"]
            }
        ]
        req_good = urllib.request.Request(
            f"{self.base_url}/api/ddlis",
            data=json.dumps({"ddlis": good_trains}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_good) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["count"], 3)
            self.assertIsNotNone(res["backup"])

        # Check that file on disk was updated
        updated_file_data = json.loads(self.test_ddlis_path.read_text(encoding="utf-8"))
        self.assertEqual(len(updated_file_data), 3)
        self.assertEqual(updated_file_data[2]["local_id"], "0xF1")

    def test_06_api_post_dids_validation_and_persistence(self):
        # 1. Invalid payload (missing dids)
        req_bad = urllib.request.Request(
            f"{self.base_url}/api/dids",
            data=json.dumps({"bad": 123}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_bad)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

        # 2. Invalid DID data (div=0)
        bad_dids = {
            "RPM": {"id": "0x580C", "memory_size": 1, "position": 1, "mul": 1, "div": 0, "add": 0}
        }
        req_zero_div = urllib.request.Request(
            f"{self.base_url}/api/dids",
            data=json.dumps({"dids": bad_dids}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_zero_div)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

        # 3. Valid update
        good_dids = {
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
        req_good = urllib.request.Request(
            f"{self.base_url}/api/dids",
            data=json.dumps({"dids": good_dids}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_good) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["count"], 3)
            self.assertIsNotNone(res["backup"])

        # Check disk contents
        disk_data = json.loads(self.test_dids_path.read_text(encoding="utf-8"))
        self.assertIn("IAT", disk_data)
        self.assertEqual(disk_data["IAT"]["unit"], "°C")

    def test_07_http_404_routes(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base_url}/api/unknown_endpoint")
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base_url}/static/css/does_not_exist_xyz.css")
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
