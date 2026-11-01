from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from uuid import uuid4


def uid() -> str:
    return uuid4().hex


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


STATES = {
    'unlabeled': '未标注', 'predicted': '已预标注', 'pending': '待复核',
    'reviewed': '已复核有目标', 'negative': '已复核无目标',
    'error': '文件异常', 'excluded': '已排除',
}
REVIEWED = {'reviewed', 'negative'}


@dataclass
class Box:
    category_id: str
    x1: float
    y1: float
    x2: float
    y2: float
    id: str = field(default_factory=uid)
    source: str = 'manual'
    score: float | None = None
    model_id: str | None = None
    model_class: int | None = None
    run_id: str | None = None
    edited: bool = False

    def validate(self, width: int, height: int) -> None:
        coords = (self.x1, self.y1, self.x2, self.y2)
        if not all(math.isfinite(v) for v in coords):
            raise ValueError('框坐标包含 NaN 或 Inf')
        if self.x2 - self.x1 < 1 - 1e-8 or self.y2 - self.y1 < 1 - 1e-8:
            raise ValueError('检测框宽高必须至少 1 像素')
        if self.x1 < -1e-8 or self.y1 < -1e-8 or self.x2 > width + 1e-8 or self.y2 > height + 1e-8:
            raise ValueError('检测框超出图像边界')
        if self.score is not None and (not math.isfinite(self.score) or not 0 <= self.score <= 1):
            raise ValueError('模型分数无效')

    def to_dict(self) -> dict:
        return asdict(self)


def iou(a: Box, b: Box) -> float:
    intersection = max(0., min(a.x2, b.x2) - max(a.x1, b.x1)) * max(
        0., min(a.y2, b.y2) - max(a.y1, b.y1))
    union = (a.x2-a.x1)*(a.y2-a.y1) + (b.x2-b.x1)*(b.y2-b.y1) - intersection
    return intersection / union if union > 0 else 0.
