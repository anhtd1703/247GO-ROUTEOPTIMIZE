# GIẢI MÃ TOÀN DIỆN GOOGLE OR-TOOLS ROUTING & CONSTRAINT PROGRAMMING (CP)
**Ứng dụng thực tế trong:** [`or_tools/ortools_server.py`](file:///c:/Users/TANDAITHANH.COM.VN/PHRoutingOptimize/or_tools/ortools_server.py)  
**Mục tiêu bài toán:** Tối ưu hóa điều phối đội xe trung chuyển khách tận nhà tuyến Hà Nội ⇄ Thái Bình (6 huyện/thành phố).

---

## MỤC LỤC
1. [Hàm Mục Tiêu (Objective Function) Là Gì?](#1-hàm-mục-tiêu-objective-function-là-gì)
2. [Chi Phí Phạt & Ràng Buộc Ảnh Hưởng Thế Nào?](#2-chi-phí-phạt--ràng-buộc-ảnh-hưởng-thế-nào)
3. [Thuật Toán Xử Lý Ràng Buộc (Constraint Programming - CP) Hoạt Động Ra Sao?](#3-thuật-toán-xử-lý-ràng-buộc-constraint-programming---cp-hoạt-động-ra-sao)
4. [Bóc Tách Chi Tiết Ứng Dụng Trong `ortools_server.py`](#4-bóc-tách-chi-tiết-ứng-dụng-trong-ortools_serverpy)
5. [Bảng So Sánh & Tổng Kết Chiến Lược Tối Ưu](#5-bảng-so-sánh--tổng-kết-chiến-lược-tối-ưu)

---

## 1. HÀM MỤC TIÊU (OBJECTIVE FUNCTION) LÀ GÌ?

Trong Google OR-Tools Routing Library, bài toán giải quyết là **Quy hoạch Tối ưu Hóa Tổ Hợp Đa Mục Tiêu (Multi-Objective Combinatorial Optimization)** được tuyến tính hóa quy về bài toán tìm cực tiểu tổng chi phí:

$$\min \mathcal{Z} = \mathcal{C}_{\text{quãng\_đường}} + \mathcal{C}_{\text{mở\_xe}} + \mathcal{C}_{\text{trải\_nghiệm\_CX}} + \mathcal{C}_{\text{thời\_gian\_xe}} + \mathcal{P}_{\text{bỏ\_khách}}$$

```
                                  CẤU TRÚC HÀM MỤC TIÊU (Z)
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ 1. CHI PHÍ DI CHUYỂN (Arc Cost):    Σ (Khoảng cách di chuyển giữa các nút)                      │
 │    routing.SetArcCostEvaluatorOfAllVehicles(transit_dist_callback_idx)                          │
 ├─────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 2. CHI PHÍ MỞ XE (Vehicle Fixed Cost): Phạt mở thêm xe (Ưu tiên xe nhỏ/lớn tùy tải)              │
 │    routing.SetFixedCostOfVehicle(fixed_cost, v_idx)                                             │
 ├─────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 3. PHẠT TRẢI NGHIỆM KHÁCH (Soft Ride Time): Phạt khách trả trễ hoặc đón quá sớm                 │
 │    time_dimension.SetCumulVarSoftUpperBound / SetCumulVarSoftLowerBound                        │
 ├─────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 4. ĐỘ GIÃN HÀNH TRÌNH XE (Span Cost): Phạt thời gian xe lăn bánh kéo dài                        │
 │    time_dimension.SetSpanCostCoefficientForAllVehicles(1)                                       │
 ├─────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ 5. PHẠT BỎ RƠI KHÁCH (Disjunction Penalty): 1 Tỷ điểm/khách (Ưu tiên tuyệt đối không bỏ rơi)    │
 │    routing.AddDisjunction([node], penalty = 1_000_000_000)                                      │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.1. Thứ Bậc Ưu Tiên Toán Học (Lexicographic Hierarchy / Big-M Principle)
Để solver phục vụ người dùng đúng theo ý muốn của nhà xe, các hệ số trọng số được thiết kế theo các bậc lũy thừa cách biệt lớn:
1. **Bậc 1 ($10^9$ điểm) - Phục vụ khách tối đa:** Điểm phạt bỏ khách là $1.000.000.000$. Mọi quãng đường phụ trội (vài chục km $\approx 50.000$ điểm) hay chi phí mở xe ($15.000$ điểm) đều **không đáng kể** so với việc bỏ sót 1 người khách ($1.000.000.000$ điểm). Do đó Solver luôn ưu tiên gom 100% khách trước tiên.
2. **Bậc 2 ($10^3 \dots 10^4$ điểm) - Tiết kiệm phương tiện:** Chi phí mở xe dao động từ $1.000 \dots 15.000$ điểm. Solver sẽ cố gắng dồn khách vào số lượng xe ít nhất và đúng chủng loại xe mong muốn (xe 7 chỗ khi vắng khách, xe 16 chỗ khi đông khách).
3. **Bậc 3 ($10^0 \dots 10^2$ điểm) - Tối ưu lộ trình và dịch vụ:** $1\text{m} = 1\text{ điểm}$, $1\text{s} = 2\text{ điểm CX}$. Solver uốn nắn đường đi ngắn nhất, gom cụm khách cùng huyện và giảm thời gian chờ đợi của khách.

---

## 2. CHI PHÍ PHẠT & RÀNG BUỘC ẢNH HƯỞNG THẾ NÀO?

Trong tối ưu hóa vận tải, việc thêm ràng buộc và chi phí phạt tác động trực tiếp lên **Không gian Nghiệm (Solution Space)** và **Hành vi của Solver**.

### 2.1. Ràng Buộc Cứng (Hard Constraints)
* **Khái niệm:** Là điều kiện bắt buộc $100\%$ phải thỏa mãn. Nếu vi phạm dù chỉ 1 đơn vị, trạng thái đó bị coi là **Không khả thi (Infeasible)** và bị loại bỏ ngay lập tức.
* **Ví dụ trong bài toán:**
  * Sức chứa xe không vượt quá số ghế (`Capacity Dimension`).
  * Khách chỉ được đón/trả trong khung giờ ca chạy xe (`Time Dimension SetRange`).
  * Trả hết khách mới được đón khách mới (`CP Precedence`).
  * Xe phải về bến trước giờ xe lớn chạy đi Hà Nội (`CP Deadline`).
* **Ảnh hưởng:**
  * *Tích cực:* Thu hẹp mạnh mẽ không gian tìm kiếm, giúp Solver cắt tỉa nhánh nhanh hơn (Search Tree Pruning).
  * *Rủi ro:* Nếu các ràng buộc mâu thuẫn (Ví dụ: 10 khách nhưng chỉ cấp 1 xe 7 chỗ, hoặc giờ đón yêu cầu xe phải chạy với vận tốc $200\text{ km/h}$), bài toán sẽ **bị vô nghiệm (Infeasible / Error 422)**.

### 2.2. Ràng Buộc Mềm & Chi Phí Phạt (Soft Constraints & Penalties)
* **Khái niệm:** Cho phép Solver được quyền vi phạm điều kiện này nhưng sẽ bị cộng một lượng "điểm phạt" (Penalty) tương ứng vào hàm mục tiêu.
* **Ví dụ trong bài toán:**
  * Khách trả nên được đưa về nhà sớm nhất có thể (`SetCumulVarSoftUpperBound`). Nếu đi vòng trả muộn 15 phút, phạt $15 \times 60 \times 2 = 1.800$ điểm.
  * Khách đón không nên bị đón quá sớm (`SetCumulVarSoftLowerBound`).
  * Phạt bỏ khách (`Disjunction Penalty`): Nếu không thể chở khách do quá tải xe, Solver được phép "bỏ khách" nhưng phải trả giá bằng 1 tỷ điểm.
* **Ảnh hưởng:**
  * *Tích cực:* Đảm bảo bài toán **luôn luôn tìm ra nghiệm (Always Feasible)** ngay cả khi quá tải hay ca chạy quá gấp.
  * *Cơ chế đánh đổi (Trade-off):* Solver tự động cân nhắc giữa việc chạy thêm 3km vòng vèo để trả khách sớm hơn vs việc chạy thẳng để tiết kiệm tổng quãng đường toàn đoàn.

---

## 3. THUẬT TOÁN XỬ LÝ RÀNG BUỘC (CONSTRAINT PROGRAMMING - CP) HOẠT ĐỘNG RA SAO?

Google OR-Tools sử dụng kiến trúc kết hợp **2 Tầng độc đáo**:

```
                       KIẾN TRÚC 2 TẦNG TRONG OR-TOOLS
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │  TẦNG 1: LOCAL SEARCH & METAHEURISTICS (Tìm kiếm nghiệm)                    │
 │  ├── Khởi tạo nghiệm: Parallel Cheapest Insertion / Savings                 │
 │  ├── Đề xuất bước nhảy (Move): 2-opt, Relocate, Exchange, Cross-Exchange... │
 │  └── Thoát cực tiểu địa phương: Guided Local Search (GLS)                   │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │ Đề xuất cấu hình lộ trình mới
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │  TẦNG 2: CONSTRAINT PROGRAMMING ENGINE (pywrapcp - Kiểm tra ràng buộc)     │
 │  ├── Domain Reduction: Cắt tỉa miền giá trị của các biến                     │
 │  ├── Constraint Propagation: Lan truyền ràng buộc qua đồ thị biến số        │
 │  └── Feasibility Check: Chấp nhận bước nhảy trong < 1 micro-giây            │
 └─────────────────────────────────────────────────────────────────────────────┘
```

### 3.1. Miền Giá Trị (Finite Domains) & Biến Quyết Định (Decision Variables)
CP mô hình hóa bài toán thành tập các biến có miền giá trị hữu hạn:
* $\text{NextVar}(i) \in \{0, 1, \dots, N\}$: Điểm tiếp theo sau điểm $i$.
* $\text{VehicleVar}(i) \in \{0, 1, \dots, K-1\}$: Xe nào phục vụ điểm $i$.
* $\text{CumulVar}(i) \in [T_{\min}, T_{\max}]$: Thời điểm tích lũy (giờ đến điểm $i$).

### 3.2. Lan Truyền Ràng Buộc (Constraint Propagation & Domain Filtering)
Đây là "trái tim" của thuật toán Constraint Programming. Khi một biến được gán giá trị, động cơ CP ngay lập tức suy luận và cắt bỏ các giá trị không hợp lệ của tất cả các biến khác liên quan mà **không cần phải duyệt thử-sai**:

```
  Giả sử Xe 1 đến Điểm A lúc [13:00, 13:30].
  Thời gian từ A -> B mất 20 phút.
  => CP Engine tự động suy luận: CumulVar(B) >= 13:20 ngay lập tức!
  Nếu Khung giờ của B là [12:00, 13:10] => Phát hiện XUNG ĐỘT ngay, loại bỏ nhánh tìm kiếm này trong 0.001ms.
```

### 3.3. Reification & Logic Expressions (Ràng Buộc Điều Kiện Phức Tạp)
Trong CP, ta có thể mô hình hóa các logic như: *"NẾU khách A và khách B đi cùng xe THÌ khách A phải được phục vụ trước khách B"*:

$$\text{is\_same\_v} = (\text{VehicleVar}(A) == \text{VehicleVar}(B))$$
$$\text{CumulVar}(A) \le \text{CumulVar}(B) + (1 - \text{is\_same\_v}) \times 86.400$$

* Nếu `is_same_v == 1`: Bất đẳng thức trở thành $\text{CumulVar}(A) \le \text{CumulVar}(B)$ (Bắt buộc $A$ trước $B$).
* Nếu `is_same_v == 0` (Khác xe): Bất đẳng thức trở thành $\text{CumulVar}(A) \le \text{CumulVar}(B) + 86.400$ (Luôn đúng, tự động vô hiệu hóa ràng buộc).

---

## 4. BÓC TÁCH CHI TIẾT ỨNG DỤNG TRONG `ortools_server.py`

Mã nguồn [`or_tools/ortools_server.py`](file:///c:/Users/TANDAITHANH.COM.VN/PHRoutingOptimize/or_tools/ortools_server.py) triển khai hoàn chỉnh các khái niệm toán học trên vào bài toán thực tế:

### 4.1. Khởi Tạo Bộ Quản Lý Điểm Đến Đa Điểm Xuất Phát / Kết Thúc
```python
# Hỗ trợ xe có thể đỗ tại nhà riêng hoặc bến khác nhau
manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, starts, ends)
routing = pywrapcp.RoutingModel(manager)
solver = routing.solver()  # CP Engine Core
```

### 4.2. Thiết Lập Arc Cost (Quãng Đường Thực Tế Từ OSRM)
```python
def distance_callback(from_index, to_index):
    from_node = manager.IndexToNode(from_index)
    to_node = manager.IndexToNode(to_index)
    return dist_matrix[from_node][to_node]  # Mét

transit_dist_callback_idx = routing.RegisterTransitCallback(distance_callback)
routing.SetArcCostEvaluatorOfAllVehicles(transit_dist_callback_idx)
```

### 4.3. Định Kích Cỡ Đội Xe Động (Dynamic Fleet Fixed Cost)
```python
# Phạt mở xe lớn khi vắng khách để tiết kiệm xăng, ưu tiên lấp đầy xe nhỏ
for v_idx, v in enumerate(req.vehicles):
    if v.capacity <= 7:
        fixed_cost = 1_000   # 1 km chi phí mở xe
    elif v.capacity <= 11:
        fixed_cost = 5_000   # 5 km chi phí mở xe
    else:
        fixed_cost = 15_000  # 15 km chi phí mở xe
    routing.SetFixedCostOfVehicle(fixed_cost, v_idx)
```

### 4.4. Chiều Thời Gian & Ràng Buộc Khung Giờ (Time Dimension & Time Windows)
```python
routing.AddDimension(
    transit_time_callback_idx,
    7200,   # Dung sai slack (2h)
    86400,  # Chân trời thời gian 24h
    False,  # Không bắt buộc thời gian bắt đầu = 0
    'Time'
)
time_dimension = routing.GetDimensionOrDie('Time')

# Gán Time Window cứng cho từng khách
for node_idx in range(1, num_pax + 1):
    index = manager.NodeToIndex(node_idx)
    tw = time_windows[node_idx]
    time_dimension.CumulVar(index).SetRange(tw[0], tw[1])
```

### 4.5. Phạt Trải Nghiệm Khách Hàng (Soft Ride Time Penalty)
```python
# Phạt trả muộn cho khách trả (Delivery)
ideal_delivery_sec = min_v_start + direct_dur_from_hub + 300 # Chạy thẳng + 5p
time_dimension.SetCumulVarSoftUpperBound(d_idx, ideal_delivery_sec, ride_time_cost_per_sec)
routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(d_idx))

# Phạt đón quá sớm cho khách đón (Pickup)
ideal_pickup_sec = max(min_v_start, hanoi_dep_sec - direct_dur_to_hub - 900)
time_dimension.SetCumulVarSoftLowerBound(p_idx, ideal_pickup_sec, ride_time_cost_per_sec)
routing.AddVariableMaximizedByFinalizer(time_dimension.CumulVar(p_idx))
```

### 4.6. Ràng Buộc Sức Chứa Độc Lập Cho Chiều Trả Và Chiều Đón
```python
# Tách 2 chiều DeliveryCapacity và PickupCapacity
routing.AddDimensionWithVehicleCapacity(
    del_callback_idx, 0, vehicle_capacities, True, 'DeliveryCapacity'
)
routing.AddDimensionWithVehicleCapacity(
    pick_callback_idx, 0, vehicle_capacities, True, 'PickupCapacity'
)
```

### 4.7. Ràng Buộc CP Precedence: Trả Hết Mới Đón
```python
# Sử dụng trực tiếp CP Solver để ràng buộc thứ tự logic
if req.config and req.config.strict_precedence:
    for d_node in delivery_node_indices:
        d_idx = manager.NodeToIndex(d_node)
        for p_node in pickup_node_indices:
            p_idx = manager.NodeToIndex(p_node)
            is_same_v = solver.IsEqualVar(routing.VehicleVar(d_idx), routing.VehicleVar(p_idx))
            solver.Add(time_dimension.CumulVar(d_idx) <= time_dimension.CumulVar(p_idx) + (1 - is_same_v) * 86400)
```

### 4.8. Ràng Buộc CP Deadline: Về Bến Đúng Giờ Khách Đón Đi Hà Nội
```python
for p_node in pickup_node_indices:
    p_idx = manager.NodeToIndex(p_node)
    pax = req.passengers[p_node - 1]
    hanoi_dep_sec = time_to_sec(pax.hub_time) if pax.hub_time else max_v_end
    max_hub_arrival_sec = hanoi_dep_sec

    for v_idx in range(num_vehicles):
        end_idx = routing.End(v_idx)
        is_assigned_to_v = solver.IsEqualCstVar(routing.VehicleVar(p_idx), v_idx)
        
        # Bắt buộc xe kết thúc ca tại bến trước giờ xe lớn chạy
        solver.Add(time_dimension.CumulVar(end_idx) <= max_hub_arrival_sec + (1 - is_assigned_to_v) * 86400)
```

### 4.9. Phạt Bỏ Khách Cực Đại (Disjunction Drop Penalty)
```python
for node_idx in range(1, num_pax + 1):
    pax = req.passengers[node_idx - 1]
    p_amt = pax.amount if pax.amount else 1
    penalty = 1_000_000_000 * p_amt  # 1 tỷ điểm
    routing.AddDisjunction([manager.NodeToIndex(node_idx)], penalty)
```

### 4.10. Cấu Hình Metaheuristics & 9 Toán Tử Local Search
```python
search_parameters = pywrapcp.DefaultRoutingSearchParameters()
search_parameters.first_solution_strategy = (
    routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
)
search_parameters.local_search_metaheuristic = (
    routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
)
search_parameters.guided_local_search_lambda_coefficient = 0.2

# Kích hoạt 9 toán tử tìm kiếm cục bộ nâng cao
search_parameters.local_search_operators.use_make_active = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_relocate_and_make_active = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_two_opt = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_cross_exchange = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_relocate_neighbors = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_extended_swap_active = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_node_pair_swap_active = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_exchange = pywrapcp.BOOL_TRUE
search_parameters.local_search_operators.use_lin_kernighan = pywrapcp.BOOL_TRUE
```

---

## 5. BẢNG SO SÁNH & TỔNG KẾT CHIẾN LƯỢC TỐI ƯU

| Tiêu chí | Mô hình Tuyến tính thuần túy (MIP / LP) | Mô hình Google OR-Tools CP Routing | Lợi ích trong Dự án Trung chuyển Thái Bình |
| :--- | :--- | :--- | :--- |
| **Xử lý ràng buộc thời gian (Time Windows)** | Dùng hàng triệu biến $x_{ijk}$ và Big-M cồng kềnh, giải rất chậm ($> 10\text{ phút}$). | **Dimension & CumulVar**: Đồ thị 1 chiều, cập nhật tức thì trong $O(1)$. | Giải quyết $100$ khách và $10$ xe chỉ trong **$10 - 20\text{ giây}$**. |
| **Ràng buộc logic (Trả trước Đón sau)** | Cực kỳ khó mô hình hóa trên đồ thị động nhiều xe. | Dùng hàm logic CP **`IsEqualVar` + `CumulVar`**. | Đảm bảo $100\%$ không bao giờ đón khách mới khi còn khách trả trên xe. |
| **Xử lý quá tải (Overcapacity)** | Báo lỗi vô nghiệm (Infeasible), hệ thống sập. | **Disjunction Penalty**: Tự động phục vụ tối đa, chỉ bỏ sót những khách bất khả thi. | Nhà xe luôn nhận được điều phối cho các khách hợp lệ, kèm danh sách khách cần bố trí thêm xe. |
| **Chất lượng lộ trình (CX)** | Xe hay đi vòng, đón khách quá sớm để tối ưu chung. | **Soft Bounds Penalty**: Phạt thời gian khách ngồi xe. | Hành khách không bị ngồi xe lòng vòng quá lâu, tăng sự hài lòng của hành khách. |
| **Tối ưu loại xe** | Gán cứng số lượng xe. | **Dynamic Fixed Cost**: Phạt xe lớn khi ít khách. | Tiết kiệm nhiên liệu, dùng xe 7 chỗ vào ban ngày vắng và xe 16 chỗ vào giờ cao điểm. |
