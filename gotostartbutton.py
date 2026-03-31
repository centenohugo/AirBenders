import cv2 as cv
import math

class GotoStartButton:
    def __init__(self, center, radius=20, label="<<"):
        self.center = center
        self.radius = radius
        self.label = label
        self.last_press_time = 0
        self.debounce_delay = 0.4

    def contains(self, px, py):
        return math.hypot(px - self.center[0], py - self.center[1]) < self.radius

    def check_press(self, pinch_positions, current_time):
        for px, py in pinch_positions:
            if self.contains(px, py):
                if current_time - self.last_press_time > self.debounce_delay:
                    self.last_press_time = current_time
                    return True
        return False

    def draw(self, frame, enabled=False):
        x, y = self.center
        color = (0, 200, 255) if enabled else (70, 70, 70)
        cv.circle(frame, (x, y), self.radius, color, -1)
        cv.circle(frame, (x, y), self.radius, (0, 0, 0), 2)
        cv.putText(frame, self.label, (x - 12, y + 5),
                   cv.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)