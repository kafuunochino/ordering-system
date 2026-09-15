"""Windows 打包入口：固定图标与资源路径，隔离同名系统 DLL 的查找顺序。"""
import os
from pathlib import Path
import sys


def main():
    if sys.platform != "win32":
        raise SystemExit("请在 Windows 上打包 exe。")
    root = Path(__file__).resolve().parent
    if not (root / "icon.png").is_file():
        raise SystemExit("项目根目录缺少 icon.png。")
    os.chdir(root)
    system = Path(os.environ["SystemRoot"])
    # 在打包进程内设置，防止启动器在 Python 启动时重新排列 PATH。
    # Qt 使用 Windows 自带的 ICU，不能被其他工具的同名 DLL 替代。
    os.environ["PATH"] = os.pathsep.join((str(system / "System32"), str(system), os.environ.get("PATH", "")))
    from PyInstaller.__main__ import run
    run(["--noconfirm", "--clean", "--onefile", "--windowed", "--name", "SanmuOrdering",
         "--icon", "icon.png", "--add-data", "icon.png:.", "--workpath", "build/windows", "main.py"])


if __name__ == "__main__":
    main()
