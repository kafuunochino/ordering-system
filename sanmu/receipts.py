"""结算单展示数据与文本导出；显示处理不修改原始订单。"""

from decimal import Decimal
import re
import unicodedata

from .money import money


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


def receipt_text(value: str) -> str:
    """小票不显示中英文圆括号及其内部内容，包括嵌套括号。"""
    text = str(value)
    while True:
        cleaned = re.sub(r"[（(][^()（）]*[)）]", "", text)
        if cleaned == text:
            return re.sub(r"[()（）]", "", cleaned).strip()
        text = cleaned


def receipt_style(settings: dict) -> dict:
    return {"version": 1, "shop_name": settings.get("shop_name", "三木点餐系统"),
            "receipt_footer": settings.get("receipt_footer", "谢谢惠顾！"),
            "paper_width": str(settings.get("paper_width", "80")),
            "logo_id": settings.get("logo_id", "")}


def legacy_receipt_style(receipt: str, settings: dict) -> dict:
    """旧账单仍使用原始小票中的店名、页脚及纸宽，Logo 使用当前设置。"""
    style = receipt_style(settings)
    lines = (receipt or "").splitlines()
    separators = [index for index, line in enumerate(lines) if line and set(line) == {"-"}]
    if separators:
        style["paper_width"] = "58" if len(lines[separators[0]]) <= 32 else "80"
        title = next((i for i, line in enumerate(lines[:separators[0]]) if line.strip() == "结 算 单"), None)
        if title is not None:
            style["shop_name"] = "".join(line.strip() for line in lines[:title])
        style["receipt_footer"] = "".join(line.strip() for line in lines[separators[-1] + 1:])
    return style


def summary_rows(order: dict) -> list[tuple[str, str]]:
    rows = [("餐品合计", f"￥{money(order['subtotal_cents'])}")]
    if order["base_cents"] != order["subtotal_cents"]:
        rows.extend([("金额调整", f"￥{money(order['base_cents'] - order['subtotal_cents'])}"),
                     ("结算金额", f"￥{money(order['base_cents'])}")])
    if Decimal(order["discount"]) != Decimal("10"):
        rows.extend([("折扣", f"{order['discount']} 折"),
                     ("折扣优惠", f"￥{money(order['base_cents'] - order['final_cents'])}")])
    rows.append(("最终实收", f"￥{money(order['final_cents'])}"))
    return rows


def format_receipt(order: dict, settings: dict) -> str:
    """纯文本使用中英文显示宽度对齐；图形预览和打印使用真实字形尺寸。"""
    columns = 32 if str(settings.get("paper_width", "80")) == "58" else 48
    separator = "-" * columns

    def center(value):
        return [" " * max(0, (columns - display_width(part)) // 2) + part
                for part in wrap_text(receipt_text(value), columns)]

    def pair(label, value):
        left = label + "："
        return left + " " * max(1, columns - display_width(left + value)) + value

    lines = center(settings.get("shop_name", "三木点餐系统")) + center("结 算 单")
    lines.extend([separator, f"单号：SM{order['id']:08d}", f"桌台：{receipt_text(order['table_name'])}",
                  f"开单：{order['opened_at']}", f"结算：{order['closed_at']}", separator])
    widths = (columns - 25, 4, 9, 9)

    def row(values):
        return " ".join(value + " " * max(0, size - display_width(value)) if index == 0 else
                        " " * max(0, size - display_width(value)) + value
                        for index, (value, size) in enumerate(zip(values, widths)))

    lines.append(row(("餐品", "数量", "单价", "金额")))
    for item in order["items"]:
        names = wrap_text(receipt_text(item["product_name"]), widths[0])
        for index, name in enumerate(names):
            values = (str(item["quantity"]), money(item["unit_cents"]), money(item["unit_cents"] * item["quantity"])) if index == 0 else ("", "", "")
            lines.append(row((name, *values)).rstrip())
    lines.append(separator)
    lines.extend(pair(label, value) for label, value in summary_rows(order))
    note = receipt_text(order.get("note", ""))
    if note:
        lines.extend(wrap_text(f"备注：{note}", columns))
    lines.append(separator)
    lines.extend(center(settings.get("receipt_footer", "谢谢惠顾！")))
    return "\n".join(part for line in lines for part in wrap_text(line, columns)) + "\n"
