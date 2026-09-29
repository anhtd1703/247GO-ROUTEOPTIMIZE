"""
Bộ chuyển đổi dữ liệu (Adapters) giữa Unified Schema và các định dạng VROOM / PyVRP / OSRM
"""

from typing import Dict, Any, List
from .models import UnifiedOptimizationRequest, UnifiedOptimizationResponse
from .utils import time_to_sec, sec_to_time

def unified_request_to_vroom_payload(req: UnifiedOptimizationRequest) -> Dict[str, Any]:
    """
    Adapter chuyển đổi từ UnifiedOptimizationRequest sang VROOM JSON Payload
    Hỗ trợ start/end point tùy biến cho từng xe!
    """
    hub_loc = req.hub.location or [106.27415, 20.438299]
    vroom_vehicles = []
    for v in req.vehicles:
        start_sec = time_to_sec(v.start_time)
        end_sec = time_to_sec(v.end_time)
        v_start = v.start_location or hub_loc
        v_end = v.end_location or hub_loc

        vroom_vehicles.append({
            "id": v.id,
            "description": v.name,
            "start": v_start,
            "end": v_end,
            "capacity": [v.capacity],
            "time_window": [start_sec, end_sec]
        })

    vroom_jobs = []
    for p in req.passengers:
        is_del = p.type == "delivery"
        job = {
            "id": p.id,
            "description": f"{p.name} ({p.district_name or ''})",
            "location": p.location,
            "service": p.service_duration_min * 60,
            "priority": 100
        }
        if is_del:
            job["delivery"] = [p.amount]
        else:
            job["pickup"] = [p.amount]
        vroom_jobs.append(job)

    return {
        "vehicles": vroom_vehicles,
        "jobs": vroom_jobs
    }
