"""BMW KWP2000 & ISO-TP Protocol Engine.

Implements:
- ISO 15765-2 (ISO-TP) multi-frame reassembly (SF, FF, CF, FC)
- ISO 14230-3 (KWP2000) service dissection and request/response correlation
- Dynamically Defined Local Identifier (DDLI, Service 0x2C) tracking
- ReadDataByLocalIdentifier (Service 0x21) and periodic broadcast unpacking
- Negative Response Code (NRC, Service 0x7F) decoding
- Unimplemented / unknown service flagging
- DID parameter scaling with engineering units

Zero pip dependencies (Python 3 stdlib only).
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import struct
from typing import Any, Dict, List, Optional, Tuple

from .can_core import CanFrame

# Canonical KWP2000 Service IDs
SID_START_DIAGNOSTIC_SESSION = 0x10
SID_READ_ECU_IDENTIFICATION = 0x1A
SID_READ_DATA_BY_LOCAL_ID = 0x21
SID_READ_DATA_BY_COMMON_ID = 0x22
SID_READ_MEMORY_BY_ADDRESS = 0x23
SID_DYNAMICALLY_DEFINE_LOCAL_ID = 0x2C
SID_WRITE_DATA_BY_LOCAL_ID = 0x3B
SID_TESTER_PRESENT = 0x3E
SID_NEGATIVE_RESPONSE = 0x7F

KWP_SERVICE_NAMES: Dict[int, str] = {
    0x10: "startDiagnosticSession",
    0x11: "ecuReset",
    0x12: "readFreezeFrameData",
    0x14: "clearDiagnosticInformation",
    0x17: "readStatusOfDiagnosticTroubleCodes",
    0x18: "readDiagnosticTroubleCodesByStatus",
    0x1A: "readECUIdentification",
    0x21: "readDataByLocalIdentifier",
    0x22: "readDataByCommonIdentifier",
    0x23: "readMemoryByAddress",
    0x27: "securityAccess",
    0x28: "disableNormalMessageTransmission",
    0x29: "enableNormalMessageTransmission",
    0x2C: "dynamicallyDefineLocalIdentifier",
    0x30: "inputOutputControlByLocalIdentifier",
    0x31: "startRoutineByLocalIdentifier",
    0x32: "stopRoutineByLocalIdentifier",
    0x33: "requestRoutineResultsByLocalIdentifier",
    0x34: "requestDownload",
    0x35: "requestUpload",
    0x36: "transferData",
    0x37: "requestTransferExit",
    0x38: "startRoutineByAddress",
    0x39: "stopRoutineByAddress",
    0x3A: "requestRoutineResultsByAddress",
    0x3B: "writeDataByLocalIdentifier",
    0x3D: "writeMemoryByAddress",
    0x3E: "testerPresent",
    0x7F: "negativeResponse",
}

# Positive response offsets (+0x40)
for req_sid, name in list(KWP_SERVICE_NAMES.items()):
    if req_sid != 0x7F:
        KWP_SERVICE_NAMES[req_sid + 0x40] = f"{name}PositiveResponse"

# Standard KWP2000 Negative Response Codes (NRC)
KWP_NRC_NAMES: Dict[int, str] = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported-invalidFormat",
    0x21: "busy-repeatRequest",
    0x22: "conditionsNotCorrectOrRequestSequenceError",
    0x23: "routineNotCompleteOrServiceInProgress",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied-securityAccessRequested",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x40: "downloadNotAccepted",
    0x41: "improperDownloadType",
    0x42: "cantDownloadToSpecifiedAddress",
    0x43: "cantDownloadNumberOfBytesRequested",
    0x50: "uploadNotAccepted",
    0x51: "improperUploadType",
    0x52: "cantUploadFromSpecifiedAddress",
    0x53: "cantUploadNumberOfBytesRequested",
    0x71: "transferSuspended",
    0x72: "generalProgrammingFailure",
    0x78: "responsePending",
    0x80: "subFunctionNotSupportedInActiveDiagnosticSession",
}

# Services natively decoded and interpreted by MiniGauge BMWP2000
IMPLEMENTED_SERVICES = {
    0x10, 0x50,
    0x1A, 0x5A,
    0x21, 0x61,
    0x2C, 0x6C,
    0x3E, 0x7E,
    0x7F,
}


@dataclass
class IsoTpMessage:
    """Reassembled ISO 15765-2 diagnostic message."""
    start_time_s: float
    end_time_s: float
    can_id: int
    direction: str       # 'OUTGOING' (Tester -> ECU) or 'INCOMING' (ECU -> Tester)
    target_ecu: int      # ECU address byte (e.g. 0x12 for DME, 0xF1 for tester)
    raw_payload: bytes   # Reassembled diagnostic service bytes
    frame_count: int     # Number of CAN frames used
    is_multiframe: bool  # True if reassembled via FF + CFs
    can_frames: List[Dict[str, Any]] = field(default_factory=list)
    is_interrupted: bool = False
    is_compliant: bool = True
    warnings: List[str] = field(default_factory=list)


@dataclass
class DdliEntry:
    """Component definition inside a Dynamically Defined Local Identifier."""
    did_hex: str
    did_name: str
    position: int
    memory_size: int
    address: Optional[int] = None


@dataclass
class DdliDefinition:
    """Structure of a Dynamically Defined Local Identifier (0xF0..0xFF)."""
    local_id: int
    name: str
    subfunction: int     # 0x01 = byIdentifier, 0x02 = byAddress/Combo, 0x03 = clear, 0x04 = broadcast
    entries: List[DdliEntry] = field(default_factory=list)
    total_bytes: int = 0


class IsoTpReassembler:
    """Reassembles CAN frames into ISO-TP N-SDU diagnostic packets with compliance verification."""

    def __init__(
        self,
        tester_id: int = 0x6F1,
        ecu_id_min: int = 0x600,
        ecu_id_max: int = 0x61F,
        session_timeout_s: float = 1.0,
    ):
        self.tester_id = tester_id
        self.ecu_id_min = ecu_id_min
        self.ecu_id_max = ecu_id_max
        self.session_timeout_s = session_timeout_s
        # Active reassembly state indexed by CAN ID
        self.active_sessions: Dict[int, Dict[str, Any]] = {}

    def is_iso_tp_candidate(self, can_id: int) -> bool:
        return can_id == self.tester_id or (self.ecu_id_min <= can_id <= self.ecu_id_max)

    def process_frame(self, frame: CanFrame) -> Optional[IsoTpMessage]:
        """Processes a CAN frame, returning a completed IsoTpMessage or None."""
        interrupted_msg, completed_msg = self.process_frame_events(frame)
        return completed_msg or interrupted_msg

    def process_frame_events(self, frame: CanFrame) -> Tuple[Optional[IsoTpMessage], Optional[IsoTpMessage]]:
        """Processes a CAN frame. Returns a tuple (interrupted_msg_if_any, completed_msg_if_any)."""
        can_id = frame.can_id
        if not self.is_iso_tp_candidate(can_id):
            return None, None

        data = frame.data
        if len(data) < 2:
            # Non-compliant ISO-TP frame length
            return None, None

        target_addr = data[0]
        pci_byte = data[1]
        pci_type = (pci_byte >> 4) & 0x0F

        direction = "OUTGOING" if can_id == self.tester_id else "INCOMING"
        frame_record = {
            "ts_s": round(frame.time_rel_s, 6),
            "can_id": f"0x{can_id:03X}",
            "data_hex": data.hex().upper(),
            "pci_type": pci_type,
        }

        interrupted_msg: Optional[IsoTpMessage] = None

        # Check for session timeout on existing session for this CAN ID
        if can_id in self.active_sessions:
            sess = self.active_sessions[can_id]
            if (frame.time_rel_s - sess["last_time_s"]) > self.session_timeout_s:
                interrupted_msg = self._abort_session(can_id, f"Session timed out after {frame.time_rel_s - sess['last_time_s']:.3f}s")

        # 0: Single Frame (SF)
        if pci_type == 0x0:
            if can_id in self.active_sessions and not interrupted_msg:
                interrupted_msg = self._abort_session(can_id, "Interrupted by new Single Frame before completion")

            length = pci_byte & 0x0F
            warnings = []
            is_compliant = True

            if length == 0:
                is_compliant = False
                warnings.append("SF with invalid DLC length 0")
                return interrupted_msg, None

            if len(data) < 2 + length:
                is_compliant = False
                warnings.append(f"SF truncated: header claims {length} bytes but frame has {len(data) - 2} bytes")
                payload = data[2:]
            else:
                payload = data[2: 2 + length]

            if len(data) < 8:
                warnings.append(f"SF frame not padded to 8 bytes (length={len(data)})")

            msg = IsoTpMessage(
                start_time_s=frame.time_rel_s,
                end_time_s=frame.time_rel_s,
                can_id=can_id,
                direction=direction,
                target_ecu=target_addr,
                raw_payload=payload,
                frame_count=1,
                is_multiframe=False,
                can_frames=[frame_record],
                is_interrupted=not is_compliant,
                is_compliant=is_compliant,
                warnings=warnings,
            )
            return interrupted_msg, msg

        # 1: First Frame (FF)
        elif pci_type == 0x1:
            if can_id in self.active_sessions and not interrupted_msg:
                interrupted_msg = self._abort_session(can_id, "Interrupted by new First Frame before completion")

            if len(data) < 3:
                return interrupted_msg, None

            total_length = ((pci_byte & 0x0F) << 8) | data[2]
            initial_payload = data[3:]
            warnings = []
            is_compliant = True

            if total_length < 8:
                is_compliant = False
                warnings.append(f"FF total_length {total_length} < 8 (should be SF)")

            self.active_sessions[can_id] = {
                "start_time_s": frame.time_rel_s,
                "last_time_s": frame.time_rel_s,
                "target_ecu": target_addr,
                "total_length": total_length,
                "expected_sn": 1,
                "direction": direction,
                "accumulated": bytearray(initial_payload),
                "frames": [frame_record],
                "warnings": warnings,
                "is_compliant": is_compliant,
            }
            return interrupted_msg, None

        # 2: Consecutive Frame (CF)
        elif pci_type == 0x2:
            if can_id not in self.active_sessions:
                # Orphaned CF without preceding FF
                orphan_msg = IsoTpMessage(
                    start_time_s=frame.time_rel_s,
                    end_time_s=frame.time_rel_s,
                    can_id=can_id,
                    direction=direction,
                    target_ecu=target_addr,
                    raw_payload=data[2:],
                    frame_count=1,
                    is_multiframe=True,
                    can_frames=[frame_record],
                    is_interrupted=True,
                    is_compliant=False,
                    warnings=[f"Orphaned Consecutive Frame (SN={pci_byte & 0x0F}) without preceding First Frame"],
                )
                return interrupted_msg, orphan_msg

            session = self.active_sessions[can_id]
            session["last_time_s"] = frame.time_rel_s
            sn = pci_byte & 0x0F
            cf_payload = data[2:]
            session["frames"].append(frame_record)

            if sn != session["expected_sn"]:
                session["is_compliant"] = False
                session["warnings"].append(f"CF sequence number mismatch: expected {session['expected_sn']}, got {sn}")

            session["accumulated"].extend(cf_payload)
            session["expected_sn"] = (sn + 1) & 0x0F

            if len(session["accumulated"]) >= session["total_length"]:
                complete_payload = bytes(session["accumulated"][: session["total_length"]])
                msg = IsoTpMessage(
                    start_time_s=session["start_time_s"],
                    end_time_s=frame.time_rel_s,
                    can_id=can_id,
                    direction=session["direction"],
                    target_ecu=session["target_ecu"],
                    raw_payload=complete_payload,
                    frame_count=len(session["frames"]),
                    is_multiframe=True,
                    can_frames=session["frames"],
                    is_interrupted=not session["is_compliant"],
                    is_compliant=session["is_compliant"],
                    warnings=session["warnings"],
                )
                del self.active_sessions[can_id]
                return interrupted_msg, msg

            return interrupted_msg, None

        # 3: Flow Control (FC)
        elif pci_type == 0x3:
            # Flow control frame: note in active session if present
            if can_id in self.active_sessions:
                self.active_sessions[can_id]["frames"].append(frame_record)
            return interrupted_msg, None

        return interrupted_msg, None

    def _abort_session(self, can_id: int, reason: str) -> IsoTpMessage:
        """Aborts an in-flight session and returns it as an interrupted message."""
        session = self.active_sessions.pop(can_id)
        accumulated = bytes(session["accumulated"])
        warnings = list(session.get("warnings", []))
        warnings.append(f"Interrupted: {reason} (received {len(accumulated)}/{session['total_length']} bytes)")
        return IsoTpMessage(
            start_time_s=session["start_time_s"],
            end_time_s=session.get("last_time_s", session["start_time_s"]),
            can_id=can_id,
            direction=session["direction"],
            target_ecu=session["target_ecu"],
            raw_payload=accumulated,
            frame_count=len(session["frames"]),
            is_multiframe=True,
            can_frames=session["frames"],
            is_interrupted=True,
            is_compliant=False,
            warnings=warnings,
        )

    def flush_interrupted_sessions(self) -> List[IsoTpMessage]:
        """Flushes any remaining incomplete sessions at the end of stream analysis."""
        interrupted = []
        for can_id in list(self.active_sessions.keys()):
            interrupted.append(self._abort_session(can_id, "End of log reached with incomplete multi-frame payload"))
        return interrupted


class BmwP2000Dissector:
    """High-level KWP2000 protocol exchange dissector and DDLI/DID interpreter."""

    def __init__(self, master_dids: Optional[Dict[str, Any]] = None):
        self.master_dids = master_dids or {}
        # Invert master dids mapping hex id -> key
        self.did_hex_map: Dict[str, str] = {}
        for key, val in self.master_dids.items():
            if key == "_schema_guide":
                continue
            raw_id = str(val.get("id", "")).strip()
            if raw_id:
                # Normalize to 0xXXXX (uppercase hex digits)
                try:
                    num_val = int(raw_id, 16)
                    norm_hex = f"0x{num_val:04X}"
                    self.did_hex_map[norm_hex] = key
                    self.did_hex_map[f"0x{num_val:X}"] = key
                except ValueError:
                    self.did_hex_map[raw_id.lower()] = key

        # Dynamic DDLI registry keyed by Local ID (e.g. 0xF0)
        self.active_ddlis: Dict[int, DdliDefinition] = {}

    def reload_dids(self, master_dids: Dict[str, Any]) -> None:
        self.master_dids = master_dids
        self.did_hex_map.clear()
        for key, val in self.master_dids.items():
            if key == "_schema_guide":
                continue
            raw_id = str(val.get("id", "")).strip()
            if raw_id:
                try:
                    num_val = int(raw_id, 16)
                    norm_hex = f"0x{num_val:04X}"
                    self.did_hex_map[norm_hex] = key
                    self.did_hex_map[f"0x{num_val:X}"] = key
                except ValueError:
                    self.did_hex_map[raw_id.lower()] = key

    def dissect_message(
        self,
        msg: IsoTpMessage,
        parse_dids: bool = True
    ) -> Dict[str, Any]:
        """Dissects an ISO-TP reassembled message into structured KWP2000 fields."""
        payload = msg.raw_payload
        if not payload:
            return {
                "service_id": 0,
                "service_name": "EmptyPayload",
                "is_implemented": False,
                "is_negative_response": False,
                "raw_hex": "",
            }

        sid = payload[0]
        service_name = KWP_SERVICE_NAMES.get(sid, f"Service_0x{sid:02X}")
        is_implemented = sid in IMPLEMENTED_SERVICES
        is_negative = (sid == SID_NEGATIVE_RESPONSE)

        result: Dict[str, Any] = {
            "time_s": round(msg.start_time_s, 6),
            "end_time_s": round(msg.end_time_s, 6),
            "can_id": f"0x{msg.can_id:03X}",
            "direction": msg.direction,
            "target_ecu": f"0x{msg.target_ecu:02X}",
            "service_id": f"0x{sid:02X}",
            "service_name": service_name,
            "is_implemented": is_implemented,
            "is_negative_response": is_negative,
            "is_interrupted": getattr(msg, "is_interrupted", False),
            "is_compliant": getattr(msg, "is_compliant", True),
            "warnings": list(getattr(msg, "warnings", [])),
            "raw_hex": payload.hex().upper(),
            "frame_count": msg.frame_count,
            "is_multiframe": msg.is_multiframe,
            "can_frames": msg.can_frames,
            "details": {},
        }

        # 1. Negative Response (0x7F)
        if is_negative and len(payload) >= 3:
            rejected_sid = payload[1]
            nrc = payload[2]
            rej_name = KWP_SERVICE_NAMES.get(rejected_sid, f"0x{rejected_sid:02X}")
            nrc_name = KWP_NRC_NAMES.get(nrc, f"NRC_0x{nrc:02X}")
            result["details"] = {
                "rejected_service_id": f"0x{rejected_sid:02X}",
                "rejected_service_name": rej_name,
                "nrc": f"0x{nrc:02X}",
                "nrc_name": nrc_name,
                "human_description": f"ECU rejected {rej_name} with error {nrc_name} (0x{nrc:02X})",
            }
            return result

        # 2. DynamicallyDefineLocalIdentifier (0x2C Request / 0x6C Response)
        if sid in (SID_DYNAMICALLY_DEFINE_LOCAL_ID, SID_DYNAMICALLY_DEFINE_LOCAL_ID + 0x40):
            if sid == SID_DYNAMICALLY_DEFINE_LOCAL_ID and len(payload) >= 2:
                local_id = payload[1]
                subfunc = payload[2] if len(payload) > 2 else 0x01
                subfunc_names = {
                    0x01: "defineByIdentifier",
                    0x02: "defineByAddress",
                    0x03: "clearDynamicallyDefinedLocalIdentifier",
                    0x04: "broadcastTransmission",
                }
                subfunc_name = subfunc_names.get(subfunc, f"Subfunction_0x{subfunc:02X}")

                entries: List[Dict[str, Any]] = []
                discovered_unknown_dids: List[Dict[str, Any]] = []
                pos = 3
                total_bytes = 0

                # In BMW KWP2000, subfunction 0x01 and 0x02 both encode sequences of entries:
                # 0x01 / 0x02: [localId, subFunc, id_hi, id_lo, elem_pos, elem_size, ...]
                # or [localId, subFunc, addr_hi, addr_lo, elem_pos, elem_size, ...]
                if subfunc in (0x01, 0x02):
                    while pos + 3 < len(payload):
                        did_val = (payload[pos] << 8) | payload[pos + 1]
                        did_hex = f"0x{did_val:04X}"
                        elem_pos = payload[pos + 2]
                        elem_size = payload[pos + 3]
                        pos += 4

                        # Check known DIDs in master dictionary
                        known_name = self.did_hex_map.get(did_hex)
                        if not known_name:
                            known_name = self.did_hex_map.get(f"0x{did_val:X}")

                        if known_name:
                            did_name = known_name
                            is_known = True
                        else:
                            did_name = f"UNKNOWN_{did_hex}"
                            is_known = False
                            discovered_unknown_dids.append({
                                "id": did_hex,
                                "name": f"DID_{did_hex}",
                                "position": elem_pos,
                                "memory_size": elem_size,
                            })

                        entries.append({
                            "did_hex": did_hex,
                            "did_name": did_name,
                            "position": elem_pos,
                            "memory_size": elem_size,
                            "is_known": is_known,
                        })
                        total_bytes += elem_size

                    if entries:
                        # Dynamically register DDLI definition
                        ddli_def = DdliDefinition(
                            local_id=local_id,
                            name=f"DDLI_0x{local_id:02X}",
                            subfunction=subfunc,
                            entries=[
                                DdliEntry(
                                    did_hex=e["did_hex"],
                                    did_name=e["did_name"],
                                    position=e["position"],
                                    memory_size=e["memory_size"],
                                )
                                for e in entries
                            ],
                            total_bytes=total_bytes,
                        )
                        self.active_ddlis[local_id] = ddli_def

                elif subfunc == 0x03:
                    # Clear DDLI
                    self.active_ddlis.pop(local_id, None)

                result["details"] = {
                    "local_id": f"0x{local_id:02X}",
                    "subfunction": f"0x{subfunc:02X}",
                    "subfunction_name": subfunc_name,
                    "entries": entries,
                    "total_bytes": total_bytes,
                    "unknown_dids": discovered_unknown_dids,
                }
            elif sid == (SID_DYNAMICALLY_DEFINE_LOCAL_ID + 0x40):
                local_id = payload[1] if len(payload) > 1 else 0
                result["details"] = {
                    "local_id": f"0x{local_id:02X}",
                    "status": "DDLI configuration accepted by ECU",
                }
            return result

        # 3. ReadDataByLocalIdentifier (0x21 Request / 0x61 Response)
        if sid in (SID_READ_DATA_BY_LOCAL_ID, SID_READ_DATA_BY_LOCAL_ID + 0x40):
            if len(payload) >= 2:
                local_id = payload[1]
                result["details"]["local_id"] = f"0x{local_id:02X}"
                result["details"]["recordLocalIdentifier"] = f"0x{local_id:02X}"

                # Request parameter decryption (transmissionMode / polling rate)
                if sid == SID_READ_DATA_BY_LOCAL_ID:
                    transmission_mode = payload[2] if len(payload) > 2 else 0x01
                    mode_map = {
                        0x00: ("stopTransmission", "Stop Transmission / Halt Polling"),
                        0x01: ("sendOneResponse", "Single Response (Single Query)"),
                        0x02: ("slowRate", "Slow Rate Polling (~1-2 Hz)"),
                        0x03: ("mediumRate", "Medium Rate Polling (~5-10 Hz)"),
                        0x04: ("fastRate", "Fast Rate Polling (~20-50 Hz)"),
                    }
                    mode_info = mode_map.get(transmission_mode, ("customMode", f"Custom Mode 0x{transmission_mode:02X}"))
                    result["details"]["transmissionMode"] = f"0x{transmission_mode:02X}"
                    result["details"]["transmission_mode"] = f"0x{transmission_mode:02X}"
                    result["details"]["transmission_mode_name"] = mode_info[0]
                    result["details"]["transmission_mode_desc"] = mode_info[1]

                # Response payload unpacking
                if sid == (SID_READ_DATA_BY_LOCAL_ID + 0x40):
                    data_bytes = payload[2:]
                    result["details"]["data_length"] = len(data_bytes)
                    result["details"]["data_hex"] = data_bytes.hex().upper()

                    if parse_dids and local_id in self.active_ddlis:
                        parsed_signals = self.unpack_ddli_payload(self.active_ddlis[local_id], data_bytes)
                        result["details"]["signals"] = parsed_signals
                    elif parse_dids:
                        result["details"]["signals_status"] = f"No active DDLI definition found for 0x{local_id:02X}"
            return result

        # 4. TesterPresent (0x3E / 0x7E)
        if sid in (SID_TESTER_PRESENT, SID_TESTER_PRESENT + 0x40):
            subfunction = payload[1] if len(payload) > 1 else 0x01
            resp_req = "responseRequired" if subfunction == 0x01 else "suppressResponse"
            result["details"]["subFunction"] = f"0x{subfunction:02X} ({resp_req})"
            result["details"]["status"] = "Heartbeat / Keep-Alive"
            return result

        # 5. StartDiagnosticSession (0x10 / 0x50)
        if sid in (SID_START_DIAGNOSTIC_SESSION, SID_START_DIAGNOSTIC_SESSION + 0x40):
            session_type = payload[1] if len(payload) > 1 else 0
            session_map = {
                0x01: "standardDiagnosticSession",
                0x02: "ecuProgrammingSession",
                0x03: "ecuDevelopmentSession",
                0x86: "bmwSpecialDiagnosticSession",
            }
            session_name = session_map.get(session_type, f"Session_0x{session_type:02X}")
            result["details"]["diagnosticSessionType"] = f"0x{session_type:02X}"
            result["details"]["diagnosticSessionName"] = session_name
            result["details"]["session_type"] = f"0x{session_type:02X} ({session_name})"
            return result

        # 6. ReadECUIdentification (0x1A / 0x5A)
        if sid in (SID_READ_ECU_IDENTIFICATION, SID_READ_ECU_IDENTIFICATION + 0x40):
            ident_opt = payload[1] if len(payload) > 1 else 0
            ident_map = {
                0x80: "basicEcuInformation",
                0x86: "bmwDiagnosticCodingData",
                0x90: "vehicleIdentificationNumber (VIN)",
                0x9E: "softwareVersionIdentifier",
            }
            ident_name = ident_map.get(ident_opt, f"Option_0x{ident_opt:02X}")
            result["details"]["identificationOption"] = f"0x{ident_opt:02X}"
            result["details"]["identificationOptionName"] = ident_name
            result["details"]["ident_option"] = f"0x{ident_opt:02X} ({ident_name})"
            if sid == (SID_READ_ECU_IDENTIFICATION + 0x40):
                result["details"]["ident_data"] = payload[2:].hex().upper()
            return result

        # 7. Fallback / Unimplemented command
        result["details"]["info"] = "Unimplemented or proprietary diagnostic service"
        result["details"]["payload_hex"] = payload[1:].hex().upper() if len(payload) > 1 else ""
        return result

    def unpack_ddli_payload(self, ddli: DdliDefinition, data_bytes: bytes) -> List[Dict[str, Any]]:
        """Unpacks raw DDLI response bytes into constituent DIDs with scaled or raw values."""
        signals: List[Dict[str, Any]] = []
        cursor = 0

        for entry in ddli.entries:
            size = entry.memory_size
            if cursor + size > len(data_bytes):
                # Frame data ended prematurely
                remaining_slice = data_bytes[cursor:]
                if remaining_slice:
                    signals.append({
                        "did_name": entry.did_name,
                        "did_hex": entry.did_hex,
                        "raw_int": int.from_bytes(remaining_slice, byteorder="big"),
                        "raw_hex": remaining_slice.hex().upper(),
                        "scaled_value": int.from_bytes(remaining_slice, byteorder="big"),
                        "unit": "",
                        "formula": "truncated",
                        "is_truncated": True,
                    })
                break

            slice_bytes = data_bytes[cursor: cursor + size]
            cursor += size

            # Unpack raw integer
            if size == 1:
                raw_int = slice_bytes[0]
            elif size == 2:
                raw_int = struct.unpack(">H", slice_bytes)[0]
            elif size == 4:
                raw_int = struct.unpack(">I", slice_bytes)[0]
            else:
                raw_int = int.from_bytes(slice_bytes, byteorder="big")

            did_meta = self.master_dids.get(entry.did_name, {})
            if not did_meta:
                # Also lookup by hex ID if did_name was generated as DID_0xXXXX
                did_meta = self.master_dids.get(entry.did_hex, {})

            mul = did_meta.get("mul", 1)
            div = did_meta.get("div", 1) or 1
            add = did_meta.get("add", 0)
            unit = did_meta.get("unit", "")

            # Apply formula if metadata exists, otherwise display raw integer
            if did_meta:
                scaled_val = round(((raw_int * mul) / div) + add, 3)
                formula_str = f"(({raw_int} * {mul}) / {div}) + {add}" if (mul != 1 or div != 1 or add != 0) else "raw"
            else:
                scaled_val = raw_int
                formula_str = "raw (unregistered in dids.json)"

            signals.append({
                "did_name": entry.did_name,
                "did_hex": entry.did_hex,
                "raw_int": raw_int,
                "raw_hex": slice_bytes.hex().upper(),
                "scaled_value": scaled_val,
                "unit": unit,
                "formula": formula_str,
                "is_truncated": False,
            })

        return signals
