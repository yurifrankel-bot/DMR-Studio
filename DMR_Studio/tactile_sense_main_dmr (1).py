#!/usr/bin/env python3
"""
TactileSense DMR Studio v1.0
Digital Master Record (DMR) Generation Platform — PT Robotic LLC

Single-file, self-contained application for Licensed Physical Therapists to:
  • Record Digital Master Records (DMR) via TactileGlove or Demo Simulator
  • Review recorded frames frame-by-frame
  • Export DMR sessions as JSON and CSV
  • Configure PT pressure zones interactively

What was removed vs. tactile_sense_main.py:
  - PTA execution mode (Co-Pilot platform, separate product)
  - WebView / tkinterweb HTML panels (no browser required)
  - Panel Server / WebSocket bridge (no Edge browser)
  - 3D orientation live visual (roll/pitch/yaw saved to DMR; no on-screen widget)

New in DMR Studio:
  - Right panel: camera placeholder, live 5-finger pressure bars, session stats
    — all native tkinter, no HTML, no browser, no extra pip installs
  - Cleaner single-file deployment: copy one .py file to any Windows machine

Layout:
  ┌──────────────┬─────────────────────────┬─────────────────────┐
  │  Left panel  │  Hand visualization     │  Right panel        │
  │  (controls,  │  (matplotlib hand +     │  (camera, pressure  │
  │   recording) │   heatmap)              │   bars, stats)      │
  └──────────────┴─────────────────────────┴─────────────────────┘
"""

import sys
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle, Circle
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers 3d projection
from datetime import datetime
import json
import os
import csv

print("Starting TactileSense DMR Studio v1.0 ...")

# ── Finger → sensor index mapping (PPS Finger TPS II, 5 fingertip sensors) ───
SENSOR_MODEL      = "PPS Finger TPS II"
N_SENSORS         = 5
FINGERS           = ["Th", "In", "Md", "Rg", "Py"]
FINGER_SENSOR_MAP = {
    "Th": [0],
    "In": [1],
    "Md": [2],
    "Rg": [3],
    "Py": [4],
}

# ── Optional 3D Glove Visualization (external module) ────────────────────────
try:
    from glove_visualization_3d import GloveVisualization3DWindow
    print("✓ 3D Glove Visualization available")
except ImportError:
    GloveVisualization3DWindow = None
    print("⚠ 3D Glove Visualization not available (glove_visualization_3d.py not found)")


# ============================================================================
# DMR SESSION DIALOG
# ============================================================================

class DMRSessionDialog:
    """
    Collects patient ID, PT ID, treatment location, and session notes
    before a DMR recording session begins.
    Frame duration and num_frames are calculated from clinical presets
    loaded from location_clinical_presets.json.
    """

    # ── Built-in fallback presets (used if JSON file not found) ──────────────
    _BUILTIN_PRESETS = {
        'left_shoulder':  {'display': 'Left Shoulder',      'frame_duration_sec': 3, 'session_duration_min': 15},
        'right_shoulder': {'display': 'Right Shoulder',     'frame_duration_sec': 3, 'session_duration_min': 15},
        'left_hip':       {'display': 'Left Hip',           'frame_duration_sec': 5, 'session_duration_min': 20},
        'right_hip':      {'display': 'Right Hip',          'frame_duration_sec': 5, 'session_duration_min': 20},
        'lower_back':     {'display': 'Lower Back',         'frame_duration_sec': 5, 'session_duration_min': 20},
        'cervical':       {'display': 'Cervical / Neck',    'frame_duration_sec': 3, 'session_duration_min': 12},
        'left_knee':      {'display': 'Left Knee',          'frame_duration_sec': 3, 'session_duration_min': 15},
        'right_knee':     {'display': 'Right Knee',         'frame_duration_sec': 3, 'session_duration_min': 15},
        'left_ankle':     {'display': 'Left Ankle',         'frame_duration_sec': 2, 'session_duration_min': 12},
        'right_ankle':    {'display': 'Right Ankle',        'frame_duration_sec': 2, 'session_duration_min': 12},
        'left_hand_wrist':  {'display': 'Left Hand / Wrist',  'frame_duration_sec': 2, 'session_duration_min': 10},
        'right_hand_wrist': {'display': 'Right Hand / Wrist', 'frame_duration_sec': 2, 'session_duration_min': 10},
    }

    @classmethod
    def _load_presets(cls):
        """Load location_clinical_presets.json from same folder as this script."""
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'location_clinical_presets.json')
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            presets = {}
            for loc in data.get('locations', []):
                presets[loc['key']] = {
                    'display':              loc['display'],
                    'frame_duration_sec':   int(loc['frame_duration_sec']),
                    'session_duration_min': int(loc['session_duration_min']),
                }
            print(f"✓ Loaded {len(presets)} location presets from {os.path.basename(json_path)}")
            return presets
        except FileNotFoundError:
            print(f"⚠ location_clinical_presets.json not found — using built-in presets")
            return dict(cls._BUILTIN_PRESETS)
        except Exception as e:
            print(f"⚠ Could not load presets JSON: {e} — using built-in presets")
            return dict(cls._BUILTIN_PRESETS)

    def __init__(self, parent, callback):
        self.parent   = parent
        self.callback = callback
        self.result   = None
        self.presets  = self._load_presets()

        root_window = parent.root if hasattr(parent, 'root') else parent
        self.dialog = tk.Toplevel(root_window)
        self.dialog.title("📋 Digital Master Record — New Session")
        self.dialog.geometry("650x700")
        self.dialog.transient(root_window)
        self.dialog.grab_set()

        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - 325
        y = (self.dialog.winfo_screenheight() // 2) - 350
        self.dialog.geometry(f"+{x}+{y}")

        self._create_ui()

    def _create_ui(self):
        header = ttk.Frame(self.dialog)
        header.pack(fill=tk.X, pady=15, padx=20)
        ttk.Label(header, text="Digital Master Record (DMR)",
                  font=('Arial', 18, 'bold')).pack()
        ttk.Label(header, text="Enter session information before recording",
                  font=('Arial', 10), foreground="blue").pack(pady=(5, 0))

        canvas = tk.Canvas(self.dialog)
        scrollbar = ttk.Scrollbar(self.dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>",
                              lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 0))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 20))

        # Auto-captured info
        auto_frame = ttk.LabelFrame(scrollable_frame, text="📅 Auto-Captured", padding=15)
        auto_frame.pack(fill=tk.X, pady=(10, 15), padx=10)
        now = datetime.now()
        self.session_id = f"DMR-{now.strftime('%Y%m%d-%H%M%S')}"
        info_grid = ttk.Frame(auto_frame)
        info_grid.pack()
        for r, (lbl, val) in enumerate([("Session ID:", self.session_id),
                                         ("Date:", now.strftime("%Y-%m-%d")),
                                         ("Time:", now.strftime("%H:%M:%S"))]):
            ttk.Label(info_grid, text=lbl, font=('Arial', 9, 'bold')).grid(
                row=r, column=0, sticky=tk.W, pady=3, padx=(0, 10))
            ttk.Label(info_grid, text=val, font=('Arial', 9),
                      foreground="darkblue").grid(row=r, column=1, sticky=tk.W)

        # Patient
        patient_frame = ttk.LabelFrame(scrollable_frame, text="👤 Patient Information *", padding=15)
        patient_frame.pack(fill=tk.X, pady=(0, 15), padx=10)
        ttk.Label(patient_frame, text="Patient ID:", font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        self.entry_patient_id = ttk.Entry(patient_frame, width=30, font=('Arial', 11))
        self.entry_patient_id.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(patient_frame, text="Date of Birth:", font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        self.entry_patient_dob = ttk.Entry(patient_frame, width=20, font=('Arial', 11))
        self.entry_patient_dob.pack(anchor=tk.W, pady=(0, 5))
        ttk.Label(patient_frame, text="Format: YYYY-MM-DD",
                  font=('Arial', 8), foreground="gray").pack(anchor=tk.W)

        # Treatment location
        location_frame = ttk.LabelFrame(scrollable_frame, text="📍 Treatment Location *", padding=15)
        location_frame.pack(fill=tk.X, pady=(0, 15), padx=10)
        ttk.Label(location_frame, text="Select body part being treated:",
                  font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 10))
        self.location_var = tk.StringVar(value="")
        locations = [(v['display'], k) for k, v in self.presets.items()]
        loc_cont = ttk.Frame(location_frame)
        loc_cont.pack(fill=tk.X)
        left_locs  = ttk.Frame(loc_cont)
        left_locs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15))
        right_locs = ttk.Frame(loc_cont)
        right_locs.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        half = (len(locations) + 1) // 2
        for i, (label, value) in enumerate(locations):
            p = left_locs if i < half else right_locs
            ttk.Radiobutton(p, text=label, variable=self.location_var,
                            value=value,
                            command=self._on_location_change).pack(anchor=tk.W, pady=2)

        self.lbl_loc_err = ttk.Label(location_frame, text="",
                                     foreground="red", font=('Arial', 8))
        self.lbl_loc_err.pack(anchor=tk.W)

        # ── Session Parameters (auto-calculated from location preset) ─────────
        params_frame = ttk.LabelFrame(scrollable_frame,
                                      text="⏱ Session Parameters (auto-calculated from location)",
                                      padding=15)
        params_frame.pack(fill=tk.X, pady=(0, 15), padx=10)

        # Mode toggle
        mode_row = ttk.Frame(params_frame)
        mode_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(mode_row, text="Calculation mode:",
                  font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        self.calc_mode_var = tk.StringVar(value="fix_frames")
        ttk.Radiobutton(mode_row, text="Fix frame duration → calculate # frames",
                        variable=self.calc_mode_var, value="fix_frames",
                        command=self._recalculate).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(mode_row, text="Fix # frames → calculate frame duration",
                        variable=self.calc_mode_var, value="fix_num_frames",
                        command=self._recalculate).pack(side=tk.LEFT)

        # Row 1: Session duration
        row1 = ttk.Frame(params_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="Session duration (min):", width=26,
                  font=('Arial', 9)).pack(side=tk.LEFT)
        self.session_dur_var = tk.IntVar(value=15)
        self.spin_session_dur = ttk.Spinbox(row1, from_=5, to=60, increment=1,
                                            textvariable=self.session_dur_var, width=6,
                                            font=('Arial', 10, 'bold'),
                                            command=self._recalculate)
        self.spin_session_dur.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(row1, text="min", font=('Arial', 9)).pack(side=tk.LEFT)

        # Row 2: Frame duration
        row2 = ttk.Frame(params_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="Frame duration (sec):", width=26,
                  font=('Arial', 9)).pack(side=tk.LEFT)
        self.frame_dur_var = tk.IntVar(value=3)
        self.spin_frame_dur = ttk.Spinbox(row2, from_=1, to=10, increment=1,
                                          textvariable=self.frame_dur_var, width=6,
                                          font=('Arial', 10, 'bold'),
                                          command=self._recalculate)
        self.spin_frame_dur.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(row2, text="sec", font=('Arial', 9)).pack(side=tk.LEFT)

        # Row 3: Num frames
        row3 = ttk.Frame(params_frame)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="Number of frames:", width=26,
                  font=('Arial', 9)).pack(side=tk.LEFT)
        self.num_frames_var = tk.IntVar(value=300)
        self.spin_num_frames = ttk.Spinbox(row3, from_=10, to=2000, increment=10,
                                           textvariable=self.num_frames_var, width=6,
                                           font=('Arial', 10, 'bold'),
                                           command=self._recalculate)
        self.spin_num_frames.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(row3, text="frames", font=('Arial', 9)).pack(side=tk.LEFT)

        # Result summary label
        self.lbl_params_summary = ttk.Label(params_frame,
                                            text="← Select a location to auto-fill",
                                            font=('Arial', 8, 'italic'), foreground="gray")
        self.lbl_params_summary.pack(anchor=tk.W, pady=(6, 0))

        self._update_spinbox_states()  # set initial enabled/disabled state

        # Practitioner
        pract_frame = ttk.LabelFrame(scrollable_frame, text="👨‍⚕️ Practitioner *", padding=15)
        pract_frame.pack(fill=tk.X, pady=(0, 15), padx=10)
        ttk.Label(pract_frame, text="Physical Therapist (PT) ID:",
                  font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        self.entry_pt_id = ttk.Entry(pract_frame, width=30, font=('Arial', 11))
        self.entry_pt_id.pack(fill=tk.X, pady=(0, 5))

        # Notes
        notes_frame = ttk.LabelFrame(scrollable_frame, text="📝 Notes (Optional)", padding=15)
        notes_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15), padx=10)
        self.text_notes = tk.Text(notes_frame, height=4, font=('Arial', 9), wrap=tk.WORD)
        self.text_notes.pack(fill=tk.BOTH, expand=True)

        # Auto-export checkbox
        export_frame = ttk.LabelFrame(scrollable_frame, text="💾 Export Settings", padding=10)
        export_frame.pack(fill=tk.X, pady=(0, 15), padx=10)
        self.auto_export_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(export_frame, text="Auto-export CSV when saving DMR",
                        variable=self.auto_export_var).pack(anchor=tk.W)

        # Buttons
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="✓ Start DMR Session",
                   command=self.validate_and_start, width=22).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="✗ Cancel",
                   command=self.cancel, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Label(self.dialog, text="* = Required field",
                  font=('Arial', 8), foreground="red").pack(pady=(0, 10))

        self.entry_patient_id.focus()

    def _on_location_change(self):
        """Auto-fill session parameters when a location is selected."""
        key = self.location_var.get()
        if key in self.presets:
            p = self.presets[key]
            self.session_dur_var.set(p['session_duration_min'])
            self.frame_dur_var.set(p['frame_duration_sec'])
            self.lbl_loc_err.config(text="")
            self._recalculate()

    def _recalculate(self, *_):
        """Recalculate the dependent field based on the current mode."""
        try:
            mode      = self.calc_mode_var.get()
            sess_min  = max(1, int(float(self.session_dur_var.get())))
            frame_sec = max(1, int(float(self.frame_dur_var.get())))
            num_fr    = max(1, int(float(self.num_frames_var.get())))

            sess_sec = sess_min * 60

            if mode == "fix_frames":
                # Frame duration is the fixed input → calculate num_frames
                calculated = max(1, sess_sec // frame_sec)
                self.num_frames_var.set(calculated)
                summary = (f"  {sess_min} min  ÷  {frame_sec} sec/frame  "
                           f"=  {calculated} frames")
            else:
                # num_frames is the fixed input → calculate frame_duration
                calculated = max(1, sess_sec // num_fr)
                self.frame_dur_var.set(calculated)
                summary = (f"  {sess_min} min  ÷  {num_fr} frames  "
                           f"=  {calculated} sec/frame")

            self.lbl_params_summary.config(
                text=summary, foreground="darkgreen",
                font=('Arial', 8, 'bold'))
        except (ValueError, tk.TclError):
            pass
        self._update_spinbox_states()

    def _update_spinbox_states(self):
        """Enable/disable spinboxes based on calculation mode."""
        mode = self.calc_mode_var.get()
        if mode == "fix_frames":
            self.spin_session_dur.config(state="normal")
            self.spin_frame_dur.config(state="normal")
            self.spin_num_frames.config(state="disabled")
        else:
            self.spin_session_dur.config(state="normal")
            self.spin_frame_dur.config(state="disabled")
            self.spin_num_frames.config(state="normal")

    def validate_and_start(self):
        patient_id  = self.entry_patient_id.get().strip()
        patient_dob = self.entry_patient_dob.get().strip()
        location    = self.location_var.get()
        pt_id       = self.entry_pt_id.get().strip()
        notes       = self.text_notes.get("1.0", tk.END).strip()

        errors = []
        # Reset field highlights
        self.entry_patient_id.config(foreground="black")
        self.entry_patient_dob.config(foreground="black")
        self.entry_pt_id.config(foreground="black")

        if not patient_id:
            errors.append("• Patient ID")
            self.entry_patient_id.config(foreground="red")
        if not patient_dob:
            errors.append("• Date of Birth")
            self.entry_patient_dob.config(foreground="red")
        if not location:
            errors.append("• Treatment Location")
            self.lbl_loc_err.config(text="⚠ Please select a location")
        if not pt_id:
            errors.append("• PT ID")
            self.entry_pt_id.config(foreground="red")
        if errors:
            messagebox.showerror("Missing Required Fields",
                "Please complete the following required fields:\n\n" +
                "\n".join(errors))
            return

        location_names = {k: v['display'] for k, v in self.presets.items()}
        now = datetime.now()

        # Resolve final frame parameters
        try:
            frame_duration_sec   = max(1, int(float(self.frame_dur_var.get())))
            session_duration_min = max(1, int(float(self.session_dur_var.get())))
            num_frames           = max(1, int(float(self.num_frames_var.get())))
        except (ValueError, tk.TclError):
            frame_duration_sec   = 3
            session_duration_min = 15
            num_frames           = 300

        self.result = {
            'session_id': self.session_id,
            'timestamp': now.isoformat(),
            'date': now.strftime("%Y-%m-%d"),
            'time': now.strftime("%H:%M:%S"),
            'patient_id': patient_id,
            'patient_dob': patient_dob,
            'treatment_location': location,
            'treatment_location_display': location_names.get(location, location),
            'treatment_type': 'pt_protocol',
            'treatment_type_display': 'PT Master Protocol',
            'pt_id': pt_id,
            'notes': notes,
            'auto_export_csv': self.auto_export_var.get(),
            'frame_duration_sec':   frame_duration_sec,
            'session_duration_min': session_duration_min,
            'num_frames_planned':   num_frames,
        }
        self.dialog.withdraw()   # Hide immediately (Windows paint lag fix)
        self.dialog.update()
        self.callback(self.result)
        self.dialog.destroy()

    def cancel(self):
        self.dialog.destroy()
        self.callback(None)


# ============================================================================
# DMR SESSION INFO BAR
# ============================================================================

class DMRSessionInfo(ttk.Frame):
    """Thin status bar showing active DMR session metadata."""

    def __init__(self, parent):
        super().__init__(parent)
        self.info_label = ttk.Label(
            self,
            text="No active DMR session — click ⏺ Record to start",
            font=('Arial', 9), foreground="gray")
        self.info_label.pack(fill=tk.X, padx=5, pady=3)

    def set_session(self, metadata):
        if metadata:
            parts = [
                f"📋 {metadata['session_id']}",
                f"Patient: {metadata['patient_id']}",
                f"Location: {metadata['treatment_location_display']}",
                f"PT: {metadata['pt_id']}",
            ]
            self.info_label.config(text=" | ".join(parts), foreground="darkgreen")
        else:
            self.clear_session()

    def clear_session(self):
        self.info_label.config(
            text="No active DMR session — click ⏺ Record to start",
            foreground="gray")


# ============================================================================
# FRAME VIEWER — clinical review of recorded DMR frames
# ============================================================================

class FrameViewer:
    """Frame-by-frame viewer for clinical review of DMR sessions."""

    def __init__(self, parent, frames, pressure_zones, session_metadata=None):
        print(f"\n=== FrameViewer: {len(frames)} frames ===")
        self.parent       = parent
        self.frames       = frames
        self.pressure_zones = pressure_zones
        self.session_metadata = session_metadata
        self.current_frame_idx = 0
        self.is_playing   = False
        self.play_speed   = 100
        self._slider_updating = False

        self.viewer = tk.Toplevel(parent)
        self.viewer.title("📊 Frame Viewer — Clinical Review")
        self.viewer.geometry("900x800")
        self.viewer.transient(parent)
        self.viewer.update_idletasks()
        x = (self.viewer.winfo_screenwidth() // 2) - 450
        y = (self.viewer.winfo_screenheight() // 2) - 400
        self.viewer.geometry(f"+{x}+{y}")
        self._create_ui()
        self._display_frame(0)

    def _create_ui(self):
        header = ttk.Frame(self.viewer)
        header.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(header, text="Frame Viewer — Clinical Review",
                  font=('Arial', 16, 'bold')).pack()
        if self.session_metadata:
            ttk.Label(header,
                      text=(f"Session: {self.session_metadata.get('session_id','N/A')} | "
                            f"Patient: {self.session_metadata.get('patient_id','N/A')} | "
                            f"Location: {self.session_metadata.get('treatment_location_display','N/A')}"),
                      font=('Arial', 9), foreground="darkblue").pack(pady=(5, 0))
        ttk.Label(header, text=f"Total Frames: {len(self.frames)}",
                  font=('Arial', 10, 'bold')).pack(pady=(5, 0))
        ttk.Separator(self.viewer, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        main = ttk.Frame(self.viewer)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Frame info
        meta_frame = ttk.LabelFrame(main, text="📋 Frame Info", padding=10)
        meta_frame.pack(fill=tk.X, pady=(0, 10))
        grid = ttk.Frame(meta_frame)
        grid.pack(fill=tk.X)
        ttk.Label(grid, text="Frame:", font=('Arial', 9, 'bold')).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.lbl_frame_num = ttk.Label(grid, text="0 / 0", font=('Arial', 9))
        self.lbl_frame_num.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))
        ttk.Label(grid, text="Elapsed:", font=('Arial', 9, 'bold')).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.lbl_timestamp = ttk.Label(grid, text="0.0 s", font=('Arial', 9))
        self.lbl_timestamp.grid(row=1, column=1, sticky=tk.W, padx=(5, 0))
        ttk.Label(grid, text="Pattern:", font=('Arial', 9, 'bold')).grid(row=2, column=0, sticky=tk.W, pady=2)
        self.lbl_pattern = ttk.Label(grid, text="N/A", font=('Arial', 9))
        self.lbl_pattern.grid(row=2, column=1, sticky=tk.W, padx=(5, 0))

        # Stats
        stats_frame = ttk.LabelFrame(main, text="📊 Pressure Stats", padding=10)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        sg = ttk.Frame(stats_frame)
        sg.pack(fill=tk.X)
        for r, (lbl, attr) in enumerate([("Peak:", "lbl_peak"), ("Average:", "lbl_avg"),
                                          ("Zone:", "lbl_zone"), ("Active:", "lbl_active")]):
            ttk.Label(sg, text=lbl, font=('Arial', 9, 'bold')).grid(row=r, column=0, sticky=tk.W, pady=3)
            widget = ttk.Label(sg, text="0.0 kPa", font=('Arial', 9 if attr != 'lbl_zone' else 10))
            widget.grid(row=r, column=1, sticky=tk.W, padx=(5, 0))
            setattr(self, attr, widget)

        # Orientation
        orient_frame = ttk.LabelFrame(main, text="🔄 Orientation (saved to DMR)", padding=10)
        orient_frame.pack(fill=tk.X, pady=(0, 10))
        og = ttk.Frame(orient_frame)
        og.pack(fill=tk.X)
        for r, (lbl, attr) in enumerate([("Roll:", "lbl_roll"), ("Pitch:", "lbl_pitch"), ("Yaw:", "lbl_yaw")]):
            ttk.Label(og, text=lbl, font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, pady=2)
            widget = ttk.Label(og, text="0°", font=('Arial', 8, 'bold'))
            widget.grid(row=r, column=1, sticky=tk.W, padx=(5, 0))
            setattr(self, attr, widget)

        # Zone ranges
        zones_frame = ttk.LabelFrame(main, text="📊 Zone Ranges", padding=8)
        zones_frame.pack(fill=tk.X)
        zones_info = [
            ("🔵 Therapeutic Min:", f"{self.pressure_zones['therapeutic_min']:.0f} kPa"),
            ("🟢 Therapeutic Max:", f"{self.pressure_zones['therapeutic_max']:.0f} kPa"),
            ("🔴 Caution Max:",     f"{self.pressure_zones['caution_max']:.0f} kPa"),
        ]
        for label, value in zones_info:
            row = ttk.Frame(zones_frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=label, font=('Arial', 8)).pack(side=tk.LEFT)
            ttk.Label(row, text=value,  font=('Arial', 8, 'bold')).pack(side=tk.RIGHT)

        # Navigation
        ttk.Separator(self.viewer, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)
        nav_frame = ttk.Frame(self.viewer)
        nav_frame.pack(fill=tk.X, padx=10, pady=10)

        pb = ttk.Frame(nav_frame)
        pb.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(pb, text="Playback:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        self.btn_play = ttk.Button(pb, text="▶ Play", command=self.toggle_playback, width=10)
        self.btn_play.pack(side=tk.LEFT, padx=2)

        sf = ttk.Frame(nav_frame)
        sf.pack(fill=tk.X, pady=(0, 10))
        self.frame_slider = ttk.Scale(sf, from_=0, to=max(len(self.frames) - 1, 0),
                                      orient=tk.HORIZONTAL, command=self._on_slider_change)
        self.frame_slider.pack(fill=tk.X)

        bf = ttk.Frame(nav_frame)
        bf.pack()
        for text, cmd in [("⏮ First", self.first_frame), ("◀ Prev", self.prev_frame),
                           ("Next ▶", self.next_frame), ("Last ⏭", self.last_frame)]:
            ttk.Button(bf, text=text, command=cmd, width=10).pack(side=tk.LEFT, padx=2)

        ttk.Button(nav_frame, text="✓ Close Viewer",
                   command=self.viewer.destroy, width=20).pack(pady=(10, 0))

    def _display_frame(self, idx):
        if idx < 0 or idx >= len(self.frames):
            return
        self.current_frame_idx = idx
        frame = self.frames[idx]
        if 'sensor_data' not in frame:
            messagebox.showerror("Data Error", f"Frame {idx} is missing sensor_data.")
            return

        self.lbl_frame_num.config(text=f"{idx + 1} / {len(self.frames)}")
        fp_ms    = frame.get('frame_period_ms', 2000)
        elapsed  = idx * fp_ms / 1000.0
        self.lbl_timestamp.config(text=f"{elapsed:.1f} s")

        pattern_names = {
            "idle": "No Activity", "ball_grip": "Ball Grip",
            "precision_pinch": "Precision Pinch", "power_grip": "Power Grip",
            "pt_shoulder": "PT: Shoulder", "pt_elbow": "PT: Elbow",
            "pt_wrist": "PT: Wrist", "three_finger": "Three-Finger",
            "lateral_pinch": "Lateral Pinch",
        }
        p = frame.get('demo_pattern', 'N/A')
        self.lbl_pattern.config(text=pattern_names.get(p, p) if p and p != 'N/A' else "N/A")

        sensor_data = np.array(frame.get('sensor_data', [0] * N_SENSORS))
        active = sensor_data > 1.0
        if np.any(active):
            peak = float(np.max(sensor_data))
            avg  = float(np.mean(sensor_data[active]))
            n    = int(np.sum(active))
            zones = self.pressure_zones
            if avg < zones['therapeutic_min']:
                zone, zc = "Below Therapeutic", "blue"
            elif avg <= zones['therapeutic_max']:
                zone, zc = "Therapeutic ✓", "green"
            elif avg <= zones['caution_max']:
                zone, zc = "Above Therapeutic", "orange"
            else:
                zone, zc = "CAUTION", "red"
        else:
            peak = avg = 0.0; n = 0; zone = "No Data"; zc = "gray"

        self.lbl_peak.config(text=f"{peak:.1f} kPa")
        self.lbl_avg.config(text=f"{avg:.1f} kPa")
        self.lbl_zone.config(text=zone, foreground=zc)
        self.lbl_active.config(text=f"{n} / {N_SENSORS}")

        orient = frame.get('hand_orientation', {})
        self.lbl_roll.config(text=f"{orient.get('roll',0):.1f}°")
        self.lbl_pitch.config(text=f"{orient.get('pitch',0):.1f}°")
        self.lbl_yaw.config(text=f"{orient.get('yaw',0):.1f}°")
        self._slider_updating = True
        self.frame_slider.set(idx)
        self._slider_updating = False

    def _on_slider_change(self, value):
        if self._slider_updating:
            return
        self._display_frame(int(float(value)))

    def first_frame(self):  self._display_frame(0)
    def last_frame(self):   self._display_frame(len(self.frames) - 1)
    def prev_frame(self):
        if self.current_frame_idx > 0:
            self._display_frame(self.current_frame_idx - 1)
    def next_frame(self):
        if self.current_frame_idx < len(self.frames) - 1:
            self._display_frame(self.current_frame_idx + 1)

    def toggle_playback(self):
        if self.is_playing:
            self.is_playing = False
            self.btn_play.config(text="▶ Play")
        else:
            self.is_playing = True
            self.btn_play.config(text="⏸ Pause")
            self._play_next()

    def _play_next(self):
        if not self.is_playing:
            return
        if self.current_frame_idx < len(self.frames) - 1:
            self.next_frame()
            self.viewer.after(self.play_speed, self._play_next)
        else:
            self.is_playing = False
            self.btn_play.config(text="▶ Play")


# ============================================================================
# INTERACTIVE ZONE CONFIGURATION DIALOG
# ============================================================================

class InteractiveZoneDialog:
    """Live slider-based pressure zone configurator."""

    def __init__(self, parent, current_zones, callback):
        self.callback = callback
        self.settings_changed = False

        self.current_zones = current_zones.copy()
        self.temp_zones    = current_zones.copy()

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("⚙️ Configure PT Pressure Zones")
        self.dialog.geometry("900x650")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - 450
        y = (self.dialog.winfo_screenheight() // 2) - 325
        self.dialog.geometry(f"+{x}+{y}")
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_close)

        self._create_ui()
        self._update_preview()

    def _create_ui(self):
        ttk.Label(self.dialog, text="Configure PT Pressure Zones",
                  font=('Arial', 16, 'bold')).pack(pady=10)
        ttk.Label(self.dialog, text="Drag sliders to adjust — watch colors change in real-time!",
                  font=('Arial', 10), foreground="blue").pack()

        main = ttk.Frame(self.dialog)
        main.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        left  = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        right = ttk.LabelFrame(main, text="👁 LIVE PREVIEW", padding=10)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._create_sliders(left)
        self._create_preview(right)

        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="✓ Save & Exit",     command=self.save_and_exit, width=18).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="✗ Discard Changes", command=self.discard_changes, width=18).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="↺ Reset to Default (20-45-60)",
                   command=self.reset_default, width=28).pack(side=tk.LEFT, padx=5)

    def _create_sliders(self, parent):
        info = ttk.Label(parent,
                         text="Drag sliders below to adjust zone boundaries.\n"
                              "Watch the preview update immediately!",
                         font=('Arial', 9), foreground="navy", justify=tk.LEFT)
        info.pack(pady=(0, 10), anchor=tk.W)

        # Min slider
        f1 = ttk.LabelFrame(parent, text="🔵 → 🟢  Therapeutic MINIMUM", padding=12)
        f1.pack(fill=tk.X, pady=8)
        ttk.Label(f1, text="Pressure below = BLUE (too low)  |  Above = GREEN",
                  font=('Arial', 8), foreground="gray").pack(anchor=tk.W, pady=(0, 5))
        self.var_min = tk.DoubleVar(value=self.current_zones['therapeutic_min'])
        sf1 = ttk.Frame(f1); sf1.pack(fill=tk.X, pady=5)
        self.lbl_min = ttk.Label(sf1, text=f"{self.var_min.get():.1f} kPa",
                                 font=('Arial', 14, 'bold'), foreground="blue", width=12)
        self.lbl_min.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Scale(sf1, from_=5, to=50, orient=tk.HORIZONTAL, variable=self.var_min,
                  command=self._on_slider_change).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Max slider
        f2 = ttk.LabelFrame(parent, text="🟢 → 🟡  Therapeutic MAXIMUM", padding=12)
        f2.pack(fill=tk.X, pady=8)
        ttk.Label(f2, text="Pressure below = GREEN (therapeutic)  |  Above = YELLOW",
                  font=('Arial', 8), foreground="gray").pack(anchor=tk.W, pady=(0, 5))
        self.var_max = tk.DoubleVar(value=self.current_zones['therapeutic_max'])
        sf2 = ttk.Frame(f2); sf2.pack(fill=tk.X, pady=5)
        self.lbl_max = ttk.Label(sf2, text=f"{self.var_max.get():.1f} kPa",
                                 font=('Arial', 14, 'bold'), foreground="green", width=12)
        self.lbl_max.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Scale(sf2, from_=20, to=70, orient=tk.HORIZONTAL, variable=self.var_max,
                  command=self._on_slider_change).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Caution slider
        f3 = ttk.LabelFrame(parent, text="🟡 → 🔴  CAUTION Maximum", padding=12)
        f3.pack(fill=tk.X, pady=8)
        ttk.Label(f3, text="Pressure below = YELLOW (high)  |  Above = RED (danger!)",
                  font=('Arial', 8), foreground="gray").pack(anchor=tk.W, pady=(0, 5))
        self.var_caut = tk.DoubleVar(value=self.current_zones['caution_max'])
        sf3 = ttk.Frame(f3); sf3.pack(fill=tk.X, pady=5)
        self.lbl_caut = ttk.Label(sf3, text=f"{self.var_caut.get():.1f} kPa",
                                  font=('Arial', 14, 'bold'), foreground="orange", width=12)
        self.lbl_caut.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Scale(sf3, from_=30, to=90, orient=tk.HORIZONTAL, variable=self.var_caut,
                  command=self._on_slider_change).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Summary
        sf = ttk.LabelFrame(parent, text="📋 Current Zone Settings", padding=10)
        sf.pack(fill=tk.X, pady=(15, 8))
        self.lbl_summary = ttk.Label(sf, text="", font=('Arial', 9), justify=tk.LEFT)
        self.lbl_summary.pack()

        # Presets
        pf = ttk.LabelFrame(parent, text="🎯 Quick Presets", padding=10)
        pf.pack(fill=tk.X, pady=8)
        presets = [
            ("Standard PT (General)",              20, 45, 60),
            ("Soft Tissue Mobilization (Light)",   15, 35, 50),
            ("Joint Mobilization Grade IV (Strong)", 30, 55, 75),
            ("Lymphatic Drainage (Very Light)",    5,  15, 25),
        ]
        for name, mn, mx, ca in presets:
            ttk.Button(pf, text=name,
                       command=lambda m=mn, x=mx, c=ca: self.apply_preset(m, x, c)
                       ).pack(fill=tk.X, pady=2)

    def _create_preview(self, parent):
        ttk.Label(parent, text="Sample fingers at different pressures:",
                  font=('Arial', 10, 'bold')).pack(pady=(0, 5))
        ttk.Label(parent, text="Watch how colors change as you drag sliders!",
                  font=('Arial', 9), foreground="blue").pack(pady=(0, 10))
        self.preview_fig = Figure(figsize=(7, 9), dpi=85)
        self.preview_ax  = self.preview_fig.add_subplot(111)
        self.preview_canvas = FigureCanvasTkAgg(self.preview_fig, parent)
        self.preview_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _on_slider_change(self, value=None):
        self.settings_changed = True
        self.lbl_min.config(text=f"{self.var_min.get():.1f} kPa")
        self.lbl_max.config(text=f"{self.var_max.get():.1f} kPa")
        self.lbl_caut.config(text=f"{self.var_caut.get():.1f} kPa")
        self.temp_zones['therapeutic_min'] = self.var_min.get()
        self.temp_zones['therapeutic_max'] = self.var_max.get()
        self.temp_zones['caution_max']     = self.var_caut.get()
        self.lbl_summary.config(
            text=f"🔵 BLUE:   < {self.var_min.get():.1f} kPa\n"
                 f"🟢 GREEN:  {self.var_min.get():.1f} – {self.var_max.get():.1f} kPa\n"
                 f"🟡 YELLOW: {self.var_max.get():.1f} – {self.var_caut.get():.1f} kPa\n"
                 f"🔴 RED:    > {self.var_caut.get():.1f} kPa")
        self._update_preview()

    def _update_preview(self):
        ax  = self.preview_ax
        ax.clear()
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 18)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title('Live Zone Preview', fontsize=14, fontweight='bold')

        sample_pressures = [0, 10, 25, 40, 55, 70]
        y_positions = [14, 11, 8, 5, 2]
        for i, p in enumerate(sample_pressures[:5]):
            color = self._get_color(p)
            zone  = self._get_zone_name(p)
            rect = Rectangle((1, y_positions[i]), 3, 2, facecolor=color,
                              edgecolor='black', linewidth=2, alpha=0.85)
            ax.add_patch(rect)
            ax.text(2.5, y_positions[i] + 1, f"{p} kPa\n{zone}",
                    ha='center', va='center', fontsize=9, fontweight='bold',
                    color='white' if p > 15 else 'black')
        ax.text(5, 16.5, "Zone legend:", ha='left', fontsize=9, fontweight='bold')
        ax.text(5, 15.5, f"🔵 < {self.temp_zones['therapeutic_min']:.0f} kPa", ha='left', fontsize=8, color='#4A90E2')
        ax.text(5, 14.0, f"🟢 {self.temp_zones['therapeutic_min']:.0f}–{self.temp_zones['therapeutic_max']:.0f} kPa", ha='left', fontsize=8, color='#4CAF50')
        ax.text(5, 12.5, f"🟡 {self.temp_zones['therapeutic_max']:.0f}–{self.temp_zones['caution_max']:.0f} kPa", ha='left', fontsize=8, color='#FFA726')
        ax.text(5, 11.0, f"🔴 > {self.temp_zones['caution_max']:.0f} kPa", ha='left', fontsize=8, color='#EF5350')
        self.preview_canvas.draw()

    def _get_color(self, pressure):
        z = self.temp_zones
        if pressure < 1:                             return '#E0E0E0'
        elif pressure < z['therapeutic_min']:        return '#4A90E2'
        elif pressure <= z['therapeutic_max']:       return '#4CAF50'
        elif pressure <= z['caution_max']:           return '#FFA726'
        else:                                        return '#EF5350'

    def _get_zone_name(self, pressure):
        z = self.temp_zones
        if pressure < 1:                             return "None"
        elif pressure < z['therapeutic_min']:        return "Low"
        elif pressure <= z['therapeutic_max']:       return "Good ✓"
        elif pressure <= z['caution_max']:           return "High"
        else:                                        return "Danger!"

    def apply_preset(self, mn, mx, ca):
        self.var_min.set(mn); self.var_max.set(mx); self.var_caut.set(ca)
        self._on_slider_change()

    def reset_default(self):
        self.apply_preset(20, 45, 60)

    def save_zones(self):
        mn = self.var_min.get(); mx = self.var_max.get(); ca = self.var_caut.get()
        if mn >= mx:
            messagebox.showerror("Invalid", f"MIN ({mn:.1f}) must be < MAX ({mx:.1f})"); return
        if mx >= ca:
            messagebox.showerror("Invalid", f"MAX ({mx:.1f}) must be < CAUTION ({ca:.1f})"); return
        self.callback({'therapeutic_min': mn, 'therapeutic_max': mx, 'caution_max': ca})
        messagebox.showinfo("✓ Zones Updated",
            f"🔵 BLUE:   < {mn:.1f} kPa\n"
            f"🟢 GREEN:  {mn:.1f} – {mx:.1f} kPa ✓\n"
            f"🟡 YELLOW: {mx:.1f} – {ca:.1f} kPa\n"
            f"🔴 RED:    > {ca:.1f} kPa")
        self.dialog.destroy()

    def save_and_exit(self):
        self.save_zones()

    def discard_changes(self):
        if self.settings_changed:
            if messagebox.askyesno("Discard Changes?", "Discard unsaved zone changes?"):
                self.dialog.destroy()
        else:
            self.dialog.destroy()

    def on_close(self):
        if self.settings_changed:
            r = messagebox.askyesnocancel("Save Changes?",
                "Save zone changes?\n\n• Yes: Save  • No: Discard  • Cancel: Keep editing")
            if r is True:   self.save_zones()
            elif r is False: self.dialog.destroy()
        else:
            self.dialog.destroy()


# ============================================================================
# MAIN APPLICATION — DMR Studio
# ============================================================================

class TactileSenseClinical:
    """
    DMR Studio: single-window application for recording and reviewing
    Digital Master Records.  No browser, no WebSocket, no HTML panels.
    """

    FINGER_RANGES = [range(0, 1), range(1, 2), range(2, 3),
                     range(3, 4), range(4, 5)]
    FINGER_NAMES  = ["Thumb", "Index", "Middle", "Ring", "Pinky"]

    def __init__(self, root):
        self.root = root
        self.root.title("TactileSense DMR Studio v1.0 — PT Robotic LLC")

        # Screen sizing
        try:
            import ctypes
            u32 = ctypes.windll.user32
            sw  = u32.GetSystemMetrics(0)
            sh  = u32.GetSystemMetrics(1)
            self.root.geometry(f"{sw}x{sh}+0+0")
        except Exception:
            self.root.geometry("1920x1080")

        # ── State ────────────────────────────────────────────────────────────
        self.sensor_mode       = "disconnected"
        self.is_recording      = False
        self.frame_count       = 0
        self.current_pattern   = "ball_grip"
        self.time_in_pattern   = 0
        self.sensor_data       = np.zeros(N_SENSORS, dtype=int)
        self.display_data      = np.zeros(N_SENSORS, dtype=int)

        self.current_session_metadata = None
        self.recorded_frames          = []
        self._session_saved           = False

        self.frame_period_ms          = 3000
        self.sample_buffer             = []
        self.last_frame_time          = 0
        self.frame_capture_scheduled  = False

        self.hand_orientation = {'roll': 0, 'pitch': 0, 'yaw': 0}
        self.active_fingers   = [True] * N_SENSORS   # per-finger enable toggle

        self.pressure_zones = {
            'therapeutic_min': 20,
            'therapeutic_max': 45,
            'caution_max':     60,
        }

        self.patterns = {
            "idle":           "No Activity",
            "ball_grip":      "Ball Grip (Full Hand)",
            "precision_pinch":"Precision Pinch",
            "power_grip":     "Power Grip",
            "pt_shoulder":    "PT: Shoulder Mobilization",
            "pt_elbow":       "PT: Elbow Mobilization",
            "pt_wrist":       "PT: Wrist Manipulation",
            "three_finger":   "Three-Finger Grip",
            "lateral_pinch":  "Lateral Pinch",
        }

        self._create_ui()
        self.update_loop()
        print("✓ DMR Studio loaded")
        print("✓ Save dir:", self._pt_dir())

    # ── File-system helpers ──────────────────────────────────────────────────

    def _get_default_dir(self):
        base = os.path.join(os.path.expanduser("~"), "TactileSense", "Protocols")
        for sub in ("PT_Protocols", "PTA_Protocols", "Robot_Executions"):
            os.makedirs(os.path.join(base, sub), exist_ok=True)
        csv_base = os.path.join(os.path.expanduser("~"), "TactileSense", "CSV_Exports")
        for sub in ("PT_CSV", "PTA_CSV"):
            os.makedirs(os.path.join(csv_base, sub), exist_ok=True)
        return base

    def _pt_dir(self):
        return os.path.join(self._get_default_dir(), "PT_Protocols")

    def _pt_csv_dir(self):
        return os.path.join(os.path.expanduser("~"), "TactileSense", "CSV_Exports", "PT_CSV")

    # ── UI construction ──────────────────────────────────────────────────────

    def _create_ui(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Sensor menu
        sensor_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Sensor", menu=sensor_menu)
        sensor_menu.add_command(label="🎭 Demo Simulator", command=self.connect_demo)
        sensor_menu.add_command(label="🧤 TactileGlove",   command=self.connect_real)
        sensor_menu.add_separator()
        sensor_menu.add_command(label="❌ Disconnect",      command=self.disconnect)

        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="⚙️ Pressure Zones (Interactive!)", command=self.configure_zones)
        if GloveVisualization3DWindow is not None:
            settings_menu.add_separator()
            settings_menu.add_command(label="🖐️ 3D Glove Visualization", command=self.show_3d_glove)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Save Session",  command=self.save_session)
        file_menu.add_command(label="Export Data",   command=self.export_data)

        # DMR menu
        dmr_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="DMR", menu=dmr_menu)
        dmr_menu.add_command(label="📋 New DMR",           command=self.start_new_dmr)
        dmr_menu.add_command(label="🎬 Review Frames",     command=self.view_frames)
        dmr_menu.add_separator()
        dmr_menu.add_command(label="📂 Load & Review DMR", command=self.load_and_review_dmr)
        dmr_menu.add_command(label="📁 Load Previous DMR", command=self.load_dmr)
        dmr_menu.add_command(label="📊 Export DMR Report", command=self.export_dmr_report)
        dmr_menu.add_separator()
        dmr_menu.add_command(label="ℹ️  About DMR",        command=self.show_about_dmr)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)

        # ── Two-column layout: controls | main visualization area ──────────────
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left column — scrollable controls (260px)
        left_outer = ttk.Frame(main, width=260)
        left_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 4))
        left_outer.pack_propagate(False)
        left_canvas = tk.Canvas(left_outer, width=244, highlightthickness=0, borderwidth=0)
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left = ttk.Frame(left_canvas)
        left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda e: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.bind_all("<MouseWheel>",
                             lambda e: left_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Right area — unified main panel (expands to fill)
        right_area = ttk.Frame(main)
        right_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._create_left_panel(left)
        self._create_main_panel(right_area)

        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(
            value="DMR Studio v1.0 — Select: Sensor → Demo Simulator or TactileGlove")
        ttk.Label(status_frame, textvariable=self.status_var,
                  relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.frame_var = tk.StringVar(value="Sensor: 0")
        ttk.Label(status_frame, textvariable=self.frame_var,
                  relief=tk.SUNKEN, width=15).pack(side=tk.RIGHT)

        # DMR session info bar above status
        self.dmr_session_widget = DMRSessionInfo(self.root)
        self.dmr_session_widget.pack(fill=tk.X, padx=5, pady=(2, 0), before=status_frame)

    def _create_left_panel(self, parent):
        """LEFT column — connection, recording controls, patterns, zones."""

        # ── Connection / Mode ─────────────────────────────────────────────────
        mode_box = ttk.LabelFrame(parent, text="🔌 Connection", padding=6)
        mode_box.pack(fill=tk.X, padx=5, pady=(6, 3))
        self.lbl_mode = ttk.Label(mode_box, text="⚠ NOT\nCONNECTED",
                                  font=('Arial', 11, 'bold'), foreground="red",
                                  justify=tk.CENTER)
        self.lbl_mode.pack(pady=2)

        # ── DMR Recording Controls ────────────────────────────────────────────
        rec_box = ttk.LabelFrame(parent, text="⏺ DMR Controls", padding=8)
        rec_box.pack(fill=tk.X, padx=5, pady=3)
        self.rec_box = rec_box

        btn_row = ttk.Frame(rec_box)
        btn_row.pack(fill=tk.X)
        self.btn_rec  = ttk.Button(btn_row, text="⏺ Record",
                                   command=self.toggle_record, width=12)
        self.btn_rec.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_stop = ttk.Button(btn_row, text="⏹ Stop & Save",
                                   command=self.stop_record, width=13, state="disabled")
        self.btn_stop.pack(side=tk.LEFT)

        self.lbl_rec = ttk.Label(rec_box, text="Click ⏺ Record to start",
                                 foreground="gray", font=('Arial', 8), wraplength=220)
        self.lbl_rec.pack(pady=(4, 0), anchor=tk.W)

        ttk.Separator(rec_box, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        ttk.Label(rec_box, text="Frame Duration (seconds):",
                  font=('Arial', 8, 'bold'), foreground="darkblue").pack(anchor=tk.W)
        self.frame_period_var = tk.IntVar(value=3)
        sf = ttk.Frame(rec_box)
        sf.pack(fill=tk.X, pady=(3, 0))
        ttk.Label(sf, text="Sec:", font=('Arial', 8)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(sf, from_=1, to=10, increment=1,
                    textvariable=self.frame_period_var, width=4,
                    font=('Arial', 10, 'bold'),
                    command=self._on_frame_period_change).pack(side=tk.LEFT)
        ttk.Label(sf, text="(set from session dialog)",
                  font=('Arial', 7), foreground="gray").pack(side=tk.LEFT, padx=(6, 0))
        self.lbl_frame_period = ttk.Label(rec_box,
                                          text="3 sec — awaiting session start",
                                          font=('Arial', 7), foreground="darkgreen")
        self.lbl_frame_period.pack(anchor=tk.W, pady=(2, 0))

        ttk.Separator(rec_box, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        self.auto_export_csv_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(rec_box, text="💾 Auto-export CSV on save",
                        variable=self.auto_export_csv_var).pack(anchor=tk.W)
        ttk.Label(rec_box, text="Saved to CSV_Exports/",
                  font=('Arial', 7), foreground="gray").pack(anchor=tk.W, padx=(20, 0))

        # ── Demo Patterns ─────────────────────────────────────────────────────
        self.demo_container = ttk.Frame(parent)

        pattern_box = ttk.LabelFrame(self.demo_container, text="🎭 Demo Pattern", padding=6)
        pattern_box.pack(fill=tk.X, padx=5, pady=3)
        self.pattern_var = tk.StringVar(value="ball_grip")
        c2 = tk.Canvas(pattern_box, height=100, highlightthickness=0)
        sb2 = ttk.Scrollbar(pattern_box, orient="vertical", command=c2.yview)
        cont = ttk.Frame(c2)
        cont.bind("<Configure>", lambda e: c2.configure(scrollregion=c2.bbox("all")))
        c2.create_window((0, 0), window=cont, anchor="nw")
        c2.configure(yscrollcommand=sb2.set)
        for key, name in self.patterns.items():
            ttk.Radiobutton(cont, text=name, variable=self.pattern_var,
                            value=key, command=self.change_pattern).pack(anchor=tk.W, pady=1)
        c2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Pressure Zones Summary ────────────────────────────────────────────
        zones_box = ttk.LabelFrame(parent, text="📊 Pressure Zones", padding=6)
        zones_box.pack(fill=tk.X, padx=5, pady=3)
        for emoji, rng, desc, color in [
            ("🔵", "< 20 kPa",  "Below therapeutic",  "blue"),
            ("🟢", "20–45 kPa", "Therapeutic ✓",      "darkgreen"),
            ("🟡", "45–60 kPa", "Above therapeutic",  "darkorange"),
            ("🔴", "> 60 kPa",  "Danger",             "red"),
        ]:
            fr = ttk.Frame(zones_box)
            fr.pack(fill=tk.X, pady=1)
            ttk.Label(fr, text=emoji, font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(fr, text=rng, font=('Arial', 8, 'bold'), foreground=color).pack(side=tk.LEFT)
            ttk.Label(fr, text=f"  {desc}", font=('Arial', 7), foreground="gray").pack(side=tk.LEFT)
        ttk.Button(zones_box, text="⚙️ Configure Zones",
                   command=self.configure_zones).pack(fill=tk.X, pady=(5, 0))

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN PANEL  (matches DMA schematic)
    # ┌──────────────────────────────┬─────────────────────────────────┐
    # │  📷 Reference Camera          │  🖐 Live Finger Pressure (vert) │
    # ├──────────────────────────────┴─────────────────────────────────┤
    # │           🧤 Tactile Glove — Live PT Pressure                  │
    # ├────────────────────────────────────────────────────────────────┤
    # │  📋 Session info  │  📋 Last Captured Frame  │  PT ID          │
    # └────────────────────────────────────────────────────────────────┘
    # ─────────────────────────────────────────────────────────────────────────

    def _create_main_panel(self, parent):
        """Main right area — only the welcome frame is built at startup.
        The execution panel is built lazily on first _show_execution_panel() call.
        """
        self._main_panel_parent = parent   # save for lazy build

        # ══════════════════════════════════════════════════════════════════════
        # WELCOME FRAME  (shown on launch and after every disconnect)
        # ══════════════════════════════════════════════════════════════════════
        self.welcome_frame = ttk.Frame(parent)
        self.welcome_frame.pack(fill=tk.BOTH, expand=True)

        wc = tk.Canvas(self.welcome_frame, bg='#f0f4f8', highlightthickness=0)
        wc.pack(fill=tk.BOTH, expand=True)

        def _draw_welcome(event=None):
            wc.delete("all")
            w = wc.winfo_width()  or 820
            h = wc.winfo_height() or 620
            cx = w // 2

            wc.create_rectangle(0, 0, w, h,   fill='#f0f4f8', outline='')
            wc.create_rectangle(0, 0, w, 6,   fill='#2c5f8a', outline='')

            wc.create_text(cx, h*0.17, text="TactileSense DMR Studio",
                           font=('Arial', 28, 'bold'), fill='#1a3a5c')
            wc.create_text(cx, h*0.26, text="Digital Master Record Edition",
                           font=('Arial', 14), fill='#5a7a9a')

            wc.create_line(cx-200, h*0.33, cx+200, h*0.33, fill='#c0d0e0', width=1)

            steps = [
                ("1", "Connect Sensor",
                 "Sensor menu  →  Demo Simulator  or  TactileGlove"),
                ("2", "Start a New DMR",
                 "DMR menu  →  New DMR  →  fill in patient details"),
                ("3", "Record & Save",
                 "Click  ⏺ Record  in the left panel to begin capture"),
            ]
            for i, (num, title, desc) in enumerate(steps):
                y = h * (0.43 + i * 0.17)
                wc.create_oval(cx-230, y-24, cx-182, y+24, fill='#2c5f8a', outline='')
                wc.create_text(cx-206, y, text=num,
                               font=('Arial', 16, 'bold'), fill='white')
                wc.create_text(cx-150, y-9, text=title,
                               font=('Arial', 13, 'bold'), fill='#1a3a5c', anchor='w')
                wc.create_text(cx-150, y+10, text=desc,
                               font=('Arial', 10), fill='#5a7a9a', anchor='w')

            wc.create_text(cx, h*0.93, fill='#8aaac8', font=('Arial', 9, 'italic'),
                           text="PT Robotic LLC  ·  TactileSense DMR Studio  ·  v1.0")

        wc.bind("<Configure>", _draw_welcome)
        self.root.after(150, _draw_welcome)

        # execution_panel will be built lazily — see _build_execution_panel()
        self.execution_panel = None

    def _build_execution_panel(self):
        """Build the full execution panel on first use (lazy init)."""
        parent = self._main_panel_parent
        ep = ttk.Frame(parent)
        self.execution_panel = ep

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(ep, bg='#1a3a5c', height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        tk.Label(hdr, text="📋  DMR Execution Panel",
                 font=('Arial', 16, 'bold'), bg='#1a3a5c', fg='white').pack(
                 side=tk.LEFT, padx=16, pady=10)

        hdr_right = tk.Frame(hdr, bg='#1a3a5c')
        hdr_right.pack(side=tk.RIGHT, padx=16)
        self.hdr_session = tk.Label(hdr_right, text="",
                                    font=('Arial', 9), bg='#1a3a5c', fg='#a8c8e8')
        self.hdr_session.pack(anchor=tk.E)
        self.hdr_patient = tk.Label(hdr_right, text="",
                                    font=('Arial', 9, 'bold'), bg='#1a3a5c', fg='#e8f4ff')
        self.hdr_patient.pack(anchor=tk.E)
        self.hdr_status = tk.Label(hdr_right, text="",
                                   font=('Arial', 9), bg='#1a3a5c', fg='#ff6b6b')
        self.hdr_status.pack(anchor=tk.E)

        # ── Content row: Camera | Glove + Bars ───────────────────────────────
        content = ttk.Frame(ep)
        content.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 2))

        # Camera
        cam_outer = ttk.LabelFrame(content, text="📷 Reference Camera", padding=4)
        cam_outer.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 4))
        self.camera_canvas = tk.Canvas(cam_outer, width=240, height=200,
                                       bg='#1a1a2e', highlightthickness=1,
                                       highlightbackground='#444')
        self.camera_canvas.pack()
        self._draw_camera_placeholder()

        # Glove + Bars
        right_content = ttk.LabelFrame(content, text="🧤 Finger TPS II — 5 Fingertip Sensors", padding=4)
        right_content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        rc_inner = ttk.Frame(right_content)
        rc_inner.pack(fill=tk.BOTH, expand=True)

        # Matplotlib glove
        self.hand_container = ttk.Frame(rc_inner)
        self.hand_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.hand_fig    = Figure(figsize=(4.5, 2.2), dpi=85)
        self.hand_ax     = self.hand_fig.add_subplot(111)
        self.hand_canvas = FigureCanvasTkAgg(self.hand_fig, self.hand_container)
        self.hand_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.hand_canvas.mpl_connect('button_press_event', self._on_hand_click)

        # Vertical pressure bars
        # ── Bottom info strip ─────────────────────────────────────────────────
        self.bottom_row = ttk.Frame(ep)
        self.bottom_row.pack(fill=tk.X, padx=6, pady=(2, 4))

        # Session
        sess_frame = ttk.LabelFrame(self.bottom_row, text="📋 Session", padding=6)
        sess_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        sg = ttk.Frame(sess_frame)
        sg.pack(fill=tk.X)
        for r, (txt, attr, default, color) in enumerate([
            ("Session:",  "lbl_sess_id",     "—",   "darkblue"),
            ("Patient:",  "lbl_sess_pat",    "—",   "black"),
            ("Frames:",   "lbl_sess_frames", "0",   "darkgreen"),
            ("Duration:", "lbl_sess_dur",    "0 s", "black"),
            ("Status:",   "lbl_sess_status", "Idle","gray"),
        ]):
            ttk.Label(sg, text=txt, font=('Arial', 8, 'bold')).grid(
                row=r, column=0, sticky=tk.W, pady=1)
            w = ttk.Label(sg, text=default, font=('Arial', 8),
                          foreground=color, wraplength=160)
            w.grid(row=r, column=1, sticky=tk.W, padx=(5, 0))
            setattr(self, attr, w)

        # Last Captured Frame
        lf_frame = ttk.LabelFrame(self.bottom_row, text="📋 Last Captured Frame", padding=6)
        lf_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self._lf_grid = ttk.Frame(lf_frame)
        self._lf_grid.pack(fill=tk.BOTH, expand=True)
        for r, (txt, attr, default, color) in enumerate([
            ("Frame #:",   "_lf_num",  "—", "darkblue"),
            ("Elapsed:",   "_lf_time", "—", "black"),
        ]):
            ttk.Label(self._lf_grid, text=txt,
                      font=('Arial', 8, 'bold')).grid(row=r, column=0, sticky=tk.W, pady=1)
            w = ttk.Label(self._lf_grid, text=default, font=('Arial', 8), foreground=color)
            w.grid(row=r, column=1, sticky=tk.W, padx=(4, 0))
            setattr(self, attr, w)
        ttk.Separator(self._lf_grid, orient=tk.HORIZONTAL).grid(
            row=2, column=0, columnspan=2, sticky='ew', pady=4)
        self._lf_finger_labels = []
        for i, fn in enumerate(["Thumb", "Index", "Middle", "Ring", "Pinky"]):
            ttk.Label(self._lf_grid, text=f"{fn}:",
                      font=('Arial', 8)).grid(row=3+i, column=0, sticky=tk.W, pady=1)
            w = ttk.Label(self._lf_grid, text="—",
                          font=('Arial', 8, 'bold'), foreground="gray")
            w.grid(row=3+i, column=1, sticky=tk.W, padx=(4, 0))
            self._lf_finger_labels.append(w)

        # Stats + PT ID
        stats_frame = ttk.LabelFrame(self.bottom_row, text="📊 Stats / PT ID", padding=6)
        stats_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sg2 = ttk.Frame(stats_frame)
        sg2.pack(anchor=tk.W)
        for r, (lbl, attr, default) in enumerate([
            ("Peak:",    "lbl_peak",   "0.0 kPa"),
            ("Avg:",     "lbl_avg",    "0.0 kPa"),
            ("In Zone:", "lbl_zone",   "N/A"),
            ("Active:",  "lbl_active", f"0/{N_SENSORS}"),
        ]):
            ttk.Label(sg2, text=lbl, font=('Arial', 8)).grid(
                row=r, column=0, sticky=tk.W, pady=2)
            w = ttk.Label(sg2, text=default, font=('Arial', 8, 'bold'))
            w.grid(row=r, column=1, sticky=tk.W, padx=(8, 0))
            setattr(self, attr, w)
        ttk.Separator(sg2, orient=tk.HORIZONTAL).grid(
            row=4, column=0, columnspan=2, sticky='ew', pady=4)
        ttk.Label(sg2, text="PT ID:", font=('Arial', 8, 'bold')).grid(
            row=5, column=0, sticky=tk.W)
        self.lbl_pt_id = ttk.Label(sg2, text="—", font=('Arial', 8), foreground="darkblue")
        self.lbl_pt_id.grid(row=5, column=1, sticky=tk.W, padx=(8, 0))


    def _show_execution_panel(self, metadata):
        """Build (if needed) then show the DMR Execution Panel."""
        # Build lazily on first call
        if self.execution_panel is None:
            self._build_execution_panel()

        # Hide welcome
        if self.welcome_frame.winfo_ismapped():
            self.welcome_frame.pack_forget()

        # Update header
        self.hdr_session.config(text=f"Session: {metadata['session_id']}")
        self.hdr_patient.config(
            text=(f"Patient: {metadata['patient_id']}  ·  "
                  f"PT: {metadata['pt_id']}  ·  "
                  f"{metadata['treatment_location_display']}"))
        self.hdr_status.config(text="🔴  Recording")

        self.execution_panel.pack(fill=tk.BOTH, expand=True)

        # Paint tkinter widgets (bars, stats) immediately — they don't need
        # geometry to settle because they use fixed canvas sizes.
        self._update_right_panel()
        self.update_stats()

        # Delay the matplotlib glove draw so tkinter can fully assign
        # pixel dimensions to hand_container before matplotlib renders.
        # update_idletasks() alone is insufficient — geometry needs ~150 ms.
        def _deferred_draw():
            self.root.update_idletasks()
            w = self.hand_container.winfo_width()
            h = self.hand_container.winfo_height()
            if w > 10 and h > 10:
                self.hand_fig.set_size_inches(w / self.hand_fig.get_dpi(),
                                              h / self.hand_fig.get_dpi())
            self.draw_hand()
            self.hand_canvas.draw()
        self.root.after(150, _deferred_draw)

    def _hide_execution_panel(self):
        """Hide execution panel and return to welcome screen."""
        if self.execution_panel is not None and self.execution_panel.winfo_ismapped():
            self.execution_panel.pack_forget()
        if not self.welcome_frame.winfo_ismapped():
            self.welcome_frame.pack(fill=tk.BOTH, expand=True)



    def _draw_camera_placeholder(self):
        """Draw camera-not-connected placeholder."""
        c = self.camera_canvas
        c.delete("ph")
        c.create_rectangle(0, 0, 240, 200, fill='#1a1a2e', outline='', tags="ph")
        c.create_oval(95, 50, 145, 100, outline='#555', width=2, tags="ph")
        c.create_line(120, 50, 120, 32, fill='#555', width=2, tags="ph")
        c.create_text(120, 130, text="📷  Camera — Not Connected",
                      fill='#888', font=('Arial', 9, 'italic'), tags="ph")
        c.create_text(120, 150, text="Logitech C920s recommended",
                      fill='#555', font=('Arial', 8), tags="ph")



    def _create_hand_panel(self, parent):
        """Stub — layout now handled by _create_main_panel."""
        pass

    def _create_right_panel(self, parent):
        """Stub — layout now handled by _create_main_panel."""
        pass



        # ── Sensor / data ────────────────────────────────────────────────────────

    def get_pressure_zone_color(self, pressure):
        if pressure < 1:                                               return '#E0E0E0'
        elif pressure < self.pressure_zones['therapeutic_min']:        return '#4A90E2'
        elif pressure <= self.pressure_zones['therapeutic_max']:       return '#4CAF50'
        elif pressure <= self.pressure_zones['caution_max']:           return '#FFA726'
        else:                                                          return '#EF5350'

    def get_zone_name(self, pressure):
        if pressure < 1:                                               return "No Contact"
        elif pressure < self.pressure_zones['therapeutic_min']:        return "Below Therapeutic"
        elif pressure <= self.pressure_zones['therapeutic_max']:       return "Therapeutic ✓"
        elif pressure <= self.pressure_zones['caution_max']:           return "Above Therapeutic"
        else:                                                          return "CAUTION!"

    def generate_data(self):
        """Generate (demo or real) 5-element sensor data array (PPS Finger TPS II).
        Index: 0=Thumb, 1=Index, 2=Middle, 3=Ring, 4=Pinky — one value per fingertip."""
        if self.sensor_mode == "disconnected":
            return np.zeros(N_SENSORS, dtype=int)

        t = self.time_in_pattern / 100.0

        if self.sensor_mode == "demo":
            pattern = self.current_pattern
            noise   = np.random.normal(0, 1.5, N_SENSORS)

            if pattern == "idle":
                return np.zeros(N_SENSORS, dtype=int)
            elif pattern == "ball_grip":
                # All fingers engaged evenly
                p = 35 + 10 * np.sin(2 * np.pi * 0.3 * t)
                data = np.full(N_SENSORS, p) + noise
            elif pattern == "precision_pinch":
                # Thumb + Index high, others low
                p = 40 + 5 * np.sin(2*np.pi*0.5*t)
                data = np.array([p, p, 5, 3, 2]) + noise
            elif pattern == "power_grip":
                # All fingers high, graded by finger
                b = 50 + 8*np.sin(2*np.pi*0.2*t)
                data = np.array([b*0.9, b, b*0.95, b*0.85, b*0.7]) + noise
            elif pattern == "pt_shoulder":
                # Thumb stabilizes, Index+Middle lead
                p = 35 + 15*np.sin(2*np.pi*0.8*t)
                data = np.array([30, p, p*0.85, 8, 5]) + noise
            elif pattern == "pt_elbow":
                # Three-finger contact
                p = 30 + 12*np.sin(2*np.pi*0.6*t)
                data = np.array([25, p, p, p*0.8, 10]) + noise
            elif pattern == "pt_wrist":
                t2 = t * 2
                data = np.array([
                    28 + 8*np.sin(2*np.pi*0.7*t2),
                    38 + 10*np.sin(2*np.pi*0.7*t2+0.5),
                    10 + np.random.uniform(0, 5),
                    8,
                    5
                ]) + noise
            elif pattern == "three_finger":
                p = 35 + 8*np.sin(2*np.pi*0.4*t)
                data = np.array([p, p, p, 5, 3]) + noise
            elif pattern == "lateral_pinch":
                # Thumb + side of Index
                data = np.array([42, 40, 5, 3, 2]) + noise
            else:
                data = np.zeros(N_SENSORS)
            return np.maximum(0, data).astype(int)

        else:  # real hardware — Finger TPS II
            v = 10 * np.sin(2*np.pi*0.5*t)
            base = np.array([20, 22, 21, 18, 15], dtype=float) + v
            return np.maximum(0, base + np.random.normal(0, 0.5, N_SENSORS)).astype(int)

    # ── Live update loop ─────────────────────────────────────────────────────

    def update_loop(self):
        """50 ms update loop: read sensor, draw hand, update right panel."""
        try:
            if self.sensor_mode != "disconnected":
                self.sensor_data = self.generate_data()

                self.display_data = self.sensor_data.copy()

                if self.is_recording and self.current_session_metadata:
                    self.sample_buffer.append(self.sensor_data.copy())
                    if not self.frame_capture_scheduled:
                        self.frame_capture_scheduled = True
                        self.root.after(self.frame_period_ms, self._capture_frame)

                self.draw_hand()
                if self.sensor_mode == "demo":
                    self.update_hand_orientation()

                self.update_stats()
                self._update_right_panel()

                self.frame_count     += 1
                self.time_in_pattern += 1
                self.frame_var.set(f"Sensor: {self.frame_count}")

            # Optional 3D glove window
            if (GloveVisualization3DWindow is not None
                    and hasattr(self, 'glove_3d_window')
                    and self.glove_3d_window.window.winfo_exists()):
                self.glove_3d_window.update_sensor_data(self.display_data)

        except Exception as e:
            import traceback; traceback.print_exc()

        self.root.after(50, self.update_loop)

    def _update_right_panel(self):
        """Update session stats panel."""
        if not hasattr(self, 'lbl_sess_id'):
            return   # execution panel not built yet

        # Session stats
        if self.current_session_metadata:
            self.lbl_sess_id.config(
                text=self.current_session_metadata['session_id'][:22], foreground="darkblue")
            self.lbl_sess_pat.config(
                text=self.current_session_metadata['patient_id'])
            if hasattr(self, 'lbl_pt_id'):
                self.lbl_pt_id.config(
                    text=self.current_session_metadata.get('pt_id', '—'))
        else:
            self.lbl_sess_id.config(text="—", foreground="darkblue")
            self.lbl_sess_pat.config(text="—")
            if hasattr(self, 'lbl_pt_id'):
                self.lbl_pt_id.config(text="—")

        self.lbl_sess_frames.config(text=str(len(self.recorded_frames)))

        dur = 0
        if self.recorded_frames:
            fp = self.recorded_frames[0].get('frame_period_ms', self.frame_period_ms)
            dur = len(self.recorded_frames) * fp / 1000.0
        self.lbl_sess_dur.config(text=f"{dur:.1f} s")

        if self.is_recording:
            self.lbl_sess_status.config(text="🔴 Recording", foreground="red")
            if hasattr(self, "hdr_status"): self.hdr_status.config(text="🔴  Recording", fg="#ff6b6b")
        elif self.current_session_metadata and not self._session_saved:
            self.lbl_sess_status.config(text="⏸ Paused",     foreground="orange")
        elif self._session_saved:
            self.lbl_sess_status.config(text="✓ Saved",       foreground="darkgreen")
        else:
            self.lbl_sess_status.config(text="Idle",          foreground="gray")


    # ── Drawing ──────────────────────────────────────────────────────────────

    def _update_last_frame_panel(self, frame_data):
        """Refresh the Last Captured Frame panel in the central column."""
        if not hasattr(self, '_lf_num'):
            return
        fn = frame_data.get('frame_number', 0)
        fp_ms   = frame_data.get('frame_period_ms', self.frame_period_ms)
        elapsed = fn * fp_ms / 1000.0
        self._lf_num.config(text=str(fn + 1))
        self._lf_time.config(text=f"{elapsed:.1f} s")
        # Per-finger kPa from averaged sensor data
        sensor = frame_data.get('sensor_data', [])
        if len(sensor) == N_SENSORS:
            data = np.array(sensor)
            color_map = {'#4A90E2': 'blue', '#4CAF50': 'darkgreen',
                         '#FFA726': 'darkorange', '#EF5350': 'red', '#E0E0E0': 'gray'}
            for i in range(N_SENSORS):
                p = float(data[i])
                col = color_map.get(self.get_pressure_zone_color(p), 'black')
                self._lf_finger_labels[i].config(text=f"{p:.1f} kPa", foreground=col)

    def draw_hand(self):
        """Draw Finger TPS II — palm shows frame number, click tip to toggle finger."""
        if self.sensor_mode == "disconnected":
            return
        if not hasattr(self, 'hand_ax'):
            return
        ax = self.hand_ax
        ax.clear()
        ax.set_xlim(0, 9); ax.set_ylim(0, 5.5)
        ax.set_aspect('auto'); ax.axis('off')
        ax.set_title('Finger TPS II  (click finger to toggle)',
                     fontsize=8, fontweight='bold', pad=3)

        # Palm — frame number displayed inside
        frame_num = len(self.recorded_frames)
        ax.add_patch(Rectangle((1.3, 0.2), 5.0, 2.0, facecolor='#E8E8E8',
                                edgecolor='#999', linewidth=1.5, alpha=0.7, zorder=1))
        ax.text(3.8, 1.40, 'Frame', ha='center', va='center',
                fontsize=7, color='#888', style='italic', zorder=2)
        ax.text(3.8, 0.78, str(frame_num), ha='center', va='center',
                fontsize=15, fontweight='bold', color='#333', zorder=2)

        # Finger shafts — dimmed when finger inactive
        shafts = [
            {'x': 0.4,  'y': 2.2, 'w': 0.95, 'h': 1.2},
            {'x': 1.5,  'y': 2.2, 'w': 0.95, 'h': 1.7},
            {'x': 2.7,  'y': 2.2, 'w': 0.95, 'h': 1.9},
            {'x': 3.9,  'y': 2.2, 'w': 0.95, 'h': 1.7},
            {'x': 5.1,  'y': 2.2, 'w': 0.85, 'h': 1.3},
        ]
        for i, s in enumerate(shafts):
            fc = '#D8D8D8' if self.active_fingers[i] else '#F2F2F2'
            ax.add_patch(Rectangle((s['x'], s['y']), s['w'], s['h'],
                                   facecolor=fc, edgecolor='#bbb',
                                   linewidth=1.2, alpha=0.7, zorder=1))

        # Fingertip circles
        TIPS = [
            {'cx': 0.87, 'cy': 3.85, 'r': 0.48, 'name': 'Thumb',  'idx': 0},
            {'cx': 1.97, 'cy': 4.35, 'r': 0.48, 'name': 'Index',  'idx': 1},
            {'cx': 3.17, 'cy': 4.55, 'r': 0.48, 'name': 'Middle', 'idx': 2},
            {'cx': 4.37, 'cy': 4.35, 'r': 0.48, 'name': 'Ring',   'idx': 3},
            {'cx': 5.53, 'cy': 3.95, 'r': 0.43, 'name': 'Pinky',  'idx': 4},
        ]
        self._tip_positions = TIPS

        source = (self.recorded_frames[-1]['sensor_data']
                  if self.is_recording and self.recorded_frames
                  else self.display_data)

        for tip in TIPS:
            i      = tip['idx']
            active = self.active_fingers[i]
            p      = float(source[i]) if active else 0.0
            if active:
                color    = self.get_pressure_zone_color(p)
                txt_col  = 'white' if p > 25 else 'black'
                edge_col = 'black'; lw = 2.0
                label    = f"{p:.0f}\nkPa"
            else:
                color    = '#E0E0E0'
                txt_col  = '#aaa'
                edge_col = '#bbb'; lw = 1.2
                label    = 'OFF'
            ax.add_patch(Circle((tip['cx'], tip['cy']), tip['r'],
                                facecolor=color, edgecolor=edge_col,
                                linewidth=lw, alpha=0.92, zorder=3))
            ax.text(tip['cx'], tip['cy'], label,
                    ha='center', va='center', fontsize=7,
                    fontweight='bold', color=txt_col, zorder=4)
            ax.text(tip['cx'], tip['cy'] - tip['r'] - 0.22, tip['name'],
                    ha='center', fontsize=7, fontweight='bold',
                    color='black' if active else '#bbb', zorder=4)

        self.hand_canvas.draw()

    def _on_hand_click(self, event):
        """Toggle finger active/inactive when its tip circle is clicked."""
        import math
        if event.inaxes != self.hand_ax or not hasattr(self, '_tip_positions'):
            return
        for tip in self._tip_positions:
            if math.hypot(event.xdata - tip['cx'], event.ydata - tip['cy']) <= tip['r'] * 1.3:
                self.active_fingers[tip['idx']] = not self.active_fingers[tip['idx']]
                self.draw_hand()
                return

    def update_hand_orientation(self):
        """Compute simulated orientation (saved to DMR; not displayed as 3D widget)."""
        if self.sensor_mode == "demo":
            t = self.time_in_pattern / 100.0
            self.hand_orientation['roll']  = 15 * np.sin(0.5 * t)
            self.hand_orientation['pitch'] = 10 * np.sin(0.3 * t + 1)
            self.hand_orientation['yaw']   = 20 * np.sin(0.2 * t + 2)

    def update_stats(self):
        """Update left-panel stats labels. During recording uses last frame data, not live pulses."""
        if not hasattr(self, 'lbl_peak'):
            return

        # Use last captured frame when recording; live data otherwise
        if self.is_recording and self.recorded_frames:
            source = np.array(self.recorded_frames[-1]['sensor_data'])
        else:
            source = self.display_data

        active = source > 1.0
        if np.any(active):
            peak = float(np.max(source))
            avg  = float(np.mean(source[active]))
            n    = int(np.sum(active))
            zone = self.get_zone_name(avg)
            color_map = {'#4A90E2': 'blue', '#4CAF50': 'green',
                         '#FFA726': 'orange', '#EF5350': 'red', '#E0E0E0': 'gray'}
            zc = color_map.get(self.get_pressure_zone_color(avg), 'black')
        else:
            peak = avg = 0.0; n = 0; zone = "N/A"; zc = "gray"

        self.lbl_peak.config(text=f"{peak:.1f} kPa")
        self.lbl_avg.config(text=f"{avg:.1f} kPa")
        self.lbl_zone.config(text=zone, foreground=zc)
        self.lbl_active.config(text=f"{n}/{N_SENSORS}")

    # ── Frame capture ────────────────────────────────────────────────────────

    def _capture_frame(self):
        if not self.is_recording or not self.current_session_metadata:
            self.frame_capture_scheduled = False
            self.sample_buffer.clear()
            return
        try:
            if self.sample_buffer:
                averaged = np.mean(self.sample_buffer, axis=0).astype(int)
                n_samples = len(self.sample_buffer)
                self.sample_buffer.clear()
            else:
                averaged  = self.sensor_data.astype(int)
                n_samples = 1

            self.display_data = averaged.copy()
            frame_data = {
                'frame_number':      len(self.recorded_frames),
                'sensor_data':       averaged.tolist(),
                'hand_orientation':  self.hand_orientation.copy(),
                'demo_pattern':      self.current_pattern if self.sensor_mode == "demo" else None,
                'frame_period_ms':   self.frame_period_ms,
                'samples_per_frame': n_samples,
            }
            self.recorded_frames.append(frame_data)

            if len(self.recorded_frames) % 10 == 0:
                print(f"✓ Frame {len(self.recorded_frames)} "
                      f"({n_samples} samples, {self.frame_period_ms} ms)")

            self.lbl_rec.config(
                text=f"🔴 Recording  DMR Frames: {len(self.recorded_frames)}",
                foreground="red")
            self._update_last_frame_panel(frame_data)

            if self.is_recording and self.current_session_metadata:
                self.root.after(self.frame_period_ms, self._capture_frame)
            else:
                self.frame_capture_scheduled = False
        except Exception as e:
            print(f"✗ _capture_frame error: {e}")
            self.frame_capture_scheduled = False

    # ── Recording controls ────────────────────────────────────────────────────

    def toggle_record(self):
        if self.sensor_mode == "disconnected":
            messagebox.showwarning("Sensor Not Connected",
                "Connect a sensor first.\n\nSensor → Demo Simulator or TactileGlove")
            return

        if self.is_recording:
            # Pause
            self.is_recording = False
            self.frame_capture_scheduled = False
            self.sample_buffer.clear()
            self.btn_rec.config(text="⏺ Resume")
            self.status_var.set("Recording PAUSED — click ⏺ Resume or ⏹ Stop & Save")
            if hasattr(self, "hdr_status"): self.hdr_status.config(text="⏸  Paused", fg="#ffaa44")
        elif self.current_session_metadata and not self._session_saved:
            # Resume
            self.is_recording = True
            self.btn_rec.config(text="⏸ Pause")
            self.btn_stop.config(state="normal")
            self.status_var.set(f"Recording RESUMED — {self.current_session_metadata['session_id']}")
            if hasattr(self, "hdr_status"): self.hdr_status.config(text="🔴  Recording", fg="#ff6b6b")
        else:
            # New session
            self.current_session_metadata = None
            self.recorded_frames = []
            self._session_saved  = False
            self.dmr_session_widget.clear_session()
            self._start_dmr_session()

    def _start_dmr_session(self):
        def on_session_created(metadata):
            if metadata:
                self.current_session_metadata = metadata
                self.recorded_frames = []
                self.is_recording    = True
                self._rec_start_time = datetime.now()

                # Apply clinically-calculated frame duration from dialog
                frame_sec = metadata.get('frame_duration_sec', 3)
                self.frame_period_ms = frame_sec * 1000
                self.frame_period_var.set(frame_sec)
                self.lbl_frame_period.config(
                    text=f"{frame_sec} sec — {metadata['treatment_location_display']} preset")

                self.btn_rec.config(text="⏸ Pause")
                self.btn_stop.config(state="normal")
                self.lbl_rec.config(
                    text=(f"{metadata['session_id']}\n"
                          f"Patient: {metadata['patient_id']}\n"
                          f"PT: {metadata['pt_id']}\n"
                          f"{metadata['treatment_location_display']}  "
                          f"({frame_sec}s/frame, {metadata['num_frames_planned']} frames planned)"),
                    foreground="red")
                self.dmr_session_widget.set_session(metadata)
                self._show_execution_panel(metadata)
                self.status_var.set(
                    f"📋 Recording DMR: {metadata['session_id']} — "
                    f"Patient {metadata['patient_id']} — PT {metadata['pt_id']} — "
                    f"{frame_sec}s/frame")
                print(f"\n{'='*50}")
                print(f"DMR SESSION STARTED: {metadata['session_id']}")
                print(f"Patient: {metadata['patient_id']}  PT: {metadata['pt_id']}")
                print(f"Location: {metadata['treatment_location_display']}")
                print(f"Frame duration: {frame_sec} sec  |  Planned frames: {metadata['num_frames_planned']}")
                print(f"Session duration: {metadata['session_duration_min']} min")
                print(f"{'='*50}\n")
        DMRSessionDialog(self, on_session_created)

    def stop_record(self):
        if not self.current_session_metadata and not self.recorded_frames:
            messagebox.showwarning("Nothing to Stop",
                "No DMR session is active.\nClick ⏺ Record to start.")
            return

        self.is_recording            = False
        self.frame_capture_scheduled = False
        self.sample_buffer.clear()
        self._session_saved          = True   # prevent Resume after Stop regardless of save outcome
        self.btn_rec.config(text="⏺ Record")
        self.btn_stop.config(state="disabled")
        self.lbl_rec.config(text="Click ⏺ Record to start a DMR session", foreground="gray")
        if hasattr(self, "hdr_status"):
            self.hdr_status.config(text="⏹  Stopped")

        if self.current_session_metadata and self.recorded_frames:
            fp   = self.recorded_frames[0].get('frame_period_ms', self.frame_period_ms)
            dur  = len(self.recorded_frames) * fp / 1000.0
            resp = messagebox.askyesno("Save Digital Master Record?",
                f"DMR Session Complete\n\n"
                f"Session:  {self.current_session_metadata['session_id']}\n"
                f"Patient:  {self.current_session_metadata['patient_id']}\n"
                f"Location: {self.current_session_metadata['treatment_location_display']}\n"
                f"Frames:   {len(self.recorded_frames)}\n"
                f"Duration: {dur:.1f} seconds\n\n"
                f"Save this Digital Master Record?")
            if resp:
                self._save_dmr_file()
            else:
                self.current_session_metadata = None
                self.recorded_frames = []
                self.dmr_session_widget.clear_session()
                self.status_var.set("DMR session discarded")
        else:
            self.status_var.set("⚠ Session stopped — no sensor data recorded")
            messagebox.showwarning("No Data",
                "Session stopped before any data was recorded.\n"
                "Make sure the sensor is connected and wait a few seconds after clicking Record.")
            self.current_session_metadata = None
            self.recorded_frames = []
            self.dmr_session_widget.clear_session()

    def _save_dmr_file(self):
        if not self.current_session_metadata:
            return
        meta = self.current_session_metadata
        suggested = (f"DMR_{meta['patient_id']}_"
                     f"{meta['treatment_location']}_"
                     f"{meta['date'].replace('-','')}.json")

        filename = filedialog.asksaveasfilename(
            title="Save Digital Master Record",
            initialdir=self._pt_dir(),
            initialfile=suggested,
            defaultextension=".json",
            filetypes=[("Digital Master Record (JSON)", "*.json"), ("All files", "*.*")])
        if not filename:
            return

        try:
            dmr_document = {
                'dmr_format_version': '1.0',
                'schema_version':     '1.2',
                'created_by':         'TactileSense DMR Studio v1.0',
                'device':             'PT Robotic Therapeutic System',
                'execution_mode':     'PT_MASTER',
                'frame_duration_sec': self.frame_period_ms / 1000.0,
                'session':            meta,
                'pressure_zones':     self.pressure_zones,
                'frames':             self.recorded_frames,
                'summary': {
                    'total_frames':      len(self.recorded_frames),
                    'duration_seconds':  len(self.recorded_frames) * (
                        self.frame_period_ms / 1000.0),
                    'recording_complete': True,
                },
            }
            with open(filename, 'w') as f:
                json.dump(dmr_document, f, indent=2)

            self._session_saved = True

            # Auto CSV export
            csv_exported  = False
            csv_filename  = None
            if meta.get('auto_export_csv', False) or self.auto_export_csv_var.get():
                csv_filename = self._auto_export_csv(meta)
                csv_exported = csv_filename is not None

            msg = (f"DMR saved!\n\nFile: {filename}\n"
                   f"Frames: {len(self.recorded_frames)}\n")
            if csv_exported:
                msg += f"CSV:  {csv_filename}\n"
            msg += "\nClick ⏺ Record to start a new session."
            messagebox.showinfo("DMR Saved", msg)
            self.status_var.set(f"✓ DMR saved: {filename}")
            print(f"✓ DMR saved: {filename}  ({len(self.recorded_frames)} frames)")
            # Clear session state — next ⏺ Record opens a fresh dialog
            self.current_session_metadata = None
            self.recorded_frames          = []
            self.dmr_session_widget.clear_session()
            self._hide_execution_panel()

        except Exception as e:
            messagebox.showerror("Save Error", f"Could not write file:\n{e}")
            print(f"Save error: {e}")

    def _auto_export_csv(self, meta):
        csv_dir  = self._pt_csv_dir()
        filename = os.path.join(csv_dir,
            f"CSV_{meta['patient_id']}_{meta['treatment_location']}_"
            f"{meta['date'].replace('-','')}.csv")
        try:
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                header = ["Frame","Elapsed_sec","Pattern","Roll","Pitch","Yaw"]
                header += ["Thumb_kPa", "Index_kPa", "Middle_kPa", "Ring_kPa", "Pinky_kPa"]
                writer.writerow(header)
                for frame in self.recorded_frames:
                    fn     = frame.get('frame_number', 0)
                    fp_ms  = frame.get('frame_period_ms', 2000)
                    elapsed = round(fn * fp_ms / 1000.0, 1)
                    row = [fn, elapsed,
                           frame.get('demo_pattern',''),
                           frame.get('hand_orientation',{}).get('roll',0),
                           frame.get('hand_orientation',{}).get('pitch',0),
                           frame.get('hand_orientation',{}).get('yaw',0)]
                    row += frame.get('sensor_data', [0]*N_SENSORS)
                    writer.writerow(row)
            print(f"✓ CSV auto-exported: {filename}")
            return filename
        except Exception as e:
            print(f"CSV export error: {e}")
            return None

    # ── DMR menu commands ────────────────────────────────────────────────────

    def start_new_dmr(self):
        if self.is_recording:
            messagebox.showwarning("Recording Active",
                "Stop the current recording before starting a new DMR.")
            return
        self.current_session_metadata = None
        self.recorded_frames = []
        self._session_saved  = False
        self.dmr_session_widget.clear_session()
        self.btn_rec.config(text="⏺ Record")
        self.lbl_rec.config(text="New DMR ready — click ⏺ Record", foreground="gray")
        self.status_var.set("Ready for new DMR session")
        self._start_dmr_session()

    def view_frames(self):
        if not self.recorded_frames:
            if self.is_recording and self.current_session_metadata:
                messagebox.showwarning("No Frames Yet",
                    "Recording active but no frames yet.\nWait a few seconds then try again.")
            else:
                messagebox.showwarning("No Frames",
                    "No recorded frames available.\n\n"
                    "Record or load a DMR session first.")
            return
        FrameViewer(self.root, self.recorded_frames, self.pressure_zones,
                    self.current_session_metadata)

    def load_dmr(self):
        filename = filedialog.askopenfilename(
            title="Load Digital Master Record",
            filetypes=[("Digital Master Record (JSON)", "*.json"), ("All files", "*.*")])
        if not filename:
            return
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            session = data.get('session', {})
            frames  = data.get('frames', [])
            self.current_session_metadata = session
            self.recorded_frames          = frames
            self.is_recording             = False
            self._session_saved           = True
            self.dmr_session_widget.set_session(session)
            self.btn_rec.config(text="⏺ Record")
            self.lbl_rec.config(
                text=(f"{session.get('session_id','')}\n"
                      f"Patient: {session.get('patient_id','')}\n"
                      f"{session.get('treatment_location_display','')}"),
                foreground="darkblue")
            messagebox.showinfo("DMR Loaded",
                f"✓ Loaded: {session.get('session_id','?')}\n"
                f"Patient: {session.get('patient_id','?')}\n"
                f"Frames: {len(frames)}")
            self.status_var.set(f"✓ DMR loaded: {len(frames)} frames")
        except Exception as e:
            messagebox.showerror("Load Error", f"Error loading DMR:\n{e}")

    def load_and_review_dmr(self):
        filename = filedialog.askopenfilename(
            title="Load DMR for Review",
            filetypes=[("Digital Master Record (JSON)", "*.json"), ("All files", "*.*")])
        if not filename:
            return
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            session = data.get('session', {})
            frames  = data.get('frames', [])
            if not frames:
                messagebox.showwarning("No Frames",
                    f"No frames in: {os.path.basename(filename)}")
                return
            self.current_session_metadata = session
            self.recorded_frames          = frames
            self.is_recording             = False
            self._session_saved           = True
            self.dmr_session_widget.set_session(session)
            self.btn_rec.config(text="⏺ Record")
            self.lbl_rec.config(
                text=(f"{session.get('session_id','')}\n"
                      f"Patient: {session.get('patient_id','')}\n"
                      f"{session.get('treatment_location_display','')}"),
                foreground="darkblue")
            self.status_var.set(f"✓ DMR loaded: {len(frames)} frames")
            self.root.update_idletasks()
            FrameViewer(self.root, self.recorded_frames, self.pressure_zones, session)
        except Exception as e:
            messagebox.showerror("Load Error", f"Error loading DMR:\n{e}")

    def export_dmr_report(self):
        if not self.current_session_metadata:
            messagebox.showwarning("No Session", "Load or record a DMR session first."); return
        if not self.recorded_frames:
            messagebox.showwarning("No Frames", "No frames recorded in this session."); return
        meta = self.current_session_metadata
        suggested = f"Report_{meta['patient_id']}_{meta['date'].replace('-','')}.csv"
        filename = filedialog.asksaveasfilename(
            title="Export DMR Report",
            initialdir=self._pt_dir(),
            initialfile=suggested,
            defaultextension=".csv",
            filetypes=[("CSV Report", "*.csv"), ("All files", "*.*")])
        if not filename:
            return
        try:
            zones = self.pressure_zones
            rows = []
            for frame in self.recorded_frames:
                sd     = frame.get('sensor_data', [])
                active = [v for v in sd if v > 1.0] if sd else []
                peak   = max(sd) if sd else 0.0
                avg    = sum(active)/len(active) if active else 0.0
                if avg < zones['therapeutic_min']:   zone = "Below Therapeutic"
                elif avg <= zones['therapeutic_max']: zone = "Therapeutic OK"
                elif avg <= zones['caution_max']:     zone = "Above Therapeutic"
                else:                                 zone = "CAUTION"
                rows.append((frame.get('frame_number', 0),
                             round(frame.get('frame_number',0)*frame.get('frame_period_ms',2000)/1000.0,1),
                             frame.get('demo_pattern', ''),
                             f"{peak:.2f}", f"{avg:.2f}", zone, len(active)))
            with open(filename, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["DMR CLINICAL REPORT"])
                w.writerow(["Generated",  datetime.now().isoformat()])
                w.writerow(["Session ID", meta.get('session_id','')])
                w.writerow(["Patient",    meta.get('patient_id','')])
                w.writerow(["Location",   meta.get('treatment_location_display','')])
                w.writerow(["PT",         meta.get('pt_id','')])
                w.writerow(["Notes",      meta.get('notes','')])
                w.writerow(["Zones", f"Min={zones['therapeutic_min']:.0f}",
                            f"Max={zones['therapeutic_max']:.0f}",
                            f"Caut={zones['caution_max']:.0f}"])
                w.writerow([])
                w.writerow(["Frame","Elapsed_sec","Pattern","Peak_kPa","Avg_kPa","Zone","Active_Sensors"])
                w.writerows(rows)
            messagebox.showinfo("Report Exported",
                f"Report saved!\nFile: {filename}\nFrames: {len(self.recorded_frames)}")
            self.status_var.set(f"✓ Report: {filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not write file:\n{e}")

    def show_about_dmr(self):
        messagebox.showinfo("About DMR",
            "Digital Master Record (DMR)\n\n"
            "The DMR captures a licensed PT's therapeutic technique\n"
            "as a time-series of haptic glove sensor readings.\n\n"
            "Each frame stores:\n"
            "  • 5 fingertip sensor readings (kPa) — PPS Finger TPS II\n"
            "  • Hand orientation (Roll/Pitch/Yaw)\n"
            "  • Elapsed time (frame_number × frame_period)\n\n"
            "DMR files are the training data for PT Robotic's\n"
            "Co-Pilot and Autopilot platforms.\n\n"
            "Saved to: ~/TactileSense/Protocols/PT_Protocols/\n"
            "Format: JSON + optional CSV export")

    # ── Sensor connection ────────────────────────────────────────────────────

    def connect_demo(self):
        if self.sensor_mode == "demo":
            return
        if self.sensor_mode != "disconnected":
            if not messagebox.askyesno("Switch?", "Switch to Demo Simulator?"):
                return
            self.disconnect()
        self.sensor_mode       = "demo"
        self.current_pattern   = "ball_grip"
        self.time_in_pattern   = 0
        self.lbl_mode.config(text="🎭 DEMO\nMODE", foreground="blue")
        self.demo_container.pack(fill=tk.X, padx=5, pady=2)
        self.status_var.set("Demo Simulator connected — open DMR → New DMR to start recording")
        messagebox.showinfo("Demo Mode",
            "🎭 DEMO Simulator Connected\n\n"
            "Sensor is active.\n\n"
            "Next step:\n"
            "  DMR menu  →  New DMR\n"
            "  Fill in patient details and start recording.")
        print("✓ Demo mode active")

    def connect_real(self):
        if self.sensor_mode != "disconnected":
            if not messagebox.askyesno("Switch?", "Switch to TactileGlove?"):
                return
            self.disconnect()
        self.sensor_mode = "real_glove"
        self.lbl_mode.config(text="🧤 GLOVE\nMODE", foreground="green")
        self.demo_container.pack_forget()
        self.status_var.set("TactileGlove connected — open DMR → New DMR to start recording")
        messagebox.showinfo("TactileGlove",
            "🧤 TactileGlove Connected\n\n"
            "Sensor is active.\n\n"
            "Next step:\n"
            "  DMR menu  →  New DMR\n"
            "  Fill in patient details and start recording.")
        print("✓ TactileGlove mode")

    def disconnect(self):
        if self.is_recording and self.current_session_metadata:
            self.is_recording            = False
            self.frame_capture_scheduled = False
            self.sample_buffer.clear()
            self.btn_rec.config(text="⏺ Resume")
            self.lbl_rec.config(
                text="⏸ PAUSED (disconnected)\nReconnect sensor then Resume or Stop & Save",
                foreground="darkorange")
            self.status_var.set("⏸ Recording PAUSED — sensor disconnected.")

        self.sensor_mode  = "disconnected"
        self.sensor_data  = np.zeros(N_SENSORS, dtype=int)
        self.display_data = np.zeros(N_SENSORS, dtype=int)
        self.lbl_mode.config(text="⚠ NOT\nCONNECTED", foreground="red")
        self.demo_container.pack_forget()
        self._hide_execution_panel()
        if not (self.is_recording and self.current_session_metadata):
            self.status_var.set("Disconnected")
        self.update_stats()

    def change_pattern(self):
        if self.sensor_mode == "demo":
            self.current_pattern = self.pattern_var.get()
            self.time_in_pattern = 0
            self.status_var.set(f"Pattern: {self.patterns[self.current_pattern]}")

    # ── Settings ─────────────────────────────────────────────────────────────

    def configure_zones(self):
        def on_zones_updated(new_zones):
            self.pressure_zones = new_zones
            self.status_var.set(
                f"Zones: {new_zones['therapeutic_min']:.0f}–"
                f"{new_zones['therapeutic_max']:.0f}–{new_zones['caution_max']:.0f} kPa")
            print(f"✓ Zones updated: {new_zones}")
            if (GloveVisualization3DWindow is not None
                    and hasattr(self, 'glove_3d_window')
                    and self.glove_3d_window.window.winfo_exists()):
                self.glove_3d_window.update_pressure_zones(new_zones)
        InteractiveZoneDialog(self.root, self.pressure_zones, on_zones_updated)

    def _on_frame_period_change(self, value=None):
        secs = max(1, min(10, int(float(self.frame_period_var.get()))))
        self.frame_period_var.set(secs)
        self.frame_period_ms = secs * 1000
        self.lbl_frame_period.config(
            text=f"{secs} sec — manual override")

    def show_3d_glove(self):
        if GloveVisualization3DWindow is None:
            messagebox.showerror("Not Available",
                "3D Glove Visualization requires glove_visualization_3d.py"); return
        if (not hasattr(self, 'glove_3d_window')
                or not self.glove_3d_window.window.winfo_exists()):
            self.glove_3d_window = GloveVisualization3DWindow(self)
            self.glove_3d_window.update_sensor_data(self.display_data)
        else:
            self.glove_3d_window.window.lift()
            self.glove_3d_window.window.focus_force()

    # ── File menu ────────────────────────────────────────────────────────────

    def save_session(self):
        if not self.recorded_frames:
            if self.is_recording and self.current_session_metadata:
                if not messagebox.askyesno("No Frames Yet",
                        "Recording active but no frames yet.\nSave metadata only?"):
                    return
            elif not self.current_session_metadata:
                messagebox.showwarning("No Session",
                    "No active DMR session.\nClick ⏺ Record first."); return

        payload = {
            'saved_by':     'TactileSense DMR Studio v1.0',
            'timestamp':    datetime.now().isoformat(),
            'session':      self.current_session_metadata,
            'pressure_zones': self.pressure_zones,
            'frames':       self.recorded_frames,
            'frame_count':  len(self.recorded_frames),
        }
        filename = filedialog.asksaveasfilename(
            title="Save Session", initialdir=self._pt_dir(),
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not filename:
            return
        try:
            with open(filename, 'w') as f:
                json.dump(payload, f, indent=2)
            messagebox.showinfo("Saved",
                f"Session saved.\nFile: {filename}\nFrames: {len(self.recorded_frames)}")
            self.status_var.set(f"✓ Session saved: {filename}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not write file:\n{e}")

    def export_data(self):
        if not self.recorded_frames:
            messagebox.showwarning("Nothing to Export",
                "No recorded frames available.\nRecord a DMR session first."); return
        filename = filedialog.asksaveasfilename(
            title="Export Sensor Data as CSV", initialdir=self._pt_csv_dir(),
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not filename:
            return
        try:
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                header = ["Frame","Elapsed_sec","Pattern","Roll","Pitch","Yaw"]
                header += ["Thumb_kPa", "Index_kPa", "Middle_kPa", "Ring_kPa", "Pinky_kPa"]
                writer.writerow(header)
                for frame in self.recorded_frames:
                    fn     = frame.get('frame_number', 0)
                    fp_ms  = frame.get('frame_period_ms', 2000)
                    elapsed = round(fn * fp_ms / 1000.0, 1)
                    row = [fn, elapsed,
                           frame.get('demo_pattern',''),
                           frame.get('hand_orientation',{}).get('roll',0),
                           frame.get('hand_orientation',{}).get('pitch',0),
                           frame.get('hand_orientation',{}).get('yaw',0)]
                    row += frame.get('sensor_data', [0]*N_SENSORS)
                    writer.writerow(row)
            messagebox.showinfo("CSV Exported",
                f"File: {filename}\nRows: {len(self.recorded_frames)}\nCols: 11")
            self.status_var.set(f"✓ CSV exported: {filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not write file:\n{e}")

    # ── Help / About ─────────────────────────────────────────────────────────

    def show_about(self):
        messagebox.showinfo("About",
            "TactileSense DMR Studio v1.0\n"
            "Digital Master Record Generation Platform\n\n"
            "PT Robotic LLC\n"
            "For use by Licensed Physical Therapists\n\n"
            "Features:\n"
            "• DMR recording via TactileGlove or Demo Simulator\n"
            "• Interactive pressure zone configuration\n"
            "• Frame-by-frame review\n"
            "• JSON + CSV export\n"
            "• Native tkinter — no browser required\n\n"
            "© 2025–2026 PT Robotic LLC")


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    # Hide console window on Windows
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(
            ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass

    try:
        root = tk.Tk()
        app  = TactileSenseClinical(root)   # noqa: F841
        root.mainloop()
    except Exception:
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
