"""
Pydantic Data Models cho Request và Response của các Solver điều phối
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
    routing_engine: Optional[str] = Field(default="auto", description="ortools | pyvrp_hybrid | vroom | auto")
    detour_factor: Optional[float] = Field(default=1.35, description="Hệ số uốn lượn đường bộ khi fallback Haversine")
    avg_speed_kmh: Optional[float] = Field(default=38.0, description="Vận tốc trung bình (km/h) khi fallback")
    ride_time_penalty_weight: Optional[float] = Field(default=2.0, description="Hệ số điểm phạt thời gian khách ngồi trên xe (Soft Ride Time Penalty)")
    distance_penalty_weight: Optional[float] = Field(default=1.0, description="Hệ số điểm phạt mỗi mét xe chạy vượt ngưỡng max_distance_km_soft (Soft Distance Penalty)")


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
    start_time: str = Field(default="13:45", description="Giờ bắt đầu ca chạy 'HH:MM'")
    end_time: str = Field(default="16:00", description="Giờ kết thúc ca chạy 'HH:MM'")
    color: Optional[str] = Field(default="#2563eb", description="Mã màu hiển thị giao diện")
    start_location: Optional[List[float]] = Field(default=None, description="[lng, lat] điểm xuất phát của xe (None = tại Hub)")
    end_location: Optional[List[float]] = Field(default=None, description="[lng, lat] điểm kết thúc của xe (None = về Hub)")
    start_location_name: Optional[str] = None
    end_location_name: Optional[str] = None
    max_distance_km_soft: Optional[float] = Field(
        default=None,
        description="Ngưỡng km khuyến cáo (Soft). OR-Tools phạt điểm nếu vượt nhưng không block. VD: 80.0"
    )
    max_distance_km_hard: Optional[float] = Field(
        default=None,
        description="Ngưỡng km tuyệt đối (Hard). Xe không bao giờ được vượt ngưỡng này. VD: 120.0"
    )

    # Hỗ trợ alias lạc hậu (backward compatibility)
    startTime: Optional[str] = None
    endTime: Optional[str] = None

    @model_validator(mode="after")
    def validate_distance_limits(self) -> "VehicleSchema":
        soft = self.max_distance_km_soft
        hard = self.max_distance_km_hard
        if soft is not None and hard is not None and soft > hard:
            raise ValueError(
                f"max_distance_km_soft ({soft} km) phải ≤ max_distance_km_hard ({hard} km)"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def handle_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "startTime" in data and "start_time" not in data:
                data["start_time"] = data["startTime"]
            if "endTime" in data and "end_time" not in data:
                data["end_time"] = data["endTime"]

            # Normalize start_location
            s_loc = data.get("start_location")
            if isinstance(s_loc, dict):
                s_lng = s_loc.get("lng")
                s_lat = s_loc.get("lat")
                if s_lng is not None and s_lat is not None:
                    data["start_location"] = [float(s_lng), float(s_lat)]
                if "name" in s_loc and not data.get("start_location_name"):
                    data["start_location_name"] = s_loc["name"]

            # Normalize end_location
            e_loc = data.get("end_location")
            if isinstance(e_loc, dict):
                e_lng = e_loc.get("lng")
                e_lat = e_loc.get("lat")
                if e_lng is not None and e_lat is not None:
                    data["end_location"] = [float(e_lng), float(e_lat)]
                if "name" in e_loc and not data.get("end_location_name"):
                    data["end_location_name"] = e_loc["name"]
        return data


class PassengerSchema(BaseModel):
    """Thông tin hành khách yêu cầu phục vụ đón hoặc trả"""
    id: int
    name: str = Field(..., description="Tên hành khách / SĐT / Ghi chú")
    type: str = Field(..., description="'delivery' (Trả từ bến về nhà) hoặc 'pickup' (Đón từ nhà ra bến)")
    amount: int = Field(default=1, ge=1, description="Số lượng ghế cần giữ")
    location: Optional[List[float]] = Field(default=None, description="[lng, lat] nhà khách")
    lng: Optional[float] = None
    lat: Optional[float] = None
    trip_time: str = Field(default="13:45", description="Giờ chuyến xe: Khách trả=xe HN xuất phát, Khách đón=xe đi HN xuất bến")
    service_duration_min: int = Field(default=2, description="Thời gian dừng xe đón/trả tại nhà (phút)")
    address: Optional[str] = None

    # Hỗ trợ alias lạc hậu
    hubTime: Optional[str] = None
    service: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_pax(cls, data: Any) -> Any:
        if isinstance(data, dict):

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

            # Trip time
            if "trip_time" not in data:
                if "hub_time" in data:
                    data["trip_time"] = data["hub_time"]
                elif "hubTime" in data:
                    data["trip_time"] = data["hubTime"]

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
    amount: Optional[int] = None
    location: List[float]
    address: Optional[str] = None
    arrival_sec: int
    arrival_time: str
    departure_sec: Optional[int] = None
    departure_time: Optional[str] = None
    service_sec: int = 0
    phase: Literal["start", "delivery", "pickup", "end"]
    current_load: Optional[int] = None


class RouteSchema(BaseModel):
    """Thông tin lộ trình chi tiết của một xe"""
    vehicle_id: int
    vehicle_name: str
    capacity: int
    color: Optional[str] = "#2563eb"
    delivery_passengers: int = 0
    pickup_passengers: int = 0
    total_distance_meters: int = 0
    total_distance_km: float = Field(default=0.0, description="Tổng quãng đường xe chạy (km)")
    total_duration_seconds: int = 0
    total_duration_minutes: float = 0.0
    is_on_time: bool = True
    start_location: Optional[List[float]] = None
    end_location: Optional[List[float]] = None
    steps: List[RouteStepSchema] = []
    geometry: List[List[float]] = []


class UnassignedPassengerSchema(BaseModel):
    """Thông tin hành khách chưa thể bố trí xe"""
    passenger_id: int
    name: str
    type: str
    amount: int
    location: Optional[List[float]] = None
    address: Optional[str] = None
    reason: str


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
