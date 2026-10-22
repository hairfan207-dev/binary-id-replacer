"""Launch the Binary ID Replacer desktop application."""

import logging
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from logging.handlers import RotatingFileHandler

from gui import BinaryIDReplacerApp


APP_VERSION = "1.0.0"


def get_log_path() -> Path:
    """Resolve a per-user path independently of CWD or frozen source paths."""
    configured = os.environ.get("LOCALAPPDATA", "")
    base = Path(configured) if configured else Path.home()
    if not base.is_absolute():
        base = Path.home()
    return base / "Binary ID Replacer" / "binary_replacer.log"


def configure_logging() -> Path:
    """Write bounded logs to a writable, per-user application folder."""
    log_path = get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024,
                                  backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return log_path


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        log_path = configure_logging()
    except OSError:
        messagebox.showerror("Unable to Start",
                             "Unable to create the application log. Check "
                             "permissions for your user application folder.",
                             parent=root)
        root.destroy()
        return
    logging.info("Binary ID Replacer %s startup; log=%s",
                 APP_VERSION, log_path)
    BinaryIDReplacerApp(root)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
