"""MiniGauge Decoder Common Library.

Shared utilities for CAN binary parsing, DBC interpretation,
calibration persistence, and zero-dependency HTTP server operations.
"""

from .can_core import (
    CanFrame,
    read_bin_file,
    find_bin_files,
    natural_sort_key,
    RECORD_STRUCT,
    RECORD_SIZE,
)
from .dbc import (
    SignalDef,
    MessageDef,
    DbcSignal,
    DbcMessage,
    DbcDatabase,
    get_dbc,
)
from .calibration import (
    load_calibration,
    save_calibration,
    get_default_calibration,
    DEFAULT_CALIBRATION_FILE,
)
from .http_server import (
    BaseAppHandler,
    find_available_port,
    start_server,
    MIME_TYPES,
)

__all__ = [
    "CanFrame",
    "read_bin_file",
    "find_bin_files",
    "natural_sort_key",
    "RECORD_STRUCT",
    "RECORD_SIZE",
    "SignalDef",
    "MessageDef",
    "DbcSignal",
    "DbcMessage",
    "DbcDatabase",
    "get_dbc",
    "load_calibration",
    "save_calibration",
    "get_default_calibration",
    "DEFAULT_CALIBRATION_FILE",
    "BaseAppHandler",
    "find_available_port",
    "start_server",
    "MIME_TYPES",
]
