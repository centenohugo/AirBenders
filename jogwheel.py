import math
import cv2
import time

class JogWheel:
    def __init__(self, center, radius=180, label=""):
        self.cx, self.cy = center
        self.radius = radius
        self.label = label
        self.angle = 0.0
        self.last_angle = None
        self.was_pinching = False
        self.last_time = time.time()
        self.on_release_callback = None
        self.center_button_radius = 35
        self.last_press_time = 0
        self.debounce_delay = 0.4

    def contains(self, x, y):
        return math.hypot(x - self.cx, y - self.cy) <= self.radius

    def contains_center_button(self, x, y):
        return math.hypot(x - self.cx, y - self.cy) <= self.center_button_radius

    def check_center_press(self, pinch_positions, current_time):
        for px, py in pinch_positions:
            if self.contains_center_button(px, py):
                if current_time - self.last_press_time > self.debounce_delay:
                    self.last_press_time = current_time
                    return True
        return False

    def _angle_from_center(self, x, y):
        return math.atan2(y - self.cy, x - self.cx)

    def update(self, frame, cursor_x, cursor_y, is_pinching, on_scrub, on_release):
        now = time.time()
        self.last_time = now

        # Store release callback
        self.on_release_callback = on_release

        if is_pinching and self.contains(cursor_x, cursor_y):
            if not self.was_pinching:
                self.was_pinching = True
                self.last_angle = self._angle_from_center(cursor_x, cursor_y)

            current_angle = self._angle_from_center(cursor_x, cursor_y)
            delta = current_angle - self.last_angle
            if delta > math.pi:
                delta -= 2 * math.pi
            elif delta < -math.pi:
                delta += 2 * math.pi
            self.angle += delta
            self.last_angle = current_angle

            on_scrub(delta)  # only move track position

    def check_release(self):
        if self.was_pinching:
            self.was_pinching = False
            self.last_angle = None
            if self.on_release_callback:
                self.on_release_callback()
                self.on_release_callback = None

    def draw(self, frame):
        cv2.circle(frame, (self.cx, self.cy), self.radius, (60, 60, 60), 2)
        
        cv2.circle(frame, (self.cx, self.cy), self.center_button_radius, (80, 80, 80), -1)
        cv2.circle(frame, (self.cx, self.cy), self.center_button_radius, (0, 200, 255), 2)
        
        x2 = int(self.cx + math.cos(self.angle) * self.radius)
        y2 = int(self.cy + math.sin(self.angle) * self.radius)
        cv2.line(frame, (self.cx, self.cy), (x2, y2), (0, 0, 255), 4)
        if self.label:
            cv2.putText(frame,
                        self.label,
                        (self.cx - 40, self.cy + self.radius + 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (200, 200, 200),
                        2)

    def draw_song_name(self, frame, song_name, color, max_chars=25):
        """Draw song name above the jog wheel with a styled background"""
        if song_name is None:
            return
        
        if len(song_name) > max_chars:
            song_name = song_name[:max_chars - 3] + "..."
        
        text_size, _ = cv2.getTextSize(song_name, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        text_w, text_h = text_size
        
        box_x1 = self.cx - text_w // 2 - 15
        box_y1 = self.cy - self.radius - text_h - 20
        box_x2 = self.cx + text_w // 2 + 15
        box_y2 = self.cy - self.radius - 5
        
        cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (30, 30, 30), cv2.FILLED)
        cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), color, 2)
        
        cv2.putText(frame, song_name, 
                    (self.cx - text_w // 2, box_y2 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)