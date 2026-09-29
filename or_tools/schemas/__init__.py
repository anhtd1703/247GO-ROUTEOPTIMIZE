"""
==================================================================================================
SCHEMAS PACKAGE FOR ROUTING OPTIMIZATION ENGINES
==================================================================================================
"""

from .constants import DISTRICT_NAMES, DISTRICT_SLA
from .utils import time_to_sec, sec_to_time, haversine_distance
from .models import (
    SolverConfig,
    HubSchema,
    VehicleSchema,
    PassengerSchema,
    UnifiedOptimizationRequest,
    RouteStepSchema,
    RouteSchema,
    UnassignedPassengerSchema,
    OptimizationSummarySchema,
    UnifiedOptimizationResponse
)
from .adapters import unified_request_to_vroom_payload

__all__ = [
    "DISTRICT_NAMES",
    "DISTRICT_SLA",
    "time_to_sec",
    "sec_to_time",
    "haversine_distance",
    "SolverConfig",
    "HubSchema",
    "VehicleSchema",
    "PassengerSchema",
    "UnifiedOptimizationRequest",
    "RouteStepSchema",
    "RouteSchema",
    "UnassignedPassengerSchema",
    "OptimizationSummarySchema",
    "UnifiedOptimizationResponse",
    "unified_request_to_vroom_payload"
]
