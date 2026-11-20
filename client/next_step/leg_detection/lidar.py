"""Transport-independent geometric extraction of candidate legs.

Scan coordinates: x points forward, y points left, angles are in radians.
This size-based heuristic cannot identify a person.
"""

import math

ROI_MAX_DISTANCE = 3.0  # Meters from the LiDAR, exclusive upper bound.
# Heuristic settings to tune on the robot, not identity criteria.
PAIR_MIN_SEPARATION = 0.10
PAIR_MAX_SEPARATION = 0.65
PAIR_MAX_DEPTH_DIFFERENCE = 0.40
PAIR_MIN_LATERAL_SEPARATION = 0.08
SELECTION_MARGIN = 0.15  # Minimum gap between the two best scores (m).
TRACK_MAX_JUMP = 0.50  # Maximum displacement between observations (m).
TRACK_TIMEOUT = 1.0  # Forget the target after one second without an observation.


def polar_to_cartesian(r, theta):
    return r * math.cos(theta), r * math.sin(theta)


def extract_clusters(scan):
    """Front half-disk with a 3 m radius; neighbors must be less than 0.15 m apart.

    Keep x > 0 and R < ROI_MAX_DISTANCE, without a separate lateral limit.
    R is the Euclidean distance to the LiDAR, not the Manhattan distance
    used later by the controller.

    An invalid ray or one outside the ROI breaks the cluster. For a full scan,
    the first and last rays are also neighbors (the 0°/360° seam).
    """
    if not scan or not scan.get("ranges"):
        return []
    angle_min = scan["angle_min"]
    increment = scan["angle_increment"]

    if not math.isfinite(angle_min) or not math.isfinite(increment) or increment == 0:
        return []

    points = []
    for index, distance in enumerate(scan["ranges"]):
        point = None
        if (distance is not None and math.isfinite(distance) and distance > 0
                and scan.get("range_min", 0) <= distance <= scan.get("range_max", math.inf)):
            x, y = polar_to_cartesian(distance, angle_min + index * increment)
            if x > 0 and distance < ROI_MAX_DISTANCE:
                point = (x, y)
        points.append(point)

    clusters = []
    current = []
    for point in points:
        if current and (point is None or math.dist(current[-1], point) >= 0.15):
            clusters.append(current)
            current = []
        if point is not None:
            current.append(point)
    if current:
        clusters.append(current)

    # Allow for angles rounded by the bridge and scans with or without
    # a duplicate final ray. Never wrap a partial scan.
    step = abs(increment)
    span = (len(points) - 1) * step
    full_circle = abs(span - math.tau) <= step * 1.01
    if (full_circle and len(clusters) > 1
            and points[0] is not None and points[-1] is not None
            and math.dist(points[-1], points[0]) < 0.15):
        clusters[0] = clusters[-1] + clusters[0]
        clusters.pop()
    return clusters


def cluster_width(cluster):
    """Width is the diameter: the maximum distance between two cluster points."""
    return max((math.dist(point, other)
                for index, point in enumerate(cluster)
                for other in cluster[index + 1:]), default=0.0)


def select_target(clusters, previous_target=None):
    """Select a plausible pair, falling back to a single candidate if needed.

    On acquisition, the score is the Euclidean distance to the LiDAR. While
    tracking, it is the distance to the last observed target, with a jump limit.
    Lower scores are better; similarly scored choices remain ambiguous.
    Selected indices match the log (1-based) and are not persistent IDs:
    temporal association relies on positions.
    """
    candidates = [(index, cluster["center"]) for index, cluster in enumerate(clusters, 1)
                  if cluster["accepted"]]
    pairs = []
    for offset, (left_id, left) in enumerate(candidates):
        for right_id, right in candidates[offset + 1:]:
            separation = math.dist(left, right)
            if (PAIR_MIN_SEPARATION <= separation <= PAIR_MAX_SEPARATION
                    and abs(left[0] - right[0]) <= PAIR_MAX_DEPTH_DIFFERENCE
                    and abs(left[1] - right[1]) >= PAIR_MIN_LATERAL_SEPARATION):
                pairs.append({"target": ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2),
                              "selected_clusters": [left_id, right_id],
                              "separation": separation})

    def rank(options):
        ranked = []
        for option in options:
            score = math.dist(option["target"], previous_target or (0, 0))
            if previous_target is None or score <= TRACK_MAX_JUMP:
                ranked.append({**option, "score": score})
        return sorted(ranked, key=lambda option: option["score"])

    ranked = rank(pairs)
    mode = "tracked_pair" if previous_target is not None else "nearest_pair"
    if not ranked:
        # One visible leg can still be tracked among background objects.
        # Without history, acquire a singleton only if it is the sole candidate.
        if previous_target is not None or len(candidates) == 1:
            ranked = rank([{"target": center, "selected_clusters": [index], "separation": None}
                           for index, center in candidates])
            mode = "tracked_leg" if previous_target is not None else "single_leg"

    result = {"target": None, "selected_clusters": [], "selection": None,
              "pair_count": len(pairs), "separation": None, "score": None,
              "reason": "target_lost" if previous_target is not None else "no_coherent_pair"}
    if not ranked:
        return result
    if len(ranked) > 1 and ranked[1]["score"] - ranked[0]["score"] < SELECTION_MARGIN:
        return {**result, "reason": "ambiguous_target"}
    return {**result, **ranked[0], "reason": "target_detected", "selection": mode}


def analyze_scan(scan, previous_target=None):
    """Extract the target and diagnostics in a single clustering pass."""
    clusters = []
    for cluster in extract_clusters(scan):
        width = cluster_width(cluster)
        clusters.append({
            "points": len(cluster),
            "width": width,
            "center": (sum(x for x, _ in cluster) / len(cluster),
                       sum(y for _, y in cluster) / len(cluster)),
            "accepted": 0.05 <= width <= 0.20,
        })
    valid_count = sum(cluster["accepted"] for cluster in clusters)
    selection = select_target(clusters, previous_target)
    if valid_count:
        reason = selection["reason"]
    elif clusters:
        reason = "no_valid_cluster"
    elif scan is None:
        reason = "scan_missing"
    elif not scan.get("ranges"):
        reason = "scan_empty"
    elif (not math.isfinite(scan["angle_min"])
          or not math.isfinite(scan["angle_increment"]) or scan["angle_increment"] == 0):
        reason = "invalid_angles"
    else:
        reason = "no_roi_points"
    return {**selection, "reason": reason, "clusters": clusters,
            "roi_points": sum(cluster["points"] for cluster in clusters),
            "valid_clusters": valid_count,
            "scan_angles": (scan.get("angle_min"), scan.get("angle_increment")) if scan else None}


class TargetTracker:
    """Remember positions only; do not predict motion."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.target = None
        self.last_seen = None

    def update(self, scan, now):
        expired = self.last_seen is not None and now - self.last_seen >= TRACK_TIMEOUT
        if expired:
            self.reset()
        info = analyze_scan(scan, self.target)
        info["tracking_expired"] = expired
        if info["target"] is not None:
            self.target = info["target"]
            self.last_seen = now
        # If the target disappears, remember its position for association,
        # but return target=None: never command motion from memory alone.
        return info


def extract_target(scan):
    """Select a target without history or return None if missing or ambiguous.

    Each cluster center is the mean of its points. Two centers are weighted
    equally, even when their point counts differ. With multiple candidates,
    select the nearest coherent pair.
    """
    return analyze_scan(scan)["target"]
