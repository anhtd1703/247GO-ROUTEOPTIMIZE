"""
==================================================================================================
VROOM TWO-PHASE OPTIMIZATION SOLVER (DELIVERY -> CHAINED PICKUP)
==================================================================================================
Bộ giải thuật điều phối 2 pha chuẩn hóa:
1. Pha 1 (Delivery): Xuất phát từ bến/gara -> Trả toàn bộ khách tại nhà.
2. Móc nối trạng thái (Chaining): Lưu điểm trả cuối & mốc giờ kết thúc ca 1 của từng xe.
3. Pha 2 (Pickup): Xe xuất phát ngay tại điểm trả cuối -> Đón khách -> Về bến trung tâm trước giờ G.
4. Hợp nhất lộ trình & Đồng bộ chỉ số OSRM High-Precision Geometry & Timeline.
"""

import os
import time
import math
import itertools
from typing import List, Dict, Any, Optional, Tuple

try:
    import httpx
except ImportError:
    httpx = None

import urllib.request
import json

try:
    from .schemas.models import (
        UnifiedOptimizationRequest,
        UnifiedOptimizationResponse,
        OptimizationSummarySchema,
        RouteSchema,
        RouteStepSchema,
        UnassignedPassengerSchema,
        VehicleSchema,
        PassengerSchema,
        HubSchema
    )
    from .schemas.constants import DISTRICT_NAMES
    from .schemas.utils import time_to_sec, sec_to_time, haversine_distance
    from .schemas.adapters import get_vehicle_fixed_cost, build_vroom_job
except (ImportError, ValueError):
    from schemas.models import (
        UnifiedOptimizationRequest,
        UnifiedOptimizationResponse,
        OptimizationSummarySchema,
        RouteSchema,
        RouteStepSchema,
        UnassignedPassengerSchema,
        VehicleSchema,
        PassengerSchema,
        HubSchema
    )
    from schemas.constants import DISTRICT_NAMES
    from schemas.utils import time_to_sec, sec_to_time, haversine_distance
    from schemas.adapters import get_vehicle_fixed_cost, build_vroom_job


OSRM_URL = os.getenv("OSRM_URL", "http://osrm:5000")
VROOM_URL = os.getenv("VROOM_URL", "http://vroom:3000")

# Cache working endpoints to avoid repetitive DNS resolution delays
_ACTIVE_VROOM_URL: Optional[str] = None
_ACTIVE_OSRM_URL: Optional[str] = None


# ==================================================================================================
# 1. NETWORK & BACKEND HELPERS
# ==================================================================================================

def _make_http_request(url: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """Helper gửi HTTP request đồng bộ / fallback nhanh qua urllib"""
    try:
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        req = urllib.request.Request(url, data=data_bytes, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if res.status == 200:
                return json.loads(res.read().decode("utf-8"))
    except Exception:
        pass
    return None


async def call_vroom_backend(payload: Dict[str, Any], vroom_url: str = VROOM_URL) -> Dict[str, Any]:
    """Gửi payload sang VROOM C++ engine (Port 3000) với auto-discovery và caching"""
    global _ACTIVE_VROOM_URL
    
    candidates = []
    if _ACTIVE_VROOM_URL:
        candidates.append(_ACTIVE_VROOM_URL)
    
    for u in [vroom_url, "http://localhost:3000", "http://127.0.0.1:3000", "http://vroom:3000"]:
        u_clean = u.rstrip("/")
        if u_clean not in candidates:
            candidates.append(u_clean)

    for base in candidates:
        url = f"{base}/"
        # Try httpx first if available
        if httpx is not None:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        _ACTIVE_VROOM_URL = base
                        return res.json()
            except Exception:
                pass
        
        # Fallback to urllib
        res_data = _make_http_request(url, payload=payload, timeout=2.0)
        if res_data is not None:
            _ACTIVE_VROOM_URL = base
            return res_data

    return {"code": 1, "error": "Không thể kết nối đến VROOM backend", "routes": [], "unassigned": []}


async def fetch_osrm_table(coords: List[List[float]], osrm_url: str = OSRM_URL) -> Optional[Dict[str, Any]]:
    """Lấy ma trận cự ly và thời gian từ OSRM Table API"""
    global _ACTIVE_OSRM_URL
    if len(coords) < 2:
        return None
        
    coords_str = ";".join([f"{c[0]},{c[1]}" for c in coords])
    candidates = []
    if _ACTIVE_OSRM_URL:
        candidates.append(_ACTIVE_OSRM_URL)
        
    for u in [osrm_url, "http://localhost:5000", "http://127.0.0.1:5000", "http://osrm:5000"]:
        u_clean = u.rstrip("/")
        if u_clean not in candidates:
            candidates.append(u_clean)

    for base in candidates:
        url = f"{base}/table/v1/driving/{coords_str}?annotations=duration,distance"
        if httpx is not None:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("code") == "Ok":
                            _ACTIVE_OSRM_URL = base
                            return data
            except Exception:
                pass
                
        res_data = _make_http_request(url, timeout=2.0)
        if res_data and res_data.get("code") == "Ok":
            _ACTIVE_OSRM_URL = base
            return res_data
            
    return None


async def fetch_osrm_route(coords: List[List[float]], osrm_url: str = OSRM_URL) -> Optional[Dict[str, Any]]:
    """Lấy chi tiết lộ trình đường bộ (geometry, distance, duration) từ OSRM Route API"""
    global _ACTIVE_OSRM_URL
    if len(coords) < 2:
        return None
        
    coords_str = ";".join([f"{c[0]},{c[1]}" for c in coords])
    candidates = []
    if _ACTIVE_OSRM_URL:
        candidates.append(_ACTIVE_OSRM_URL)
        
    for u in [osrm_url, "http://localhost:5000", "http://127.0.0.1:5000", "http://osrm:5000"]:
        u_clean = u.rstrip("/")
        if u_clean not in candidates:
            candidates.append(u_clean)

    for base in candidates:
        url = f"{base}/route/v1/driving/{coords_str}?overview=full&geometries=geojson&steps=true"
        if httpx is not None:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("code") == "Ok" and data.get("routes"):
                            _ACTIVE_OSRM_URL = base
                            return data["routes"][0]
            except Exception:
                pass
                
        res_data = _make_http_request(url, timeout=2.0)
        if res_data and res_data.get("code") == "Ok" and res_data.get("routes"):
            _ACTIVE_OSRM_URL = base
            return res_data["routes"][0]
            
    return None


# ==================================================================================================
# 2. TOUR SEQUENCE OPTIMIZER (TRIO MULTI-OBJECTIVE)
# ==================================================================================================

def optimize_tour_sequence(
    start_coord: List[float],
    job_steps: List[Dict[str, Any]],
    end_coord: Optional[List[float]],
    dist_matrix: List[List[float]],
    dur_matrix: List[List[float]],
    start_time_sec: int,
    phase_type: str = "delivery",
    central_hub: List[float] = [106.27415, 20.438299],
    candidate_next_coords: Optional[List[List[float]]] = None,
    max_phase_deadline_sec: int = 54000
) -> List[int]:
    """
    Tối ưu hóa thứ tự ghé thăm khách trong từng pha (TSP / 2-Opt):
    - Mục tiêu 1: Tổng cự ly đường bộ ngắn nhất.
    - Mục tiêu 2: Trải nghiệm khách hàng (khách gần trả sớm, khách xa đón trước).
    - Mục tiêu 3: Chặng chuyển tiếp mượt mà sang vị trí khách đón của pha sau.
    """
    n = len(job_steps)
    if n <= 1:
        return list(range(n))

    indices = list(range(n))
    has_end = end_coord is not None
    end_idx = (n + 1) if has_end else None

    def compute_cost(order: List[int]) -> float:
        total_dist = dist_matrix[0][order[0] + 1]
        total_dur = dur_matrix[0][order[0] + 1]
        current_clock = start_time_sec + total_dur
        overtime_pen = 0.0

        if current_clock > max_phase_deadline_sec:
            overtime_pen += 1000000.0 + (current_clock - max_phase_deadline_sec) * 5000.0

        svc = job_steps[order[0]].get("service", 60)
        current_clock += svc
        leg_durs = [total_dur]

        for i in range(len(order) - 1):
            curr_n = order[i] + 1
            next_n = order[i + 1] + 1
            d = dist_matrix[curr_n][next_n]
            t = dur_matrix[curr_n][next_n]
            total_dist += d
            total_dur += t
            current_clock += t
            if current_clock > max_phase_deadline_sec:
                overtime_pen += 1000000.0 + (current_clock - max_phase_deadline_sec) * 5000.0
            current_clock += job_steps[order[i + 1]].get("service", 60)
            leg_durs.append(total_dur)

        if has_end and end_idx is not None:
            last_n = order[-1] + 1
            d_end = dist_matrix[last_n][end_idx]
            t_end = dur_matrix[last_n][end_idx]
            total_dist += d_end
            total_dur += t_end
            current_clock += t_end
            if phase_type == "pickup" and current_clock > (max_phase_deadline_sec - 600):
                overtime_pen += 1000000.0 + (current_clock - (max_phase_deadline_sec - 600)) * 5000.0

        # Score chính: Distance (km) + Duration (min) + Overtime
        score = (total_dist / 1000.0) * 1.0 + (total_dur / 60.0) * 0.1 + (overtime_pen / 1000.0)

        # Trải nghiệm khách ngồi trên xe (CX Ride Time)
        for i, idx in enumerate(order):
            loc = job_steps[idx]["location"]
            dx = (loc[0] - central_hub[0]) * 102.0
            dy = (loc[1] - central_hub[1]) * 111.0
            dist_to_hub = math.hypot(dx, dy)
            if phase_type == "delivery":
                arr_min = leg_durs[i] / 60.0
                score += (arr_min / (dist_to_hub + 1.0)) * 0.05
            else:
                ride_min = (total_dur - leg_durs[i]) / 60.0
                score += (ride_min / (dist_to_hub + 1.0)) * 0.05

        # Chặng nối sang Pha 2
        if phase_type == "delivery" and candidate_next_coords:
            last_loc = job_steps[order[-1]]["location"]
            min_trans = float("inf")
            for c_loc in candidate_next_coords:
                td = math.hypot((last_loc[0] - c_loc[0]) * 102.0, (last_loc[1] - c_loc[1]) * 111.0)
                if td < min_trans:
                    min_trans = td
            if min_trans < float("inf"):
                score += min_trans * 0.8

        return score

    best_order = list(indices)
    best_cost = compute_cost(best_order)

    # Exact permutations nếu <= 7 stops
    if n <= 7:
        for p in itertools.permutations(indices):
            cost = compute_cost(list(p))
            if cost < best_cost - 1e-4:
                best_cost = cost
                best_order = list(p)
        return best_order

    # 2-Opt Local Search nếu > 7 stops
    improved = True
    while improved:
        improved = False
        for i in range(len(best_order) - 1):
            for j in range(i + 1, len(best_order)):
                new_order = best_order[:i] + best_order[i:j+1][::-1] + best_order[j+1:]
                cost = compute_cost(new_order)
                if cost < best_cost - 1e-4:
                    best_cost = cost
                    best_order = new_order
                    improved = True
                    break
            if improved:
                break

    return best_order


# ==================================================================================================
# 3. CORE TWO-PHASE OPTIMIZATION ENGINE
# ==================================================================================================

# ==================================================================================================
# 3. CORE TWO-PHASE OPTIMIZATION SUBPROBLEM SOLVER
# ==================================================================================================

async def _solve_two_phase_subproblem(
    fleet: List[VehicleSchema],
    passengers: List[PassengerSchema],
    hub_coords: List[float],
    hub_name: str,
    p1_start_str: Optional[str] = None,
    p1_end_str: Optional[str] = None,
    p2_end_str: Optional[str] = None,
    strict_precedence: bool = True,
    is_near_zone: bool = False,
    opt_mode_label: str = "mode2"
) -> Tuple[List[RouteSchema], List[Any], int, int, int]:
    """
    Thực hiện giải bài toán điều phối 2 pha cho một tập xe và khách cụ thể:
    Pha 1 (Delivery): p1_start -> p1_end
    Pha 2 (Pickup): chained finish -> p2_end
    """
    if not passengers or not fleet:
        return [], [], 0, 0, 0

    delivery_pax = [p for p in passengers if p.type == "delivery"]
    pickup_pax = [p for p in passengers if p.type == "pickup"]

    has_deliveries = len(delivery_pax) > 0
    has_pickups = len(pickup_pax) > 0

    fleet_start_secs = [time_to_sec(v.start_time) for v in fleet if v.start_time]
    fleet_end_secs = [time_to_sec(v.end_time) for v in fleet if v.end_time]
    min_fleet_start = min(fleet_start_secs) if fleet_start_secs else 24600
    max_fleet_end = max(fleet_end_secs) if fleet_end_secs else (min_fleet_start + 7200)

    p1_start_sec = time_to_sec(p1_start_str) if p1_start_str else min_fleet_start
    p2_end_sec = time_to_sec(p2_end_str) if p2_end_str else max_fleet_end
    if p2_end_sec <= p1_start_sec:
        p2_end_sec = p1_start_sec + 7200

    if p1_end_str:
        p1_end_sec = time_to_sec(p1_end_str)
    else:
        if has_deliveries and has_pickups:
            p1_end_sec = p1_start_sec + max(1800, int((p2_end_sec - p1_start_sec) * 0.55))
        else:
            p1_end_sec = p2_end_sec

    p1_start_str = sec_to_time(p1_start_sec)
    p1_end_str = sec_to_time(p1_end_sec)
    p2_end_str = sec_to_time(p2_end_sec)

    phase1_routes = []
    phase1_unassigned = []
    veh_p1_end_map = {}

    # ----------------------------------------------------------------------------------------------
    # BƯỚC 1: PHA 1 (TRẢ KHÁCH - DELIVERY)
    # ----------------------------------------------------------------------------------------------
    if has_deliveries:
        p1_vehicles = []
        for v in fleet:
            v_start = v.start_location or hub_coords
            v_start_sec = time_to_sec(v.start_time) if v.start_time else p1_start_sec
            v_end_sec = time_to_sec(v.end_time) if v.end_time else p2_end_sec
            
            # Thời hạn kết thúc pha 1 của xe
            veh_p1_end_limit = min(v_end_sec, p1_end_sec) if has_pickups else v_end_sec
            if veh_p1_end_limit <= v_start_sec:
                veh_p1_end_limit = max(v_end_sec, v_start_sec + 3600)

            v_obj = {
                "id": v.id,
                "description": v.name,
                "profile": "car",
                "start": v_start,
                "capacity": [v.capacity],
                "costs": {"fixed": get_vehicle_fixed_cost(v.capacity)},
                "time_window": [v_start_sec, veh_p1_end_limit]
            }
            if v.max_distance_km_hard:
                v_obj["max_distance"] = v.max_distance_km_hard * 1000

            if not has_pickups or not strict_precedence:
                v_obj["end"] = v.end_location or hub_coords
            p1_vehicles.append(v_obj)

        p1_jobs = [build_vroom_job(p, p1_start_str, p1_end_str) for p in delivery_pax]
        p1_payload = {"vehicles": p1_vehicles, "jobs": p1_jobs}

        p1_response = await call_vroom_backend(p1_payload)
        phase1_routes = p1_response.get("routes", [])
        phase1_unassigned = p1_response.get("unassigned", [])

        # Tinh chỉnh thứ tự stops Pha 1 qua OSRM Table
        candidate_pickup_locs = [p.location for p in pickup_pax]
        for r in phase1_routes:
            job_steps = [s for s in r.get("steps", []) if s.get("type") == "job"]
            if len(job_steps) >= 2:
                start_loc = r["steps"][0]["location"]
                coords = [start_loc] + [s["location"] for s in job_steps]
                table_res = await fetch_osrm_table(coords)
                if table_res and table_res.get("distances") and table_res.get("durations"):
                    opt_order = optimize_tour_sequence(
                        start_coord=start_loc,
                        job_steps=job_steps,
                        end_coord=None,
                        dist_matrix=table_res["distances"],
                        dur_matrix=table_res["durations"],
                        start_time_sec=p1_start_sec,
                        phase_type="delivery",
                        central_hub=hub_coords,
                        candidate_next_coords=candidate_pickup_locs,
                        max_phase_deadline_sec=p1_end_sec
                    )
                    r["steps"] = [r["steps"][0]] + [job_steps[i] for i in opt_order]

        # Ghi nhận điểm kết thúc của từng xe sau Pha 1
        for r in phase1_routes:
            v_id = r.get("vehicle", 1)
            job_steps = [s for s in r.get("steps", []) if s.get("type") == "job"]
            if job_steps:
                last_job = job_steps[-1]
                finish_sec = last_job.get("arrival", p1_start_sec) + last_job.get("service", 60)
                veh_p1_end_map[v_id] = {
                    "location": last_job.get("location", hub_coords),
                    "finish_time": finish_sec,
                    "last_job_id": last_job.get("job") or last_job.get("id")
                }

    # ----------------------------------------------------------------------------------------------
    # BƯỚC 2: PHA 2 (ĐÓN KHÁCH - PICKUP)
    # ----------------------------------------------------------------------------------------------
    phase2_routes = []
    phase2_unassigned = []

    if has_pickups:
        p2_vehicles = []
        for v in fleet:
            v_end = v.end_location or hub_coords
            v_end_sec = time_to_sec(v.end_time) if v.end_time else p2_end_sec
            
            if v.id in veh_p1_end_map:
                p1_info = veh_p1_end_map[v.id]
                p2_start_sec = p1_info["finish_time"]
                p2_start_loc = p1_info["location"]
                target_p2_end = max(v_end_sec, p2_start_sec + 3600)
                v2_obj = {
                    "id": v.id,
                    "description": v.name,
                    "profile": "car",
                    "start": p2_start_loc,
                    "end": v_end,
                    "capacity": [v.capacity],
                    "costs": {"fixed": 0},
                    "time_window": [p2_start_sec, target_p2_end]
                }
                if v.max_distance_km_hard:
                    v2_obj["max_distance"] = v.max_distance_km_hard * 1000
                p2_vehicles.append(v2_obj)
            else:
                v_start = v.start_location or hub_coords
                v_start_sec = time_to_sec(v.start_time) if v.start_time else p1_start_sec
                target_p2_end = max(v_end_sec, v_start_sec + 3600)
                v2_obj = {
                    "id": v.id,
                    "description": v.name,
                    "profile": "car",
                    "start": v_start,
                    "end": v_end,
                    "capacity": [v.capacity],
                    "costs": {"fixed": get_vehicle_fixed_cost(v.capacity)},
                    "time_window": [v_start_sec, target_p2_end]
                }
                if v.max_distance_km_hard:
                    v2_obj["max_distance"] = v.max_distance_km_hard * 1000
                p2_vehicles.append(v2_obj)

        p2_jobs = []
        for p in pickup_pax:
            p_trip_sec = time_to_sec(p.trip_time) if p.trip_time else p2_end_sec
            job_tw_end_sec = max(p1_start_sec + 1800, min(p2_end_sec, p_trip_sec))
            p2_jobs.append(build_vroom_job(p, p1_start_str, sec_to_time(job_tw_end_sec)))

        p2_payload = {"vehicles": p2_vehicles, "jobs": p2_jobs}

        p2_response = await call_vroom_backend(p2_payload)
        phase2_routes = p2_response.get("routes", [])
        phase2_unassigned = p2_response.get("unassigned", [])

        # Tinh chỉnh thứ tự stops Pha 2 qua OSRM Table
        for r in phase2_routes:
            job_steps = [s for s in r.get("steps", []) if s.get("type") == "job"]
            if len(job_steps) >= 2:
                start_loc = r["steps"][0]["location"]
                end_loc = r["steps"][-1]["location"] if r["steps"][-1].get("type") == "end" else hub_coords
                coords = [start_loc] + [s["location"] for s in job_steps] + [end_loc]
                table_res = await fetch_osrm_table(coords)
                if table_res and table_res.get("distances") and table_res.get("durations"):
                    start_sec = veh_p1_end_map.get(r.get("vehicle"), {}).get("finish_time", p1_start_sec)
                    opt_order = optimize_tour_sequence(
                        start_coord=start_loc,
                        job_steps=job_steps,
                        end_coord=end_loc,
                        dist_matrix=table_res["distances"],
                        dur_matrix=table_res["durations"],
                        start_time_sec=start_sec,
                        phase_type="pickup",
                        central_hub=hub_coords,
                        candidate_next_coords=None,
                        max_phase_deadline_sec=p2_end_sec
                    )
                    end_step = [s for s in r.get("steps", []) if s.get("type") == "end"]
                    r["steps"] = [r["steps"][0]] + [job_steps[i] for i in opt_order] + end_step

    # ----------------------------------------------------------------------------------------------
    # BƯỚC 3: HỢP NHẤT LỘ TRÌNH 2 PHA & TÁI TẠO OSRM GEOMETRY
    # ----------------------------------------------------------------------------------------------
    merged_routes_dict: Dict[int, Dict[str, Any]] = {}
    pax_map = {p.id: p for p in passengers}
    veh_map = {v.id: v for v in fleet}

    for r in phase1_routes:
        v_id = r.get("vehicle", 1)
        p1_job_steps = [s for s in r.get("steps", []) if s.get("type") == "job"]
        p1_heads = sum((pax_map.get(s.get("job") or s.get("id")).amount if pax_map.get(s.get("job") or s.get("id")) else 1) for s in p1_job_steps)
        merged_routes_dict[v_id] = {
            "vehicle_id": v_id,
            "p1_job_steps": p1_job_steps,
            "p2_job_steps": [],
            "delivery_count": p1_heads,
            "pickup_count": 0
        }

    for r in phase2_routes:
        v_id = r.get("vehicle", 1)
        p2_job_steps = [s for s in r.get("steps", []) if s.get("type") == "job"]
        p2_heads = sum((pax_map.get(s.get("job") or s.get("id")).amount if pax_map.get(s.get("job") or s.get("id")) else 1) for s in p2_job_steps)
        if v_id in merged_routes_dict:
            merged_routes_dict[v_id]["p2_job_steps"] = p2_job_steps
            merged_routes_dict[v_id]["pickup_count"] = p2_heads
        else:
            merged_routes_dict[v_id] = {
                "vehicle_id": v_id,
                "p1_job_steps": [],
                "p2_job_steps": p2_job_steps,
                "delivery_count": 0,
                "pickup_count": p2_heads
            }

    sub_routes: List[RouteSchema] = []
    sub_system_dist = 0
    sub_system_dur = 0
    sub_system_service = 0

    for v_id, r_info in merged_routes_dict.items():
        v_obj = veh_map.get(v_id)
        if not v_obj:
            v_obj = VehicleSchema(id=v_id, name=f"Xe {v_id:02d}", capacity=16)

        v_start_loc = v_obj.start_location or hub_coords
        v_end_loc = v_obj.end_location or hub_coords
        p1_jobs = r_info["p1_job_steps"]
        p2_jobs = r_info["p2_job_steps"]

        all_job_steps = p1_jobs + p2_jobs
        if not all_job_steps:
            continue

        route_coords = [v_start_loc] + [s["location"] for s in all_job_steps] + [v_end_loc]

        # Lấy OSRM Route chính xác
        osrm_data = await fetch_osrm_route(route_coords)
        
        legs = osrm_data.get("legs", []) if osrm_data else []
        geometry = osrm_data.get("geometry", {}).get("coordinates", []) if osrm_data else []
        total_dist_meters = int(osrm_data.get("distance", 0)) if osrm_data else 0
        total_dur_sec = int(osrm_data.get("duration", 0)) if osrm_data else 0

        # Nếu OSRM route bị lỗi, fallback qua Haversine
        if total_dist_meters == 0:
            for i in range(len(route_coords) - 1):
                d = haversine_distance(route_coords[i][0], route_coords[i][1], route_coords[i+1][0], route_coords[i+1][1]) * 1.35
                total_dist_meters += int(d)
                total_dur_sec += int((d / 1000.0 / 38.0) * 3600)
            geometry = route_coords

        # Xây dựng các bước dừng (RouteStepSchema)
        current_clock = time_to_sec(v_obj.start_time) if v_obj.start_time else p1_start_sec
        cum_dist = 0
        cum_dur = 0
        current_load = r_info["delivery_count"]
        step_index = 0

        final_steps: List[RouteStepSchema] = []

        # 1. Start Step
        start_step = RouteStepSchema(
            step_index=step_index,
            type="start",
            node_id=0,
            name=f"Xuất phát: {v_obj.start_location_name or hub_name}",
            location=v_start_loc,
            arrival_sec=current_clock,
            arrival_time=sec_to_time(current_clock),
            departure_sec=current_clock,
            departure_time=sec_to_time(current_clock),
            service_sec=0,
            phase="start",
            current_load=current_load,
            arrival=current_clock,
            duration=0,
            distance=0,
            service=0
        )
        final_steps.append(start_step)

        # 2. Job Steps (Pha 1 Delivery trước -> Pha 2 Pickup sau)
        for i, js in enumerate(all_job_steps):
            step_index += 1
            j_id = js.get("job") or js.get("id")
            p_obj = pax_map.get(j_id)

            leg_dur = int(legs[i].get("duration", 180)) if i < len(legs) else 180
            leg_dist = int(legs[i].get("distance", 1500)) if i < len(legs) else 1500

            current_clock += leg_dur
            cum_dist += leg_dist
            cum_dur += leg_dur

            p_type = p_obj.type if p_obj else ("delivery" if i < len(p1_jobs) else "pickup")
            p_amount = p_obj.amount if p_obj else 1

            svc_sec = (p_obj.service_duration_min * 60) if p_obj else js.get("service", 120)
            sub_system_service += (svc_sec // 60)

            if p_type == "delivery":
                current_load = max(0, current_load - p_amount)
            else:
                current_load += p_amount

            job_step_obj = RouteStepSchema(
                step_index=step_index,
                type="job",
                node_id=step_index,
                job_id=j_id,
                name=p_obj.name if p_obj else f"Khách #{j_id}",
                passenger_type=p_type,
                amount=p_amount,
                location=js.get("location", [0.0, 0.0]),
                address=p_obj.address if p_obj else None,
                arrival_sec=current_clock,
                arrival_time=sec_to_time(current_clock),
                departure_sec=current_clock + svc_sec,
                departure_time=sec_to_time(current_clock + svc_sec),
                service_sec=svc_sec,
                phase=p_type,
                current_load=current_load,
                arrival=current_clock,
                duration=cum_dur,
                distance=cum_dist,
                service=svc_sec,
                job=j_id
            )
            final_steps.append(job_step_obj)
            current_clock += svc_sec

        # 3. End Step (Về Bến / Gara)
        step_index += 1
        last_leg_idx = len(all_job_steps)
        end_leg_dur = int(legs[last_leg_idx].get("duration", 300)) if last_leg_idx < len(legs) else 300
        end_leg_dist = int(legs[last_leg_idx].get("distance", 3000)) if last_leg_idx < len(legs) else 3000

        current_clock += end_leg_dur
        cum_dist += end_leg_dist
        cum_dur += end_leg_dur

        end_step = RouteStepSchema(
            step_index=step_index,
            type="end",
            node_id=step_index,
            name=f"Về bến/kết thúc: {v_obj.end_location_name or hub_name}",
            location=v_end_loc,
            arrival_sec=current_clock,
            arrival_time=sec_to_time(current_clock),
            departure_sec=current_clock,
            departure_time=sec_to_time(current_clock),
            service_sec=0,
            phase="end",
            current_load=0,
            arrival=current_clock,
            duration=cum_dur,
            distance=cum_dist,
            service=0
        )
        final_steps.append(end_step)

        # Tính toán KPI xe
        is_on_time = current_clock <= p2_end_sec
        total_dur_min = round(cum_dur / 60.0, 1)

        route_model = RouteSchema(
            vehicle_id=v_obj.id,
            vehicle_name=v_obj.name,
            capacity=v_obj.capacity,
            color=v_obj.color or "#2563eb",
            delivery_passengers=r_info["delivery_count"],
            pickup_passengers=r_info["pickup_count"],
            total_distance_meters=cum_dist,
            total_duration_seconds=cum_dur,
            total_duration_minutes=total_dur_min,
            is_on_time=is_on_time,
            start_location=v_start_loc,
            end_location=v_end_loc,
            steps=final_steps,
            geometry=geometry,
            vehicle=v_obj.id,
            delivery=[r_info["delivery_count"]],
            pickup=[r_info["pickup_count"]],
            distance=cum_dist,
            duration=cum_dur,
            cost=cum_dist,
            targetBusTime=p2_end_str,
            peakLoad=max(r_info["delivery_count"], r_info["pickup_count"])
        )
        sub_routes.append(route_model)

        sub_system_dist += cum_dist
        sub_system_dur += cum_dur

    raw_unassigned = phase1_unassigned + phase2_unassigned
    return sub_routes, raw_unassigned, sub_system_dist, sub_system_dur, sub_system_service


# ==================================================================================================
# 4. MAIN TWO-PHASE OPTIMIZATION SERVICE HANDLER
# ==================================================================================================

async def solve_vroom_two_phase(req: UnifiedOptimizationRequest) -> UnifiedOptimizationResponse:
    """
    Điểm vào chính xử lý tối ưu hóa điều phối 2 pha:
    - Mode 1: Phân tách Zone Gần (<15km) & Zone Xa (>=15km) với đội xe hoàn toàn tách biệt.
    - Mode 2: Toàn cục liên huyện ca chạy linh hoạt theo đội xe.
    """
    start_time = time.time()

    hub_coords = req.hub.location or [106.27415, 20.438299]
    hub_name = req.hub.name or "Bến xe Thái Bình (QL10 Vũ Thư)"
    opt_mode = req.config.opt_mode if (req.config and req.config.opt_mode) else "mode2"
    strict_prec = req.config.strict_precedence if req.config else True

    # Xác định ca chạy chung của đợt điều xe từ danh sách xe
    fleet_start_secs = [time_to_sec(v.start_time) for v in req.vehicles if v.start_time]
    fleet_end_secs = [time_to_sec(v.end_time) for v in req.vehicles if v.end_time]
    min_v_start_sec = min(fleet_start_secs) if fleet_start_secs else 24600
    max_v_end_sec = max(fleet_end_secs) if fleet_end_secs else (min_v_start_sec + 7200)
    if max_v_end_sec <= min_v_start_sec:
        max_v_end_sec = min_v_start_sec + 7200

    min_v_start_str = sec_to_time(min_v_start_sec)
    max_v_end_str = sec_to_time(max_v_end_sec)
    mid_sec = min_v_start_sec + max(1800, int((max_v_end_sec - min_v_start_sec) * 0.55))
    mid_str = sec_to_time(mid_sec)

    pax_map = {p.id: p for p in req.passengers}
    final_routes: List[RouteSchema] = []
    raw_unassigned: List[Any] = []
    total_system_dist = 0
    total_system_dur = 0
    total_system_service = 0

    if opt_mode == "mode1":
        # CÁCH 1: Phân tách Zone Gần (<15km) & Zone Xa (>=15km), đội xe rời nhau
        def is_near_pax(p: PassengerSchema) -> bool:
            if not p.location or len(p.location) < 2:
                return True
            dist = haversine_distance(p.location[0], p.location[1], hub_coords[0], hub_coords[1])
            # haversine_distance returns meters, 15km = 15000m
            return dist < 15000.0

        near_pax = [p for p in req.passengers if is_near_pax(p)]
        far_pax = [p for p in req.passengers if not is_near_pax(p)]

        used_far_veh_ids = set()

        # 1. Tối ưu nhóm Xa trước (nếu có khách xa)
        if far_pax:
            f_routes, f_unassigned, f_dist, f_dur, f_svc = await _solve_two_phase_subproblem(
                fleet=req.vehicles,
                passengers=far_pax,
                hub_coords=hub_coords,
                hub_name=hub_name,
                p1_start_str=min_v_start_str,
                p1_end_str=mid_str,
                p2_end_str=max_v_end_str,
                strict_precedence=strict_prec,
                is_near_zone=False,
                opt_mode_label="mode1"
            )
            final_routes.extend(f_routes)
            raw_unassigned.extend(f_unassigned)
            total_system_dist += f_dist
            total_system_dur += f_dur
            total_system_service += f_svc
            used_far_veh_ids = {r.vehicle_id for r in f_routes}

        # 2. Phân bổ đội xe còn lại cho nhóm Gần (rời nhau hoàn toàn)
        available_for_near = [v for v in req.vehicles if v.id not in used_far_veh_ids]
        if not available_for_near and near_pax:
            available_for_near = list(req.vehicles)

        # 3. Tối ưu nhóm Gần
        if near_pax:
            near_end_sec = min_v_start_sec + min(3600, max_v_end_sec - min_v_start_sec)
            near_mid_sec = min_v_start_sec + int((near_end_sec - min_v_start_sec) * 0.55)
            n_routes, n_unassigned, n_dist, n_dur, n_svc = await _solve_two_phase_subproblem(
                fleet=available_for_near,
                passengers=near_pax,
                hub_coords=hub_coords,
                hub_name=hub_name,
                p1_start_str=min_v_start_str,
                p1_end_str=sec_to_time(near_mid_sec),
                p2_end_str=sec_to_time(near_end_sec),
                strict_precedence=strict_prec,
                is_near_zone=True,
                opt_mode_label="mode1"
            )
            final_routes.extend(n_routes)
            raw_unassigned.extend(n_unassigned)
            total_system_dist += n_dist
            total_system_dur += n_dur
            total_system_service += n_svc

    else:
        # CÁCH 2: Toàn Cục Liên Huyện Theo Hành Khách (Ca linh hoạt theo đội xe)
        final_routes, raw_unassigned, total_system_dist, total_system_dur, total_system_service = await _solve_two_phase_subproblem(
            fleet=req.vehicles,
            passengers=req.passengers,
            hub_coords=hub_coords,
            hub_name=hub_name,
            p1_start_str=min_v_start_str,
            p1_end_str=mid_str,
            p2_end_str=max_v_end_str,
            strict_precedence=strict_prec,
            is_near_zone=False,
            opt_mode_label="mode2"
        )

    # ----------------------------------------------------------------------------------------------
    # BƯỚC 4: TỔNG HỢP DANH SÁCH KHÁCH CHƯA PHỤC VỤ (UNASSIGNED)
    # ----------------------------------------------------------------------------------------------
    assigned_pax_ids = set()
    for r in final_routes:
        for s in r.steps:
            if s.job_id:
                assigned_pax_ids.add(s.job_id)

    unassigned_models: List[UnassignedPassengerSchema] = []
    seen_unassigned_ids = set()

    for u in raw_unassigned:
        u_id = u.get("id")
        if u_id in seen_unassigned_ids or u_id in assigned_pax_ids:
            continue
        seen_unassigned_ids.add(u_id)
        p_obj = pax_map.get(u_id)
        
        reason = u.get("description") or "Không đủ số lượng xe khả dụng hoặc vượt quá khung thời gian cam kết ca chạy"
        if p_obj:
            unassigned_models.append(UnassignedPassengerSchema(
                passenger_id=p_obj.id,
                name=p_obj.name,
                type=p_obj.type,
                amount=p_obj.amount,
                location=p_obj.location,
                address=p_obj.address,
                reason=reason,
                id=p_obj.id,
                description=p_obj.name
            ))

    for p in req.passengers:
        if p.id not in assigned_pax_ids and p.id not in seen_unassigned_ids:
            seen_unassigned_ids.add(p.id)
            unassigned_models.append(UnassignedPassengerSchema(
                passenger_id=p.id,
                name=p.name,
                type=p.type,
                amount=p.amount,
                location=p.location,
                address=p.address,
                reason="Vượt quá tổng sức chứa hoặc không thể phục vụ kịp khung giờ ca chạy",
                id=p.id,
                description=p.name
            ))

    # ----------------------------------------------------------------------------------------------
    # BƯỚC 5: TỔNG HỢP KẾT QUẢ CHUẨN HÓA (UNIFIED RESPONSE)
    # ----------------------------------------------------------------------------------------------
    total_pax_served = sum(r.delivery_passengers + r.pickup_passengers for r in final_routes)
    all_on_time = all(r.is_on_time for r in final_routes)
    comp_time_ms = int((time.time() - start_time) * 1000)

    summary_schema = OptimizationSummarySchema(
        total_vehicles_used=len(final_routes),
        total_vehicles_available=len(req.vehicles),
        total_passengers_served=total_pax_served,
        total_unassigned=len(unassigned_models),
        total_distance_meters=total_system_dist,
        total_distance_km=round(total_system_dist / 1000.0, 2),
        total_duration_seconds=total_system_dur,
        total_duration_minutes=round(total_system_dur / 60.0, 1),
        total_service_minutes=float(total_system_service),
        all_routes_on_time=all_on_time,
        cost=total_system_dist,
        routes=len(final_routes),
        unassigned=len(unassigned_models),
        service=total_system_service * 60,
        duration=total_system_dur,
        distance=total_system_dist
    )

    engine_label = "VROOM 2-Phase Mode 1 (Zone-Based Disjoint Fleet)" if opt_mode == "mode1" else "VROOM 2-Phase Mode 2 (Global Inter-District Fleet)"

    return UnifiedOptimizationResponse(
        code=0,
        status="success",
        solver_engine=engine_label,
        computation_time_ms=comp_time_ms,
        summary=summary_schema,
        routes=final_routes,
        unassigned=unassigned_models,
        warnings=[]
    )

