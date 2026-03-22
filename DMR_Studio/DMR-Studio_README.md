# DMR Studio

**TactileSense Platform — PT Application**  
*PT Robotic LLC — Apache License 2.0*

DMR Studio is the Physical Therapist-facing application of the TactileSense haptic platform. Licensed PTs use it to record Digital Master Records (DMRs) — reference therapy sessions captured through the PPS Finger TPS II haptic glove — which are then delivered to patients via the Co-Pilot application.

---

## Requirements

- Python 3.11 or higher (tested on 3.11 and 3.14 on Windows)
- Windows 10/11 (primary target); Linux/macOS for development only
- PPS Finger TPS II haptic glove (or Demo mode)
- Logitech C920s camera (optional — for session video capture)

---

## Installation

```bash
git clone https://github.com/PTRoboticLLC/DMR-Studio.git
cd DMR-Studio
pip install -r requirements.txt
```

---

## Running the Application

**Windows (recommended):**

Double-click `RUN_DMR_STUDIO.bat`

The launcher performs a preflight check — Python version, required files, packages — and reports any missing dependencies before attempting to start the application.

**Manual launch:**

```bash
python tactile_sense_main_dmr.py
```

---

## First-Time Setup

1. Copy `config/config_template.json` to `config/config.json`
2. Edit `config/config.json` to set your `protocol_library_path` — the shared folder where DMR files will be saved (must match the path configured in Co-Pilot)
3. Launch the application

---

## File Structure

```
DMR-Studio/
├── tactile_sense_main_dmr.py     # Main application
├── camera_manager.py             # Camera integration
├── panels/
│   └── pt_panel_with_camera.html # PT session panel
├── RUN_DMR_STUDIO.bat            # Windows launcher
├── config/
│   └── config_template.json      # Copy to config.json before first run
└── requirements.txt
```

**Runtime folders (created automatically, not in repository):**

```
PT_Protocols/                     # Recorded DMR files — local only
```

---

## Protocol Library

DMR Studio saves completed DMR files to the `protocol_library_path` defined in `config.json`. This shared folder is the only data interface between DMR Studio and Co-Pilot. It must be accessible from both machines (local drive or network share).

Default path: `C:\TactileSense\ProtocolLibrary\`

---

## Contributing

This repository is maintained by PT Robotic LLC. Collaborators should:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Follow existing coding conventions — ASCII-safe, tkinter-native UI, no external GUI frameworks
4. Submit a pull request with a clear description of the change

**Do not commit patient data, session recordings, or real `config.json` files.**

---

## License

Apache License 2.0 — see [LICENSE](LICENSE)

&copy; 2026 PT Robotic LLC. TactileSense is a trademark of PT Robotic LLC.
