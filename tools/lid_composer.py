#!/usr/bin/env python3
"""MiniGauge BMWP2000 LID Composer & Master CID Editor.

Provides an interactive local web interface to compose and reorder Dynamically
Defined Local Identifier (LID) transmission trains, inspect ISO-TP payload framing
and CAN frame counts, and edit the master CID dictionary with zero external pip dependencies.

Conforms to BMW-FAST-over-CAN, ISO 14230-3 (KWP2000), and ISO 15765-2 (ISO-TP).
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
DEFAULT_CIDS_PATH = REPO_ROOT / "config" / "cids.json"
DEFAULT_LIDS_PATH = REPO_ROOT / "config" / "lids.json"

CIDS_FILE_PATH: Path = DEFAULT_CIDS_PATH
LIDS_FILE_PATH: Path = DEFAULT_LIDS_PATH


def create_backup(target_file: Path) -> Optional[Path]:
    """Creates a timestamped backup before modifying a JSON configuration file."""
    if not target_file.is_file():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target_file.with_name(f"{target_file.name}.bak_{timestamp}")
    shutil.copy2(target_file, backup_path)
    return backup_path


def generate_unique_cid_key(base_key: str, existing_keys: Any) -> str:
    """Generates a unique CID dictionary key by suffixing an incrementing counter if needed."""
    candidate = base_key.strip()
    if not candidate:
        candidate = "cid"
    if candidate not in existing_keys:
        return candidate

    counter = 1
    # Check if candidate already has a numeric suffix e.g. "rpm_1"
    match = re.match(r"^(.*?)(?:_(\d+))?$", candidate)
    root = match.group(1) if match else candidate

    while True:
        candidate = f"{root}_{counter}"
        if candidate not in existing_keys:
            return candidate
        counter += 1


def validate_cids(cids_dict: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates the structure of the master CID dictionary."""
    if not isinstance(cids_dict, dict):
        return False, "Master CIDs payload must be a JSON object"

    hex_re = re.compile(r"^0x[0-9a-fA-F]{2,6}$")

    for key, val in cids_dict.items():
        if key == "_schema_guide":
            continue

        if not isinstance(val, dict):
            return False, f"CID '{key}' definition must be an object"

        cid_id = str(val.get("id", ""))
        if not hex_re.match(cid_id):
            return False, f"CID '{key}' has invalid hex id: '{cid_id}' (expected format 0xXXXX)"

        mem_size = val.get("memory_size")
        if mem_size not in (1, 2, 4):
            return False, f"CID '{key}' memory_size must be 1, 2, or 4 (got {mem_size})"

        position = val.get("position")
        if not isinstance(position, int) or position < 1:
            return False, f"CID '{key}' position must be a positive integer >= 1"

        div = val.get("div")
        if not isinstance(div, (int, float)) or abs(div) < 1e-12:
            return False, f"CID '{key}' divisor 'div' must be a non-zero number (got {div})"

        mul = val.get("mul")
        if not isinstance(mul, (int, float)):
            return False, f"CID '{key}' multiplier 'mul' must be a number (got {mul})"

        add = val.get("add")
        if not isinstance(add, (int, float)):
            return False, f"CID '{key}' offset 'add' must be a number (got {add})"

        if "signed" in val and not isinstance(val["signed"], bool):
            return False, f"CID '{key}' 'signed' field must be a boolean (got {val['signed']})"

        if "description" in val and not isinstance(val["description"], str):
            return False, f"CID '{key}' 'description' field must be a string"

    return True, ""


def validate_lids(lids_list: List[Any], known_cids: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Validates the structure of the LID train definitions list."""
    if not isinstance(lids_list, list):
        return False, "LIDs payload must be a JSON array"

    hex_id_re = re.compile(r"^0x[0-9a-fA-F]{2}$")
    valid_modes = {"fast", "medium", "slow", "single", "stop"}

    seen_ids = set()

    for idx, item in enumerate(lids_list):
        if isinstance(item, dict) and "_schema_guide" in item:
            continue

        if not isinstance(item, dict):
            return False, f"LID entry at index {idx} must be an object"

        local_id = str(item.get("local_id", ""))
        if not hex_id_re.match(local_id):
            return False, f"LID train at index {idx} has invalid local_id '{local_id}' (expected format 0xXX)"

        norm_id = local_id.upper()
        if norm_id in seen_ids:
            return False, f"Duplicate local_id '{local_id}' found at index {idx}"
        seen_ids.add(norm_id)

        mode = item.get("transmission_mode", "")
        if mode not in valid_modes:
            return False, f"LID '{local_id}' invalid transmission_mode: '{mode}' (valid: {sorted(valid_modes)})"

        cids = item.get("cids")
        if not isinstance(cids, list):
            return False, f"LID '{local_id}' field 'cids' must be a list of CID keys"

        for cid_key in cids:
            if not isinstance(cid_key, str):
                return False, f"LID '{local_id}' contains non-string CID key: {cid_key}"

    return True, ""


class LIDComposerHandler(BaseAppHandler):
    """HTTP request handler for BMWP2000 LID Composer & CID Editor."""

    def do_GET(self) -> None:
        path, _ = self.parse_query()

        if path.startswith("/static/"):
            if self.serve_static(path):
                return
            self.send_error(404, f"Static asset not found: {path}")
            return

        try:
            if path in ("/", "/index.html"):
                template_path = SCRIPT_DIR / "web" / "templates" / "lid_composer.html"
                if not template_path.is_file():
                    # Fallback if old name still around
                    template_path = SCRIPT_DIR / "web" / "templates" / "ddli_composer.html"
                if not template_path.is_file():
                    self.send_error(404, "Template lid_composer.html not found")
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
                cids_data: Dict[str, Any] = {}
                if CIDS_FILE_PATH.is_file():
                    try:
                        cids_data = json.loads(CIDS_FILE_PATH.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as ex:
                        self.send_json({"error": f"Failed to parse {CIDS_FILE_PATH}: {ex}"}, status=500)
                        return

                lids_data: List[Any] = []
                if LIDS_FILE_PATH.is_file():
                    try:
                        lids_data = json.loads(LIDS_FILE_PATH.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as ex:
                        self.send_json({"error": f"Failed to parse {LIDS_FILE_PATH}: {ex}"}, status=500)
                        return

                response_payload = {
                    "cids": cids_data,
                    "lids": lids_data,
                    "cids_path": str(CIDS_FILE_PATH),
                    "lids_path": str(LIDS_FILE_PATH),
                }
                self.send_json(response_payload)

            else:
                self.send_error(404, "Not Found")

        except Exception as ex:
            self.send_error(500, f"Internal Server Error: {str(ex)}")

    def do_POST(self) -> None:
        path, _ = self.parse_query()

        try:
            if path == "/api/lids":
                body = self.read_json_body()
                lids = body.get("lids")
                if lids is None:
                    self.send_json({"error": "Missing 'lids' field in JSON payload"}, status=400)
                    return

                valid, err_msg = validate_lids(lids)
                if not valid:
                    self.send_json({"error": f"Validation failed: {err_msg}"}, status=400)
                    return

                # Create backup
                backup_path = create_backup(LIDS_FILE_PATH)

                # Format and write updated file
                json_text = json.dumps(lids, indent=2, ensure_ascii=False) + "\n"
                LIDS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
                LIDS_FILE_PATH.write_text(json_text, encoding="utf-8")

                self.send_json({
                    "status": "ok",
                    "backup": backup_path.name if backup_path else None,
                    "count": len(lids)
                })

            elif path == "/api/cids":
                body = self.read_json_body()
                cids = body.get("cids")
                if cids is None:
                    self.send_json({"error": "Missing 'cids' field in JSON payload"}, status=400)
                    return

                valid, err_msg = validate_cids(cids)
                if not valid:
                    self.send_json({"error": f"Validation failed: {err_msg}"}, status=400)
                    return

                # Create backup
                backup_path = create_backup(CIDS_FILE_PATH)

                # Format and write updated file
                json_text = json.dumps(cids, indent=2, ensure_ascii=False) + "\n"
                CIDS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CIDS_FILE_PATH.write_text(json_text, encoding="utf-8")

                self.send_json({
                    "status": "ok",
                    "backup": backup_path.name if backup_path else None,
                    "count": len(cids)
                })

            else:
                self.send_error(404, "Not Found")

        except Exception as ex:
            self.send_json({"error": f"Internal Server Error: {str(ex)}"}, status=500)


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses command line arguments for the LID Composer server."""
    parser = argparse.ArgumentParser(
        description="MiniGauge BMWP2000 LID Composer & Master CID Editor"
    )
    parser.add_argument(
        "--cids",
        type=str,
        default=str(DEFAULT_CIDS_PATH),
        help=f"Path to cids.json master dictionary (default: {DEFAULT_CIDS_PATH})"
    )
    parser.add_argument(
        "--lids",
        type=str,
        default=str(DEFAULT_LIDS_PATH),
        help=f"Path to lids.json train compositions (default: {DEFAULT_LIDS_PATH})"
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

    global CIDS_FILE_PATH, LIDS_FILE_PATH
    CIDS_FILE_PATH = Path(args.cids).resolve()
    LIDS_FILE_PATH = Path(args.lids).resolve()

    LIDComposerHandler.verbose_logging = args.verbose

    print(f"[+] CIDs dictionary path:  {CIDS_FILE_PATH}")
    print(f"[+] LIDs train comp path: {LIDS_FILE_PATH}")

    start_server(
        handler_cls=LIDComposerHandler,
        port=args.port,
        host="127.0.0.1",
        open_browser=not args.no_browser,
        server_name="MiniGauge BMWP2000 LID Composer",
    )


if __name__ == "__main__":
    main()
