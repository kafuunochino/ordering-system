"""金额以整数分持久化；折扣使用 Decimal，避免浮点误差。"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MAX_CENTS = 99_999_999


class ValidationError(ValueError):
    """可以直接展示给收银员的输入错误。"""


def decimal_value(value: str, label: str) -> Decimal:
    text = str(value).strip()
    if len(text) > 32:
        raise ValidationError(f"{label}输入过长。")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"请输入有效的{label}。") from None
    if not number.is_finite():
        raise ValidationError(f"请输入有效的{label}。")
    return number


def to_cents(value: str, label: str = "金额") -> int:
    number = decimal_value(value, label)
    if not Decimal(0) <= number <= Decimal(MAX_CENTS) / 100:
        raise ValidationError(f"{label}应在 0 至 999999.99 元之间。")
    cents = number * 100
    if cents != cents.to_integral_value():
        raise ValidationError(f"{label}最多保留两位小数。")
    return int(cents)


def discount_value(value: str) -> Decimal:
    discount = decimal_value(value, "折扣")
    if not Decimal(0) <= discount <= Decimal(10):
        raise ValidationError("折扣应在 0 至 10 之间，10 表示不打折，8.5 表示八五折。")
    if discount * 100 != (discount * 100).to_integral_value():
        raise ValidationError("折扣最多保留两位小数。")
    return discount


def discounted_cents(base_cents: int, discount: str) -> int:
    return int((Decimal(base_cents) * discount_value(discount) / 10).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    ))


def money(cents: int) -> str:
    return f"{Decimal(cents) / 100:.2f}"


def positive_int(value: str, label: str, maximum: int = 999) -> int:
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= maximum:
        raise ValidationError(f"{label}应为 1 至 {maximum} 的整数。")
    return int(text)


def clean_text(value: str, label: str, maximum: int = 60, required: bool = True) -> str:
    text = str(value).strip()
    if (required and not text) or len(text) > maximum:
        raise ValidationError(f"{label}{'不能为空，且' if required else ''}最多 {maximum} 个字符。")
    if any(ord(character) < 32 for character in text):
        raise ValidationError(f"{label}不能包含换行或控制字符。")
    return text
