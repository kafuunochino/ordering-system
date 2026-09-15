import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox

from .storage import Store
from .ui import App


def default_data_dir() -> Path:
    """固定用户数据目录，升级或移动 exe 不影响数据。"""
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "SanmuOrdering"


def main():
    parser = argparse.ArgumentParser(description="三木点餐系统")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir(), help="指定数据目录（默认 Windows 本地应用数据目录）")
    args = parser.parse_args()
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    try:
        data_dir = args.data_dir.expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                            handlers=[RotatingFileHandler(data_dir / "sanmu.log", maxBytes=1_000_000,
                                                          backupCount=3, encoding="utf-8")])
        store = Store(data_dir / "sanmu.sqlite3")
        app = App(store)
    except Exception as error:
        logging.exception("启动失败")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("三木点餐系统无法启动", f"{error}\n\n请检查数据目录权限，或使用 --data-dir 指定可写目录。", parent=root)
        root.destroy()
        raise SystemExit(1) from error
    app.mainloop()


if __name__ == "__main__":
    main()
