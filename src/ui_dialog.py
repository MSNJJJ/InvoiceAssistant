# src/ui_dialog.py
# 职责：弹出确认框/提示框，供 FR-1/FR-10 复用

import os

_DISPLAY_AVAILABLE: bool | None = None


def _has_gui() -> bool:
    """检测当前环境是否有可用的 GUI（tkinter 可正常打开窗口）。"""
    global _DISPLAY_AVAILABLE
    if _DISPLAY_AVAILABLE is not None:
        return _DISPLAY_AVAILABLE

    # Windows 下通常 GUI 可用，无需 DISPLAY 检查
    if os.name == "nt":
        try:
            import tkinter as tk  # noqa: F401
            root = tk.Tk()
            root.withdraw()
            root.destroy()
            _DISPLAY_AVAILABLE = True
            return True
        except Exception:
            _DISPLAY_AVAILABLE = False
            return False
    else:
        # Unix-like：检查 DISPLAY 环境变量
        if not os.environ.get("DISPLAY"):
            _DISPLAY_AVAILABLE = False
            return False
        try:
            import tkinter as tk  # noqa: F401
            root = tk.Tk()
            root.withdraw()
            root.destroy()
            _DISPLAY_AVAILABLE = True
            return True
        except Exception:
            _DISPLAY_AVAILABLE = False
            return False


def _get_tk_root():
    """创建并返回一个隐藏的 tkinter 根窗口。"""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    return root


def show_alert(title: str, message: str, level: str = "warning") -> None:
    """弹出提示框。

    level: "info" | "warning" | "error"

    - 有 GUI 环境时使用 tkinter.messagebox 展示
    - 无 GUI 环境时回退到 print()
    """
    if _has_gui():
        import tkinter.messagebox as mb

        root = _get_tk_root()
        try:
            if level == "info":
                mb.showinfo(title, message)
            elif level == "error":
                mb.showerror(title, message)
            else:  # "warning" 及默认
                mb.showwarning(title, message)
        finally:
            root.destroy()
    else:
        level_label = {"info": "INFO", "warning": "WARN", "error": "ERROR"}
        print(f"[{level_label.get(level, 'WARN')}] {title}: {message}")


def confirm_dialog(title: str, message: str) -> bool:
    """弹出确认对话框。

    返回 True（确认）/ False（取消）。

    - 有 GUI 环境时使用 tkinter.messagebox.askyesno
    - 无 GUI 环境时回退到 print() + input()
    """
    if _has_gui():
        import tkinter.messagebox as mb

        root = _get_tk_root()
        try:
            return mb.askyesno(title, message)
        finally:
            root.destroy()
    else:
        print(f"[CONFIRM] {title}: {message}")
        while True:
            answer = input("确认？(y/n): ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            print("请输入 y 或 n。")
