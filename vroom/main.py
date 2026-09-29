"""
==================================================================================================
VROOM TWO-PHASE OPTIMIZATION SERVICE (FASTAPI APPLICATION)
==================================================================================================
API Service chuẩn hóa giải quyết bài toán điều phối 2 pha Đón & Trả.
Hỗ trợ Unified Optimization Schema (SCHEMAS_GUIDE.md & API_DOCUMENTATION.md).
"""

import os
import time
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

try:
    from .schemas.models import (
        UnifiedOptimizationRequest,
        UnifiedOptimizationResponse
    )
    from .two_phase_solver import solve_vroom_two_phase, OSRM_URL, VROOM_URL
except (ImportError, ValueError):
    from schemas.models import (
        UnifiedOptimizationRequest,
        UnifiedOptimizationResponse
    )
    from two_phase_solver import solve_vroom_two_phase, OSRM_URL, VROOM_URL

app = FastAPI(
    title="WeMap VROOM 2-Phase Optimization Service",
    description="Hệ thống điều phối xe trung chuyển 2 pha (Đón & Trả) khép kín chuẩn hóa",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
@app.get("/health")
async def health_check():
    """Kiểm tra trạng thái hoạt động của Service & các Engine phụ trợ"""
    return {
        "status": "ok",
        "service": "WeMap VROOM 2-Phase Optimization Service",
        "version": "2.0.0",
        "endpoints": {
            "optimize": "/api/optimize (POST)",
            "health": "/health (GET)"
        },
        "backends": {
            "vroom_core": VROOM_URL,
            "osrm_backend": OSRM_URL
        }
    }


@app.post("/api/optimize", response_model=UnifiedOptimizationResponse)
@app.post("/optimize", response_model=UnifiedOptimizationResponse)
@app.post("/optimize-2phase", response_model=UnifiedOptimizationResponse)
@app.post("/", response_model=UnifiedOptimizationResponse)
async def optimize_endpoint(payload: UnifiedOptimizationRequest) -> UnifiedOptimizationResponse:
    """
    Điểm cuối điều phối chính của VROOM 2-Pha:
    - Nhận: UnifiedOptimizationRequest (Hub, Vehicles, Passengers, Config)
    - Xử lý: Tự động chạy 2 pha (Pha 1: Trả -> Móc nối xe -> Pha 2: Đón)
    - Trả về: UnifiedOptimizationResponse (Summary KPI, Chi tiết lộ trình & Timeline, Unassigned)
    """
    try:
        response = await solve_vroom_two_phase(payload)
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Lỗi khi thực hiện tối ưu hóa VROOM 2-Pha: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8006, reload=True)
