"""
Định nghĩa các hằng số địa bàn và SLA cam kết của 6 Huyện / TP Thái Bình
"""

DISTRICT_NAMES = {
    1: "Đông Hưng",
    2: "Tiền Hải",
    3: "Kiến Xương",
    4: "Thái Thụy",
    5: "Vũ Thư",
    6: "TP. Thái Bình"
}

DISTRICT_SLA = {
    1: {"name": "Đông Hưng", "outbound": 30, "inbound": 30, "turnaround_limit_hours": 1},
    2: {"name": "Tiền Hải", "outbound": 40, "inbound": 40, "turnaround_limit_hours": 2},
    3: {"name": "Kiến Xương", "outbound": 25, "inbound": 25, "turnaround_limit_hours": 1},
    4: {"name": "Thái Thụy", "outbound": 45, "inbound": 45, "turnaround_limit_hours": 2},
    5: {"name": "Vũ Thư", "outbound": 20, "inbound": 20, "turnaround_limit_hours": 1},
    6: {"name": "TP. Thái Bình", "outbound": 15, "inbound": 15, "turnaround_limit_hours": 1}
}
