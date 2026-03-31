import cv2 as cv
import math
import numpy as np


class CueButton:
    def __init__(self, center, radius=25, label="CUE"):
        self.center = center
        self.radius = radius
        self.label = label

    def draw(self, frame, state="no_cue"):
        x, y = self.center
        if state == "active":
            color = (0, 255, 0)      # green — active pinch
        elif state == "cue_set":
            color = (0, 200, 255)    # yellow-orange — cue set
        else:
            color = (80, 80, 80)     # dark gray — no cue

        cv.circle(frame, (x, y), self.radius, color, -1)
        cv.circle(frame, (x, y), self.radius, (0, 0, 0), 2)

        # Cue symbol: vertical line + triangle pointing to it
        bar_x = x - self.radius // 3
        bar_h = self.radius // 2
        cv.rectangle(frame, (bar_x - 2, y - bar_h), (bar_x + 2, y + bar_h), (0, 0, 0), -1)
        tri_pts = np.array([
            (bar_x + 4, y - bar_h + 2),
            (bar_x + 4, y + bar_h - 2),
            (bar_x + self.radius // 2, y),
        ], dtype=np.int32)
        cv.fillPoly(frame, [tri_pts], (0, 0, 0))

        cv.putText(frame, self.label,
                   (x - self.radius + 2, y + self.radius + 14),
                   cv.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1)

    def contains(self, px, py):
        return math.hypot(px - self.center[0], py - self.center[1]) < self.radius
