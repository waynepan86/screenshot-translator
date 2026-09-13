"""Conservative reconstruction of flat or smoothly varying screenshot backgrounds."""
import numpy as np


def smooth_background(region):
    h, w = region.shape[:2]
    if min(h, w) < 6:
        return None
    import cv2
    edge = np.zeros((h, w), dtype=bool)
    edge[:2] = edge[-2:] = True
    edge[:, :2] = edge[:, -2:] = True
    top = np.median(region[:2], axis=0).astype(float)
    bottom = np.median(region[-2:], axis=0).astype(float)
    top = cv2.GaussianBlur(top[None], (15, 1), 0)[0]
    bottom = cv2.GaussianBlur(bottom[None], (15, 1), 0)[0]
    alpha = np.linspace(0, 1, h)[:, None, None]
    predicted = top[None] * (1-alpha) + bottom[None] * alpha
    errors = np.abs(predicted[edge] - region[edge].astype(float))
    # A control border, neighboring glyph or textured edge rejects this path.
    if np.quantile(errors, .99) > 5 or errors.max() > 14:
        return None
    if predicted.min() < -2 or predicted.max() > 257:
        return None
    return np.clip(np.rint(predicted), 0, 255).astype(np.uint8)
