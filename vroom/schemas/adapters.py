"""
Bộ chuyển đổi dữ liệu (Adapters) giữa Unified Schema và các định dạng VROOM / OSRM
"""

from typing import Dict, Any, List, Optional
from .models import UnifiedOptimizationRequest, VehicleSchema, PassengerSchema
from .utils import time_to_sec

def get_vehicle_fixed_cost(capacity: int) -> int:
    """Hệ số phụ phí cố định phục vụ thuật toán Fleet Right-Sizing của VROOM"""
    if capacity >= 16:
        return 100000
    if capacity >= 10:
        return 50000
    return 20000

def build_vroom_job(p: PassengerSchema, default_tw_start: str = "13:00", default_tw_end: str = "15:00") -> Dict[str, Any]:
    """Chuyển đổi một đối tượng PassengerSchema sang VROOM Job format"""
    is_del = p.type == "delivery"
    tw_s = p.tw_start or default_tw_start
    tw_e = p.tw_end or default_tw_end
    
    tw_s_sec = time_to_sec(tw_s)
    tw_e_sec = time_to_sec(tw_e)

    job_obj = {
        "id": p.id,
        "description": f"[{'Trả' if is_del else 'Đón'}] {p.name} ({p.district_name or ''})",
        "location": p.location,
        "service": p.service_duration_min * 60,
        "priority": 100,
        "time_windows": [[tw_s_sec, tw_e_sec]]
    }
    if is_del:
        job_obj["delivery"] = [p.amount]
    else:
        job_obj["pickup"] = [p.amount]
        
    return job_obj

def unified_request_to_vroom_payload(req: UnifiedOptimizationRequest) -> Dict[str, Any]:
    """
    Adapter chuyển đổi từ UnifiedOptimizationRequest sang VROOM JSON Payload tổng quát
    """
    hub_loc = req.hub.location or [106.27415, 20.438299]
    vroom_vehicles = []
    
    for v in req.vehicles:
        start_sec = time_to_sec(v.start_time)
        end_sec = time_to_sec(v.end_time)
        v_start = v.start_location or hub_loc
        v_end = v.end_location or hub_loc

        veh = {
            "id": v.id,
            "description": v.name,
            "profile": "car",
            "start": v_start,
            "end": v_end,
            "capacity": [v.capacity],
            "costs": {"fixed": get_vehicle_fixed_cost(v.capacity)},
            "time_window": [start_sec, end_sec]
        }
        vroom_vehicles.append(veh)

    vroom_jobs = [build_vroom_job(p) for p in req.passengers]

    return {
        "vehicles": vroom_vehicles,
        "jobs": vroom_jobs
    }
