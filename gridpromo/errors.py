"""异常类型定义。"""


class GridPromoError(Exception):
    """本模块所有业务异常的基类。"""


class GridNotFoundError(GridPromoError):
    """网格不存在。"""


class PromotionNotFoundError(GridPromoError):
    """促销不存在。"""


class InvalidTimeError(GridPromoError):
    """时间格式非法或结束不晚于开始。"""


class ConflictError(GridPromoError):
    """排期违反容量或格位独占约束，整单拒绝。"""
