"""
Pydantic Data Models cho Request và Response của các Solver điều phối (Theo chuẩn SCHEMAS_GUIDE.md)
"""

from typing import List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field, model_validator
from .constants import DISTRICT_NAMES

# ==================================================================================================
# 1. REQUEST SCHEMAS
# ==================================================================================================

class SolverConfig(BaseModel):
    """Cấu hình tham số điều khiển bộ giải tối ưu"""
    time_limit_seconds: Optional[int] = Field(default=5, description="Giới hạn thời gian solver chạy (giây)")
    strict_precedence: Optional[bool] = Field(default=True, description="Ràng buộc tuyệt đối: Trả hết khách mới bắt đầu đón khách")
    routing_engine: Optional[str] = Field(default="vroom", description="vroom | pyvrp_hybrid | ortools | auto")
    detour_factor: Optional[float] = Field(default=1.35, description="Hệ số uốn lượn đường bộ khi fallback Haversine")
    avg_speed_kmh: Optional[float] = Field(default=38.0, description="Vận tốc trung bình (km/h) khi fallback")
    opt_mode: Optional[str] = Field(default="mode2", description="mode1: phân tách zone gần/xa | mode2: toàn cục liên huyện 2h")


class HubSchema(BaseModel):
    """Bến xe Trung tâm (Depot chính)"""
    id: Optional[int] = 0
    name: Optional[str] = "Bến xe Thái Bình (QL10 Vũ Thư)"
    location: Optional[List[float]] = Field(default=None, description="Tọa độ [lng, lat]")
    lng: Optional[float] = Field(default=None, description="Kinh độ GPS")
    lat: Optional[float] = Field(default=None, description="Vĩ độ GPS")
    address: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_coords(cls, data: Any) -> Any:
        if isinstance(data, dict):
            loc = data.get("location")
            lng = data.get("lng")
            lat = data.get("lat")
            if loc and isinstance(loc, (list, tuple)) and len(loc) >= 2:
                data["lng"] = float(loc[0])
                data["lat"] = float(loc[1])
                data["location"] = [float(loc[0]), float(loc[1])]
            elif lng is not None and lat is not None:
                data["location"] = [float(lng), float(lat)]
        return data


class VehicleSchema(BaseModel):
    """
    Thông tin xe trung chuyển.
    Hỗ trợ điểm xuất phát (start_location) và điểm kết thúc (end_location) linh hoạt cho từng xe:
    - Nếu không chỉ định: mặc định lấy theo vị trí của Hub.
    - Cho phép xe xuất phát từ huyện xa (VD: bãi đỗ Tiền Hải, Thái Thụy) hoặc kết thúc tại gara riêng.
    """
    id: int
    name: str = Field(..., description="Tên xe / Biển số xe")
    capacity: int = Field(default=16, ge=1, description="Số ghế chở khách")
    start_time: str = Field(default="13:00", description="Giờ bắt đầu ca chạy 'HH:MM'")
    end_time: str = Field(default="15:00", description="Giờ kết thúc ca chạy 'HH:MM'")
    color: Optional[str] = Field(default="#2563eb", description="Mã màu hiển thị giao diện")
    start_location: Optional[List[float]] = Field(default=None, description="[lng, lat] điểm xuất phát của xe (None = tại Hub)")
    end_location: Optional[List[float]] = Field(default=None, description="[lng, lat] điểm kết thúc của xe (None = về Hub)")
    start_location_name: Optional[str] = None
    end_location_name: Optional[str] = None

    # Hỗ trợ alias lạc hậu (backward compatibility)
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    startLocation: Optional[List[float]] = None
    endLocation: Optional[List[float]] = None

    @model_validator(mode="before")
    @classmethod
    def handle_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "startTime" in data and "start_time" not in data:
                data["start_time"] = data["startTime"]
            if "endTime" in data and "end_time" not in data:
                data["end_time"] = data["endTime"]
            if "startLocation" in data and "start_location" not in data:
                data["start_location"] = data["startLocation"]
            if "endLocation" in data and "end_location" not in data:
                data["end_location"] = data["endLocation"]
        return data


class PassengerSchema(BaseModel):
    """Thông tin hành khách yêu cầu phục vụ đón hoặc trả"""
    id: int
    name: str = Field(..., description="Tên hành khách / SĐT / Ghi chú")
    type: str = Field(..., description="'delivery' (Trả từ bến về nhà) hoặc 'pickup' (Đón từ nhà ra bến)")
    amount: int = Field(default=1, ge=1, description="Số lượng ghế cần giữ")
    district_id: int = Field(default=6, description="Mã huyện: 1..6")
    district_name: Optional[str] = None
    location: Optional[List[float]] = Field(default=None, description="[lng, lat] nhà khách")
    lng: Optional[float] = None
    lat: Optional[float] = None
    hub_time: str = Field(default="13:00", description="Giờ bến: Delivery=xe HN đến bến, Pickup=xe đi HN xuất bến")
    service_duration_min: int = Field(default=2, description="Thời gian dừng xe đón/trả tại nhà (phút)")
    address: Optional[str] = None
    tw_start: Optional[str] = None
    tw_end: Optional[str] = None

    # Hỗ trợ alias lạc hậu
    district: Optional[int] = None
    hubTime: Optional[str] = None
    service: Optional[int] = None
    twStart: Optional[str] = None
    twEnd: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_pax(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # District normalization
            d_id = data.get("district_id") or data.get("district") or 6
            data["district_id"] = int(d_id)
            if "district_name" not in data or not data["district_name"]:
                data["district_name"] = DISTRICT_NAMES.get(int(d_id), f"Huyện {d_id}")

            # Location normalization
            loc = data.get("location")
            lng = data.get("lng")
            lat = data.get("lat")
            if loc and isinstance(loc, (list, tuple)) and len(loc) >= 2:
                data["lng"] = float(loc[0])
                data["lat"] = float(loc[1])
                data["location"] = [float(loc[0]), float(loc[1])]
            elif lng is not None and lat is not None:
                data["location"] = [float(lng), float(lat)]

            # Type normalization
            t = str(data.get("type", "delivery")).lower()
            data["type"] = "pickup" if "pick" in t else "delivery"

            # Service time
            if "service_duration_min" not in data:
                svc = data.get("service", 2)
                data["service_duration_min"] = int(svc // 60) if svc > 15 else int(svc)

            # Hub time & Time windows
            if "hub_time" not in data and "hubTime" in data:
                data["hub_time"] = data["hubTime"]
            elif "hub_time" not in data and "timeInput" in data:
                data["hub_time"] = data["timeInput"]
            elif "hub_time" not in data and "time_input" in data:
                data["hub_time"] = data["time_input"]
            elif "hub_time" not in data:
                data["hub_time"] = "15:00" if data["type"] == "pickup" else "13:00"

            if "tw_start" not in data and "twStart" in data:
                data["tw_start"] = data["twStart"]
            if "tw_end" not in data and "twEnd" in data:
                data["tw_end"] = data["twEnd"]

        return data


class UnifiedOptimizationRequest(BaseModel):
    """Payload chuẩn hóa toàn diện cho tất cả các Router & Engine"""
    config: Optional[SolverConfig] = Field(default_factory=SolverConfig)
    hub: HubSchema
    vehicles: List[VehicleSchema]
    passengers: List[PassengerSchema]
    selected_districts: Optional[List[int]] = None
    timeLimitSeconds: Optional[int] = None  # Legacy support

    @model_validator(mode="before")
    @classmethod
    def handle_request_compat(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "timeLimitSeconds" in data and data["timeLimitSeconds"] is not None:
                if "config" not in data or not data["config"]:
                    data["config"] = {"time_limit_seconds": data["timeLimitSeconds"]}
                elif isinstance(data["config"], dict) and "time_limit_seconds" not in data["config"]:
                    data["config"]["time_limit_seconds"] = data["timeLimitSeconds"]
        return data


# ==================================================================================================
# 2. RESPONSE SCHEMAS
# ==================================================================================================

class RouteStepSchema(BaseModel):
    """Từng bước dừng / chặng ghé thăm trên lộ trình xe"""
    step_index: int
    type: Literal["start", "job", "end"]
    node_id: int
    job_id: Optional[int] = None
    name: str
    passenger_type: Optional[Literal["delivery", "pickup"]] = None
    district_id: Optional[int] = None
    district_name: Optional[str] = None
    amount: Optional[int] = None
    location: List[float]
    arrival_sec: int
    arrival_time: str
    departure_sec: Optional[int] = None
    departure_time: Optional[str] = None
    service_sec: int = 0
    phase: Literal["start", "delivery", "pickup", "end"]
    current_load: Optional[int] = None

    # Alias / compat properties
    arrival: Optional[int] = None
    duration: Optional[int] = None
    distance: Optional[int] = None
    service: Optional[int] = None
    job: Optional[int] = None


class RouteSchema(BaseModel):
    """Thông tin lộ trình chi tiết của một xe"""
    vehicle_id: int
    vehicle_name: str
    capacity: int
    color: Optional[str] = "#2563eb"
    delivery_passengers: int = 0
    pickup_passengers: int = 0
    total_distance_meters: int = 0
    total_duration_seconds: int = 0
    total_duration_minutes: float = 0.0
    districts_served: List[int] = []
    is_on_time: bool = True
    start_location: Optional[List[float]] = None
    end_location: Optional[List[float]] = None
    steps: List[RouteStepSchema] = []
    geometry: Union[str, List[List[float]]] = []

    # UI/Frontend compatibility fields
    vehicle: Optional[int] = None
    delivery: Optional[List[int]] = None
    pickup: Optional[List[int]] = None
    distance: Optional[int] = None
    duration: Optional[int] = None
    cost: Optional[int] = None
    corridorName: Optional[str] = None
    isNearZone: Optional[bool] = None
    isFarRoute: Optional[bool] = None
    targetBusTime: Optional[str] = None
    peakLoad: Optional[int] = None


class UnassignedPassengerSchema(BaseModel):
    """Thông tin hành khách chưa thể bố trí xe"""
    passenger_id: int
    name: str
    type: str
    amount: int
    district_id: int
    district_name: Optional[str] = None
    location: Optional[List[float]] = None
    reason: str

    # Alias
    id: Optional[int] = None
    description: Optional[str] = None


class OptimizationSummarySchema(BaseModel):
    """Bảng tổng hợp chỉ số hiệu năng ca điều phối"""
    total_vehicles_used: int
    total_vehicles_available: int
    total_passengers_served: int
    total_unassigned: int
    total_distance_meters: int
    total_distance_km: float
    total_duration_seconds: int
    total_duration_minutes: float
    total_service_minutes: float
    all_routes_on_time: bool = True

    # Compat fields
    cost: Optional[int] = None
    routes: Optional[int] = None
    unassigned: Optional[int] = None
    service: Optional[int] = None
    duration: Optional[int] = None
    distance: Optional[int] = None


class UnifiedOptimizationResponse(BaseModel):
    """Kết quả trả về chuẩn hóa của hệ thống điều phối"""
    code: int = 0
    status: Literal["success", "error", "partial"] = "success"
    solver_engine: str
    computation_time_ms: int
    summary: OptimizationSummarySchema
    routes: List[RouteSchema]
    unassigned: List[UnassignedPassengerSchema] = []
    warnings: List[str] = []
