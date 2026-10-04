"""MiniGauge Tools Common Library.

Shared utilities for CAN binary parsing, ISO-TP / KWP2000 handling,
multi-format log loading, and zero-dependency HTTP server operations.
"""

from .can_core import (
    CanFrame,
    read_bin_file,
    find_bin_files,
    resolve_bin_file,
    natural_sort_key,
    RECORD_STRUCT,
    RECORD_SIZE,
)
from .http_server import (
    BaseAppHandler,
    find_available_port,
    start_server,
    MIME_TYPES,
)
from .log_loader import (
    parse_candump_log,
    parse_asc_log,
    detect_log_format,
    load_log_file,
    find_all_log_files,
)
from .isotp_kwp import (
    IsoTpReassembler,
    BmwP2000Dissector,
    LidDefinition,
    LidEntry,
    IsoTpMessage,
)

__all__ = [
    "CanFrame",
    "read_bin_file",
    "find_bin_files",
    "resolve_bin_file",
    "natural_sort_key",
    "RECORD_STRUCT",
    "RECORD_SIZE",
    "BaseAppHandler",
    "find_available_port",
    "start_server",
    "MIME_TYPES",
    "parse_candump_log",
    "parse_asc_log",
    "detect_log_format",
    "load_log_file",
    "find_all_log_files",
    "IsoTpReassembler",
    "BmwP2000Dissector",
    "LidDefinition",
    "LidEntry",
    "IsoTpMessage",
]
