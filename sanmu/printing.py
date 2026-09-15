"""Windows GDI 小票打印；图形排版与预览一致，支持居中 Logo。"""

import ctypes
from ctypes import wintypes
import sys

from .money import ValidationError
from .receipts import display_width, format_receipt, wrap_text  # 兼容原有文本导出调用


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


def print_receipt(printer_name: str, receipt: dict, title: str = "三木点餐系统结算单") -> int:
    """返回 Windows 队列作业 ID；提交成功不等于硬件实际出纸。在线程中调用。"""
    _windows()
    if not printer_name:
        raise ValidationError("请先在系统设置中选择已安装的打印机。")
    from .receipt_render import ReceiptLayout
    layout = ReceiptLayout(receipt)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)

    class DOCINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR),
                    ("lpszOutput", wintypes.LPCWSTR), ("lpszDatatype", wintypes.LPCWSTR),
                    ("fwType", wintypes.DWORD)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    # Explicit pointer-sized signatures are necessary on 64-bit Python.
    signatures = {
        "CreateDCW": ([wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p], ctypes.c_void_p),
        "DeleteDC": ([ctypes.c_void_p], wintypes.BOOL),
        "GetDeviceCaps": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
        "StartDocW": ([ctypes.c_void_p, ctypes.POINTER(DOCINFO)], ctypes.c_int),
        "StartPage": ([ctypes.c_void_p], ctypes.c_int),
        "EndPage": ([ctypes.c_void_p], ctypes.c_int),
        "EndDoc": ([ctypes.c_void_p], ctypes.c_int),
        "AbortDoc": ([ctypes.c_void_p], ctypes.c_int),
        "StretchDIBits": ([ctypes.c_void_p] + [ctypes.c_int] * 8 + [ctypes.c_void_p,
                           ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT, wintypes.DWORD], ctypes.c_int),
    }
    for name, (arguments, returns) in signatures.items():
        function = getattr(gdi, name)
        function.argtypes, function.restype = arguments, returns

    def checked(result, operation):
        if result <= 0:
            raise OSError(f"{operation}失败（Windows 错误 {ctypes.get_last_error()}）。请检查打印队列和驱动。")
        return result

    dc = gdi.CreateDCW("WINSPOOL", printer_name, None, None)
    if not dc:
        raise OSError("无法连接打印机。请检查设备名称、驱动和 Windows 打印队列。")
    started = False
    try:
        width, height = gdi.GetDeviceCaps(dc, 8), gdi.GetDeviceCaps(dc, 10)
        dpi_x, dpi_y = gdi.GetDeviceCaps(dc, 88), gdi.GetDeviceCaps(dc, 90)
        if min(width, height, dpi_x, dpi_y) <= 0:
            raise OSError("打印机驱动没有返回有效的纸张尺寸。")
        target_width = min(width, round(int(receipt["style"]["paper_width"]) * dpi_x / 25.4))
        if target_width < dpi_x * 40 / 25.4:
            raise OSError("打印纸张尺寸过小，请在打印机驱动中设置正确纸宽。")
        ratio = dpi_y / dpi_x
        logical_height = int(height / (target_width / layout.width * ratio))
        pages = layout.pages(logical_height)
        physical_width, offset_x = gdi.GetDeviceCaps(dc, 110), gdi.GetDeviceCaps(dc, 112)
        x = max(0, min(width - target_width, round((physical_width - target_width) / 2) - offset_x)) if physical_width else (width - target_width) // 2
        info = DOCINFO(ctypes.sizeof(DOCINFO), title, None, None, 0)
        job_id = checked(gdi.StartDocW(dc, ctypes.byref(info)), "创建打印任务")
        started = True
        for page in pages:
            image = layout.render(page, target_width, ratio)
            pixels = ctypes.create_string_buffer(bytes(image.constBits()))
            # RGB32 在 Windows 内存中为 BGRX；负高度表示从顶部开始的 DIB。
            bitmap = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), image.width(), -image.height(),
                                      1, 32, 0, image.sizeInBytes(), 0, 0, 0, 0)
            checked(gdi.StartPage(dc), "开始打印页面")
            checked(gdi.StretchDIBits(dc, x, 0, image.width(), image.height(), 0, 0,
                    image.width(), image.height(), pixels, ctypes.byref(bitmap), 0, 0x00CC0020), "输出小票图像")
            checked(gdi.EndPage(dc), "结束打印页面")
        checked(gdi.EndDoc(dc), "提交打印任务")
        started = False
        return job_id
    finally:
        if started:
            gdi.AbortDoc(dc)
        gdi.DeleteDC(dc)
