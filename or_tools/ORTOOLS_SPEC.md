# TÀI LIỆU KỸ THUẬT VÀ MÔ HÌNH TOÁN HỌC GOOGLE OR-TOOLS (CP ENGINE)
**Dự án**: Hệ thống Điều phối & Tối ưu hóa Xe Trung Chuyển Thái Bình (`PHRoutingOptimize`)  
**Tệp nguồn**: [`or_tools/ortools_server.py`](file:///c:/Users/TANDAITHANH.COM.VN/PHRoutingOptimize/or_tools/ortools_server.py)  
**Phiên bản Engine**: 2.1.0  
**Tác giả**: WeMap Dispatching Engine Team  

---

## 1. Tổng Quan Kiến Trúc Kỹ Thuật (Technical Architecture)

Hệ thống điều phối xe trung chuyển tuyến Thái Bình ⇄ Hà Nội được thiết kế dựa trên sự kết hợp giữa **Google OR-Tools Routing Library** và **Constraint Programming Solver (CP Engine)**:

```
                                  KIẾN TRÚC TỔNG THỂ
                                  
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                       UnifiedOptimizationRequest                            │
 │     (Bến Hub, Danh sách Xe & Ca chạy, Danh sách Khách Đón/Trả, Config)      │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                Ma Trận Khoảng Cách & Thời Gian (Distance/Duration)          │
 │       OSRM Table API (Thực tế) ──Fallback──> Haversine (Detour x1.35)       │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │             Mô Hình Lập Trình Ràng Buộc (OR-Tools CP Routing Model)         │
 │  ├── Arc Cost: Quãng đường thực tế (Mét)                                    │
 │  ├── Dynamic Fixed Cost: Chi phí mở xe động theo dung lượng khách           │
 │  ├── Time Dimension: Khung giờ đón/trả, ca xe, Soft CX Ride Time Penalty    │
 │  ├── Capacity Dimension: Sức chứa xe chiều Trả (Delivery) & Đón (Pickup)    │
 │  ├── CP Constraints: Ràng buộc Precedence (Trả trước Đón sau)               │
 │  ├── CP Constraints: Deadline về bến đúng giờ cho khách đón đi Hà Nội       │
 │  └── Disjunction Penalty: Phạt 1 tỷ điểm/khách để phục vụ tối đa khách      │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │            Thuật Toán Tìm Kiếm Sâu & Metaheuristics (GLS Engine)            │
 │   Parallel Cheapest Insertion ──> Guided Local Search (9 Operators, 30s)    │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                       UnifiedOptimizationResponse                           │
 │     (Lộ trình chi tiết từng xe, Tải trọng tức thời, GeoJSON, KPI Summary)   │
 └─────────────────────────────────────────────────────────────────────────────┘
```

### Các thành phần cốt lõi:
1. **Routing Index Manager (`pywrapcp.RoutingIndexManager`)**:
   - Quản lý ánh xạ chỉ số giữa các nút khách hàng ($1 \dots N$), nút Bến xe trung tâm (Nút $0$) và các điểm xuất phát/kết thúc độc lập của từng xe (`starts`, `ends`).
2. **Routing Model (`pywrapcp.RoutingModel`)**:
   - Quản lý đồ thị di chuyển, chi phí cạnh (Arc Costs), chi phí mở xe (Fixed Costs) và biến quyết định gán xe (`VehicleVar`), biến thứ tự ghé thăm (`NextVar`).
3. **CP Solver (`solver = routing.solver()`)**:
   - Thực thi các ràng buộc logic phức tạp (Logical Constraints, Implication, Reification) mà mô hình Routing thuần túy không thể giải trực tiếp.
4. **Bộ tính toán Ma trận Cự ly / Thời gian**:
   - **OSRM Table Service**: Gọi API mạng lưới đường thực tế tại `OSRM_URL`.
   - **Haversine Fallback**: Tự động kích hoạt khi OSRM không phản hồi, áp dụng hệ số uốn khúc nông thôn Thái Bình $1.35$ và vận tốc trung bình $38 \text{ km/h}$ ($\approx 10.55 \text{ m/s}$).

---

## 2. Hệ Thống Ràng Buộc Thời Gian (Time Constraints & Time Windows)

Chiều thời gian được khởi tạo bằng `routing.AddDimension()` với chân trời thời gian $86.400 \text{ giây}$ ($24\text{h}$) và dung sai (`Slack = 7.200 \text{ giây} = 2\text{h}`):

$$\text{CumulVar}(j) \ge \text{CumulVar}(i) + \text{Duration}(i, j) + \text{ServiceDuration}(i)$$

### 2.1. Khung thời gian Khách Trả (Delivery Time Windows)
Khách đi từ Hà Nội về bến trung tâm lúc `p.hub_time` ($T_{\text{hub\_arr}}$):
- **Thời điểm sớm nhất có thể phục vụ ($T_{\min}$)**:
  $$T_{\min} = \max\left(T_{\text{ca\_xe\_bắt\_đầu}}, T_{\text{hub\_arr}}\right)$$
- **Thời điểm muộn nhất ($T_{\max}$)**:
  $$T_{\max} = \max\left(T_{\min}, T_{\text{ca\_xe\_kết\_thúc}}\right)$$
- **Ý nghĩa**: Xe chỉ có thể nhận khách sau khi xe lớn từ Hà Nội đã cập bến. Khách được trả tận nhà trong suốt ca chạy nhưng luôn ưu tiên trả sớm.

### 2.2. Khung thời gian Khách Đón (Pickup Time Windows)
Khách cần đón từ nhà để kịp chuyến xe lớn đi Hà Nội lúc `p.hub_time` ($T_{\text{hanoi\_dep}}$):
- **Thời điểm đón sớm nhất ($T_{\min}$)**: $T_{\text{ca\_xe\_bắt\_đầu}}$.
- **Thời điểm đón muộn nhất ($T_{\max}$)**:
  $$T_{\max} = \max\left(T_{\min}, \min\left(T_{\text{ca\_xe\_kết\_thúc}}, T_{\text{hanoi\_dep}} - \text{DirectDuration}(\text{nhà}, \text{bến})\right)\right)$$
- **Ý nghĩa**: Đảm bảo giờ đón không bao giờ trễ hơn mốc thời gian chạy thẳng về bến.

### 2.3. Khung thời gian Ca chạy của Xe (Vehicle Shifts)
Mỗi xe $v$ có ca làm việc $[T_{\text{v\_start}}, T_{\text{v\_end}}]$ (thường là 2 tiếng, ví dụ 13:45 – 15:45):
- $\text{CumulVar}(\text{Start}_v) \in [T_{\text{v\_start}}, T_{\text{v\_end}}]$
- $\text{CumulVar}(\text{End}_v) \in [T_{\text{v\_start}}, T_{\text{v\_end}}]$

### 2.4. Ràng buộc CP Deadline về Bến Trung Tâm cho Khách Đón
Mọi hành khách đón $p$ được xếp lên xe $v$ đều yêu cầu xe $v$ phải kết thúc hành trình tại bến trước hoặc đúng giờ xe lớn xuất bến:

$$\text{is\_assigned\_to\_v} = (\text{VehicleVar}(p) == v)$$
$$\text{CumulVar}(\text{End}_v) \le T_{\text{hanoi\_dep}}(p) + (1 - \text{is\_assigned\_to\_v}) \times 86.400$$

*(Sử dụng kỹ thuật Big-M $86.400$ để chỉ áp dụng ràng buộc khi khách $p$ thực sự đi xe $v$).*

### 2.5. Ràng buộc CP Precedence Tuyệt Đối (Trả Hết Khách Mới Đón Khách)
Trên cùng một xe $v$, tất cả các điểm Trả khách ($d \in \text{Delivery}$) phải được hoàn thành trước khi xe bắt đầu đón bất kỳ khách nào ($p \in \text{Pickup}$):

$$\text{VehicleVar}(d) == \text{VehicleVar}(p) \implies \text{CumulVar}(d) \le \text{CumulVar}(p)$$

Trong mã nguồn:
```python
is_same_v = solver.IsEqualVar(routing.VehicleVar(d_idx), routing.VehicleVar(p_idx))
solver.Add(time_dimension.CumulVar(d_idx) <= time_dimension.CumulVar(p_idx) + (1 - is_same_v) * 86400)
```

---

## 3. Hệ Thống Chi Phí & Điểm Phạt (Objective Function & Penalties)

Hàm mục tiêu tổng quát của bộ giải tối ưu:

$$\min \Big( \mathcal{F}_{\text{quãng đường}} + \mathcal{F}_{\text{mở xe}} + \mathcal{F}_{\text{trải nghiệm CX}} + \mathcal{F}_{\text{thời gian xe}} + \mathcal{F}_{\text{phạt bỏ khách}} \Big)$$

```
                               CẤU TRÚC ĐIỂM PHẠT
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ P0 (Ưu tiên tuyệt đối): Disjunction Penalty (1.000.000.000 điểm / khách)    │
 │    └─ Phục vụ 100% hành khách, không bỏ rơi khách vì chi phí km             │
 ├─────────────────────────────────────────────────────────────────────────────┤
 │ P1 (Quy mô đội xe): Dynamic Fixed Cost (0 - 15.000 điểm / xe)               │
 │    └─ Tải thấp: Đi xe 7C | Tải vừa: Đi 16C | Cao điểm: Bung toàn bộ 10 xe   │
 ├─────────────────────────────────────────────────────────────────────────────┤
 │ P2 (Hạ tầng giao thông): Arc Transit Distance Cost (1 điểm / 1 mét)         │
 │    └─ Rút ngắn tổng quãng đường di chuyển của toàn đội xe                   │
 ├─────────────────────────────────────────────────────────────────────────────┤
 │ P3 (Trải nghiệm khách): Soft In-Vehicle Ride Time Penalty (2 điểm / giây)   │
 │    └─ Trả khách càng sớm càng tốt, đón khách càng sát giờ càng tốt          │
 ├─────────────────────────────────────────────────────────────────────────────┤
 │ P4 (Hiệu suất vận hành): Vehicle Global Span Cost (1 điểm / giây ca xe)     │
 │    └─ Giảm thiểu tổng thời gian xe lăn bánh trên đường                      │
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

### Chi tiết các hệ số chi phí và điểm phạt:

### 3.1. Chi phí Quãng đường Di chuyển (Arc Transit Cost)
- **Hệ số quy đổi**: $1 \text{ mét} = 1 \text{ điểm chi phí}$.
- **Cơ chế**: `routing.SetArcCostEvaluatorOfAllVehicles(transit_dist_callback_idx)`.
- **Mục tiêu**: Hạn chế xe chạy đường vòng, tối ưu tuyến đường ngắn nhất.

### 3.2. Chi phí Mở xe Động (Dynamic Fleet Right-Sizing Fixed Costs)
Chi phí mở xe được tự động điều chỉnh theo tổng dung lượng khách của ca chạy:

| Kịch bản nhu cầu | Số lượng khách | Xe 7 chỗ | Xe 11 chỗ | Xe 16 chỗ | Chiến thuật điều phối |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 🟢 **Thấp điểm** | $\le 14$ khách | **$1.000$** ($1\text{km}$) | **$5.000$** ($5\text{km}$) | **$15.000$** ($15\text{km}$) | Ưu tiên dùng xe nhỏ (7C), hạn chế xe 16C lãng phí nhiên liệu. |
| 🟡 **Trung bình** | $15 - 40$ khách | **$6.000$** ($6\text{km}$) | **$3.000$** ($3\text{km}$) | **$1.000$** ($1\text{km}$) | Ưu tiên lấp đầy 1-2 xe 16C lớn trước khi mở thêm xe nhỏ. |
| 🔴 **Cao điểm / Quá tải** | $> 40$ khách | **$200$** | **$100$** | **$0$** | Giảm chi phí mở xe về $\sim 0$ để solver thoải mái kích hoạt cả 10 xe. |

### 3.3. Điểm Phạt Mềm Thời Gian Khách Ngồi Trên Xe (Soft In-Vehicle Ride Time Penalty)
Tối ưu trải nghiệm khách hàng (Customer Experience - CX) bằng cơ chế **Soft Upper Bound** và **Soft Lower Bound** mà không làm bó hẹp không gian nghiệm khả thi:
- **Hệ số phạt**: `ride_time_cost_per_sec = 2` ($2 \text{ điểm} / 1 \text{ giây} = 7.200 \text{ điểm} / 1 \text{ giờ}$ ngồi xe vượt mốc lý tưởng).

#### a. Khách Trả (Delivery):
- **Thời điểm trả lý tưởng**:
  $$T_{\text{ideal\_del}} = T_{\text{v\_start}} + \text{Duration}(\text{Bến} \rightarrow \text{Nhà}) + 300 \text{ giây (5 phút đệm)}$$
- **Hàm phạt**: $\text{Penalty} = \max\left(0, \text{CumulVar}(d) - T_{\text{ideal\_del}}\right) \times 2$.
- **Cơ chế**: `time_dimension.SetCumulVarSoftUpperBound(d_idx, ideal_delivery_sec, 2)` kết hợp `routing.AddVariableMinimizedByFinalizer`.

#### b. Khách Đón (Pickup):
- **Thời điểm đón lý tưởng**:
  $$T_{\text{ideal\_pick}} = \max\left(T_{\text{v\_start}}, T_{\text{hanoi\_dep}} - \text{Duration}(\text{Nhà} \rightarrow \text{Bến}) - 900 \text{ giây (15 phút đệm)}\right)$$
- **Hàm phạt**: $\text{Penalty} = \max\left(0, T_{\text{ideal\_pick}} - \text{CumulVar}(p)\right) \times 2$.
- **Cơ chế**: `time_dimension.SetCumulVarSoftLowerBound(p_idx, ideal_pickup_sec, 2)` kết hợp `routing.AddVariableMaximizedByFinalizer`.

### 3.4. Điểm Phạt Độ Giãn Hành Trình Toàn Xe (Global Span Cost)
- **Hệ số**: $1 \text{ điểm} / 1 \text{ giây}$.
- **Cơ chế**: `time_dimension.SetSpanCostCoefficientForAllVehicles(1)`.
- **Mục đích**: Phạt độ dài tổng thời gian từ lúc xe xuất bến đến khi về bến $(\text{End}_v - \text{Start}_v)$, thúc đẩy xe kết thúc lộ trình sớm để nghỉ ngơi.

### 3.5. Điểm Phạt Bỏ Sót Hành Khách (Disjunction Drop Penalty)
- **Mức phạt**: **$1.000.000.000 \times \text{amount}$** ($1 \text{ tỷ điểm} / \text{người}$).
- **Cơ chế**: `routing.AddDisjunction([manager.NodeToIndex(node_idx)], penalty)`.
- **Ý nghĩa**: Vì quãng đường chạy xa nhất chỉ tốn khoảng $100.000 \text{ mét} = 100.000 \text{ điểm}$, mức phạt $1 \text{ tỷ điểm}$ buộc solver luôn ưu tiên phục vụ hành khách lên vị trí cao nhất. Khách chỉ bị bỏ sót khi vượt quá giới hạn sức chứa hoặc vượt quá khung giờ ca chạy $120 \text{ phút}$.

---

## 4. Ràng Buộc Sức Chứa (Capacity Dimensions)

Mô hình tách biệt 2 chiều tải trọng độc lập để kiểm soát chặt chẽ trạng thái chở khách:
1. **`DeliveryCapacity`**:
   - Khởi tạo tải trọng khi xe rời bến bằng tổng số khách Trả trên xe ($\sum \text{pax}_{\text{del}} \le \text{Capacity}_v$).
   - Tại mỗi điểm trả khách: Giảm tải tương ứng với số vé của khách.
2. **`PickupCapacity`**:
   - Khởi tạo tải trọng bằng $0$ khi bắt đầu giai đoạn đón.
   - Tại mỗi điểm đón khách: Tăng tải tương ứng và đảm bảo tổng số khách đón khi về bến $\le \text{Capacity}_v$.

---

## 5. Chiến Lược Giải Toán & Metaheuristics (Guided Local Search)

### 5.1. Thuật toán tìm nghiệm ban đầu (First Solution Strategy)
- `PARALLEL_CHEAPEST_INSERTION`: Chèn đồng thời các điểm vào nhiều lộ trình xe, giúp cân bằng tải giữa các xe ngay từ bước khởi tạo.

### 5.2. Metaheuristic: Guided Local Search (GLS)
- Thuật toán `GUIDED_LOCAL_SEARCH` với hệ số phạt cực tiểu $\lambda = 0.2$. Khi solver bị kẹt ở nghiệm cực tiểu cục bộ, GLS tự động phạt các cạnh trong nghiệm hiện tại để ép solver khám phá các cấu hình phân xe mới.

### 5.3. Kích hoạt toàn bộ 9 Toán tử Local Search nâng cao:
1. `use_make_active`: Đưa khách đang bị bỏ rơi vào lộ trình xe.
2. `use_relocate_and_make_active`: Chuyển điểm giữa các xe đồng thời kích hoạt điểm mới.
3. `use_two_opt`: Đảo đoạn đường để khử các điểm giao cắt chéo.
4. `use_cross_exchange`: Hoán đổi 2 đoạn lộ trình giữa 2 xe khác nhau.
5. `use_relocate_neighbors`: Di chuyển cụm điểm lân cận sang xe khác.
6. `use_extended_swap_active`: Hoán đổi vị trí các điểm đã được gán.
7. `use_node_pair_swap_active`: Hoán đổi cặp điểm liền kề.
8. `use_exchange`: Đổi chỗ 2 điểm đơn lẻ giữa 2 xe.
9. `use_lin_kernighan`: Tối ưu hóa chu trình đường đi phức tạp.

### 5.4. Dynamic Time Limit Phân Cấp (Ngân sách lên tới 30 giây)
- $\le 15$ khách: **$5\text{s}$** (Quét sạch không gian hoán vị xe nhỏ).
- $16 - 40$ khách: **$10\text{s}$** (Gom cụm và nắn thẳng các trục huyện).
- $41 - 80$ khách: **$20\text{s}$** (Vượt qua các điểm cực tiểu cục bộ phức tạp).
- $> 80$ khách: **$30\text{s}$** (Cao điểm/Quá tải: tối đa hóa $100\%$ tỷ lệ phục vụ và giảm km).

### 5.5. Cơ chế Fallback 2 tầng
Nếu chiến lược khởi tạo ban đầu gặp trường hợp khó không ra nghiệm:
1. **Fallback 1**: Tự động thử `SAVINGS` Strategy.
2. **Fallback 2**: Tự động thử `PATH_CHEAPEST_ARC` Strategy.
