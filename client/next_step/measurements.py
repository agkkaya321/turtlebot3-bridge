"""Transport-independent NextStep measurements in meters and laser angles in radians.

Assume flat ground and a centered person facing and stepping toward a stationary
robot. Distance is measured from the laser's ground projection; no offset
between the laser and the robot's origin is corrected here.
"""

from dataclasses import dataclass
import math


def _finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("The value must be finite.")
    return value


def cm_to_m(value):
    """Convert a length from centimeters to meters."""
    return _finite(value) / 100.0


def mm_to_m(value):
    """Convert a length from millimeters to meters."""
    return _finite(value) / 1000.0


def m_to_cm(value):
    return _finite(value) * 100.0


def degrees_to_radians(value):
    return math.radians(_finite(value))


def radians_to_degrees(value):
    return math.degrees(_finite(value))


@dataclass(frozen=True)
class LaserAngles:
    """Negative pitch points downward; positive yaw points to the robot's left."""

    pitch_rad: float
    yaw_rad: float

    def to_degrees(self):
        """Return (vertical angle, horizontal angle) in degrees."""
        return radians_to_degrees(self.pitch_rad), radians_to_degrees(self.yaw_rad)


@dataclass(frozen=True)
class LaserAngleLimits:
    """Independent (minimum, maximum) bounds, not paired foot placement targets."""

    pitch_rad: tuple[float, float]
    yaw_rad: tuple[float, float]

    def to_degrees(self):
        """Return (vertical interval, horizontal interval) in degrees."""
        return (tuple(map(radians_to_degrees, self.pitch_rad)),
                tuple(map(radians_to_degrees, self.yaw_rad)))


@dataclass(frozen=True)
class Measurements:
    """Per-instance configuration; use dataclasses.replace to adjust it.

    Intervals are ordered (minimum, maximum). Foot spacing is the total distance
    between the feet, not the distance from one foot to the center.
    Person height is a project reference with no clinical use.
    """

    robot_height_m: float = 0.214
    robot_with_stage_height_m: float = 0.33
    laser_height_m: float = 0.33
    person_height_m: float = 1.80
    person_distance_m: float = 2.275
    foot_spacing_m: tuple[float, float] = (0.25, 0.50)
    step_length_m: tuple[float, float] = (0.20, 0.45)

    def __post_init__(self):
        for name in ("robot_height_m", "robot_with_stage_height_m", "laser_height_m",
                     "person_height_m", "person_distance_m"):
            value = _finite(getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be strictly positive.")
            object.__setattr__(self, name, value)
        for name in ("foot_spacing_m", "step_length_m"):
            bounds = tuple(_finite(value) for value in getattr(self, name))
            if len(bounds) != 2 or not 0 < bounds[0] <= bounds[1]:
                raise ValueError(f"{name} must contain two ordered positive bounds.")
            object.__setattr__(self, name, bounds)
        if self.step_length_m[1] >= self.person_distance_m:
            raise ValueError("Maximum step length must be less than the person-to-robot distance.")

    def target_distance_bounds_m(self):
        """Return longitudinal distances to future foot placements (near, far)."""
        return (self.person_distance_m - self.step_length_m[1],
                self.person_distance_m - self.step_length_m[0])

    def laser_angles(self, foot, step_length_m, foot_spacing_m):
        """Return angles for a specific future foot placement within configured ranges.

        foot = 'left' or 'right' refers to the person's anatomical foot.
        Their left foot appears on the robot's right, giving a negative yaw.
        These beam angles are not servo commands.
        """
        if foot not in ("left", "right"):
            raise ValueError("foot must be 'left' or 'right'.")
        step = _finite(step_length_m)
        spacing = _finite(foot_spacing_m)
        if not self.step_length_m[0] <= step <= self.step_length_m[1]:
            raise ValueError("Step length is outside the configured range.")
        if not self.foot_spacing_m[0] <= spacing <= self.foot_spacing_m[1]:
            raise ValueError("Foot spacing is outside the configured range.")
        distance = self.person_distance_m - step
        lateral = spacing / 2 * (-1 if foot == "left" else 1)
        return LaserAngles(
            pitch_rad=-math.atan2(self.laser_height_m, math.hypot(distance, lateral)),
            yaw_rad=math.atan2(lateral, distance),
        )

    def laser_angle_limits(self, foot):
        """Recalculate exact bounds from the dimensions, without rounding."""
        corners = [self.laser_angles(foot, step, spacing)
                   for step in self.step_length_m for spacing in self.foot_spacing_m]
        return LaserAngleLimits(
            pitch_rad=(min(a.pitch_rad for a in corners), max(a.pitch_rad for a in corners)),
            yaw_rad=(min(a.yaw_rad for a in corners), max(a.yaw_rad for a in corners)),
        )


DEFAULT_MEASUREMENTS = Measurements()
