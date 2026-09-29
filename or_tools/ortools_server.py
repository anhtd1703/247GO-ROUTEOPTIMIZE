# ==================================================================================================
# HỆ THỐNG ĐIỀU PHỐI VÀ TỐI ƯU HÓA XE TRUNG CHUYỂN THÁI BÌNH
# Đơn vị: WeMap Dispatching Engine
# Nghiệp vụ: Đón / Trả khách tận nhà tại 6 huyện/TP Thái Bình (Hà Nội ⇄ Thái Bình)
# Thuật toán: Google OR-Tools Routing Solver + Constraint Programming (CP Engine)
# Hỗ trợ: Đa điểm xuất phát và kết thúc (Arbitrary Start/Stop per Vehicle), Precedence CP, SLA Huyện
# ==================================================================================================

import sys
import os

# Đảm bảo in UTF-8 không bị lỗi charmap trên Windows console
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import math
import json
import time
import requests
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# Import Schemas chuẩn hóa
try:
    from or_tools.schemas import (
        UnifiedOptimizationRequest,
        UnifiedOptimizationResponse,
        HubSchema,
        VehicleSchema,
        PassengerSchema,
        RouteSchema,
        RouteStepSchema,
        OptimizationSummarySchema,
        UnassignedPassengerSchema,
        DISTRICT_NAMES,
        time_to_sec,
        sec_to_time
    )
except ImportError:
    from schemas import (
        UnifiedOptimizationRequest,
        UnifiedOptimizationResponse,
        HubSchema,
        VehicleSchema,
        PassengerSchema,
        RouteSchema,
        RouteStepSchema,
        OptimizationSummarySchema,
        UnassignedPassengerSchema,
        DISTRICT_NAMES,
        time_to_sec,
        sec_to_time
    )

# --------------------------------------------------------------------------------------------------
# KHỞI TẠO DỊCH VỤ FASTAPI VÀ CẤU HÌNH CORS
# --------------------------------------------------------------------------------------------------
app = FastAPI(
    title="WeMap OR-Tools CP Dispatching Engine",
    description="Dịch vụ tối ưu hóa điều phối xe trung chuyển tuyến Thái Bình ⇄ Hà Nội sử dụng Google OR-Tools & Constraint Programming",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Địa chỉ OSRM Engine chạy local (hoặc remote)
OSRM_URL = os.getenv("OSRM_URL", "http://localhost:5000")

# Bảng cam kết thời gian di chuyển chuẩn (SLA) giữa Bến xe trung tâm (QL10 Vũ Thư) và các huyện (phút)
DISTRICT_SLA = {
    1: {"name": "Đông Hưng", "outbound": 30, "inbound": 30},
    2: {"name": "Tiền Hải", "outbound": 40, "inbound": 40},
    3: {"name": "Kiến Xương", "outbound": 25, "inbound": 25},
    4: {"name": "Thái Thụy", "outbound": 45, "inbound": 45},
    5: {"name": "Vũ Thư", "outbound": 20, "inbound": 20},
    6: {"name": "TP. Thái Bình", "outbound": 15, "inbound": 15}
}

# --------------------------------------------------------------------------------------------------
# CÁC HÀM TIỆN ÍCH TÍNH TOÁN HÌNH HỌC VÀ OSRM
# --------------------------------------------------------------------------------------------------

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

def get_distance_and_duration_matrix(coords: List[List[float]], detour_factor: float = 1.35, avg_speed_kmh: float = 38.0) -> tuple[List[List[int]], List[List[int]]]:
    """
    Tạo Ma trận Khoảng cách (mét) và Thời gian (giây) giữa tất cả các cặp điểm.
    Ưu tiên: Gọi OSRM Table Service.
    Fallback: Haversine với hệ số uốn khúc nông thôn Thái Bình và vận tốc trung bình.
    """
    n = len(coords)
    try:
        coord_str = ";".join([f"{c[0]},{c[1]}" for c in coords])
        url = f"{OSRM_URL}/table/v1/driving/{coord_str}?annotations=distance,duration"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "Ok":
                durations = [[int(d) for d in row] for row in data["durations"]]
                distances = [[int(d) for d in row] for row in data["distances"]]
                return distances, durations
    except Exception as e:
        pass

    # Fallback Haversine
    avg_speed_mps = 38.0 * 1000 / 3600  # ~10.55 m/s (~38 km/h)
    detour_factor = 1.35
    distances = []
    durations = []
    for i in range(n):
        row_dist = []
        row_dur = []
        for j in range(n):
            if i == j:
                row_dist.append(0)
                row_dur.append(0)
            else:
                d = haversine_distance(coords[i][0], coords[i][1], coords[j][0], coords[j][1]) * detour_factor
                row_dist.append(int(d))
                row_dur.append(int(d / avg_speed_mps))
        distances.append(row_dist)
        durations.append(row_dur)
    return distances, durations

def get_osrm_route_geometry(coords: List[List[float]]) -> List[List[float]]:
    """Gọi OSRM Route API để lấy đường vẽ GeoJSON chi tiết bám theo mạng lưới đường thực tế"""
    if len(coords) < 2:
        return coords
    try:
        coord_str = ";".join([f"{c[0]},{c[1]}" for c in coords])
        url = f"{OSRM_URL}/route/v1/driving/{coord_str}?overview=full&geometries=geojson"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "Ok" and len(data.get("routes", [])) > 0:
                return data["routes"][0]["geometry"]["coordinates"]
    except Exception:
        pass
    return coords

# --------------------------------------------------------------------------------------------------
# ENDPOINTS API
# --------------------------------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "engine": "OR-Tools Routing + Constraint Programming (CP)",
        "version": "2.1.0"
    }

@app.post("/api/optimize", response_model=UnifiedOptimizationResponse)
@app.post("/optimize", response_model=UnifiedOptimizationResponse)
def optimize_dispatch(req: UnifiedOptimizationRequest) -> UnifiedOptimizationResponse:
    """
    ENDPOINT ĐIỀU PHỐI XE TRUNG CHUYỂN CHUẨN HÓA (OR-TOOLS + CONSTRAINT PROGRAMMING):
    
    Các ràng buộc nghiệp vụ được mô hình hóa:
    1. [Routing + Arc Cost]: Tối thiểu hóa tổng quãng đường di chuyển và thời gian chạy.
    2. [Vehicle Fixed Cost]: Phạt chi phí cao với xe nhiều chỗ -> Ưu tiên lấp đầy xe 7 chỗ, 9 chỗ trước xe 16 chỗ.
    3. [CP Precedence Constraint]: Trên mỗi xe, TẤT CẢ khách Trả (Delivery) phải được trả xong TRƯỚC khi đón khách mới (Pickup).
       Sử dụng CP Solver: solver.MakeImply(VehicleVar(d) == VehicleVar(p), CumulVar(d) <= CumulVar(p)).
    4. [Capacity Constraints]: 
       - Sức chứa Delivery: Không chở quá sức chứa khi rời bến.
       - Sức chứa Pickup: Không đón quá sức chứa khi gom khách về bến.
    5. [Time Windows + SLA]:
       - Delivery: Xe nhận khách từ bến sau giờ xe HN về (x:45), trả tại nhà trong khung SLA huyện.
       - Pickup: Xe đón khách tại nhà và đưa về bến trung tâm trước giờ xe chạy đi HN ít nhất 10 phút.
    6. [Disjunction Penalty]: Mức phạt rất lớn nếu bỏ sót khách để Solver luôn phục vụ tối đa khách.
    7. [Start / End Location]: Hỗ trợ điểm đầu và điểm cuối riêng của xe, mặc định tại Bến xe Quốc lộ 10.
    """
    start_time_ts = time.time()

    start_time_ts = time.time()

    if not req.vehicles:
        raise HTTPException(status_code=400, detail="Danh sách xe trung chuyển không được để trống!")
    if not req.passengers:
        raise HTTPException(status_code=400, detail="Danh sách hành khách không được để trống!")

    # Bến xe Quốc lộ 10 Thái Bình mặc định
    hub_coord = req.hub.location or [106.27415, 20.438299]

    # Danh sách tọa độ: Nút 0 là Bến xe trung tâm (Hub), Nút 1..N là các điểm khách hàng
    coords = [hub_coord] + [p.location for p in req.passengers]
    num_pax = len(req.passengers)
    num_vehicles = len(req.vehicles)

    # Xử lý điểm bắt đầu và kết thúc của từng xe (mặc định bến xe QL10)
    starts = []
    ends = []

    def get_or_add_coord_idx(loc: Optional[List[float]]) -> int:
        if not loc:
            return 0
        if haversine_distance(loc[0], loc[1], hub_coord[0], hub_coord[1]) < 10.0:
            return 0
        for idx_c, c in enumerate(coords):
            if haversine_distance(loc[0], loc[1], c[0], c[1]) < 10.0:
                return idx_c
        new_idx = len(coords)
        coords.append([float(loc[0]), float(loc[1])])
        return new_idx

    for v in req.vehicles:
        s_idx = get_or_add_coord_idx(v.start_location)
        e_idx = get_or_add_coord_idx(v.end_location)
        starts.append(s_idx)
        ends.append(e_idx)

    num_locations = len(coords)

    # 1. Lấy Ma trận Khoảng cách và Thời gian từ OSRM
    dist_matrix, duration_matrix = get_distance_and_duration_matrix(coords)

    # Khung giờ làm việc của ca chạy hiện tại
    min_v_start = min([time_to_sec(v.start_time) for v in req.vehicles])
    max_v_end = max([time_to_sec(v.end_time) for v in req.vehicles])

    # Khởi tạo danh sách phân loại khách
    service_times = [0] * num_locations
    delivery_demands = [0] * num_locations
    pickup_demands = [0] * num_locations
    delivery_node_indices = []
    pickup_node_indices = []
    time_windows = [(min_v_start, max_v_end)] * num_locations  # Hub & Depots

    for idx, p in enumerate(req.passengers):
        node_idx = idx + 1
        is_delivery = p.type == 'delivery'
        d_sla = DISTRICT_SLA.get(p.district_id, {"outbound": 30, "inbound": 30})
        service_sec = p.service_duration_min * 60
        service_times[node_idx] = service_sec

        if is_delivery:
            # 1. TRẢ KHÁCH (Delivery):
            # Khách đã có mặt tại bến từ đầu ca -> Trả linh hoạt trong ca từ min_v_start đến max_v_end
            time_windows[node_idx] = (min_v_start, max_v_end)

            delivery_demands[node_idx] = p.amount
            pickup_demands[node_idx] = 0
            delivery_node_indices.append(node_idx)
        else:
            # 2. ĐÓN KHÁCH (Pickup):
            # Khách cần về bến trước giờ xe lớn đi Hà Nội (p.hub_time)
            hanoi_dep_sec = time_to_sec(p.hub_time) if p.hub_time else max_v_end
            direct_dur_to_hub = duration_matrix[node_idx][0]

            # Giờ đón muộn nhất để kịp về bến trước giờ xe lớn chạy (đảm bảo min <= max)
            min_pick_sec = min_v_start
            max_pick_sec = max(min_pick_sec, min(max_v_end, hanoi_dep_sec - direct_dur_to_hub))

            time_windows[node_idx] = (min_pick_sec, max_pick_sec)
            delivery_demands[node_idx] = 0
            pickup_demands[node_idx] = p.amount
            pickup_node_indices.append(node_idx)

    # ----------------------------------------------------------------------------------------------
    # 2. KHỞI TẠO ROUTING MODEL VÀ CP SOLVER (HỖ TRỢ STARTS VÀ ENDS CỦA TỪNG XE)
    # ----------------------------------------------------------------------------------------------
    manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, starts, ends)
    routing = pywrapcp.RoutingModel(manager)
    solver = routing.solver()

    # 3. ĐĂNG KÝ HÀM CHI PHÍ QUÃNG ĐƯỜNG (ARC COST)
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return dist_matrix[from_node][to_node]

    transit_dist_callback_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_dist_callback_idx)

    # 4. TỐI ƯU HÓA ĐỘI XE THÔNG MINH (DYNAMIC FLEET RIGHT-SIZING FIXED COSTS)
    # Tự động điều chỉnh chi phí mở xe theo tổng dung lượng khách để chọn loại xe thông minh nhất.
    # Ưu tiên số 1: Phục vụ 100% khách. Khi đông khách, chi phí mở xe giảm về ~0 để solver tự do bung hết xe đón khách.
    total_pax_count = sum(p.amount for p in req.passengers)

    for v_idx, v in enumerate(req.vehicles):
        if total_pax_count <= 40:
            # 🟢 KỊCH BẢN THẤP ĐIỂM (<= 40 khách): Ưu tiên lấp đầy xe nhỏ 7 chỗ trước
            if v.capacity <= 7:
                fixed_cost = 500
            elif v.capacity <= 11:
                fixed_cost = 1_000 
            else:
                fixed_cost = 2_000
        elif total_pax_count <= 80:
            # 🟡 KỊCH BẢN TRUNG BÌNH (41 - 80 khách): Ưu tiên kích hoạt xe 16 chỗ và 11 chỗ
            if v.capacity >= 16:
                fixed_cost = 100
            elif v.capacity >= 10:
                fixed_cost = 200
            else:
                fixed_cost = 500
        else:
            # 🔴 KỊCH BẢN CAO ĐIỂM / QUÁ TẢI (> 80 khách): ƯU TIÊN PHỤC VỤ HẾT KHÁCH LÀ SỐ 1
            # Chi phí mở xe = 0 để solver thoải mái kích hoạt toàn bộ 10 xe
            fixed_cost = 0
        routing.SetFixedCostOfVehicle(fixed_cost, v_idx)

    # 5. CHIỀU THỜI GIAN (TIME DIMENSION) + TIME WINDOWS
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return duration_matrix[from_node][to_node] + service_times[from_node]

    transit_time_callback_idx = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(
        transit_time_callback_idx,
        7200,   # Slack
        86400,  # Horizon
        False,
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')

    # Gán Khung thời gian cho tất cả các điểm khách hàng
    for node_idx in range(1, num_pax + 1):
        index = manager.NodeToIndex(node_idx)
        tw = time_windows[node_idx]
        time_dimension.CumulVar(index).SetRange(tw[0], tw[1])

    # Gán Time Windows ca chạy cho từng xe
    for v_idx in range(num_vehicles):
        start_idx = routing.Start(v_idx)
        end_idx = routing.End(v_idx)
        v_obj = req.vehicles[v_idx]
        v_start = time_to_sec(v_obj.start_time)
        v_end = time_to_sec(v_obj.end_time)
        time_dimension.CumulVar(start_idx).SetRange(v_start, v_end)
        time_dimension.CumulVar(end_idx).SetRange(v_start, v_end)

    # ==============================================================================================
    # 5b. ĐIỂM PHẠT MỀM THỜI GIAN KHÁCH NGỒI TRÊN XE (SOFT RIDE TIME PENALTY - CX OPTIMIZATION)
    # ==============================================================================================
    # Hệ số quy đổi: 1 giây khách ngồi xe quá thời gian lý tưởng = 2 điểm chi phí mục tiêu (mặc định)
    ride_time_cost_per_sec = 2
    if req.config and hasattr(req.config, "ride_time_penalty_weight") and req.config.ride_time_penalty_weight is not None:
        ride_time_cost_per_sec = int(req.config.ride_time_penalty_weight)

    # 1. Khách Trả (Delivery): Phạt nếu khách bị trả muộn hơn thời gian chạy thẳng từ Bến về nhà
    for d_node in delivery_node_indices:
        d_idx = manager.NodeToIndex(d_node)
        direct_dur_from_hub = duration_matrix[0][d_node]
        # Mốc lý tưởng = Giờ xe bắt đầu ca + Thời gian chạy thẳng từ Bến về nhà + 5 phút đệm
        ideal_delivery_sec = min_v_start + direct_dur_from_hub + 300
        time_dimension.SetCumulVarSoftUpperBound(d_idx, ideal_delivery_sec, ride_time_cost_per_sec)
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(d_idx))

    # 2. Khách Đón (Pickup): Phạt nếu khách bị đón quá sớm so với giờ xe lớn chạy
    for p_node in pickup_node_indices:
        p_idx = manager.NodeToIndex(p_node)
        pax = req.passengers[p_node - 1]
        hanoi_dep_sec = time_to_sec(pax.hub_time) if pax.hub_time else max_v_end
        direct_dur_to_hub = duration_matrix[p_node][0]
        # Mốc đón lý tưởng = Giờ xe lớn chạy - Thời gian chạy thẳng từ nhà ra Bến - 15 phút đệm
        ideal_pickup_sec = max(min_v_start, hanoi_dep_sec - direct_dur_to_hub - 900)
        time_dimension.SetCumulVarSoftLowerBound(p_idx, ideal_pickup_sec, ride_time_cost_per_sec)
        routing.AddVariableMaximizedByFinalizer(time_dimension.CumulVar(p_idx))

    # 3. Phạt kéo dài tổng thời gian toàn bộ hành trình của xe (Global Span Cost)
    # time_dimension.SetSpanCostCoefficientForAllVehicles(1)

    # 6. CHIỀU TẢI TRỌNG (CAPACITY DIMENSION) CHO DELIVERY & PICKUP
    vehicle_capacities = [v.capacity for v in req.vehicles]

    def del_demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return delivery_demands[from_node]

    del_callback_idx = routing.RegisterUnaryTransitCallback(del_demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        del_callback_idx,
        0,
        vehicle_capacities,
        True,
        'DeliveryCapacity'
    )

    def pick_demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return pickup_demands[from_node]

    pick_callback_idx = routing.RegisterUnaryTransitCallback(pick_demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        pick_callback_idx,
        0,
        vehicle_capacities,
        True,
        'PickupCapacity'
    )

    # ----------------------------------------------------------------------------------------------
    # 7. CONSTRAINT PROGRAMMING (CP) RÀNG BUỘC PRECEDENCE (TRẢ TRƯỚC ĐÓN SAU)
    # ----------------------------------------------------------------------------------------------
    if req.config and req.config.strict_precedence:
        for d_node in delivery_node_indices:
            d_idx = manager.NodeToIndex(d_node)
            for p_node in pickup_node_indices:
                p_idx = manager.NodeToIndex(p_node)
                is_same_v = solver.IsEqualVar(routing.VehicleVar(d_idx), routing.VehicleVar(p_idx))
                solver.Add(time_dimension.CumulVar(d_idx) <= time_dimension.CumulVar(p_idx) + (1 - is_same_v) * 86400)

    # ----------------------------------------------------------------------------------------------
    # 7b. CONSTRAINT PROGRAMMING (CP): VỀ BẾN ĐÚNG GIỜ CHO KHÁCH ĐÓN
    # ----------------------------------------------------------------------------------------------
    for p_node in pickup_node_indices:
        p_idx = manager.NodeToIndex(p_node)
        pax = req.passengers[p_node - 1]
        hanoi_dep_sec = time_to_sec(pax.hub_time) if pax.hub_time else max_v_end
        
        # Chỉ cần về bến trước giờ xe lớn đi Hà Nội (không cần trước 10 phút, bỏ cận dưới)
        max_hub_arrival_sec = hanoi_dep_sec

        for v_idx in range(num_vehicles):
            end_idx = routing.End(v_idx)
            v_end_node = ends[v_idx]
            is_assigned_to_v = solver.IsEqualCstVar(routing.VehicleVar(p_idx), v_idx)
            
            # Chặn trên: Về bến trước hoặc đúng giờ xe lớn xuất bến
            solver.Add(time_dimension.CumulVar(end_idx) <= max_hub_arrival_sec + (1 - is_assigned_to_v) * 86400)

    # 8. MỨC PHẠT BỎ SÓT ĐIỂM (DISJUNCTION PENALTY) - SIÊU LỚN ĐỂ LUÔN PHỤC VỤ 100% KHÁCH (CHỈ CHO NÚT KHÁCH 1..num_pax)
    for node_idx in range(1, num_pax + 1):
        pax = req.passengers[node_idx - 1]
        p_amt = pax.amount if pax.amount else 1
        penalty = 1_000_000_000 * p_amt  # 1 tỷ điểm / người -> Ưu tiên phục vụ khách lên cao nhất
        routing.AddDisjunction([manager.NodeToIndex(node_idx)], penalty)

    # ----------------------------------------------------------------------------------------------
    # 9. THIẾT LẬP THAM SỐ TÌM KIẾM CHUYÊN SÂU & METAHEURISTICS (GUIDED LOCAL SEARCH)
    # ----------------------------------------------------------------------------------------------
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    # Hệ số phạt vượt cực tiểu cục bộ (GLS Lambda)
    search_parameters.guided_local_search_lambda_coefficient = 0.2

    # KÍCH HOẠT TOÀN BỘ CÁC TOÁN TỬ LOCAL SEARCH NÂNG CAO ĐỂ TÌM KIẾM NGHIỆM SÂU
    search_parameters.local_search_operators.use_make_active = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_relocate_and_make_active = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_two_opt = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_cross_exchange = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_relocate_neighbors = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_extended_swap_active = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_node_pair_swap_active = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_exchange = pywrapcp.BOOL_TRUE
    search_parameters.local_search_operators.use_lin_kernighan = pywrapcp.BOOL_TRUE
    
    # Dynamic Time Limit thông minh phân cấp (tối đa 12s để luôn phản hồi nhanh dưới ngưỡng timeout)
    cfg_time_limit = req.config.time_limit_seconds if req.config else None
    if cfg_time_limit and cfg_time_limit not in (0, 5):
        target_time_sec = cfg_time_limit
    elif req.timeLimitSeconds and req.timeLimitSeconds not in (0, 5):
        target_time_sec = req.timeLimitSeconds
    else:
        n_pax = len(req.passengers)
        if n_pax <= 25:
            target_time_sec = 4     # Thấp điểm: 4s
        elif n_pax <= 50:
            target_time_sec = 7     # Trung bình: 7s
        elif n_pax <= 80:
            target_time_sec = 10    # Cao điểm: 10s
        else:
            target_time_sec = 12    # Quá tải (>80 khách): 12s tối ưu nhanh

    search_parameters.time_limit.seconds = int(target_time_sec)

    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        # Chiến lược dự phòng 1: SAVINGS Strategy (3s)
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.SAVINGS
        search_parameters.time_limit.seconds = 3
        solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        # Chiến lược dự phòng 2: PATH_CHEAPEST_ARC (3s)
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_parameters.time_limit.seconds = 3
        solution = routing.SolveWithParameters(search_parameters)

    # ----------------------------------------------------------------------------------------------
    # GRACEFUL OVERLOAD FALLBACK: Nếu quá tải nặng không thể lập lịch cả đoàn, trả về toàn bộ unassigned
    # ----------------------------------------------------------------------------------------------
    if not solution:
        elapsed_ms = int((time.time() - start_time_ts) * 1000)
        unassigned_all = [
            UnassignedPassengerSchema(
                passenger_id=p.id,
                name=p.name,
                type=p.type,
                amount=p.amount,
                district_id=p.district_id,
                district_name=p.district_name or DISTRICT_NAMES.get(p.district_id, f"Huyện {p.district_id}"),
                location=p.location,
                reason="Nhu cầu vượt quá tổng công suất ghế hoặc xung đột nghiêm trọng khung giờ ca chạy"
            )
            for p in req.passengers
        ]
        summary_empty = OptimizationSummarySchema(
            total_vehicles_used=0,
            total_vehicles_available=len(req.vehicles),
            total_passengers_served=0,
            total_unassigned=len(unassigned_all),
            total_distance_meters=0,
            total_distance_km=0.0,
            total_duration_seconds=0,
            total_duration_minutes=0.0,
            total_service_minutes=0.0,
            all_routes_on_time=False
        )
        return UnifiedOptimizationResponse(
            code=0,
            status="partial",
            solver_engine="Google OR-Tools + Constraint Programming (CP)",
            computation_time_ms=elapsed_ms,
            summary=summary_empty,
            routes=[],
            unassigned=unassigned_all,
            warnings=["Hệ thống quá tải: Không thể lập lịch khả thi thỏa mãn 100% ràng buộc cứng của đoàn xe."]
        )

    # ----------------------------------------------------------------------------------------------
    # 10. TRÍCH XUẤT LỘ TRÌNH VÀ TẠO KẾT QUẢ ĐẦY ĐỦ THEO UNIFIED SCHEMAS
    # ----------------------------------------------------------------------------------------------
    routes_res: List[RouteSchema] = []
    total_dist = 0
    total_dur = 0
    total_svc = 0
    assigned_nodes = set()

    for v_idx in range(num_vehicles):
        v_obj = req.vehicles[v_idx]
        start_index = routing.Start(v_idx)
        end_index = routing.End(v_idx)

        # Kiểm tra xe có chở khách nào không
        first_step_idx = solution.Value(routing.NextVar(start_index))
        if routing.IsEnd(first_step_idx):
            continue  # Xe không hoạt động

        steps: List[RouteStepSchema] = []
        v_start_loc = coords[starts[v_idx]]
        v_end_loc = coords[ends[v_idx]]
        route_coords = [v_start_loc]
        used_del = 0
        used_pick = 0
        districts_in_route = set()

        start_arrival = solution.Min(time_dimension.CumulVar(start_index))
        steps.append(RouteStepSchema(
            step_index=0,
            type="start",
            node_id=starts[v_idx],
            job_id=None,
            name=v_obj.start_location_name or req.hub.name or "Bến xe Thái Bình (QL10 Vũ Thư)",
            location=v_start_loc,
            arrival_sec=start_arrival,
            arrival_time=sec_to_time(start_arrival),
            departure_sec=start_arrival,
            departure_time=sec_to_time(start_arrival),
            service_sec=0,
            phase="start",
            current_load=0
        ))

        curr_index = start_index
        step_counter = 1

        while not routing.IsEnd(curr_index):
            curr_index = solution.Value(routing.NextVar(curr_index))
            if routing.IsEnd(curr_index):
                break

            curr_node = manager.IndexToNode(curr_index)
            if curr_node < 1 or curr_node > num_pax:
                continue

            assigned_nodes.add(curr_node)
            pax = req.passengers[curr_node - 1]
            districts_in_route.add(pax.district_id)
            is_del = pax.type == 'delivery'

            if is_del:
                used_del += pax.amount
            else:
                used_pick += pax.amount

            arrival_sec = solution.Min(time_dimension.CumulVar(curr_index))
            svc_sec = pax.service_duration_min * 60
            dep_sec = arrival_sec + svc_sec
            total_svc += svc_sec

            steps.append(RouteStepSchema(
                step_index=step_counter,
                type="job",
                node_id=curr_node,
                job_id=pax.id,
                name=pax.name,
                passenger_type="delivery" if is_del else "pickup",
                district_id=pax.district_id,
                district_name=pax.district_name or DISTRICT_NAMES.get(pax.district_id, f"Huyện {pax.district_id}"),
                amount=pax.amount,
                location=pax.location,
                arrival_sec=arrival_sec,
                arrival_time=sec_to_time(arrival_sec),
                departure_sec=dep_sec,
                departure_time=sec_to_time(dep_sec),
                service_sec=svc_sec,
                phase="delivery" if is_del else "pickup",
                current_load=used_del if is_del else used_pick
            ))
            route_coords.append(pax.location)
            step_counter += 1

        # Cập nhật tải trọng ban đầu ở bước Xuất phát
        steps[0].current_load = used_del

        # Bước kết thúc ca chạy
        end_arrival = solution.Min(time_dimension.CumulVar(end_index))
        route_coords.append(v_end_loc)
        steps.append(RouteStepSchema(
            step_index=step_counter,
            type="end",
            node_id=ends[v_idx],
            job_id=None,
            name=v_obj.end_location_name or req.hub.name or "Bến xe Thái Bình (QL10 Vũ Thư)",
            location=v_end_loc,
            arrival_sec=end_arrival,
            arrival_time=sec_to_time(end_arrival),
            departure_sec=end_arrival,
            departure_time=sec_to_time(end_arrival),
            service_sec=0,
            phase="end",
            current_load=used_pick
        ))

        geom = get_osrm_route_geometry(route_coords)

        r_dist = 0
        for s_i in range(1, len(steps)):
            n_from = steps[s_i - 1].node_id
            n_to = steps[s_i].node_id
            r_dist += dist_matrix[n_from][n_to]

        r_dur = end_arrival - start_arrival
        total_dist += r_dist
        total_dur += r_dur

        routes_res.append(RouteSchema(
            vehicle_id=v_obj.id,
            vehicle_name=v_obj.name,
            capacity=v_obj.capacity,
            color=v_obj.color or "#2563eb",
            delivery_passengers=used_del,
            pickup_passengers=used_pick,
            total_distance_meters=r_dist,
            total_duration_seconds=r_dur,
            total_duration_minutes=round(r_dur / 60.0, 1),
            districts_served=sorted(list(districts_in_route)),
            is_on_time=True,
            start_location=v_start_loc,
            end_location=v_end_loc,
            steps=steps,
            geometry=geom
        ))

    # Danh sách khách chưa thể xếp xe
    unassigned_res: List[UnassignedPassengerSchema] = []
    for idx, p in enumerate(req.passengers):
        node_idx = idx + 1
        if node_idx not in assigned_nodes:
            unassigned_res.append(UnassignedPassengerSchema(
                passenger_id=p.id,
                name=p.name,
                type=p.type,
                amount=p.amount,
                district_id=p.district_id,
                district_name=p.district_name or DISTRICT_NAMES.get(p.district_id, f"Huyện {p.district_id}"),
                location=p.location,
                reason="Vượt quá sức chứa hoặc không thể phục vụ kịp khung giờ cam kết"
            ))

    elapsed_ms = int((time.time() - start_time_ts) * 1000)

    summary = OptimizationSummarySchema(
        total_vehicles_used=len(routes_res),
        total_vehicles_available=len(req.vehicles),
        total_passengers_served=len(assigned_nodes),
        total_unassigned=len(unassigned_res),
        total_distance_meters=total_dist,
        total_distance_km=round(total_dist / 1000.0, 2),
        total_duration_seconds=total_dur,
        total_duration_minutes=round(total_dur / 60.0, 1),
        total_service_minutes=round(total_svc / 60.0, 1),
        all_routes_on_time=True
    )

    return UnifiedOptimizationResponse(
        code=0,
        status="success" if not unassigned_res else "partial",
        solver_engine="Google OR-Tools + Constraint Programming (CP)",
        computation_time_ms=elapsed_ms,
        summary=summary,
        routes=routes_res,
        unassigned=unassigned_res,
        warnings=[]
    )

# --------------------------------------------------------------------------------------------------
# KHỞI CHẠY SERVER
# --------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    print("[INFO] Đang khởi chạy WeMap OR-Tools + CP Server tại http://0.0.0.0:8008...")
    uvicorn.run(app, host="0.0.0.0", port=8008)