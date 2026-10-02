"""异常类型定义。"""


class GridPromoError(Exception):
    """本模块所有异常的基类。"""


class GridNotFoundError(GridPromoError):
    """网格不存在。"""


class PromoNotFoundError(GridPromoError):
    """促销不存在或已取消。"""


class InvalidTimeError(GridPromoError):
    """时间格式非法，或结束时间不晚于开始时间。"""


class InvalidCellError(GridPromoError):
    """格位坐标越界。"""


class ConflictError(GridPromoError):
    """排期越界：某时刻生效促销数超上限，或同一格位出现重叠。"""
