"""Tkinter interface for the existing binary processing engine."""

import logging
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from binary_processor import (
    decimal_to_little_endian,
    format_hex,
    generate_output_path,
    replace_binary_ids,
)

logger = logging.getLogger(__name__)


def parse_id(text: str) -> int:
    """Accept decimal digits only and validate the UINT32 range."""
    if not isinstance(text, str):
        raise TypeError("ID must be entered as decimal text.")
    text = text.strip()
    if not text or not text.isascii() or not text.isdecimal():
        raise ValueError("Enter a decimal integer between 0 and 4294967295.")
    value = int(text)
    decimal_to_little_endian(value)
    return value


def friendly_error(error: Exception) -> str:
    """Translate technical failures into concise desktop messages."""
    if isinstance(error, FileNotFoundError):
        return "The selected file or output folder no longer exists."
    if isinstance(error, PermissionError):
        return "Access was denied. Check file and output folder permissions."
    if isinstance(error, FileExistsError):
        return "The output file already exists. Please try again for a new name."
    if isinstance(error, (ValueError, TypeError)):
        return str(error)
    if isinstance(error, OSError):
        return ("Unable to read or save the file. Check access permissions, "
                "available disk space, and the output folder.")
    return "Processing could not be completed. See the application log."


class BinaryIDReplacerApp:
    """Responsive desktop form; only the main thread accesses Tkinter."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.busy = False
        self.worker: Optional[threading.Thread] = None
        self.output_path: Optional[Path] = None
        self.results: queue.Queue = queue.Queue()
        self.file_path = tk.StringVar(root)
        self.old_id = tk.StringVar(root)
        self.new_id = tk.StringVar(root)
        self.old_hex = tk.StringVar(root, "Invalid ID")
        self.new_hex = tk.StringVar(root, "Invalid ID")
        self.status = tk.StringVar(root, "Ready")
        root.title("Binary ID Replacer")
        root.geometry("620x450")
        root.minsize(580, 430)
        root.protocol("WM_DELETE_WINDOW", self._close)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Primary.TButton", padding=(16, 10))
        style.configure("Hex.TLabel", font=("Consolas", 10))
        self._build()
        for variable in (self.file_path, self.old_id, self.new_id):
            variable.trace_add("write", self._inputs_changed)
        self._inputs_changed()
        root.update_idletasks()
        width = max(620, root.winfo_reqwidth())
        height = max(450, root.winfo_reqheight())
        root.minsize(width, height)
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        self.poll_id = root.after(100, self._poll_results)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=24)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="Binary ID Replacer", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(frame, text="Replace 4-byte Little Endian integer IDs "
                  "inside binary files.").grid(row=1, column=0, sticky="w",
                                              pady=(5, 20))
        files = ttk.LabelFrame(frame, text="Selected File", padding=12)
        files.grid(row=2, column=0, sticky="ew")
        files.columnconfigure(0, weight=1)
        ttk.Entry(files, textvariable=self.file_path, state="readonly").grid(
            row=0, column=0, sticky="ew", padx=(0, 10))
        self.browse_button = ttk.Button(files, text="Browse", command=self.browse)
        self.browse_button.grid(row=0, column=1)
        ids = ttk.Frame(frame)
        ids.grid(row=3, column=0, sticky="ew", pady=20)
        ids.columnconfigure((0, 1), weight=1, uniform="ids")
        entries = []
        for col, title, value, preview in (
            (0, "Old ID", self.old_id, self.old_hex),
            (1, "New ID", self.new_id, self.new_hex),
        ):
            group = ttk.Frame(ids, padding=(0 if col == 0 else 12, 0,
                                            12 if col == 0 else 0, 0))
            group.grid(row=0, column=col, sticky="ew")
            group.columnconfigure(0, weight=1)
            ttk.Label(group, text=title).grid(row=0, column=0, sticky="w")
            entry = ttk.Entry(group, textvariable=value)
            entry.grid(row=1, column=0, sticky="ew", pady=(5, 8))
            entries.append(entry)
            ttk.Label(group, text="Little Endian HEX:").grid(
                row=2, column=0, sticky="w")
            ttk.Label(group, textvariable=preview, style="Hex.TLabel").grid(
                row=3, column=0, sticky="w", pady=(3, 0))
        self.old_entry, self.new_entry = entries
        self.process_button = ttk.Button(
            frame, text="Process & Save", style="Primary.TButton",
            command=self.process)
        self.process_button.grid(row=4, column=0, sticky="ew")
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=5, column=0, sticky="ew", pady=(12, 8))
        self.progress.grid_remove()
        frame.rowconfigure(6, weight=1)
        footer = ttk.Frame(frame)
        footer.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status).grid(
            row=0, column=0, sticky="w")
        self.folder_button = ttk.Button(
            footer, text="Open Output Folder", command=self.open_output_folder,
            state="disabled")
        self.folder_button.grid(row=0, column=1)

    def _validated_inputs(self) -> tuple:
        if not self.file_path.get():
            raise ValueError("Please select a binary file.")
        path = Path(self.file_path.get())
        if not path.is_file():
            raise ValueError("The selected file is missing or is not a file.")
        old, new = parse_id(self.old_id.get()), parse_id(self.new_id.get())
        if old == new:
            raise ValueError("Old ID and New ID must differ.")
        return path, old, new

    def _inputs_changed(self, *_args: str) -> None:
        for value, preview in ((self.old_id, self.old_hex),
                               (self.new_id, self.new_hex)):
            try:
                preview.set(format_hex(decimal_to_little_endian(
                    parse_id(value.get()))))
            except (ValueError, TypeError):
                preview.set("Invalid ID")
        if self.busy:
            return
        try:
            self._validated_inputs()
        except (ValueError, TypeError, OSError):
            self.process_button.state(["disabled"])
            self.status.set("File selected" if self.file_path.get() else "Ready")
        else:
            self.process_button.state(["!disabled"])
            self.status.set("Ready to process")

    def browse(self) -> None:
        if self.busy:
            return
        selected = filedialog.askopenfilename(
            parent=self.root, title="Select a binary file",
            filetypes=[("PAK Files", "*.pak"), ("Binary Files", "*.bin"),
                       ("DAT Files", "*.dat"), ("All Files", "*.*")])
        if selected:
            self.file_path.set(str(Path(selected).absolute()))
            logger.info("Selected file: %s", selected)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (self.browse_button, self.old_entry, self.new_entry):
            widget.state(["disabled" if busy else "!disabled"])
        if busy:
            self.process_button.state(["disabled"])
            self.folder_button.state(["disabled"])
            self.progress.grid()
            self.progress.start(12)
            self.status.set("Processing...")
        else:
            self.progress.stop()
            self.progress.grid_remove()
            self._inputs_changed()

    def process(self) -> None:
        if self.busy:
            return
        try:
            path, old, new = self._validated_inputs()
            output = generate_output_path(path)
        except (ValueError, TypeError, OSError) as error:
            logger.exception("Input validation failed")
            messagebox.showerror("Unable to Process", friendly_error(error),
                                 parent=self.root)
            return
        self.output_path = None
        self._set_busy(True)
        try:
            # Non-daemon: never abandon an in-progress file write on exit.
            self.worker = threading.Thread(
                target=self._worker, args=(path, output, old, new),
                name="binary-id-worker", daemon=False)
            self.worker.start()
        except Exception as error:
            logger.exception("Could not start worker")
            self.worker = None
            self._set_busy(False)
            self.status.set("Processing failed")
            messagebox.showerror("Processing Failed", friendly_error(error),
                                 parent=self.root)

    def _worker(self, path: Path, output: Path, old: int, new: int) -> None:
        """Perform disk work and enqueue results, without any Tk calls."""
        try:
            logger.info("GUI processing started: %s", path)
            original_size = path.stat().st_size
            count = replace_binary_ids(path, output, old, new)
            output_stat = output.lstat()
            output_size = output_stat.st_size
            cleanup_error = None
            if count == 0:
                try:
                    # Remove only the generated regular file, never an alias
                    # of the input or a path replaced since the size check.
                    if (output.is_symlink() or output.samefile(path)
                            or output.lstat() != output_stat):
                        raise OSError("Output changed before cleanup")
                    output.unlink()
                    logger.info("Removed zero-match output: %s", output)
                except OSError as error:
                    cleanup_error = str(error)
                    logger.exception("Could not remove zero-match output: %s",
                                     output)
            logger.info("GUI processing success: replacements=%d output=%s",
                        count, output)
            self.results.put(("success", (output, count, original_size,
                                          output_size, cleanup_error)))
        except Exception as error:
            logger.exception("GUI processing failed")
            self.results.put(("error", error))

    def _poll_results(self) -> None:
        # Consume the result only after its worker has exited. Never block Tk
        # waiting for a running worker, and reap completed threads promptly.
        if self.worker is not None:
            if self.worker.is_alive():
                self.poll_id = self.root.after(100, self._poll_results)
                return
            self.worker.join()
            self.worker = None
        try:
            kind, result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._set_busy(False)
            if kind == "error":
                self.status.set("Processing failed")
                messagebox.showerror("Processing Failed", friendly_error(result),
                                     parent=self.root)
            else:
                output, count, original_size, output_size, cleanup_error = result
                if count == 0:
                    self.output_path = None
                    self.folder_button.state(["disabled"])
                    self.status.set("No matching ID found")
                    detail = "No modified file was created."
                    if cleanup_error is not None:
                        detail = ("No IDs were changed, but the generated copy "
                                  "could not be removed automatically.\n\n"
                                  f"Please check this path:\n{output}")
                    messagebox.showwarning(
                        "No Matching ID Found",
                        "The Old ID was not found in the selected file.\n\n"
                        + detail, parent=self.root)
                else:
                    self.output_path = output
                    if os.name == "nt":
                        self.folder_button.state(["!disabled"])
                    self.status.set(f"Completed — {count} replacements")
                    messagebox.showinfo(
                        "Processing Complete",
                        f"Replacements Made: {count}\n\n"
                        f"Original Size: {original_size:,} bytes\n"
                        f"Output Size: {output_size:,} bytes\n\n"
                        f"Saved To:\n{output}", parent=self.root)
        self.poll_id = self.root.after(100, self._poll_results)

    def open_output_folder(self) -> None:
        if self.output_path is None or self.busy:
            return
        try:
            os.startfile(str(self.output_path.parent))
        except (OSError, AttributeError) as error:
            logger.exception("Could not open output folder")
            messagebox.showerror("Unable to Open Folder", friendly_error(error),
                                 parent=self.root)

    def _close(self) -> None:
        if self.busy:
            messagebox.showinfo("Processing in Progress",
                                "Please wait for processing to finish "
                                "before closing the application.",
                                parent=self.root)
            return
        self.root.after_cancel(self.poll_id)
        self.root.destroy()
