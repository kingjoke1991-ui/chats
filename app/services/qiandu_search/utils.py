import random
import numpy as np
from typing import List, Tuple

def get_bezier_curve(start: Tuple[float, float], end: Tuple[float, float], points_count: int = 30) -> List[Tuple[float, float]]:
    """Generate a Bezier curve between start and end points for human-like mouse movement."""
    # Create 1-2 random control points
    cp1 = (
        start[0] + (end[0] - start[0]) * random.uniform(0.1, 0.4) + random.uniform(-50, 50),
        start[1] + (end[1] - start[1]) * random.uniform(0.1, 0.4) + random.uniform(-50, 50)
    )
    cp2 = (
        start[0] + (end[0] - start[0]) * random.uniform(0.6, 0.9) + random.uniform(-50, 50),
        start[1] + (end[1] - start[1]) * random.uniform(0.6, 0.9) + random.uniform(-50, 50)
    )

    curve = []
    for i in range(points_count + 1):
        t = i / points_count
        # Cubic Bezier formula
        x = (1-t)**3 * start[0] + 3*(1-t)**2*t * cp1[0] + 3*(1-t)*t**2 * cp2[0] + t**3 * end[0]
        y = (1-t)**3 * start[1] + 3*(1-t)**2*t * cp1[1] + 3*(1-t)*t**2 * cp2[1] + t**3 * end[1]
        
        # Add slight jitter
        x += random.uniform(-0.5, 0.5)
        y += random.uniform(-0.5, 0.5)
        
        curve.append((x, y))
    
    return curve

def get_human_intervals(count: int, total_time: float = 0.5) -> List[float]:
    """Generate non-linear intervals for movement (accelerate then decelerate)."""
    # Simple sinus-based distribution or random weights
    weights = [random.uniform(0.5, 1.5) for _ in range(count)]
    # Maybe add some "pause" tendency near the end
    total_weight = sum(weights)
    return [(w / total_weight) * total_time for w in weights]
