# MiniGauge BMWP2000 Diagnostic Tools

This directory contains standalone, zero-dependency tools for inspecting ISO-TP / KWP2000 exchanges and composing BMW FAST-over-CAN Local Identifier (LID) trains for Mini R56.

The toolset consists of two web utilities:
1. **BMWP2000 LID Composer (`lid_composer.py`)**: Web configuration workstation to compose and reorder Dynamically Defined Local Identifier (LID) trains, inspect ISO-TP payload framing (SF vs. FF+CF), compute CAN frame counts, and view/edit the master CID dictionary (`config/cids.json`).
2. **BMWP2000 Diagnostic Exchange Viewer (`bmwp2000_viewer.py`)**: Interactive web inspector for ISO-TP reassembled exchanges, KWP2000 service dissection, dynamic LID tracking, CID scaling, Negative Response Codes (NRC), and unknown command alerts.

Both tools are written in pure Python 3 and have **zero external pip dependencies**.

---

## Directory Structure

```
tools/
├── bmwp2000_viewer.py        # Web KWP2000 log inspector & exchange timeline
├── lid_composer.py           # Web LID train composer with CID lookup
├── common/                   # Shared zero-pip Python library
│   ├── can_core.py           # CAN binary record unpacker & CanFrame class
│   ├── log_loader.py         # Multi-format CAN log parser (.bin, candump .log, Vector .asc)
│   ├── isotp_kwp.py          # ISO-TP transport reassembler & BMW KWP2000 dissector
│   └── http_server.py        # BaseAppHandler, MIME resolver & port finder
├── fixtures/                 # Canonical .bin and candump .log test captures
├── tests/                    # Automated unit & integration tests
│   ├── test_bmwp2000_viewer.py
│   ├── test_lid_composer.py
│   └── test_common_components.py
└── web/                      # Web frontend assets
    ├── static/
    │   ├── css/
    │   │   ├── base.css
    │   │   ├── components.css
    │   │   ├── theme.css
    │   │   ├── bmwp2000_viewer.css
    │   │   └── lid_composer.css
    │   └── js/
    │       ├── theme.js
    │       ├── toast.js
    │       ├── bmwp2000_viewer.js
    │       └── lid_composer.js
    └── templates/
        ├── bmwp2000_viewer.html
        └── lid_composer.html
```

---

## Quickstart

### 1. Launch the BMWP2000 Diagnostic Exchange Viewer
```bash
python3 tools/bmwp2000_viewer.py
```
Open [http://localhost:8080](http://localhost:8080) to inspect incoming/outgoing diagnostic exchanges, drill down into raw underlying CAN frames, view positive/negative responses, and visualize the CID train memory map.

### 2. Launch the LID Composer
```bash
python3 tools/lid_composer.py
```
Open [http://localhost:8092](http://localhost:8092) to view and modify active LID trains (`config/lids.json`) and master CID formulas (`config/cids.json`).

### 3. Run Test Suite
```bash
python3 -m unittest discover -s tools/tests
```
