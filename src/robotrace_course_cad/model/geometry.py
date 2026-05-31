from __future__ import annotations

from dataclasses import dataclass
import math

TAU = 2.0 * math.pi
EPSILON = 1e-9


@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scale: float) -> Vec2:
        return Vec2(self.x * scale, self.y * scale)

    def __rmul__(self, scale: float) -> Vec2:
        return self * scale

    def __truediv__(self, scale: float) -> Vec2:
        return Vec2(self.x / scale, self.y / scale)

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec2) -> float:
        return self.x * other.y - self.y * other.x

    def norm(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self) -> Vec2:
        n = self.norm()
        if n < EPSILON:
            raise ValueError("Cannot normalize zero vector")
        return self / n

    def distance_to(self, other: Vec2) -> float:
        return (self - other).norm()

    def left_normal(self) -> Vec2:
        return Vec2(-self.y, self.x)

    def right_normal(self) -> Vec2:
        return Vec2(self.y, -self.x)


def point_angle(center: Vec2, point: Vec2) -> float:
    return math.atan2(point.y - center.y, point.x - center.x)


def angle_ccw(start: float, end: float) -> float:
    return (end - start) % TAU


def angle_cw(start: float, end: float) -> float:
    return (start - end) % TAU


def point_line_distance(point: Vec2, a: Vec2, b: Vec2) -> float:
    ab = b - a
    length = ab.norm()
    if length < EPSILON:
        return point.distance_to(a)
    return abs(ab.cross(point - a)) / length


def project_point_to_line(point: Vec2, a: Vec2, b: Vec2) -> Vec2:
    ab = b - a
    denom = ab.dot(ab)
    if denom < EPSILON:
        return a
    t = (point - a).dot(ab) / denom
    return a + ab * t
