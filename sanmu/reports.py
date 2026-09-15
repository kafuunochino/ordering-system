"""营业统计的日期边界。按本机日期、结算时间计算，结束日期包含整天。"""

from calendar import monthrange
from datetime import date, timedelta

from .money import ValidationError


def parse_date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ValidationError("请选择有效日期。") from None


def date_bounds(start: str, end: str) -> tuple[str, str]:
    first, last = parse_date(start), parse_date(end)
    if first > last:
        raise ValidationError("开始日期不能晚于结束日期。")
    try:
        exclusive_end = last + timedelta(days=1)
    except OverflowError:
        raise ValidationError("结束日期超出支持范围。") from None
    return first.isoformat(), exclusive_end.isoformat()


def report_period(mode: str, selected: date | None = None, *, year: int | None = None,
                  month: int | None = None, end: date | None = None) -> tuple[str, str, str]:
    """返回包含首尾的日期范围和明细粒度；自然月、自然年支持闰年。"""
    today = date.today()
    selected = selected or today
    try:
        if mode == "today":
            first = last = today
        elif mode == "day":
            first = last = selected
        elif mode == "month":
            year = today.year if year is None else year
            month = today.month if month is None else month
            first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
        elif mode == "year":
            year = today.year if year is None else year
            first, last = date(year, 1, 1), date(year, 12, 31)
        elif mode == "range":
            first, last = selected, end or selected
        else:
            raise ValidationError("请选择有效的统计方式。")
    except (TypeError, ValueError):
        raise ValidationError("请选择有效的年份和月份。") from None
    date_bounds(first.isoformat(), last.isoformat())
    return first.isoformat(), last.isoformat(), "month" if mode == "year" else "day"
