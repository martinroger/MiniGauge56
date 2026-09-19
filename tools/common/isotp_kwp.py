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

# Canonical KWP2000 Service IDs (ISO 14230-3 Table 4.3)
SID_START_DIAGNOSTIC_SESSION = 0x10
SID_ECU_RESET = 0x11
SID_READ_FREEZE_FRAME_DATA = 0x12
SID_READ_DIAGNOSTIC_TROUBLE_CODES = 0x13
SID_CLEAR_DIAGNOSTIC_INFORMATION = 0x14
SID_READ_STATUS_OF_DTC = 0x17
SID_READ_DTC_BY_STATUS = 0x18
SID_READ_ECU_IDENTIFICATION = 0x1A
SID_STOP_DIAGNOSTIC_SESSION = 0x20
SID_READ_DATA_BY_LOCAL_ID = 0x21
SID_READ_DATA_BY_COMMON_ID = 0x22
SID_READ_MEMORY_BY_ADDRESS = 0x23
SID_SET_DATA_RATES = 0x26
SID_SECURITY_ACCESS = 0x27
SID_DYNAMICALLY_DEFINE_LOCAL_ID = 0x2C
SID_WRITE_DATA_BY_COMMON_ID = 0x2E
SID_INPUT_OUTPUT_CONTROL_BY_COMMON_ID = 0x2F
SID_INPUT_OUTPUT_CONTROL_BY_LOCAL_ID = 0x30
SID_START_ROUTINE_BY_LOCAL_ID = 0x31
SID_STOP_ROUTINE_BY_LOCAL_ID = 0x32
SID_REQUEST_ROUTINE_RESULTS_BY_LOCAL_ID = 0x33
SID_REQUEST_DOWNLOAD = 0x34
SID_REQUEST_UPLOAD = 0x35
SID_TRANSFER_DATA = 0x36
SID_REQUEST_TRANSFER_EXIT = 0x37
SID_START_ROUTINE_BY_ADDRESS = 0x38
SID_STOP_ROUTINE_BY_ADDRESS = 0x39
SID_REQUEST_ROUTINE_RESULTS_BY_ADDRESS = 0x3A
SID_WRITE_DATA_BY_LOCAL_ID = 0x3B
SID_WRITE_MEMORY_BY_ADDRESS = 0x3D
SID_TESTER_PRESENT = 0x3E
SID_ESCAPE_CODE = 0x80
SID_NEGATIVE_RESPONSE = 0x7F

KWP_SERVICE_NAMES: Dict[int, str] = {
    0x10: "startDiagnosticSession",
    0x11: "ecuReset",
    0x12: "readFreezeFrameData",
    0x13: "readDiagnosticTroubleCodes",
    0x14: "clearDiagnosticInformation",
    0x17: "readStatusOfDiagnosticTroubleCodes",
    0x18: "readDiagnosticTroubleCodesByStatus",
    0x1A: "readECUIdentification",
    0x20: "stopDiagnosticSession",
    0x21: "readDataByLocalIdentifier",
    0x22: "readDataByCommonIdentifier",
    0x23: "readMemoryByAddress",
    0x26: "setDataRates",
    0x27: "securityAccess",
    0x28: "disableNormalMessageTransmission",
    0x29: "enableNormalMessageTransmission",
    0x2C: "dynamicallyDefineLocalIdentifier",
    0x2E: "writeDataByCommonIdentifier",
    0x2F: "inputOutputControlByCommonIdentifier",
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
    0x80: "escapeCode",
    0x7F: "negativeResponse",
}

# Positive response offsets (+0x40)
for req_sid, name in list(KWP_SERVICE_NAMES.items()):
    if req_sid not in (0x7F, 0x80):
        KWP_SERVICE_NAMES[req_sid + 0x40] = f"{name}PositiveResponse"
KWP_SERVICE_NAMES[0xC0] = "escapeCodePositiveResponse"

# Standard KWP2000 Negative Response Codes (NRC) (ISO 14230-3 Table 4.4)
KWP_NRC_NAMES: Dict[int, str] = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported-invalidFormat",
    0x21: "busy-RepeatRequest",
    0x22: "conditionsNotCorrect or requestSequenceError",
    0x23: "routineNotComplete",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x40: "downloadNotAccepted",
    0x41: "improperDownloadType",
    0x42: "can'tDownloadToSpecifiedAddress",
    0x43: "can'tDownloadNumberOfBytesRequested",
    0x50: "uploadNotAccepted",
    0x51: "improperUploadType",
    0x52: "can'tUploadFromSpecifiedAddress",
    0x53: "can'tUploadNumberOfBytesRequested",
    0x71: "transferSuspended",
    0x72: "transferAborted",
    0x74: "illegalAddressInBlockTransfer",
    0x75: "illegalByteCountInBlockTransfer",
    0x76: "illegalBlockTransferType",
    0x77: "blockTransferDataChecksumError",
    0x78: "reqCorrectlyRcvd-RspPending (requestCorrectlyReceived-ResponsePending)",
    0x79: "incorrectByteCountDuringBlockTransfer",
}

# All standardized KWP2000 services supported by the dissector (ISO 14230-3 Table 4.3)
IMPLEMENTED_SERVICES = {
    0x10, 0x50,
    0x11, 0x51,
    0x12, 0x52,
    0x13, 0x53,
    0x14, 0x54,
    0x17, 0x57,
    0x18, 0x58,
    0x1A, 0x5A,
    0x20, 0x60,
    0x21, 0x61,
    0x22, 0x62,
    0x23, 0x63,
    0x26, 0x66,
    0x27, 0x67,
    0x2C, 0x6C,
    0x2E, 0x6E,
    0x2F, 0x6F,
    0x30, 0x70,
    0x31, 0x71,
    0x32, 0x72,
    0x33, 0x73,
    0x34, 0x74,
    0x35, 0x75,
    0x36, 0x76,
    0x37, 0x77,
    0x38, 0x78,
    0x39, 0x79,
    0x3A, 0x7A,
    0x3B, 0x7B,
    0x3D, 0x7D,
    0x3E, 0x7E,
    0x7F,
    0x80, 0xC0,
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
class LidEntry:
    """Component definition inside a Dynamically Defined Local Identifier (ISO 14230-3 Section 7.4)."""
    definition_mode: int       # 0x01=byLocalId, 0x02=byCommonId, 0x03=byMemoryAddress
    definition_mode_name: str  # 'defineByCommonIdentifier', etc.
    pos_in_lid: int            # Position in destination LID record (1-indexed)
    memory_size: int           # Number of data bytes
    cid_hex: str               # Hex string of CID (e.g. '0x580C') or address ('0x01DE05')
    cid_name: str              # Friendly symbol/name or UNKNOWN_...
    pos_in_source: int         # Starting position in source record / offset
    is_known: bool = False
    address: Optional[int] = None


@dataclass
class LidDefinition:
    """Structure of a Dynamically Defined Local Identifier (0xF0..0xFF)."""
    local_id: int
    name: str
    entries: List[LidEntry] = field(default_factory=list)
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
    """High-level KWP2000 protocol exchange dissector and LID/CID interpreter."""

    def __init__(self, master_cids: Optional[Dict[str, Any]] = None):
        self.master_cids = master_cids or {}
        # Invert master cids mapping hex id -> key
        self.cid_hex_map: Dict[str, str] = {}
        for key, val in self.master_cids.items():
            if key == "_schema_guide":
                continue
            raw_id = str(val.get("id", "")).strip()
            if raw_id:
                # Normalize to 0xXXXX (uppercase hex digits)
                try:
                    num_val = int(raw_id, 16)
                    norm_hex = f"0x{num_val:04X}"
                    self.cid_hex_map[norm_hex] = key
                    self.cid_hex_map[f"0x{num_val:X}"] = key
                except ValueError:
                    self.cid_hex_map[raw_id.lower()] = key

        # Dynamic LID registry keyed by Local ID (e.g. 0xF0)
        self.active_lids: Dict[int, LidDefinition] = {}

    def reload_cids(self, master_cids: Dict[str, Any]) -> None:
        self.master_cids = master_cids
        self.cid_hex_map.clear()
        for key, val in self.master_cids.items():
            if key == "_schema_guide":
                continue
            raw_id = str(val.get("id", "")).strip()
            if raw_id:
                try:
                    num_val = int(raw_id, 16)
                    norm_hex = f"0x{num_val:04X}"
                    self.cid_hex_map[norm_hex] = key
                    self.cid_hex_map[f"0x{num_val:X}"] = key
                except ValueError:
                    self.cid_hex_map[raw_id.lower()] = key

    def dissect_message(
        self,
        msg: IsoTpMessage,
        parse_cids: bool = True
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
                entries: List[Dict[str, Any]] = []
                discovered_unknown_cids: List[Dict[str, Any]] = []
                total_bytes = 0
                definition_modes_used = set()

                def_mode_names = {
                    0x01: "defineByLocalIdentifier",
                    0x02: "defineByCommonIdentifier",
                    0x03: "defineByMemoryAddress",
                    0x04: "clearDynamicallyDefinedLocalIdentifier",
                }

                # Check if it's a clear command: [0x2C, local_id, 0x04]
                if len(payload) >= 3 and payload[2] == 0x04:
                    self.active_lids.pop(local_id, None)
                    result["details"] = {
                        "local_id": f"0x{local_id:02X}",
                        "subfunction": "0x04",
                        "subfunction_name": "clearDynamicallyDefinedLocalIdentifier",
                        "entries": [],
                        "total_bytes": 0,
                        "status": f"Clear LID 0x{local_id:02X}",
                    }
                    return result

                # Parse sequence of definitions according to ISO 14230-3 Section 7.4.2
                pos = 2
                while pos < len(payload):
                    mode = payload[pos]
                    definition_modes_used.add(mode)
                    mode_name = def_mode_names.get(mode, f"mode_0x{mode:02X}")

                    if mode == 0x01:
                        # 0x01: defineByLocalIdentifier -> 5 bytes per entry:
                        # [0x01, positionInLID, memorySize, recordLocalIdentifier, positionInRecordLocalIdentifier]
                        if pos + 4 >= len(payload):
                            break
                        pos_in_lid = payload[pos + 1]
                        mem_size = payload[pos + 2]
                        rlocid = payload[pos + 3]
                        pos_in_source = payload[pos + 4]
                        pos += 5

                        cid_hex = f"0x{rlocid:02X}"
                        known_name = self.cid_hex_map.get(cid_hex) or self.cid_hex_map.get(f"0x{rlocid:X}")
                        is_known = bool(known_name)
                        cid_name = known_name if known_name else f"LOCAL_0x{rlocid:02X}"

                        entries.append({
                            "definition_mode": mode,
                            "definition_mode_name": mode_name,
                            "pos_in_lid": pos_in_lid,
                            "memory_size": mem_size,
                            "cid_hex": cid_hex,
                            "cid_name": cid_name,
                            "pos_in_source": pos_in_source,
                            "is_known": is_known,
                        })
                        total_bytes += mem_size

                    elif mode == 0x02:
                        # 0x02: defineByCommonIdentifier -> 6 bytes per entry:
                        # [0x02, positionInLID, memorySize, commonId_Hi, commonId_Lo, positionInRecordCommonIdentifier]
                        if pos + 5 >= len(payload):
                            break
                        pos_in_lid = payload[pos + 1]
                        mem_size = payload[pos + 2]
                        cid_val = (payload[pos + 3] << 8) | payload[pos + 4]
                        cid_hex = f"0x{cid_val:04X}"
                        pos_in_source = payload[pos + 5]
                        pos += 6

                        known_name = self.cid_hex_map.get(cid_hex) or self.cid_hex_map.get(f"0x{cid_val:X}")
                        if known_name:
                            cid_name = known_name
                            is_known = True
                        else:
                            cid_name = f"UNKNOWN_{cid_hex}"
                            is_known = False
                            discovered_unknown_cids.append({
                                "id": cid_hex,
                                "name": f"CID_{cid_hex}",
                                "position": pos_in_source,
                                "memory_size": mem_size,
                            })

                        entries.append({
                            "definition_mode": mode,
                            "definition_mode_name": mode_name,
                            "pos_in_lid": pos_in_lid,
                            "memory_size": mem_size,
                            "cid_hex": cid_hex,
                            "cid_name": cid_name,
                            "pos_in_source": pos_in_source,
                            "is_known": is_known,
                        })
                        total_bytes += mem_size

                    elif mode == 0x03:
                        # 0x03: defineByMemoryAddress -> 6 bytes per entry:
                        # [0x03, positionInLID, memorySize, addr_Hi, addr_Mid, addr_Lo]
                        if pos + 5 >= len(payload):
                            break
                        pos_in_lid = payload[pos + 1]
                        mem_size = payload[pos + 2]
                        addr_val = (payload[pos + 3] << 16) | (payload[pos + 4] << 8) | payload[pos + 5]
                        addr_hex = f"0x{addr_val:06X}"
                        pos += 6

                        entries.append({
                            "definition_mode": mode,
                            "definition_mode_name": mode_name,
                            "pos_in_lid": pos_in_lid,
                            "memory_size": mem_size,
                            "cid_hex": addr_hex,
                            "cid_name": f"MEM_{addr_hex}",
                            "pos_in_source": 1,
                            "is_known": True,
                            "address": addr_val,
                        })
                        total_bytes += mem_size

                    elif mode == 0x04:
                        # Clear inline
                        self.active_lids.pop(local_id, None)
                        pos += 1
                        break
                    else:
                        # Unrecognized mode byte, advance 1
                        pos += 1

                # Sort entries by destination position in LID train
                entries.sort(key=lambda x: x["pos_in_lid"])

                if entries:
                    lid_def = LidDefinition(
                        local_id=local_id,
                        name=f"LID_0x{local_id:02X}",
                        entries=[
                            LidEntry(
                                definition_mode=e["definition_mode"],
                                definition_mode_name=e["definition_mode_name"],
                                pos_in_lid=e["pos_in_lid"],
                                memory_size=e["memory_size"],
                                cid_hex=e["cid_hex"],
                                cid_name=e["cid_name"],
                                pos_in_source=e["pos_in_source"],
                                is_known=e["is_known"],
                                address=e.get("address"),
                            )
                            for e in entries
                        ],
                        total_bytes=total_bytes,
                    )
                    self.active_lids[local_id] = lid_def

                primary_mode = next(iter(definition_modes_used)) if definition_modes_used else 0x02
                primary_mode_name = def_mode_names.get(primary_mode, f"0x{primary_mode:02X}")

                result["details"] = {
                    "local_id": f"0x{local_id:02X}",
                    "subfunction": f"0x{primary_mode:02X}",
                    "subfunction_name": primary_mode_name,
                    "entries": entries,
                    "total_bytes": total_bytes,
                    "unknown_cids": discovered_unknown_cids,
                }
            elif sid == (SID_DYNAMICALLY_DEFINE_LOCAL_ID + 0x40):
                local_id = payload[1] if len(payload) > 1 else 0
                result["details"] = {
                    "local_id": f"0x{local_id:02X}",
                    "status": f"LID 0x{local_id:02X} configuration accepted by ECU",
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
                        0x01: ("single", "Single Response (On Demand Query)"),
                        0x02: ("slow", "Slow Rate Periodic Polling"),
                        0x03: ("medium", "Medium Rate Periodic Polling"),
                        0x04: ("fast", "Fast Rate Periodic Polling (As fast as possible)"),
                        0x05: ("stop", "Stop Periodic Transmission"),
                    }
                    mode_info = mode_map.get(transmission_mode, ("customMode", f"Custom Mode 0x{transmission_mode:02X}"))
                    result["details"]["transmissionMode"] = f"0x{transmission_mode:02X}"
                    result["details"]["transmission_mode"] = f"0x{transmission_mode:02X}"
                    result["details"]["transmission_mode_name"] = mode_info[0]
                    result["details"]["transmission_mode_desc"] = mode_info[1]
                    if len(payload) > 3:
                        result["details"]["maximumNumberOfResponsesToSend"] = payload[3]

                # Response payload unpacking
                if sid == (SID_READ_DATA_BY_LOCAL_ID + 0x40):
                    data_bytes = payload[2:]
                    result["details"]["data_length"] = len(data_bytes)
                    result["details"]["data_hex"] = data_bytes.hex().upper()

                    if parse_cids and local_id in self.active_lids:
                        parsed_signals = self.unpack_lid_payload(self.active_lids[local_id], data_bytes)
                        result["details"]["signals"] = parsed_signals
                    elif parse_cids:
                        result["details"]["signals_status"] = f"No active LID definition found for 0x{local_id:02X}"
            return result

        # 4. ReadDataByCommonIdentifier (0x22 / 0x62)
        if sid in (SID_READ_DATA_BY_COMMON_ID, SID_READ_DATA_BY_COMMON_ID + 0x40):
            if len(payload) >= 3:
                cid_val = (payload[1] << 8) | payload[2]
                cid_hex = f"0x{cid_val:04X}"
                known_name = self.cid_hex_map.get(cid_hex) or f"CID_{cid_hex}"
                result["details"]["recordCommonIdentifier"] = cid_hex
                result["details"]["cid_name"] = known_name

                if sid == SID_READ_DATA_BY_COMMON_ID and len(payload) > 3:
                    tx_mode = payload[3]
                    result["details"]["transmissionMode"] = f"0x{tx_mode:02X}"

                if sid == (SID_READ_DATA_BY_COMMON_ID + 0x40):
                    data_bytes = payload[3:]
                    result["details"]["data_hex"] = data_bytes.hex().upper()
                    result["details"]["data_length"] = len(data_bytes)
            return result

        # 5. ReadMemoryByAddress (0x23 / 0x63)
        if sid in (SID_READ_MEMORY_BY_ADDRESS, SID_READ_MEMORY_BY_ADDRESS + 0x40):
            if sid == SID_READ_MEMORY_BY_ADDRESS and len(payload) >= 5:
                addr = (payload[1] << 16) | (payload[2] << 8) | payload[3]
                size = payload[4]
                result["details"]["memoryAddress"] = f"0x{addr:06X}"
                result["details"]["memorySize"] = size
                if len(payload) > 5:
                    result["details"]["transmissionMode"] = f"0x{payload[5]:02X}"
            elif sid == (SID_READ_MEMORY_BY_ADDRESS + 0x40):
                result["details"]["recordValue"] = payload[1:].hex().upper()
            return result

        # 6. SetDataRates (0x26 / 0x66)
        if sid in (SID_SET_DATA_RATES, SID_SET_DATA_RATES + 0x40):
            if sid == SID_SET_DATA_RATES and len(payload) >= 4:
                result["details"]["slowRate"] = f"0x{payload[1]:02X}"
                result["details"]["mediumRate"] = f"0x{payload[2]:02X}"
                result["details"]["fastRate"] = f"0x{payload[3]:02X}"
            return result

        # 7. SecurityAccess (0x27 / 0x67)
        if sid in (SID_SECURITY_ACCESS, SID_SECURITY_ACCESS + 0x40):
            if len(payload) >= 2:
                access_mode = payload[1]
                is_req_seed = (access_mode % 2 != 0)
                mode_desc = "requestSeed" if is_req_seed else "sendKey"
                result["details"]["accessMode"] = f"0x{access_mode:02X} ({mode_desc})"

                if sid == SID_SECURITY_ACCESS:
                    if not is_req_seed and len(payload) > 2:
                        result["details"]["key"] = payload[2:].hex().upper()
                else:
                    # Positive Response
                    if is_req_seed and len(payload) > 2:
                        result["details"]["seed"] = payload[2:].hex().upper()
                    if len(payload) >= 3 and payload[-1] == 0x34:
                        result["details"]["securityAccessStatus"] = "0x34 (securityAccessAllowed)"
            return result

        # 8. StartDiagnosticSession (0x10 / 0x50)
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

        # 9. StopDiagnosticSession (0x20 / 0x60)
        if sid in (SID_STOP_DIAGNOSTIC_SESSION, SID_STOP_DIAGNOSTIC_SESSION + 0x40):
            result["details"]["status"] = "Stop Diagnostic Session"
            return result

        # 10. EcuReset (0x11 / 0x51)
        if sid in (SID_ECU_RESET, SID_ECU_RESET + 0x40):
            if sid == SID_ECU_RESET and len(payload) >= 2:
                reset_mode = payload[1]
                reset_map = {
                    0x01: "powerOn",
                    0x02: "powerOnWhileMaintainingCommunication",
                }
                reset_name = reset_map.get(reset_mode, f"ManufacturerSpecific_0x{reset_mode:02X}")
                result["details"]["resetMode"] = f"0x{reset_mode:02X} ({reset_name})"
            elif sid == (SID_ECU_RESET + 0x40):
                result["details"]["resetStatus"] = payload[1:].hex().upper() if len(payload) > 1 else "Reset OK"
            return result

        # 11. ReadFreezeFrameData (0x12 / 0x52)
        if sid in (SID_READ_FREEZE_FRAME_DATA, SID_READ_FREEZE_FRAME_DATA + 0x40):
            if len(payload) >= 2:
                result["details"]["freezeFrameNumber"] = payload[1]
            return result

        # 12. ReadDiagnosticTroubleCodes (0x13 / 0x53, 0x17 / 0x57, 0x18 / 0x58)
        if sid in (SID_READ_DIAGNOSTIC_TROUBLE_CODES, SID_READ_DIAGNOSTIC_TROUBLE_CODES + 0x40,
                   SID_READ_STATUS_OF_DTC, SID_READ_STATUS_OF_DTC + 0x40,
                   SID_READ_DTC_BY_STATUS, SID_READ_DTC_BY_STATUS + 0x40):
            if sid in (0x53, 0x57, 0x58) and len(payload) >= 2:
                result["details"]["numberOfDTC"] = payload[1]
                result["details"]["dtc_data"] = payload[2:].hex().upper()
            return result

        # 13. ClearDiagnosticInformation (0x14 / 0x54)
        if sid in (SID_CLEAR_DIAGNOSTIC_INFORMATION, SID_CLEAR_DIAGNOSTIC_INFORMATION + 0x40):
            result["details"]["status"] = "Clear Diagnostic Information / DTCs"
            if len(payload) > 1:
                result["details"]["groupOfDiagnosticInformation"] = payload[1:].hex().upper()
            return result

        # 14. ReadECUIdentification (0x1A / 0x5A)
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

        # 15. InputOutputControl (0x30 / 0x70 & 0x2F / 0x6F)
        if sid in (SID_INPUT_OUTPUT_CONTROL_BY_LOCAL_ID, SID_INPUT_OUTPUT_CONTROL_BY_LOCAL_ID + 0x40,
                   SID_INPUT_OUTPUT_CONTROL_BY_COMMON_ID, SID_INPUT_OUTPUT_CONTROL_BY_COMMON_ID + 0x40):
            if len(payload) > 1:
                result["details"]["io_identifier"] = payload[1:].hex().upper()
            return result

        # 16. RoutineControl (0x31..0x33 / 0x71..0x73, 0x38..0x3A / 0x78..0x7A)
        if sid in (0x31, 0x71, 0x32, 0x72, 0x33, 0x73, 0x38, 0x78, 0x39, 0x79, 0x3A, 0x7A):
            if len(payload) >= 2:
                result["details"]["routineIdentifier"] = f"0x{payload[1]:02X}"
                if len(payload) > 2:
                    result["details"]["routineOptionsOrStatus"] = payload[2:].hex().upper()
            return result

        # 17. Upload / Download (0x34..0x37 / 0x74..0x77)
        if sid in (0x34, 0x74, 0x35, 0x75, 0x36, 0x76, 0x37, 0x77):
            result["details"]["transferPayload"] = payload[1:].hex().upper()
            return result

        # 18. WriteDataByLocal/CommonIdentifier (0x3B / 0x7B, 0x2E / 0x6E)
        if sid in (SID_WRITE_DATA_BY_LOCAL_ID, SID_WRITE_DATA_BY_LOCAL_ID + 0x40,
                   SID_WRITE_DATA_BY_COMMON_ID, SID_WRITE_DATA_BY_COMMON_ID + 0x40):
            if len(payload) >= 2:
                result["details"]["recordIdentifier"] = f"0x{payload[1]:02X}"
                result["details"]["recordValue"] = payload[2:].hex().upper()
            return result

        # 19. WriteMemoryByAddress (0x3D / 0x7D)
        if sid in (SID_WRITE_MEMORY_BY_ADDRESS, SID_WRITE_MEMORY_BY_ADDRESS + 0x40):
            if sid == SID_WRITE_MEMORY_BY_ADDRESS and len(payload) >= 5:
                addr = (payload[1] << 16) | (payload[2] << 8) | payload[3]
                size = payload[4]
                result["details"]["memoryAddress"] = f"0x{addr:06X}"
                result["details"]["memorySize"] = size
                result["details"]["recordValue"] = payload[5:].hex().upper()
            return result

        # 20. TesterPresent (0x3E / 0x7E)
        if sid in (SID_TESTER_PRESENT, SID_TESTER_PRESENT + 0x40):
            subfunction = payload[1] if len(payload) > 1 else 0x01
            resp_req = "responseRequired" if subfunction == 0x01 else "suppressResponse"
            result["details"]["subFunction"] = f"0x{subfunction:02X} ({resp_req})"
            result["details"]["status"] = "Heartbeat / Keep-Alive"
            return result

        # 21. EscapeCode (0x80 / 0xC0)
        if sid in (SID_ESCAPE_CODE, SID_ESCAPE_CODE + 0x40):
            if len(payload) >= 2:
                result["details"]["manufacturerSpecificServiceId"] = f"0x{payload[1]:02X}"
                result["details"]["recordValue"] = payload[2:].hex().upper()
            return result

        # 22. Fallback for unmapped services
        result["details"]["info"] = "Diagnostic service payload"
        result["details"]["payload_hex"] = payload[1:].hex().upper() if len(payload) > 1 else ""
        return result

    def unpack_lid_payload(self, lid: LidDefinition, data_bytes: bytes) -> List[Dict[str, Any]]:
        """Unpacks raw LID response bytes into constituent CIDs with scaled or raw values."""
        signals: List[Dict[str, Any]] = []
        cursor = 0

        for entry in lid.entries:
            size = entry.memory_size
            if cursor + size > len(data_bytes):
                # Frame data ended prematurely
                remaining_slice = data_bytes[cursor:]
                if remaining_slice:
                    signals.append({
                        "cid_name": entry.cid_name,
                        "cid_hex": entry.cid_hex,
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

            # Unpack raw integer (signed or unsigned according to metadata)
            cid_meta = self.master_cids.get(entry.cid_name, {})
            if not cid_meta:
                # Also lookup by hex ID if cid_name was generated as CID_0xXXXX
                cid_meta = self.master_cids.get(entry.cid_hex, {})

            is_signed = bool(cid_meta.get("signed", False))

            if size == 1:
                raw_int = struct.unpack(">b" if is_signed else ">B", slice_bytes)[0]
            elif size == 2:
                raw_int = struct.unpack(">h" if is_signed else ">H", slice_bytes)[0]
            elif size == 4:
                raw_int = struct.unpack(">i" if is_signed else ">I", slice_bytes)[0]
            else:
                raw_int = int.from_bytes(slice_bytes, byteorder="big", signed=is_signed)

            mul = cid_meta.get("mul", 1)
            div = cid_meta.get("div", 1) or 1
            add = cid_meta.get("add", 0)
            unit = cid_meta.get("unit", "")

            # Apply formula if metadata exists, otherwise display raw integer
            if cid_meta:
                scaled_val = round(((raw_int * mul) / div) + add, 4)
                formula_str = f"(({raw_int} * {mul}) / {div}) + {add}" if (mul != 1 or div != 1 or add != 0) else "raw"
            else:
                scaled_val = raw_int
                formula_str = "raw (unregistered in cids.json)"

            signals.append({
                "cid_name": entry.cid_name,
                "cid_hex": entry.cid_hex,
                "raw_int": raw_int,
                "raw_hex": slice_bytes.hex().upper(),
                "scaled_value": scaled_val,
                "unit": unit,
                "formula": formula_str,
                "is_truncated": False,
            })

        return signals
