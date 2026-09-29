"""
Tiện ích chuyển đổi thời gian và hình học phục vụ điều phối
"""

import math
from typing import List

def time_to_sec(time_str: str) -> int:
    """Chuyển đổi chuỗi 'HH:MM' sang số giây từ 00:00 (VD: '13:45' -> 49500)"""
    try:
        parts = time_str.strip().split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60
    except Exception:
        return 49500

def sec_to_time(sec: int) -> str:
    """Chuyển đổi số giây từ 00:00 sang chuỗi 'HH:MM' (VD: 49500 -> '13:45')"""
    sec = int(sec) % 86400
    h = sec // 3600
    m = (sec % 3600) // 60
    return f"{h:02d}:{m:02d}"

def haversine_distance(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Tính khoảng cách mặt cầu Haversine (mét) giữa 2 tọa độ GPS"""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
