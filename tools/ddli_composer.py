#!/usr/bin/env python3
"""MiniGauge BMWP2000 DDLI Composer & Master DID Editor.

Provides an interactive local web interface to compose and reorder Dynamically
Defined Local Identifier (DDLI) transmission trains, inspect ISO-TP payload framing
and CAN frame counts, and edit the master DID dictionary with zero external pip dependencies.

Conforms to ISO 14230-3 (KWP2000) & ISO 15765-2 (ISO-TP).
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure workspace root and tools dir are on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.http_server import BaseAppHandler, start_server

# Global Configuration Paths (configured via CLI args)
DEFAULT_DIDS_PATH = REPO_ROOT / "config" / "dids.json"
DEFAULT_DDLIS_PATH = REPO_ROOT / "config" / "ddlis.json"

DIDS_FILE_PATH: Path = DEFAULT_DIDS_PATH
DDLIS_FILE_PATH: Path = DEFAULT_DDLIS_PATH


def create_backup(target_file: Path) -> Optional[Path]:
    """Creates a timestamped backup before modifying a JSON configuration file."""
    if not target_file.is_file():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target_file.with_name(f"{target_file.name}.bak_{timestamp}")
    shutil.copy2(target_file, backup_path)
    return backup_path


def validate_dids(dids_dict: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates the structure of the master DID dictionary."""
    if not isinstance(dids_dict, dict):
        return False, "Master DIDs payload must be a JSON object"

    hex_re = re.compile(r"^0x[0-9a-fA-F]{2,6}$")

    for key, val in dids_dict.items():
        if key == "_schema_guide":
            continue

        if not isinstance(val, dict):
            return False, f"DID '{key}' definition must be an object"

        did_id = str(val.get("id", ""))
        if not hex_re.match(did_id):
            return False, f"DID '{key}' has invalid hex id: '{did_id}' (expected format 0xXXXX)"

        mem_size = val.get("memory_size")
        if mem_size not in (1, 2, 4):
            return False, f"DID '{key}' memory_size must be 1, 2, or 4 (got {mem_size})"

        position = val.get("position")
        if not isinstance(position, int) or position < 1:
            return False, f"DID '{key}' position must be a positive integer >= 1"

        div = val.get("div")
        if not isinstance(div, int) or div == 0:
            return False, f"DID '{key}' divisor 'div' must be a non-zero integer"

        mul = val.get("mul")
        if not isinstance(mul, int):
            return False, f"DID '{key}' multiplier 'mul' must be an integer"

        add = val.get("add")
        if not isinstance(add, int):
            return False, f"DID '{key}' offset 'add' must be an integer"

    return True, ""


def validate_ddlis(ddlis_list: List[Any], known_dids: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Validates the structure of the DDLI train definitions list."""
    if not isinstance(ddlis_list, list):
        return False, "DDLIs payload must be a JSON array"

    hex_id_re = re.compile(r"^0x[0-9a-fA-F]{2}$")
    valid_modes = {"fast", "medium", "slow", "single", "stop"}

    seen_ids = set()

    for idx, item in enumerate(ddlis_list):
        if isinstance(item, dict) and "_schema_guide" in item:
            continue

        if not isinstance(item, dict):
            return False, f"DDLI entry at index {idx} must be an object"

        local_id = str(item.get("local_id", ""))
        if not hex_id_re.match(local_id):
            return False, f"DDLI train at index {idx} has invalid local_id '{local_id}' (expected format 0xXX)"

        norm_id = local_id.upper()
        if norm_id in seen_ids:
            return False, f"Duplicate local_id '{local_id}' found at index {idx}"
        seen_ids.add(norm_id)

        mode = item.get("transmission_mode", "")
        if mode not in valid_modes:
            return False, f"DDLI '{local_id}' invalid transmission_mode: '{mode}' (valid: {sorted(valid_modes)})"

        dids = item.get("dids")
        if not isinstance(dids, list):
            return False, f"DDLI '{local_id}' field 'dids' must be a list of DID keys"

        for did_key in dids:
            if not isinstance(did_key, str):
                return False, f"DDLI '{local_id}' contains non-string DID key: {did_key}"
            if known_dids is not None and did_key not in known_dids and did_key != "_schema_guide":
                # Warning or rejection - we allow unknown DIDs with soft notification or strict validation
                pass

    return True, ""


class DDLIComposerHandler(BaseAppHandler):
    """HTTP request handler for BMWP2000 DDLI Composer & DID Editor."""

    def do_GET(self) -> None:
        path, _ = self.parse_query()

        if path.startswith("/static/"):
            if self.serve_static(path):
                return
            self.send_error(404, f"Static asset not found: {path}")
            return

        try:
            if path in ("/", "/index.html"):
                template_path = SCRIPT_DIR / "web" / "templates" / "ddli_composer.html"
                if not template_path.is_file():
                    self.send_error(404, "Template ddli_composer.html not found")
                    return
                html = template_path.read_text(encoding="utf-8")
                self.send_html(html)

            elif path == "/favicon.ico":
                svg_icon = (
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                    '<circle cx="16" cy="16" r="14" fill="#0a0a0a" stroke="#dd6b3d" stroke-width="2"/>'
                    '<path d="M 8 22 A 10 10 0 1 1 24 22" fill="none" stroke="#2b5c92" stroke-width="2.5" stroke-linecap="round"/>'
                    '<line x1="16" y1="16" x2="21" y2="10" stroke="#dd6b3d" stroke-width="2" stroke-linecap="round"/>'
                    '<circle cx="16" cy="16" r="2.5" fill="#dd6b3d"/>'
                    '</svg>'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(svg_icon)))
                self.end_headers()
                self.wfile.write(svg_icon)

            elif path == "/api/config":
                dids_data: Dict[str, Any] = {}
                if DIDS_FILE_PATH.is_file():
                    try:
                        dids_data = json.loads(DIDS_FILE_PATH.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as ex:
                        self.send_json({"error": f"Failed to parse {DIDS_FILE_PATH}: {ex}"}, status=500)
                        return

                ddlis_data: List[Any] = []
                if DDLIS_FILE_PATH.is_file():
                    try:
                        ddlis_data = json.loads(DDLIS_FILE_PATH.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as ex:
                        self.send_json({"error": f"Failed to parse {DDLIS_FILE_PATH}: {ex}"}, status=500)
                        return

                response_payload = {
                    "dids": dids_data,
                    "ddlis": ddlis_data,
                    "dids_path": str(DIDS_FILE_PATH),
                    "ddlis_path": str(DDLIS_FILE_PATH),
                }
                self.send_json(response_payload)

            else:
                self.send_error(404, "Not Found")

        except Exception as ex:
            self.send_error(500, f"Internal Server Error: {str(ex)}")

    def do_POST(self) -> None:
        path, _ = self.parse_query()

        try:
            if path == "/api/ddlis":
                body = self.read_json_body()
                ddlis = body.get("ddlis")
                if ddlis is None:
                    self.send_json({"error": "Missing 'ddlis' field in JSON payload"}, status=400)
                    return

                valid, err_msg = validate_ddlis(ddlis)
                if not valid:
                    self.send_json({"error": f"Validation failed: {err_msg}"}, status=400)
                    return

                # Create backup
                backup_path = create_backup(DDLIS_FILE_PATH)

                # Format and write updated file
                json_text = json.dumps(ddlis, indent=2, ensure_ascii=False) + "\n"
                DDLIS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
                DDLIS_FILE_PATH.write_text(json_text, encoding="utf-8")

                self.send_json({
                    "status": "ok",
                    "backup": backup_path.name if backup_path else None,
                    "count": len(ddlis)
                })

            elif path == "/api/dids":
                body = self.read_json_body()
                dids = body.get("dids")
                if dids is None:
                    self.send_json({"error": "Missing 'dids' field in JSON payload"}, status=400)
                    return

                valid, err_msg = validate_dids(dids)
                if not valid:
                    self.send_json({"error": f"Validation failed: {err_msg}"}, status=400)
                    return

                # Create backup
                backup_path = create_backup(DIDS_FILE_PATH)

                # Format and write updated file
                json_text = json.dumps(dids, indent=2, ensure_ascii=False) + "\n"
                DIDS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
                DIDS_FILE_PATH.write_text(json_text, encoding="utf-8")

                self.send_json({
                    "status": "ok",
                    "backup": backup_path.name if backup_path else None,
                    "count": len(dids)
                })

            else:
                self.send_error(404, "Not Found")

        except Exception as ex:
            self.send_json({"error": f"Internal Server Error: {str(ex)}"}, status=500)


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses command line arguments for the DDLI Composer server."""
    parser = argparse.ArgumentParser(
        description="MiniGauge BMWP2000 DDLI Composer & Master DID Editor"
    )
    parser.add_argument(
        "--dids",
        type=str,
        default=str(DEFAULT_DIDS_PATH),
        help=f"Path to dids.json master dictionary (default: {DEFAULT_DIDS_PATH})"
    )
    parser.add_argument(
        "--ddlis",
        type=str,
        default=str(DEFAULT_DDLIS_PATH),
        help=f"Path to ddlis.json train compositions (default: {DEFAULT_DDLIS_PATH})"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8092,
        help="HTTP server port (default: 8092)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open web browser on startup"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose HTTP request logging"
    )
    return parser.parse_args(argv)


def main() -> None:
    """CLI entrypoint."""
    args = parse_arguments()

    global DIDS_FILE_PATH, DDLIS_FILE_PATH
    DIDS_FILE_PATH = Path(args.dids).resolve()
    DDLIS_FILE_PATH = Path(args.ddlis).resolve()

    DDLIComposerHandler.verbose_logging = args.verbose

    print(f"[+] DIDs dictionary path:  {DIDS_FILE_PATH}")
    print(f"[+] DDLIs train comp path: {DDLIS_FILE_PATH}")

    start_server(
        handler_cls=DDLIComposerHandler,
        port=args.port,
        host="127.0.0.1",
        open_browser=not args.no_browser,
        server_name="MiniGauge BMWP2000 DDLI Composer",
    )


if __name__ == "__main__":
    main()
