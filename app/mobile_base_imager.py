from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import zstandard

from app import __version__
from app.core import (
    Disk,
    backup_disk,
    download_file,
    enumerate_disks,
    flash_and_verify,
    format_disk,
    human_size,
    image_format,
    is_supported_image,
    prepare_image,
    sha256_file,
    verify_image_against_disk,
    write_checksum,
)


PRODUCT = "Mobile Base Imager"
MANIFEST_URL = "https://its-ze.github.io/mobile-base-imager/release-manifest.json"
FALLBACK_MANIFEST = {
    "imageVersion": "0.9.5",
    "imageAsset": "mobile-base-pi5-0.9.5.img.zst",
    "imageUrl": "https://github.com/Its-ze/mobile-base-imager/releases/download/v0.4.0/mobile-base-pi5-0.9.5.img.zst",
    "imageBytes": 535962477,
    "imageSha256": "A09839AAB1727648055C1438A6CC5E3BF397694D741A4E12E2C18E3B242D87D1",
}
BG = "#071013"
NAV = "#09171b"
PANEL = "#0d1a1e"
PANEL_2 = "#102329"
LINE = "#1b3a40"
MINT = "#59e2d2"
AMBER = "#f3b861"
TEXT = "#e8f4f2"
MUTED = "#78989b"
RED = "#ff6e72"


def is_admin() -> bool:
    if os.name != "nt":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def user_identity() -> tuple[Path, int | None, int | None]:
    if os.name != "nt" and os.getenv("PKEXEC_UID", "").isdigit():
        import pwd

        account = pwd.getpwuid(int(os.environ["PKEXEC_UID"]))
        return Path(account.pw_dir), account.pw_uid, account.pw_gid
    return Path.home(), None, None


def restore_user_ownership(*paths: Path) -> None:
    _home, uid, gid = user_identity()
    if uid is None or gid is None:
        return
    for path in paths:
        if path.exists():
            os.chown(path, uid, gid)


def app_data() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MobileBaseImager"
    else:
        home, _uid, _gid = user_identity()
        xdg_root = os.getenv("XDG_DATA_HOME")
        root = Path(xdg_root or home / ".local/share") / "mobile-base-imager"
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt" and not os.getenv("XDG_DATA_HOME"):
        restore_user_ownership(home / ".local", home / ".local/share")
    restore_user_ownership(root.parent, root)
    return root


def get_manifest() -> dict:
    request = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": f"MobileBaseImager/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode())
        required = {"imageVersion", "imageAsset", "imageUrl", "imageSha256"}
        if required.issubset(data):
            return data
    except Exception:
        pass
    return dict(FALLBACK_MANIFEST)


def adjacent_checksum(path: Path) -> str | None:
    candidates = [Path(str(path) + ".sha256"), path.with_suffix(path.suffix + ".sha256")]
    for candidate in candidates:
        if candidate.exists():
            parts = candidate.read_text(encoding="utf-8-sig").strip().split()
            if parts and len(parts[0]) == 64:
                return parts[0].upper()
    if path.name == FALLBACK_MANIFEST["imageAsset"]:
        return FALLBACK_MANIFEST["imageSha256"]
    return None


class ImagerApp:
    def __init__(self, root: tk.Tk, demo: bool = False, screenshot: str | None = None, start_page: str = "flash"):
        self.root = root
        self.demo = demo
        self.screenshot = screenshot
        self.admin = is_admin() or demo
        self.disks: list[Disk] = []
        self.disk_by_display: dict[str, Disk] = {}
        self.disk_combos: list[ttk.Combobox] = []
        self.action_controls: list[tk.Widget] = []
        self.pages: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.busy = False
        self.manifest = dict(FALLBACK_MANIFEST)
        self.source_path = tk.StringVar()
        self.source_info = tk.StringVar(value="Choose an image or download Mobile Base Stable.")
        self.disk_value = tk.StringVar()
        self.fs_value = tk.StringVar(value="exfat")
        self.label_value = tk.StringVar(value="MOBILEBASE")
        self.verify_value = tk.BooleanVar(value=True)
        self.backup_compress = tk.BooleanVar(value=True)
        self.backup_path = tk.StringVar()
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="READY")
        self.percent_text = tk.StringVar(value="0%")
        self.status_detail = tk.StringVar(value="Waiting for an operation")
        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._refresh_admin()
        self.refresh_disks()
        self.show_page(start_page)
        threading.Thread(target=self._load_manifest, daemon=True).start()
        if screenshot:
            self.root.after(1500, self._capture_screenshot)

    def _configure_window(self):
        self.root.title(f"{PRODUCT} {__version__}")
        self.root.geometry("1220x820")
        self.root.minsize(1040, 720)
        self.root.configure(bg=BG)
        resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        icon = resource_root / "assets" / "mobile-base-imager.ico"
        png_icon = resource_root / "assets" / "mobile-base-imager.png"
        if os.name != "nt" and png_icon.exists():
            try:
                self._icon_photo = tk.PhotoImage(file=str(png_icon))
                self.root.iconphoto(True, self._icon_photo)
            except tk.TclError:
                pass
        elif icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    def _configure_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor="#081417", background=MINT, bordercolor=LINE, lightcolor=MINT, darkcolor=MINT)
        style.configure("TCombobox", fieldbackground="#081417", background=PANEL_2, foreground=TEXT, arrowcolor=MINT, bordercolor=LINE, padding=8)
        style.map("TCombobox", fieldbackground=[("readonly", "#081417")], foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, focuscolor=PANEL, indicatorbackground="#081417", indicatorforeground=MINT)

    def _build_ui(self):
        header = tk.Canvas(self.root, height=88, bg="#081518", highlightthickness=0)
        header.pack(fill="x")
        header.create_rectangle(28, 20, 76, 68, outline=MINT, width=2)
        header.create_text(52, 44, text="MB", fill=MINT, font=("Segoe UI", 15, "bold"))
        header.create_text(94, 31, text="MOBILE BASE", fill=MINT, font=("Segoe UI", 9, "bold"), anchor="w")
        header.create_text(94, 54, text="IMAGER", fill=TEXT, font=("Segoe UI", 20, "bold"), anchor="w")
        platform_label = "WINDOWS" if os.name == "nt" else "LINUX"
        header.create_text(260, 44, text=f"{platform_label}  /  FLASH  /  VERIFY  /  BACKUP  /  FORMAT", fill=MUTED, font=("Consolas", 10), anchor="w")
        header.create_line(0, 87, 1220, 87, fill=LINE)
        self.admin_button = self._canvas_button(header, "", self.restart_admin, 998, 24, 190, 38, accent=False)

        workspace = tk.Frame(self.root, bg=BG)
        workspace.pack(fill="both", expand=True)

        sidebar = tk.Frame(workspace, bg=NAV, width=216, highlightbackground=LINE, highlightthickness=1)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="IMAGING WORKSPACE", bg=NAV, fg=MUTED, font=("Consolas", 8, "bold")).pack(anchor="w", padx=20, pady=(24, 12))
        for key, title, subtitle in (
            ("flash", "FLASH IMAGE", "Write and verify"),
            ("backup", "BACKUP MEDIA", "Read to image"),
            ("format", "FORMAT MEDIA", "Prepare a card"),
            ("tools", "IMAGE TOOLS", "Inspect and manage"),
        ):
            button = tk.Button(
                sidebar,
                text=f"{title}\n{subtitle}",
                command=lambda page=key: self.show_page(page),
                justify="left",
                anchor="w",
                bg=NAV,
                fg=TEXT,
                activebackground=PANEL_2,
                activeforeground=MINT,
                relief="flat",
                bd=0,
                padx=20,
                pady=13,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
            )
            button.pack(fill="x")
            self.nav_buttons[key] = button
        tk.Frame(sidebar, bg=LINE, height=1).pack(fill="x", padx=20, pady=18)
        tk.Label(sidebar, text="SAFETY POLICY", bg=NAV, fg=MINT, font=("Consolas", 8, "bold")).pack(anchor="w", padx=20)
        tk.Label(
            sidebar,
            text="Only removable USB/SD media appears. Boot and system disks are always blocked.",
            bg=NAV,
            fg=MUTED,
            wraplength=170,
            justify="left",
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=20, pady=(8, 0))

        content = tk.Frame(workspace, bg=BG)
        content.pack(side="left", fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        for key in ("flash", "backup", "format", "tools"):
            page = tk.Frame(content, bg=BG, padx=26, pady=22)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        self._build_flash_page(self.pages["flash"])
        self._build_backup_page(self.pages["backup"])
        self._build_format_page(self.pages["format"])
        self._build_tools_page(self.pages["tools"])

        status = tk.Frame(self.root, bg="#081518", highlightbackground=LINE, highlightthickness=1)
        status.pack(fill="x", side="bottom")
        status.grid_columnconfigure(1, weight=1)
        tk.Label(status, textvariable=self.progress_text, bg="#081518", fg=MINT, font=("Consolas", 9, "bold"), width=20, anchor="w").grid(row=0, column=0, padx=(24, 12), pady=(10, 2))
        ttk.Progressbar(status, variable=self.progress_value, maximum=100).grid(row=0, column=1, sticky="ew", pady=(10, 2))
        tk.Label(status, textvariable=self.percent_text, bg="#081518", fg=TEXT, font=("Consolas", 9), width=7).grid(row=0, column=2, padx=(12, 24), pady=(10, 2))
        tk.Label(status, textvariable=self.status_detail, bg="#081518", fg=MUTED, font=("Segoe UI", 8), anchor="w").grid(row=1, column=0, columnspan=3, sticky="ew", padx=24, pady=(0, 9))

    def _build_flash_page(self, page: tk.Frame):
        self._page_title(page, "Flash an operating system", "Download Mobile Base or choose any supported Raspberry Pi image.")
        source = self._panel(page, "01  IMAGE SOURCE", 1)
        source.grid_columnconfigure(0, weight=1)
        self._entry(source, self.source_path).grid(row=1, column=0, sticky="ew", pady=(12, 4), ipady=10)
        self._grid_button(source, "BROWSE", self.browse_image, 1, 1)
        self.download_button = self._grid_button(source, "MOBILE BASE STABLE", self.download_recommended, 1, 2, primary=True)
        self.custom_button = self._grid_button(source, "DOWNLOAD URL", self.download_custom, 1, 3)
        tk.Label(source, textvariable=self.source_info, bg=PANEL, fg=MUTED, font=("Segoe UI", 9), anchor="w").grid(row=2, column=0, columnspan=4, sticky="ew", pady=(5, 0))

        target = self._panel(page, "02  TARGET + OPTIONS", 2, pady=(14, 0))
        target.grid_columnconfigure(0, weight=1)
        combo = self._disk_combo(target)
        combo.grid(row=1, column=0, sticky="ew", pady=(12, 6))
        self._grid_button(target, "REFRESH", self.refresh_disks, 1, 1)
        ttk.Checkbutton(target, text="Full byte-for-byte readback after writing", variable=self.verify_value).grid(row=2, column=0, sticky="w", pady=(8, 0))
        tk.Label(target, text="The target is erased only after disk details and typed confirmation.", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(row=3, column=0, sticky="w", pady=(6, 0))

        actions = tk.Frame(page, bg=BG)
        actions.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        actions.grid_columnconfigure(0, weight=1)
        self.flash_button = self._action_button(actions, "FLASH IMAGE + VERIFY", self.start_flash, primary=True)
        self.flash_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.verify_button = self._action_button(actions, "VERIFY EXISTING MEDIA", self.start_verify)
        self.verify_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        cards = tk.Frame(page, bg=BG)
        cards.grid(row=4, column=0, sticky="ew", pady=(20, 0))
        for column, (title, value, note) in enumerate((
            ("FORMATS", "IMG / ZST / GZ / XZ / ZIP", "Single-image archives"),
            ("IMAGE TRUST", "SHA-256", "Sidecars and official hashes"),
            ("WRITE PROOF", "FULL READBACK", "Enabled by default"),
        )):
            cards.grid_columnconfigure(column, weight=1)
            card = tk.Frame(cards, bg=PANEL, highlightbackground=LINE, highlightthickness=1, padx=15, pady=13)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
            tk.Label(card, text=title, bg=PANEL, fg=MUTED, font=("Consolas", 7, "bold")).pack(anchor="w")
            tk.Label(card, text=value, bg=PANEL, fg=MINT, font=("Consolas", 10, "bold")).pack(anchor="w", pady=(7, 2))
            tk.Label(card, text=note, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")

    def _build_backup_page(self, page: tk.Frame):
        self._page_title(page, "Create a complete image backup", "Read every byte from removable media into a reusable image and checksum it.")
        target = self._panel(page, "01  SOURCE MEDIA", 1)
        target.grid_columnconfigure(0, weight=1)
        combo = self._disk_combo(target)
        combo.grid(row=1, column=0, sticky="ew", pady=(12, 6))
        self._grid_button(target, "REFRESH", self.refresh_disks, 1, 1)
        tk.Label(target, text="Backup is read-only. No partition or filesystem is changed.", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=(5, 0))

        output = self._panel(page, "02  BACKUP DESTINATION", 2, pady=(14, 0))
        output.grid_columnconfigure(0, weight=1)
        self._entry(output, self.backup_path).grid(row=1, column=0, sticky="ew", pady=(12, 4), ipady=10)
        self._grid_button(output, "CHOOSE FILE", self.choose_backup_path, 1, 1)
        ttk.Checkbutton(output, text="Compress backup with Zstandard (.img.zst)", variable=self.backup_compress, command=self._backup_extension_changed).grid(row=2, column=0, sticky="w", pady=(8, 0))
        tk.Label(output, text="A SHA-256 sidecar is written beside every completed backup.", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(row=3, column=0, sticky="w", pady=(6, 0))

        self.backup_button = self._action_button(page, "CREATE FULL BACKUP IMAGE", self.start_backup, primary=True)
        self.backup_button.grid(row=3, column=0, sticky="ew", pady=(20, 0))

        note = self._panel(page, "BACKUP NOTES", 4, pady=(20, 0))
        tk.Label(note, text="The output includes empty space because it is a full-device image. A 128 GB card may take substantial time and storage even when compressed.", bg=PANEL, fg=TEXT, wraplength=800, justify="left", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(10, 0))

    def _build_format_page(self, page: tk.Frame):
        self._page_title(page, "Format removable media", "Prepare an SD card or USB drive for files, transfers, or a new imaging job.")
        target = self._panel(page, "01  TARGET MEDIA", 1)
        target.grid_columnconfigure(0, weight=1)
        combo = self._disk_combo(target)
        combo.grid(row=1, column=0, sticky="ew", pady=(12, 6))
        self._grid_button(target, "REFRESH", self.refresh_disks, 1, 1)

        options = self._panel(page, "02  FILESYSTEM", 2, pady=(14, 0))
        options.grid_columnconfigure(1, weight=1)
        tk.Label(options, text="Filesystem", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(12, 4))
        fs = ttk.Combobox(options, textvariable=self.fs_value, state="readonly", values=["exfat", "fat32", "ntfs"], width=12)
        fs.grid(row=1, column=1, sticky="w", padx=(16, 0), pady=(12, 4))
        tk.Label(options, text="Volume label", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=4)
        self._entry(options, self.label_value, width=22).grid(row=2, column=1, sticky="w", padx=(16, 0), pady=4, ipady=8)
        format_note = "Use exFAT for cards larger than 32 GB. Windows limits FAT32 formatting to 32 GB." if os.name == "nt" else "Use exFAT for broad large-card compatibility; FAT32 and NTFS are also available."
        tk.Label(options, text=format_note, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.format_button = self._action_button(page, "ERASE + FORMAT MEDIA", self.start_format, danger=True)
        self.format_button.grid(row=3, column=0, sticky="ew", pady=(20, 0))

    def _build_tools_page(self, page: tk.Frame):
        self._page_title(page, "Image tools and operation history", "Inspect checksums, open app storage, and review imaging activity.")
        tools = self._panel(page, "IMAGE INSPECTION", 1)
        tools.grid_columnconfigure(0, weight=1)
        tk.Label(tools, textvariable=self.source_path, bg=PANEL, fg=TEXT, font=("Segoe UI", 9), anchor="w").grid(row=1, column=0, columnspan=4, sticky="ew", pady=(12, 5))
        self.hash_button = self._grid_button(tools, "CALCULATE SHA-256", self.inspect_image, 2, 0, primary=True)
        self._grid_button(tools, "OPEN DOWNLOADS", lambda: self.open_folder(app_data() / "downloads"), 2, 1)
        self._grid_button(tools, "OPEN CACHE", lambda: self.open_folder(app_data() / "cache"), 2, 2)
        self._grid_button(tools, "CLEAR CACHE", self.clear_cache, 2, 3, danger=True)
        tk.Label(tools, textvariable=self.source_info, bg=PANEL, fg=MUTED, font=("Segoe UI", 8), anchor="w").grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        history = self._panel(page, "OPERATION LOG", 2, pady=(14, 0))
        history.grid_columnconfigure(0, weight=1)
        history.grid_rowconfigure(1, weight=1)
        self.log = tk.Text(history, bg="#061013", fg="#b8cecb", insertbackground=MINT, relief="flat", font=("Consolas", 9), height=13, padx=10, pady=8, state="disabled")
        self.log.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 8))
        self._grid_button(history, "SAVE LOG", self.save_log, 2, 1)
        self._log("Mobile Base Imager full workspace initialized.")
        self._log("No destructive operation can begin without exact target confirmation.")

    def _page_title(self, page: tk.Frame, title: str, subtitle: str):
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(99, weight=1)
        heading = tk.Frame(page, bg=BG)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        tk.Label(heading, text=title, bg=BG, fg=TEXT, font=("Segoe UI", 24, "bold")).pack(anchor="w")
        tk.Label(heading, text=subtitle, bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))

    def _panel(self, parent, title: str, row: int, pady=0):
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1, padx=16, pady=14)
        frame.grid(row=row, column=0, sticky="nsew", pady=pady)
        tk.Label(frame, text=title, bg=PANEL, fg=MINT, font=("Consolas", 9, "bold")).grid(row=0, column=0, columnspan=5, sticky="w")
        return frame

    def _entry(self, parent, variable, width=None):
        return tk.Entry(parent, textvariable=variable, width=width, bg="#081417", fg=TEXT, insertbackground=MINT, relief="flat", font=("Segoe UI", 10))

    def _disk_combo(self, parent):
        combo = ttk.Combobox(parent, textvariable=self.disk_value, state="readonly", font=("Segoe UI", 10))
        self.disk_combos.append(combo)
        return combo

    def _canvas_button(self, canvas, text, command, x, y, width, height, accent=True):
        button = tk.Button(canvas, text=text, command=command, bg=MINT if accent else PANEL_2, fg=BG if accent else MINT, activebackground="#7af3e5", activeforeground=BG, relief="flat", bd=0, font=("Segoe UI", 9, "bold"), cursor="hand2")
        canvas.create_window(x, y, width=width, height=height, anchor="nw", window=button)
        return button

    def _grid_button(self, parent, text, command, row, column, primary=False, danger=False):
        bg = MINT if primary else ("#3b2024" if danger else PANEL_2)
        fg = BG if primary else (RED if danger else MINT)
        button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=MINT, activeforeground=BG, relief="flat", bd=0, font=("Segoe UI", 8, "bold"), padx=12, pady=10, cursor="hand2")
        button.grid(row=row, column=column, padx=(8 if column else 0, 0), pady=(12, 4))
        self.action_controls.append(button)
        return button

    def _action_button(self, parent, text, command, primary=False, danger=False):
        bg = MINT if primary else ("#3b2024" if danger else PANEL_2)
        fg = BG if primary else (RED if danger else MINT)
        button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg, activebackground=MINT, activeforeground=BG, relief="flat", bd=0, font=("Segoe UI", 10, "bold"), padx=18, pady=14, cursor="hand2")
        self.action_controls.append(button)
        return button

    def show_page(self, name: str):
        self.pages[name].tkraise()
        for key, button in self.nav_buttons.items():
            button.configure(bg=PANEL_2 if key == name else NAV, fg=MINT if key == name else TEXT)

    def _load_manifest(self):
        self.manifest = get_manifest()
        text = f"Mobile Base {self.manifest['imageVersion']} Stable  /  {human_size(int(self.manifest.get('imageBytes') or 0))} download  /  SHA-256 verified"
        self.root.after(0, lambda: self.source_info.set(text))

    def _refresh_admin(self):
        if self.admin:
            self.admin_button.configure(text="ADMINISTRATOR READY" if os.name == "nt" else "ROOT ACCESS READY", fg=MINT, state="disabled")
        else:
            self.admin_button.configure(text="RESTART AS ADMIN" if os.name == "nt" else "RESTART AS ROOT", fg=AMBER, state="normal")

    def restart_admin(self):
        if os.name != "nt":
            if getattr(sys, "frozen", False):
                arguments = [sys.executable, *sys.argv[1:]]
            else:
                project_root = str(Path(__file__).resolve().parents[1])
                arguments = ["env", f"PYTHONPATH={project_root}", sys.executable, "-m", "app.mobile_base_imager", *sys.argv[1:]]
            try:
                subprocess.Popen(["pkexec", *arguments])
            except Exception as exc:
                messagebox.showerror(PRODUCT, f"Linux did not grant root access: {exc}")
                return
            self.root.destroy()
            return
        executable = sys.executable
        arguments = sys.argv[1:] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve()), *sys.argv[1:]]
        parameters = subprocess.list2cmdline(arguments)
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters, None, 1)
        if result <= 32:
            messagebox.showerror(PRODUCT, "Windows did not grant administrator access.")
            return
        self.root.destroy()

    def browse_image(self):
        path = filedialog.askopenfilename(
            title="Choose a disk image",
            filetypes=[("Supported images", "*.img *.img.zst *.img.gz *.img.xz *.zip"), ("Raw image", "*.img"), ("Compressed images", "*.zst *.gz *.xz *.zip"), ("All files", "*.*")],
        )
        if path:
            self._select_source(Path(path))

    def _select_source(self, path: Path):
        self.source_path.set(str(path))
        self.source_info.set(f"{image_format(path)}  /  {human_size(path.stat().st_size)}  /  {path.name}")

    def refresh_disks(self):
        if self.busy:
            return
        try:
            if self.demo:
                first_path = "" if os.name == "nt" else "/dev/sdb"
                second_path = "" if os.name == "nt" else "/dev/sdc"
                self.disks = [
                    Disk(3, "Generic SD/MMC Reader", 64_000_000_000, 12, "SD", "Removable Media", "SD\\CARD", False, False, False, "OK", first_path),
                    Disk(5, "SanDisk USB Reader", 128_000_000_000, 7, "USB", "Removable Media", "USBSTOR\\DISK", False, False, False, "OK", second_path),
                ]
            else:
                self.disks = enumerate_disks()
            self.disk_by_display = {disk.display: disk for disk in self.disks}
            values = list(self.disk_by_display)
            for combo in self.disk_combos:
                combo["values"] = values
            self.disk_value.set(self.disks[0].display if self.disks else "No safe removable media detected")
            self._set_backup_default()
            self._log(f"Drive scan complete: {len(self.disks)} safe removable target(s).")
        except Exception as exc:
            self._log(f"Drive scan failed: {exc}", error=True)

    def download_recommended(self):
        if self.busy:
            return
        destination = app_data() / "downloads" / self.manifest["imageAsset"]
        self._run_operation("DOWNLOAD", lambda: self._download_worker(self.manifest["imageUrl"], destination, self.manifest["imageSha256"]))

    def download_custom(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Download image URL")
        dialog.configure(bg=PANEL)
        dialog.geometry("650x310")
        dialog.transient(self.root)
        dialog.grab_set()
        url = tk.StringVar()
        checksum = tk.StringVar()
        tk.Label(dialog, text="DOWNLOAD IMAGE", bg=PANEL, fg=MINT, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=28, pady=(24, 8))
        tk.Label(dialog, text="HTTPS URL", bg=PANEL, fg=MUTED).pack(anchor="w", padx=28)
        self._entry(dialog, url).pack(fill="x", padx=28, pady=(5, 12), ipady=9)
        tk.Label(dialog, text="SHA-256 (recommended; optional)", bg=PANEL, fg=MUTED).pack(anchor="w", padx=28)
        self._entry(dialog, checksum).pack(fill="x", padx=28, pady=(5, 12), ipady=9)
        result: dict[str, str] = {}

        def accept():
            value = url.get().strip()
            digest = checksum.get().strip()
            if not value.lower().startswith("https://"):
                messagebox.showwarning(PRODUCT, "Enter an HTTPS image URL.", parent=dialog)
                return
            filename = Path(urllib.parse.urlparse(value).path).name
            if not filename or not is_supported_image(filename):
                messagebox.showwarning(PRODUCT, "The URL must end in .img, .img.zst, .img.gz, .img.xz, or .zip.", parent=dialog)
                return
            if digest and (len(digest) != 64 or any(character not in "0123456789abcdefABCDEF" for character in digest)):
                messagebox.showwarning(PRODUCT, "The SHA-256 value must contain exactly 64 hexadecimal characters.", parent=dialog)
                return
            if not digest and not messagebox.askyesno(PRODUCT, "No published checksum was provided. The app will calculate a local checksum, but cannot prove publisher authenticity. Continue?", parent=dialog):
                return
            result.update(url=value, checksum=digest.upper(), filename=filename)
            dialog.destroy()

        tk.Button(dialog, text="DOWNLOAD IMAGE", command=accept, bg=MINT, fg=BG, relief="flat", padx=18, pady=10, font=("Segoe UI", 9, "bold")).pack(pady=6)
        dialog.wait_window()
        if result:
            destination = app_data() / "downloads" / result["filename"]
            self._run_operation("DOWNLOAD", lambda: self._download_worker(result["url"], destination, result["checksum"] or None))

    def _download_worker(self, url: str, destination: Path, checksum: str | None):
        if destination.exists() and checksum and sha256_file(destination, self._progress, "VERIFYING DOWNLOAD") == checksum.upper():
            self._progress("VERIFIED CACHED DOWNLOAD", 1, 1)
        else:
            download_file(url, destination, checksum, self._progress)
        restore_user_ownership(destination.parent, destination, Path(str(destination) + ".sha256"))
        self.root.after(0, lambda: self._select_source(destination))
        return f"Image ready: {destination}"

    def selected_disk(self) -> Disk | None:
        return self.disk_by_display.get(self.disk_value.get())

    def _require_admin_disk(self) -> Disk | None:
        disk = self.selected_disk()
        if not disk:
            messagebox.showwarning(PRODUCT, "Insert and select a safe removable SD/USB device first.")
            return None
        if not self.admin:
            messagebox.showwarning(PRODUCT, "Restart as Administrator before accessing raw media." if os.name == "nt" else "Restart as root before accessing raw media.")
            return None
        return disk

    def _confirm_erase(self, action: str) -> Disk | None:
        disk = self._require_admin_disk()
        if not disk:
            return None
        if not messagebox.askyesno("Destructive operation", f"{action} will permanently erase {disk.identifier}:\n\n{disk.name}\n{disk.size_label}\n{disk.bus_name}\n\nContinue to typed confirmation?"):
            return None
        expected = disk.confirmation_text
        dialog = tk.Toplevel(self.root)
        dialog.title("Confirm target disk")
        dialog.configure(bg=PANEL)
        dialog.geometry("520x235")
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text="FINAL TARGET CONFIRMATION", bg=PANEL, fg=RED, font=("Segoe UI", 12, "bold")).pack(pady=(24, 8))
        tk.Label(dialog, text=f"Type {expected} to continue.", bg=PANEL, fg=TEXT).pack()
        value = tk.StringVar()
        entry = self._entry(dialog, value)
        entry.pack(fill="x", padx=36, pady=18, ipady=8)
        accepted = {"value": False}

        def confirm():
            if value.get().strip().upper() == expected:
                accepted["value"] = True
                dialog.destroy()
            else:
                messagebox.showwarning(PRODUCT, "Confirmation text does not match.", parent=dialog)

        tk.Button(dialog, text="ERASE SELECTED DISK", command=confirm, bg="#3b2024", fg=RED, relief="flat", padx=16, pady=9).pack()
        entry.focus_set()
        dialog.wait_window()
        return disk if accepted["value"] else None

    def _source(self) -> Path | None:
        source = Path(self.source_path.get().strip())
        if not source.exists() or not is_supported_image(source):
            messagebox.showwarning(PRODUCT, "Download or choose a supported image file first.")
            return None
        return source

    def start_flash(self):
        if self.busy:
            return
        source = self._source()
        if not source:
            return
        if not source.name.lower().endswith(".img") and not adjacent_checksum(source):
            if not messagebox.askyesno(PRODUCT, "This compressed image has no adjacent SHA-256 file. Continue after calculating and saving a local integrity checksum?"):
                return
        disk = self._confirm_erase("Flashing")
        if disk:
            self._run_operation("FLASH", lambda: self._flash_worker(source, disk))

    def _prepare_source(self, source: Path) -> Path:
        if not source.name.lower().endswith(".img"):
            expected = adjacent_checksum(source)
            actual = sha256_file(source, self._progress, "VERIFYING SOURCE")
            if expected and actual != expected:
                raise RuntimeError(f"Source checksum mismatch. Expected {expected}, received {actual}.")
            if not expected:
                write_checksum(source, actual)
                self._log(f"Created local checksum sidecar for {source.name}.")
        cache = app_data() / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        if not source.name.lower().endswith(".img") and shutil.disk_usage(cache).free < 10 * 1024**3:
            raise RuntimeError("At least 10 GB of free local space is required to prepare a compressed image.")
        image = prepare_image(source, cache, self._progress)
        restore_user_ownership(cache, image)
        return image

    def _flash_worker(self, source: Path, disk: Disk):
        image = self._prepare_source(source)
        if self.demo:
            self._demo_progress("DEMO FLASH + VERIFY")
            digest = sha256_file(image) if image.exists() else "DEMO"
        else:
            digest = flash_and_verify(image, disk, self._progress, self.verify_value.get())
        return f"{disk.identifier} is ready. Image SHA-256: {digest}"

    def start_verify(self):
        if self.busy:
            return
        source = self._source()
        disk = self._require_admin_disk()
        if not source or not disk:
            return
        if not messagebox.askyesno(PRODUCT, f"Read {disk.identifier} and compare it byte-for-byte with {source.name}? No data will be changed."):
            return
        self._run_operation("VERIFY", lambda: self._verify_worker(source, disk))

    def _verify_worker(self, source: Path, disk: Disk):
        image = self._prepare_source(source)
        if self.demo:
            self._demo_progress("DEMO VERIFY")
            digest = "DEMO-VERIFIED"
        else:
            digest = verify_image_against_disk(image, disk, self._progress)
        return f"{disk.identifier} matches the selected image. SHA-256: {digest}"

    def _set_backup_default(self):
        disk = self.selected_disk()
        if disk and not self.backup_path.get():
            stamp = time.strftime("%Y%m%d-%H%M")
            device_name = Path(disk.device_path).name if os.name != "nt" else f"disk-{disk.number}"
            home, _uid, _gid = user_identity()
            self.backup_path.set(str(home / "Documents" / f"{device_name}-backup-{stamp}.img.zst"))

    def choose_backup_path(self):
        extension = ".img.zst" if self.backup_compress.get() else ".img"
        filetypes = [("Zstandard disk image", "*.img.zst")] if self.backup_compress.get() else [("Raw disk image", "*.img")]
        path = filedialog.asksaveasfilename(title="Save full media backup", defaultextension=extension, filetypes=filetypes)
        if path:
            self.backup_path.set(path)

    def _backup_extension_changed(self):
        value = self.backup_path.get()
        if not value:
            return
        if self.backup_compress.get() and value.lower().endswith(".img"):
            self.backup_path.set(value + ".zst")
        elif not self.backup_compress.get() and value.lower().endswith(".img.zst"):
            self.backup_path.set(value[:-4])

    def start_backup(self):
        if self.busy:
            return
        disk = self._require_admin_disk()
        destination_text = self.backup_path.get().strip()
        if not disk:
            return
        if not destination_text:
            messagebox.showwarning(PRODUCT, "Choose a backup destination first.")
            return
        destination = Path(destination_text)
        if destination.exists() and not messagebox.askyesno(PRODUCT, f"Replace existing file?\n\n{destination}"):
            return
        if not messagebox.askyesno(PRODUCT, f"Create a full {disk.size_label} backup of {disk.identifier}?\n\nThis is read-only but may take a long time and require substantial storage."):
            return
        self._run_operation("BACKUP", lambda: self._backup_worker(disk, destination))

    def _backup_worker(self, disk: Disk, destination: Path):
        if self.demo:
            self._demo_progress("DEMO BACKUP")
            return f"Demo backup completed for {disk.identifier}: {destination}"
        result = backup_disk(disk, destination, self._progress, self.backup_compress.get())
        restore_user_ownership(result.path.parent, result.path, Path(str(result.path) + ".sha256"))
        return f"Backup complete: {result.path} / SHA-256: {result.sha256}"

    def start_format(self):
        if self.busy:
            return
        disk = self._confirm_erase("Formatting")
        if disk:
            self._run_operation("FORMAT", lambda: self._format_worker(disk))

    def _format_worker(self, disk: Disk):
        self._progress("FORMATTING MEDIA", 0, 1)
        if self.demo:
            time.sleep(1)
        else:
            format_disk(disk, self.fs_value.get(), self.label_value.get())
        self._progress("FORMAT COMPLETE", 1, 1)
        return f"{disk.identifier} formatted as {self.fs_value.get().upper()} with label {self.label_value.get().upper()}."

    def inspect_image(self):
        if self.busy:
            return
        source = self._source()
        if source:
            self._run_operation("INSPECT", lambda: self._inspect_worker(source))

    def _inspect_worker(self, source: Path):
        digest = sha256_file(source, self._progress, "CALCULATING SHA-256")
        checksum_path = write_checksum(source, digest)
        restore_user_ownership(checksum_path)
        self.root.after(0, lambda: self.source_info.set(f"{image_format(source)}  /  {human_size(source.stat().st_size)}  /  SHA-256 {digest}"))
        return f"Checksum written beside {source.name}: {digest}"

    def open_folder(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def clear_cache(self):
        cache = app_data() / "cache"
        if not cache.exists():
            messagebox.showinfo(PRODUCT, "The decompressed-image cache is already empty.")
            return
        if messagebox.askyesno(PRODUCT, "Remove all prepared/decompressed images from the app cache? Downloaded source images are kept."):
            shutil.rmtree(cache)
            cache.mkdir(parents=True, exist_ok=True)
            restore_user_ownership(cache)
            self._log("Prepared-image cache cleared.")

    def save_log(self):
        path = filedialog.asksaveasfilename(title="Save operation log", defaultextension=".log", filetypes=[("Log file", "*.log"), ("Text file", "*.txt")])
        if path:
            log_path = Path(path)
            log_path.write_text(self.log.get("1.0", "end-1c") + "\n", encoding="utf-8")
            restore_user_ownership(log_path)
            self._log(f"Log saved to {path}")

    def _demo_progress(self, stage: str):
        for index in range(101):
            self._progress(stage, index, 100)
            time.sleep(0.012)

    def _run_operation(self, name: str, worker):
        self.busy = True
        self._set_controls(False)
        self.progress_value.set(0)
        self.progress_text.set(name)
        self.percent_text.set("0%")
        self.status_detail.set(f"{name.title()} operation is running")
        self._log(f"{name} operation started.")

        def run():
            try:
                result = worker()
                self.root.after(0, lambda: self._finish_operation(result, None))
            except Exception as exc:
                self.root.after(0, lambda: self._finish_operation("", exc))

        threading.Thread(target=run, daemon=True).start()

    def _finish_operation(self, result: str, error: Exception | None):
        self.busy = False
        self._set_controls(True)
        if error:
            self.progress_text.set("FAILED")
            self.status_detail.set(str(error))
            self._log(str(error), error=True)
            messagebox.showerror(PRODUCT, str(error))
        else:
            self.progress_value.set(100)
            self.percent_text.set("100%")
            self.progress_text.set("COMPLETE")
            self.status_detail.set(result)
            self._log(result)
            messagebox.showinfo(PRODUCT, result)
        self.refresh_disks()

    def _set_controls(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for control in self.action_controls:
            control.configure(state=state)
        for combo in self.disk_combos:
            combo.configure(state="readonly" if enabled else "disabled")

    def _progress(self, stage: str, done: int, total: int):
        percent = (done / total * 100) if total else 0

        def update():
            self.progress_text.set(stage)
            self.progress_value.set(percent)
            self.percent_text.set(f"{percent:.0f}%")
            self.status_detail.set(f"{human_size(done)} of {human_size(total)}" if total else stage)

        self.root.after(0, update)

    def _log(self, message: str, error: bool = False):
        def write():
            if not hasattr(self, "log"):
                return
            self.log.configure(state="normal")
            self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {'ERROR  ' if error else ''}{message}\n")
            self.log.see("end")
            self.log.configure(state="disabled")

        if threading.current_thread() is threading.main_thread():
            write()
        else:
            self.root.after(0, write)

    def _capture_screenshot(self):
        try:
            from PIL import ImageGrab

            self.root.update_idletasks()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            width, height = self.root.winfo_width(), self.root.winfo_height()
            destination = Path(self.screenshot)
            destination.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab((x, y, x + width, y + height)).save(destination)
        finally:
            self.root.after(500, self.root.destroy)


def main() -> int:
    parser = argparse.ArgumentParser(description=PRODUCT)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--screenshot")
    parser.add_argument("--page", choices=["flash", "backup", "format", "tools"], default="flash")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sample = b"mobile-base-imager-full-self-test"
        packed = zstandard.ZstdCompressor().compress(sample)
        zstd_ready = zstandard.ZstdDecompressor().decompress(packed) == sample
        if not zstd_ready:
            raise RuntimeError("Zstandard round-trip self-test failed")
        print(json.dumps({"name": PRODUCT, "version": __version__, "platform": sys.platform, "admin": is_admin(), "manifest": FALLBACK_MANIFEST["imageAsset"], "zstandard": zstd_ready, "formats": 5, "modes": ["flash", "verify", "backup", "format"]}))
        return 0
    root = tk.Tk()
    ImagerApp(root, demo=args.demo, screenshot=args.screenshot, start_page=args.page)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
