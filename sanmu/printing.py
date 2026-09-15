"""文本结算单及 Windows GDI 驱动打印。无需第三方 Python 包。"""

import ctypes
from ctypes import wintypes
import sys
import unicodedata

from .money import ValidationError, money


def display_width(text: str) -> int:
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def wrap_text(text: str, columns: int) -> list[str]:
    result, current, width = [], "", 0
    for char in text:
        size = display_width(char)
        if current and width + size > columns:
            result.append(current)
            current, width = "", 0
        current += char
        width += size
    result.append(current)
    return result


def format_receipt(order: dict, settings: dict) -> str:
    columns = 32 if str(settings.get("paper_width", "80")) == "58" else 48
    separator = "-" * columns
    lines = [settings.get("shop_name", "三木点餐系统"), "结 算 单", separator,
             f"单号：SM{order['id']:08d}", f"桌号：{order['table_name']}",
             f"开单：{order['opened_at']}", f"结算：{order['closed_at']}", separator]
    for item in order["items"]:
        lines.append(item["product_name"])
        lines.append(f"  {item['quantity']} × {money(item['unit_cents'])} = "
                     f"{money(item['quantity'] * item['unit_cents'])}")
    lines.extend([separator, f"餐品合计：￥{money(order['subtotal_cents'])}",
                  f"结算金额：￥{money(order['base_cents'])}",
                  f"金额调整：￥{money(order['base_cents'] - order['subtotal_cents'])}",
                  f"折扣：{order['discount']} 折（10 折为原价）",
                  f"折扣优惠：￥{money(order['base_cents'] - order['final_cents'])}",
                  f"最终实收：￥{money(order['final_cents'])}"])
    if order.get("note"):
        lines.append(f"备注：{order['note']}")
    lines.extend([separator, settings.get("receipt_footer", "谢谢惠顾！")])
    return "\n".join(part for line in lines for part in wrap_text(line, columns)) + "\n"


def _windows():
    if sys.platform != "win32":
        raise ValidationError("打印功能仅支持 Windows。")


def available_printers() -> list[str]:
    _windows()

    class PRINTER_INFO_4(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR),
                    ("Attributes", wintypes.DWORD)]

    spool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    enum = spool.EnumPrintersW
    enum.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                     wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    enum.restype = wintypes.BOOL
    needed, count = wintypes.DWORD(), wintypes.DWORD()
    success = enum(2 | 4, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(count))
    if not needed.value:
        if not success and ctypes.get_last_error() not in (0, 122):
            raise ctypes.WinError(ctypes.get_last_error())
        return []
    buffer = ctypes.create_string_buffer(needed.value)
    if not enum(2 | 4, None, 4, buffer, needed, ctypes.byref(needed), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    records = ctypes.cast(buffer, ctypes.POINTER(PRINTER_INFO_4))
    return sorted({records[index].pPrinterName for index in range(count.value)})


def print_receipt(printer_name: str, receipt: str, title: str = "三木点餐系统结算单") -> int:
    """返回 Windows 队列作业 ID；提交成功不等于硬件实际出纸。在线程中调用。"""
    _windows()
    if not printer_name:
        raise ValidationError("请先在系统设置中选择已安装的打印机。")
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)

    class DOCINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR),
                    ("lpszOutput", wintypes.LPCWSTR), ("lpszDatatype", wintypes.LPCWSTR),
                    ("fwType", wintypes.DWORD)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

    # Explicit pointer-sized signatures are necessary on 64-bit Python.
    signatures = {
        "CreateDCW": ([wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p], ctypes.c_void_p),
        "DeleteDC": ([ctypes.c_void_p], wintypes.BOOL),
        "GetDeviceCaps": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
        "CreateFontW": ([ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR], ctypes.c_void_p),
        "SelectObject": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p),
        "DeleteObject": ([ctypes.c_void_p], wintypes.BOOL),
        "StartDocW": ([ctypes.c_void_p, ctypes.POINTER(DOCINFO)], ctypes.c_int),
        "StartPage": ([ctypes.c_void_p], ctypes.c_int),
        "EndPage": ([ctypes.c_void_p], ctypes.c_int),
        "EndDoc": ([ctypes.c_void_p], ctypes.c_int),
        "AbortDoc": ([ctypes.c_void_p], ctypes.c_int),
        "TextOutW": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int], wintypes.BOOL),
        "GetTextExtentPoint32W": ([ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(SIZE)], wintypes.BOOL),
    }
    for name, (arguments, returns) in signatures.items():
        function = getattr(gdi, name)
        function.argtypes, function.restype = arguments, returns

    def checked(result, operation):
        if result <= 0:
            raise OSError(f"{operation}失败（Windows 错误 {ctypes.get_last_error()}）。请检查打印队列和驱动。")
        return result

    def units(text):
        return len(text.encode("utf-16-le")) // 2

    dc = gdi.CreateDCW("WINSPOOL", printer_name, None, None)
    if not dc:
        raise OSError("无法连接打印机。请检查设备名称、驱动和 Windows 打印队列。")
    font = old_font = None
    started = False
    try:
        width, height = gdi.GetDeviceCaps(dc, 8), gdi.GetDeviceCaps(dc, 10)
        dpi_x, dpi_y = gdi.GetDeviceCaps(dc, 88), gdi.GetDeviceCaps(dc, 90)
        if min(width, height, dpi_x, dpi_y) <= 0:
            raise OSError("打印机驱动没有返回有效的纸张尺寸。")
        margin = max(1, round(dpi_x * 1.5 / 25.4))
        font_height = max(8, round(dpi_y * 9 / 72))
        font = gdi.CreateFontW(-font_height, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft YaHei")
        if not font:
            raise OSError("创建中文打印字体失败。")
        old_font = gdi.SelectObject(dc, font)
        line_height = round(font_height * 1.45)
        printable_width = width - 2 * margin
        if printable_width <= font_height * 2 or height < line_height + 2 * margin:
            raise OSError("打印纸张尺寸过小，请在打印机驱动中设置正确纸宽。")
        # Wrap using actual glyph widths to avoid clipping Chinese and long product names.
        lines = []
        for original in receipt.splitlines():
            line = ""
            for character in original:
                candidate = line + character
                extent = SIZE()
                checked(gdi.GetTextExtentPoint32W(dc, candidate, units(candidate), ctypes.byref(extent)), "测量文本")
                if line and extent.cx > printable_width:
                    lines.append(line)
                    line = character
                else:
                    line = candidate
            lines.append(line)
        info = DOCINFO(ctypes.sizeof(DOCINFO), title, None, None, 0)
        job_id = checked(gdi.StartDocW(dc, ctypes.byref(info)), "创建打印任务")
        started = True
        checked(gdi.StartPage(dc), "开始打印页面")
        y = margin
        for line in lines:
            if y + line_height > height - margin:
                checked(gdi.EndPage(dc), "结束打印页面")
                checked(gdi.StartPage(dc), "开始打印页面")
                y = margin
            checked(gdi.TextOutW(dc, margin, y, line, units(line)), "输出文本")
            y += line_height
        checked(gdi.EndPage(dc), "结束打印页面")
        checked(gdi.EndDoc(dc), "提交打印任务")
        started = False
        return job_id
    finally:
        if started:
            gdi.AbortDoc(dc)
        if old_font:
            gdi.SelectObject(dc, old_font)
        if font:
            gdi.DeleteObject(font)
        gdi.DeleteDC(dc)
