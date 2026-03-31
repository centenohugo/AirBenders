import cv2 as cv
import math

def clamp(val, lo, hi):
    return max(lo, min(val, hi))

def is_claw(hand_landmarks, threshold=0.1):
    """
    Returns True if all 5 fingers are extended (claw).
    hand_landmarks: list of 21 landmarks
    """
    if not hand_landmarks:
        return False

    tips = [4, 8, 12, 16, 20]
    mcps = [1, 5, 9, 13, 17]

    extended = []
    for tip_idx, mcp_idx in zip(tips, mcps):
        tip = hand_landmarks[tip_idx]
        mcp = hand_landmarks[mcp_idx]
        extended.append(tip.y < mcp.y - threshold)

    return all(extended)

SMOOTH = 0.18       # EMA alpha: menor = más suave, mayor = más reactivo
DEAD_ZONE = 3       # píxeles mínimos de movimiento Y para actualizar

class VolumeSlider:
    def __init__(self, x, y, width, height, track_index):
        self.x = x
        self.y = y
        self.w = width
        self.h = height
        self.track_index = track_index
        self.volume = 1.0
        self._target_volume = 1.0
        self.grabbed = False
        self.grab_offset_y = 0
        self._last_py = None
        self.HANDLE_H = 20
        self.GRAB_RADIUS = 35

    def _handle_y(self):
        return self.y + int((1.0 - self.volume) * self.h) - self.HANDLE_H // 2

    def update(self, pinch_positions):
        handle_cy = self._handle_y() + self.HANDLE_H // 2
        handle_cx = self.x + self.w // 2

        if self.grabbed:
            if not pinch_positions:
                self.grabbed = False
                self._last_py = None
            else:
                px, py = min(pinch_positions, key=lambda p: abs(p[0] - handle_cx))
                # Zona muerta: ignora micro-movimientos
                if self._last_py is None or abs(py - self._last_py) >= DEAD_ZONE:
                    self._last_py = py
                    target_y = py - self.grab_offset_y
                    rel_y = clamp(target_y - self.y, 0, self.h)
                    self._target_volume = clamp(1.0 - (rel_y / self.h), 0.0, 1.0)
        else:
            for px, py in pinch_positions:
                if math.hypot(px - handle_cx, py - handle_cy) < self.GRAB_RADIUS:
                    self.grabbed = True
                    self.grab_offset_y = py - handle_cy
                    self._last_py = py
                    break

        # Suavizado exponencial (EMA)
        self.volume += (self._target_volume - self.volume) * SMOOTH

    def draw(self, frame):
        # Pista
        cv.rectangle(frame, (self.x, self.y), (self.x+self.w, self.y+self.h), (50,50,50), -1)
        cv.rectangle(frame, (self.x, self.y), (self.x+self.w, self.y+self.h), (180,180,180), 2)

        # Relleno debajo del handle
        hy = self._handle_y()
        mid_y = hy + self.HANDLE_H // 2
        if mid_y < self.y + self.h:
            cv.rectangle(frame, (self.x, mid_y), (self.x+self.w, self.y+self.h), (40,120,40), -1)

        # Handle
        color = (0, 255, 100) if self.grabbed else (200, 200, 200)
        cv.rectangle(frame, (self.x-8, hy), (self.x+self.w+8, hy+self.HANDLE_H), color, -1)
        cv.rectangle(frame, (self.x-8, hy), (self.x+self.w+8, hy+self.HANDLE_H), (255,255,255), 1)

        # Label
        cv.putText(frame, f"{int(self.volume*100)}%",
                   (self.x-5, self.y-10), cv.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
