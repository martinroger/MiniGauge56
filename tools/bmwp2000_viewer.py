#!/usr/bin/env python3
"""MiniGauge BMWP2000 Exchange Viewer.

Interactive local web workstation to inspect and review BMW KWP2000 diagnostic
transactions over ISO-TP, decode positive/negative responses, interpret DDLIs,
unpack DID physical parameters, and highlight unimplemented services.

Zero pip dependencies (Python 3 stdlib only).
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
from common.log_loader import find_all_log_files, load_log_file, detect_log_format
from common.isotp_kwp import (
    IsoTpReassembler,
    BmwP2000Dissector,
    KWP_SERVICE_NAMES,
    KWP_NRC_NAMES,
)

DEFAULT_CIDS_PATH = REPO_ROOT / "config" / "cids.json"
CIDS_FILE_PATH: Path = DEFAULT_CIDS_PATH
INITIAL_LOG_FILE: Optional[Path] = None


def create_backup(target_file: Path) -> Optional[Path]:
    """Creates a timestamped backup before modifying a JSON configuration file."""
    if not target_file.is_file():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target_file.with_name(f"{target_file.name}.bak_{timestamp}")
    shutil.copy2(target_file, backup_path)
    return backup_path


def load_cids_dictionary(path: Path) -> Dict[str, Any]:
    """Loads master CIDs dictionary from JSON file."""
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def analyze_log_exchanges(
    log_path: Path,
    parse_cids: bool = True,
    master_cids: Optional[Dict[str, Any]] = None,
    include_raw_can: bool = True,
) -> Dict[str, Any]:
    """Parses a log file and reconstructs BMWP2000 diagnostic exchanges and raw CAN traffic."""
    frames = load_log_file(log_path)
    reassembler = IsoTpReassembler()
    dissector = BmwP2000Dissector(master_cids)

    # Ingest frames and correlate raw CAN frames and reassembled ISO-TP messages
    events: List[Dict[str, Any]] = []

    for frame in frames:
        # Check if frame is an ISO-TP candidate
        is_candidate = reassembler.is_iso_tp_candidate(frame.can_id)

        interrupted_msg, completed_msg = reassembler.process_frame_events(frame)
        if interrupted_msg:
            events.append(dissector.dissect_message(interrupted_msg, parse_cids=parse_cids))
        if completed_msg:
            events.append(dissector.dissect_message(completed_msg, parse_cids=parse_cids))

        # If not an ISO-TP candidate or if raw CAN inclusion is enabled for non-diagnostic frames
        if include_raw_can and not is_candidate:
            raw_event = {
                "time_s": round(frame.time_rel_s, 6),
                "end_time_s": round(frame.time_rel_s, 6),
                "can_id": f"0x{frame.can_id:03X}",
                "direction": "BROADCAST",
                "target_ecu": "-",
                "service_id": "-",
                "service_name": "Raw CAN Frame",
                "is_implemented": True,
                "is_negative_response": False,
                "is_interrupted": False,
                "is_compliant": True,
                "is_raw_can": True,
                "warnings": [],
                "raw_hex": frame.data.hex().upper(),
                "frame_count": 1,
                "is_multiframe": False,
                "can_frames": [{
                    "ts_s": round(frame.time_rel_s, 6),
                    "can_id": f"0x{frame.can_id:03X}",
                    "data_hex": frame.data.hex().upper(),
                    "pci_type": None,
                }],
                "details": {
                    "dlc": frame.dlc,
                    "info": f"Standard vehicle broadcast frame (ID 0x{frame.can_id:03X})",
                },
            }
            events.append(raw_event)

    for flushed_msg in reassembler.flush_interrupted_sessions():
        events.append(dissector.dissect_message(flushed_msg, parse_cids=parse_cids))

    # Sort all events chronologically by time_s
    events.sort(key=lambda x: x["time_s"])

    # Correlate requests and responses, and compute delta timings
    exchanges: List[Dict[str, Any]] = []
    unanswered_requests: Dict[str, Dict[str, Any]] = {}

    prev_time_s: Optional[float] = None
    prev_req_time_s: Optional[float] = None

    # Track identified canonical services count
    identified_services: Dict[str, Dict[str, Any]] = {}

    for idx, item in enumerate(events):
        item["index"] = idx
        direction = item.get("direction", "BROADCAST")
        service_id_hex = item.get("service_id", "-")
        is_raw_can = item.get("is_raw_can", False)

        # Delta timing to immediate previous message (any frame)
        if prev_time_s is not None:
            item["delta_prev_ms"] = round((item["time_s"] - prev_time_s) * 1000.0, 2)
        else:
            item["delta_prev_ms"] = None
        prev_time_s = item["time_s"]

        if is_raw_can:
            item["exchange_type"] = "broadcast"
            item["req_interval_ms"] = None
            exchanges.append(item)
            continue

        # Count service occurrence in identified_services
        if service_id_hex != "-":
            try:
                sid_num = int(service_id_hex, 16)
                # Map positive responses back to base service ID
                base_sid = (sid_num - 0x40) if (sid_num > 0x40 and sid_num != 0x7F and (sid_num - 0x40) in KWP_SERVICE_NAMES) else sid_num
                base_sid_hex = f"0x{base_sid:02X}"
                if base_sid_hex not in identified_services:
                    identified_services[base_sid_hex] = {
                        "sid_hex": base_sid_hex,
                        "service_name": KWP_SERVICE_NAMES.get(base_sid, f"Service_{base_sid_hex}"),
                        "total_count": 0,
                        "req_count": 0,
                        "resp_count": 0,
                    }
                identified_services[base_sid_hex]["total_count"] += 1
                if direction == "OUTGOING":
                    identified_services[base_sid_hex]["req_count"] += 1
                else:
                    identified_services[base_sid_hex]["resp_count"] += 1
            except (ValueError, TypeError):
                pass

        try:
            sid_int = int(service_id_hex, 16)
        except (ValueError, TypeError):
            sid_int = 0

        if direction == "OUTGOING":
            # Outgoing tester request
            item["exchange_type"] = "request"
            if prev_req_time_s is not None:
                item["req_interval_ms"] = round((item["time_s"] - prev_req_time_s) * 1000.0, 2)
            else:
                item["req_interval_ms"] = None
            prev_req_time_s = item["time_s"]

            exchanges.append(item)
            unanswered_requests[item["target_ecu"]] = item
        else:
            # Incoming ECU response
            item["req_interval_ms"] = None
            matched_req = None
            for ecu_key, req in list(unanswered_requests.items()):
                # If negative response, matches rejected SID
                if item.get("is_negative_response"):
                    rej_sid_hex = item.get("details", {}).get("rejected_service_id")
                    if rej_sid_hex and req["service_id"] == rej_sid_hex:
                        matched_req = req
                        del unanswered_requests[ecu_key]
                        break
                else:
                    # Positive response: response SID is request SID + 0x40
                    try:
                        req_sid_int = int(req["service_id"], 16)
                        if sid_int == (req_sid_int + 0x40):
                            matched_req = req
                            del unanswered_requests[ecu_key]
                            break
                    except (ValueError, TypeError):
                        pass

            if matched_req:
                delta_ms = round((item["time_s"] - matched_req["time_s"]) * 1000.0, 2)
                item["delta_ms"] = delta_ms
                matched_req["response_index"] = idx
                item["request_index"] = matched_req["index"]

            item["exchange_type"] = "response"
            exchanges.append(item)

    # Compile canonical services list for checklist panel
    canonical_services = []
    for sid_val, s_name in sorted(KWP_SERVICE_NAMES.items()):
        if sid_val <= 0x7F:  # Only list base request services + negative response
            sid_hex = f"0x{sid_val:02X}"
            is_active = sid_hex in identified_services
            svc_data = identified_services.get(sid_hex, {})
            canonical_services.append({
                "sid_hex": sid_hex,
                "service_name": s_name,
                "is_active": is_active,
                "total_count": svc_data.get("total_count", 0),
                "req_count": svc_data.get("req_count", 0),
                "resp_count": svc_data.get("resp_count", 0),
            })

    # Diagnostic messages only for statistics
    diag_messages = [m for m in exchanges if not m.get("is_raw_can", False)]

    # Gather statistics
    stats = {
        "total_messages": len(diag_messages),
        "total_events": len(exchanges),
        "raw_can_count": sum(1 for m in exchanges if m.get("is_raw_can", False)),
        "outgoing_count": sum(1 for m in diag_messages if m["direction"] == "OUTGOING"),
        "incoming_count": sum(1 for m in diag_messages if m["direction"] == "INCOMING"),
        "negative_responses": sum(1 for m in diag_messages if m["is_negative_response"]),
        "unimplemented_count": sum(1 for m in diag_messages if not m["is_implemented"]),
        "interrupted_count": sum(1 for m in diag_messages if m.get("is_interrupted", False)),
        "non_compliant_count": sum(1 for m in diag_messages if not m.get("is_compliant", True)),
        "lid_count": len(dissector.active_lids),
        "identified_services_count": len(identified_services),
    }

    # Gather any unknown CIDs discovered in LID definition frames
    unknown_cids: List[Dict[str, Any]] = []
    seen_unknown = set()
    for m in diag_messages:
        for uk in m.get("details", {}).get("unknown_cids", []):
            cid_id = uk["id"]
            if cid_id not in seen_unknown:
                seen_unknown.add(cid_id)
                unknown_cids.append(uk)

    active_lids_summary = {
        f"0x{lid:02X}": {
            "name": lid_def.name,
            "subfunction": lid_def.entries[0].definition_mode if lid_def.entries else 0x02,
            "entries_count": len(lid_def.entries),
            "total_bytes": lid_def.total_bytes,
        }
        for lid, lid_def in dissector.active_lids.items()
    }

    return {
        "filename": log_path.name,
        "format": detect_log_format(log_path),
        "frame_count": len(frames),
        "duration_s": round(frames[-1].time_rel_s, 3) if frames else 0.0,
        "stats": stats,
        "exchanges": exchanges,
        "canonical_services": canonical_services,
        "identified_services": identified_services,
        "active_lids": active_lids_summary,
        "unknown_cids": unknown_cids,
    }


class BmwP2000ViewerHandler(BaseAppHandler):
    """HTTP Request Handler for BMWP2000 Exchange Viewer."""

    def do_GET(self) -> None:
        path, query = self.parse_query()

        if path.startswith("/static/"):
            if self.serve_static(path):
                return
            self.send_error(404, f"Static asset {path} not found")
            return

        if path in ("/", "/index.html"):
            template_path = SCRIPT_DIR / "web" / "templates" / "bmwp2000_viewer.html"
            if template_path.is_file():
                self.send_html(template_path.read_text(encoding="utf-8"))
            else:
                self.send_error(500, "Dashboard template bmwp2000_viewer.html not found")
            return

        if path == "/api/files":
            candidates = find_all_log_files(INITIAL_LOG_FILE)
            files_meta = []
            for p in candidates:
                fmt = detect_log_format(p)
                files_meta.append({
                    "filename": p.name,
                    "path": str(p),
                    "size": p.stat().st_size,
                    "format": fmt,
                })
            self.send_json(files_meta)
            return

        if path == "/api/cids":
            cids = load_cids_dictionary(CIDS_FILE_PATH)
            self.send_json(cids)
            return

        if path == "/api/exchanges":
            target_name = query.get("file", [""])[0]
            parse_cids = query.get("parse_cids", ["true"])[0].lower() != "false"

            target_path = None
            if target_name:
                cand = Path(target_name)
                if cand.is_file():
                    target_path = cand
                else:
                    for p in find_all_log_files(INITIAL_LOG_FILE):
                        if p.name == target_name or str(p) == target_name:
                            target_path = p
                            break

            if not target_path and INITIAL_LOG_FILE and INITIAL_LOG_FILE.is_file():
                target_path = INITIAL_LOG_FILE

            if not target_path:
                candidates = find_all_log_files()
                if candidates:
                    target_path = candidates[0]

            if not target_path or not target_path.is_file():
                self.send_error(404, f"Log file '{target_name}' not found")
                return

            master_cids = load_cids_dictionary(CIDS_FILE_PATH)
            analysis = analyze_log_exchanges(
                target_path,
                parse_cids=parse_cids,
                master_cids=master_cids,
            )
            self.send_json(analysis)
            return

        self.send_error(404, "Endpoint not found")

    def do_POST(self) -> None:
        path, _ = self.parse_query()
        if path == "/api/upload":
            payload = self.read_json_body()
            filename = payload.get("filename", "").strip()
            content_b64 = payload.get("content_base64", "")

            if not filename or not content_b64:
                self.send_error(400, "Missing filename or content_base64 in upload payload")
                return

            import base64
            try:
                file_bytes = base64.b64decode(content_b64)
            except Exception as ex:
                self.send_error(400, f"Failed to decode base64 content: {ex}")
                return

            # Save uploaded log into fixtures directory so it is discoverable
            fixtures_dir = SCRIPT_DIR / "fixtures"
            fixtures_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(filename).name
            target_path = fixtures_dir / safe_name
            target_path.write_bytes(file_bytes)

            fmt = detect_log_format(target_path)
            self.send_json({
                "status": "success",
                "filename": safe_name,
                "path": str(target_path),
                "size": len(file_bytes),
                "format": fmt,
            })
            return

        if path == "/api/add_cid":
            payload = self.read_json_body()
            if payload is None:
                self.send_error(400, "Invalid or missing JSON payload")
                return

            cid_name = str(payload.get("name", "")).strip()
            raw_id = str(payload.get("id", "")).strip()
            mem_size = payload.get("memory_size", 1)
            position = payload.get("position", 1)
            unit = str(payload.get("unit", "")).strip()
            description = str(payload.get("description", "")).strip()
            is_signed = bool(payload.get("signed", False))

            try:
                mul = float(payload.get("mul", 1.0))
                if mul.is_integer():
                    mul = int(mul)
            except (ValueError, TypeError):
                mul = 1

            try:
                div = float(payload.get("div", 1.0))
                if abs(div) < 1e-12:
                    div = 1.0
                elif div.is_integer():
                    div = int(div)
            except (ValueError, TypeError):
                div = 1

            try:
                add = float(payload.get("add", 0.0))
                if add.is_integer():
                    add = int(add)
            except (ValueError, TypeError):
                add = 0

            if not cid_name:
                self.send_error(400, "Missing CID name")
                return

            if not re.match(r"^0[xX][0-9a-fA-F]{2,6}$", raw_id):
                self.send_error(400, f"Invalid hex ID format: '{raw_id}' (expected 0xXXXX)")
                return

            # Canonicalize hex string as '0xXXXX' with uppercase hex digits
            hex_digits = raw_id[2:].upper()
            cid_hex = f"0x{hex_digits}"

            # Read current cids
            current_cids = load_cids_dictionary(CIDS_FILE_PATH)

            # Ensure unique key name by suffixing an incrementing counter if needed
            unique_name = cid_name
            if unique_name in current_cids:
                counter = 1
                match = re.match(r"^(.*?)(?:_(\d+))?$", cid_name)
                root = match.group(1) if match else cid_name
                while f"{root}_{counter}" in current_cids:
                    counter += 1
                unique_name = f"{root}_{counter}"

            # Create backup before mutation
            backup_created = create_backup(CIDS_FILE_PATH)

            cid_entry: Dict[str, Any] = {
                "id": cid_hex,
                "memory_size": int(mem_size),
                "position": int(position),
                "signed": is_signed,
                "mul": mul,
                "div": div,
                "add": add,
                "unit": unit,
            }
            if description:
                cid_entry["description"] = description

            current_cids[unique_name] = cid_entry

            CIDS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CIDS_FILE_PATH.write_text(json.dumps(current_cids, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            self.send_json({
                "status": "success",
                "name": unique_name,
                "original_name": cid_name,
                "renamed": (unique_name != cid_name),
                "message": f"CID '{unique_name}' ({cid_hex}) added successfully" + (f" (suffixed from '{cid_name}')" if unique_name != cid_name else ""),
                "backup": str(backup_created) if backup_created else None,
            })
            return

        self.send_error(404, "Endpoint not found")


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses command line arguments for BMWP2000 Exchange Viewer."""
    parser = argparse.ArgumentParser(
        description="MiniGauge BMWP2000 Exchange Viewer & Protocol Inspector"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8096,
        help="TCP port to run the web server on (default: 8096)",
    )
    parser.add_argument(
        "--log",
        type=str,
        default=None,
        help="Path to initial CAN log file (.bin, candump .log, or Vector .asc)",
    )
    parser.add_argument(
        "--cids",
        type=str,
        default=str(DEFAULT_CIDS_PATH),
        help=f"Path to master cids.json file (default: {DEFAULT_CIDS_PATH})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically launch system browser",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser.parse_args(argv)


def main() -> None:
    global CIDS_FILE_PATH, INITIAL_LOG_FILE

    args = parse_arguments(sys.argv[1:])

    CIDS_FILE_PATH = Path(args.cids).resolve()
    if args.log:
        p = Path(args.log).resolve()
        if p.is_file():
            INITIAL_LOG_FILE = p

    start_server(
        BmwP2000ViewerHandler,
        port=args.port,
        open_browser=not args.no_browser,
        server_name="BMWP2000 Exchange Viewer",
    )


if __name__ == "__main__":
    main()
