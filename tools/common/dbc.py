"""MiniGauge DBC Parser and CAN Signal Interpretation.

Provides lightweight, zero-dependency parsing of industry-standard CAN DBC
files, decoding Motorola (Big Endian) and Intel (Little Endian) bit-packings,
linear scalings, min/max bounds, unit strings, IEEE-754 floats, and value tables.
Zero pip dependencies (Python 3 stdlib only).
"""

import re
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


class SignalDef:
    """Defines an individual signal layout within a CAN message."""

    def __init__(
        self,
        name: str,
        start_bit: int,
        bit_len: int,
        is_intel: bool,
        is_signed: bool,
        factor: float,
        offset: float,
        min_val: float,
        max_val: float,
        unit: str,
        valtype: int = 0,
        choices: Optional[Dict[int, str]] = None,
        mux: Optional[str] = None,
    ):
        self.name = name
        self.start_bit = start_bit
        self.bit_len = bit_len
        self.is_intel = is_intel
        self.is_signed = is_signed
        self.factor = factor
        self.offset = offset
        self.min_val = min_val
        self.max_val = max_val
        self.unit = unit
        self.valtype = valtype  # 0: int, 1: float32, 2: float64
        self.choices = choices or {}
        self.mux = mux  # 'M' for multiplexor, 'm<N>' for multiplexed, None for standard

        # Backwards compatibility attributes
        self.length = bit_len
        self.is_little = is_intel
        self.value_table = self.choices

    def decode_raw(self, payload: bytes) -> int:
        """Extracts raw integer bits from payload according to endianness."""
        if len(payload) < 8:
            payload = payload.ljust(8, b"\x00")

        if self.is_intel:
            val_int = int.from_bytes(payload, "little")
            return (val_int >> self.start_bit) & ((1 << self.bit_len) - 1)
        else:
            # Motorola (Big Endian) sequential bit extraction
            val = 0
            cur_bit = self.start_bit
            for _ in range(self.bit_len):
                byte_idx = cur_bit // 8
                bit_in_byte = cur_bit % 8
                if byte_idx < len(payload):
                    bit = (payload[byte_idx] >> bit_in_byte) & 1
                else:
                    bit = 0
                val = (val << 1) | bit
                if bit_in_byte == 0:
                    cur_bit = (byte_idx + 2) * 8 - 1
                else:
                    cur_bit -= 1
            return val

    def decode_value(self, payload: bytes) -> Optional[float]:
        """Decodes the physical numeric value from raw payload bytes."""
        phys, _ = self.decode(payload)
        return phys

    def decode(self, payload: bytes) -> Tuple[Any, Optional[str]]:
        """Decodes raw bits into physical value and optional named enum choice."""
        raw = self.decode_raw(payload)

        # Signed conversion if not float
        if self.is_signed and not self.valtype:
            if raw & (1 << (self.bit_len - 1)):
                raw -= 1 << self.bit_len

        # Float handling
        if self.valtype == 1:  # 32-bit float
            raw_bytes = (raw & 0xFFFFFFFF).to_bytes(4, "little")
            raw_float = struct.unpack("<f", raw_bytes)[0]
            phys = raw_float * self.factor + self.offset
        elif self.valtype == 2:  # 64-bit double
            raw_bytes = (raw & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
            raw_double = struct.unpack("<d", raw_bytes)[0]
            phys = raw_double * self.factor + self.offset
        else:
            phys = raw * self.factor + self.offset

        # Round clean floats or preserve integer
        if isinstance(phys, float):
            if phys.is_integer():
                phys = int(phys)
            else:
                phys = round(phys, 5)

        named = self.choices.get(int(raw))
        return phys, named


class SignalList(list):
    """Hybrid list/dict collection of SignalDefs supporting both list iteration and key lookups."""

    def __init__(self, signals: Optional[Sequence[SignalDef]] = None):
        super().__init__(signals or [])
        self._by_name: Dict[str, SignalDef] = {s.name: s for s in self}

    def append(self, sig: SignalDef) -> None:
        super().append(sig)
        if not hasattr(self, "_by_name"):
            self._by_name = {}
        self._by_name[sig.name] = sig

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, str):
            return item in self._by_name
        return super().__contains__(item)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            return self._by_name[item]
        return super().__getitem__(item)

    def get(self, name: str, default: Any = None) -> Any:
        return self._by_name.get(name, default)

    def keys(self):
        return self._by_name.keys()

    def values(self):
        return self._by_name.values()

    def items(self):
        return self._by_name.items()


DbcSignal = SignalDef


class MessageDef:
    """Defines a CAN message specification containing multiple signals."""

    def __init__(self, msg_id: int, name: str, dlc: int, sender: str = "Vector__XXX"):
        self.msg_id = msg_id
        self.can_id = msg_id
        self.name = name
        self.dlc = dlc
        self.sender = sender
        self.signals = SignalList()
        self.mux_signal: Optional[SignalDef] = None

    @property
    def signal_list(self) -> List[SignalDef]:
        return list(self.signals)

    def add_signal(self, sig: SignalDef):
        self.signals.append(sig)
        if sig.mux == "M":
            self.mux_signal = sig

    def decode(self, payload: bytes) -> Dict[str, Dict[str, Any]]:
        """Decodes payload into dictionary of signal name to value/unit/choice."""
        if len(payload) < 8:
            payload = payload.ljust(8, b"\x00")

        mux_val = None
        if self.mux_signal:
            mux_val = self.mux_signal.decode_raw(payload)

        results = {}
        for sig in self.signals:
            if sig.mux and sig.mux != "M":
                try:
                    expected_mux = int(sig.mux[1:])
                    if mux_val != expected_mux:
                        continue
                except ValueError:
                    pass

            phys_val, choice_name = sig.decode(payload)
            results[sig.name] = {
                "value": phys_val,
                "unit": sig.unit,
                "choice": choice_name,
            }

        return results


DbcMessage = MessageDef


class DbcDatabase:
    """In-memory database of parsed CAN DBC messages and signals."""

    def __init__(self, filepath: Optional[Union[str, Path]] = None):
        self.filepath = Path(filepath) if filepath else None
        self.messages: Dict[int, MessageDef] = {}
        self.value_tables: Dict[str, Dict[int, str]] = {}
        if self.filepath and self.filepath.is_file():
            self._parse(self.filepath)

    @classmethod
    def parse(cls, filepath: Union[str, Path]) -> "DbcDatabase":
        return cls(filepath)

    def get_message(self, msg_id: int) -> Optional[MessageDef]:
        return self.messages.get(msg_id)

    def _parse(self, filepath: Path):
        content = filepath.read_text(encoding="utf-8", errors="ignore")

        # 1. Parse SIG_VALTYPE_
        valtype_re = re.compile(r"^SIG_VALTYPE_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s*;", re.MULTILINE)
        valtypes: Dict[Tuple[int, str], int] = {}
        for m in valtype_re.finditer(content):
            valtypes[(int(m.group(1)), m.group(2))] = int(m.group(3))

        # 2. Parse VAL_ enum tables
        val_re = re.compile(r"^VAL_\s+(\d+)\s+(\w+)\s+(.+);", re.MULTILINE)
        val_entry_re = re.compile(r'(\d+)\s+"([^"]*)"')
        val_choices: Dict[Tuple[int, str], Dict[int, str]] = {}
        for m in val_re.finditer(content):
            msg_id = int(m.group(1))
            sig_name = m.group(2)
            entries = val_entry_re.findall(m.group(3))
            val_choices[(msg_id, sig_name)] = {int(k): v for k, v in entries}

        # Also standalone VAL_TABLE_ definitions
        val_table_re = re.compile(r"^VAL_TABLE_\s+(\w+)\s+(.*?);", re.MULTILINE | re.DOTALL)
        for match in val_table_re.finditer(content):
            tname, tbody = match.group(1), match.group(2)
            self.value_tables[tname] = {
                int(e.group(1)): e.group(2) for e in re.finditer(r'(\d+)\s+"([^"]*)"', tbody)
            }

        # 3. Parse BO_ and SG_
        sg_re = re.compile(
            r'SG_\s+(\w+)\s*(?:(M|m\d+))?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s+\(([-0-9.eE+]+),([-0-9.eE+]+)\)\s+\[([-0-9.eE+]+)\|([-0-9.eE+]+)\]\s+\"([^\"]*)\"'
        )

        current_msg: Optional[MessageDef] = None
        for line in content.splitlines():
            stripped = line.strip()
            if line.startswith("BO_ "):
                parts = line.split()
                if len(parts) >= 5:
                    msg_id = int(parts[1]) & 0x1FFFFFFF
                    name = parts[2].rstrip(":")
                    dlc = int(parts[3])
                    sender = parts[4]
                    current_msg = MessageDef(msg_id, name, dlc, sender)
                    self.messages[msg_id] = current_msg
            elif stripped.startswith("SG_ ") and current_msg is not None:
                m = sg_re.search(stripped)
                if m:
                    sig_name = m.group(1)
                    mux = m.group(2)
                    start_bit = int(m.group(3))
                    bit_len = int(m.group(4))
                    is_intel = m.group(5) == "1"
                    is_signed = m.group(6) == "-"
                    factor = float(m.group(7))
                    offset = float(m.group(8))
                    min_val = float(m.group(9))
                    max_val = float(m.group(10))
                    unit = m.group(11)

                    valtype = valtypes.get((current_msg.msg_id, sig_name), 0)
                    choices = val_choices.get((current_msg.msg_id, sig_name), {})

                    sig = SignalDef(
                        name=sig_name,
                        start_bit=start_bit,
                        bit_len=bit_len,
                        is_intel=is_intel,
                        is_signed=is_signed,
                        factor=factor,
                        offset=offset,
                        min_val=min_val,
                        max_val=max_val,
                        unit=unit,
                        valtype=valtype,
                        choices=choices,
                        mux=mux,
                    )
                    current_msg.add_signal(sig)


# Global singleton cache
_GLOBAL_DBC: Optional[DbcDatabase] = None
_DEFAULT_DBC_PATH = Path(__file__).resolve().parent.parent / "binocan.dbc"


def get_dbc(dbc_path: Optional[Union[str, Path]] = None) -> DbcDatabase:
    """Returns the shared DbcDatabase instance, parsing default or specified DBC file."""
    global _GLOBAL_DBC
    target = Path(dbc_path) if dbc_path else _DEFAULT_DBC_PATH
    if _GLOBAL_DBC is None or (_GLOBAL_DBC.filepath != target):
        _GLOBAL_DBC = DbcDatabase.parse(target)
    return _GLOBAL_DBC


# Compatibility aliases
DbcSignal = SignalDef
DbcMessage = MessageDef
