# -*- coding: utf-8 -*-
"""Config สำหรับ Recovery Score — แก้เลขตรงนี้ได้โดยไม่ต้องแตะ logic"""

DEFAULT_RECOVERY_WEIGHTS = {
    "hrv": 0.30,
    "rhr": 0.20,
    "sleep_performance": 0.25,
    "sleep_efficiency": 0.15,
}

DEFAULT_LOAD_BASELINE = 150.0

TRAINING_LOAD_PENALTY_MAX = 15.0
TRAINING_LOAD_PENALTY_SLOPE = 25.0
