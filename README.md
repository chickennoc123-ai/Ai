# EA Factory Pro

Nền tảng giao dịch thống nhất cho **vàng và ngoại hối** (XAUUSD, EURUSD, USDJPY,
GBPUSD, AUDUSD): nghiên cứu chiến lược bằng đa tác nhân AI, kiểm định thống kê
nghiêm ngặt, thực thi lệnh qua XMTrading và giám sát rủi ro thời gian thực.

```
Nghiên cứu  →  Kiểm thử  →  Kiểm định  →  Phân bổ vốn  →  Thực thi  →  Giám sát
(Research)     (Backtest)    (WFA/PBO)     (Kelly)        (XM)        (Risk/Meta)
```

---

## 1. Khởi chạy nhanh

### 1.1. Chạy toàn bộ hệ thống bằng Docker

```bash
git clone <repository-url> ea-factory-pro
cd ea-factory-pro
cp .env.example .env          # không cần sửa gì để chạy thử
docker-compose up -d
```

| Dịch vụ | Địa chỉ | Ghi chú |
|---|---|---|
| Bảng điều khiển | http://localhost:8501 | Giao diện Streamlit, 6 trang |
| API + tài liệu | http://localhost:8000/docs | OpenAPI/Swagger tự sinh |
| Kiểm tra sức khoẻ | http://localhost:8000/health | Trạng thái mọi thành phần |
| Prometheus | http://localhost:8000/metrics | Số liệu giám sát |
| InfluxDB | http://localhost:8086 | Dữ liệu chuỗi thời gian |

Kiểm tra và theo dõi:

```bash
docker-compose ps
docker-compose logs -f worker      # nhật ký các tác nhân AI
docker-compose down                # dừng (giữ dữ liệu)
docker-compose down -v             # dừng và xoá toàn bộ dữ liệu
```

### 1.2. Chạy trực tiếp bằng Python (không cần Docker)

Hệ thống tự động chuyển sang SQLite và message bus nội bộ khi không có
PostgreSQL/Redis, nên chạy trên máy cá nhân không cần cài thêm gì:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python scripts/init_db.py            # tạo bảng
python scripts/seed_data.py          # nạp dữ liệu mẫu

uvicorn api.main:app --reload        # cửa sổ 1: API + tác nhân
streamlit run dashboard/app.py       # cửa sổ 2: bảng điều khiển
```

Hoặc dùng `make`:

```bash
make help        # xem mọi lệnh
make up          # chạy toàn bộ bằng Docker
make api         # chạy API cục bộ
make worker      # chạy riêng cụm tác nhân
make dashboard   # chạy bảng điều khiển
make test        # chạy bộ kiểm thử
make pipeline    # chạy toàn bộ quy trình nghiên cứu và in báo cáo
```

---

## 2. Những điều cần biết trước khi dùng

Ba điểm dưới đây quyết định cách bạn diễn giải mọi con số trên bảng điều khiển.

### 2.1. Chế độ mô phỏng là mặc định

XMTrading **không công bố REST API giao dịch công khai**. Vì vậy tầng broker có
hai chế độ, chọn bằng biến `XM_MODE`:

| Chế độ | Ý nghĩa |
|---|---|
| `simulated` *(mặc định)* | Engine khớp lệnh nội bộ đầy đủ: báo giá hai chiều, spread, trượt giá, lệnh chờ, SL/TP, ký quỹ, swap, margin call. Không cần tài khoản, không có tiền thật. |
| `rest` | Gọi tới một cổng REST/WebSocket tương thích XM do bạn tự dựng (ví dụ dịch vụ FastAPI bọc thư viện `MetaTrader5`). Xem hợp đồng API ở mục 7. |

Toàn bộ phần còn lại của hệ thống không biết nó đang nói chuyện với engine mô
phỏng hay sàn thật — cùng một lớp `XMConnection`, cùng một luồng lệnh.

### 2.2. Dữ liệu giá mặc định là dữ liệu tổng hợp

Nhà cung cấp mặc định (`data.default_provider: simulated`) sinh chuỗi giá tất
định từ mô hình có cụm biến động (GARCH), xen kẽ giai đoạn xu hướng và giai
đoạn hồi quy trung bình, kèm cú sốc tin tức. Dữ liệu này **không chứa lợi thế
giao dịch bền vững**, và đó là chủ ý: nó cho phép chạy thử toàn hệ thống, đồng
thời để cổng kiểm định chứng minh nó biết **từ chối** những chiến lược không có
lợi thế thật.

> **Vì vậy: nếu chạy quy trình nghiên cứu trên dữ liệu mặc định và thấy "0 chiến
> lược được cấp vốn", đó là hệ thống đang hoạt động đúng.** Muốn có kết luận
> thật, hãy chuyển sang dữ liệu thật (mục 4.3).

### 2.3. Chi phí giao dịch đã được hiệu chỉnh so với bản mô tả ban đầu

Bản đặc tả đề xuất `commission: 0.0004` và `slippage: 0.0002` (tính theo tỷ lệ
notional/giá). Với EURUSD, mức đó tương đương **khoảng 40 USD phí mỗi lot mỗi
chiều và 2 pip trượt giá** — cao hơn thực tế khoảng 40 lần, đủ để mọi chiến
lược trong ngày đều lỗ bất kể chất lượng tín hiệu. Cấu hình mặc định đã đổi
thành:

```yaml
backtest:
  commission: 0.00007   # ~3.5 USD/lot/chiều, tương đương tài khoản XM Zero
  slippage:   0.00002   # ~0.2 pip
```

Bạn có thể tăng lại bất cứ lúc nào trong `config.yaml` hoặc theo từng lần chạy
qua API để kiểm tra sức chịu đựng chi phí của chiến lược.

---

## 3. Kiến trúc

```
┌──────────────────────────────────────────────────────────────────────┐
│  BẢNG ĐIỀU KHIỂN (Streamlit, cổng 8501)                              │
│  Tổng quan · Thị trường · Chiến lược · Rủi ro · Kiểm định · Cấu hình  │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ REST + WebSocket
┌────────────────────────────────▼─────────────────────────────────────┐
│  API (FastAPI, cổng 8000)                                            │
│  routers: account · orders · positions · strategies · backtest ·     │
│           validation · market · system      + /api/v1/ws             │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────┐
│  CỤM TÁC NHÂN AI (worker)                                            │
│  Research · Analysis · Execution · Risk · Meta                       │
│                    ↕ Message Bus (Redis Pub/Sub, dự phòng in-memory) │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────┐
│  LÕI HỆ THỐNG                                                        │
│  DataManager · Indicators · Strategy Registry (17) · BacktestEngine  │
│  ValidationSuite (WFA/PBO/Calibration/Robustness)                    │
│  LifecycleManager · DecisionEngine (Kelly có phạt bất định)          │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────┐
│  XMTRADING: XMConnection · XMAccount · XMOrders · XMPositions ·      │
│             XMWebSocket        (simulated | rest)                    │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────┐
│  LƯU TRỮ: PostgreSQL (giao dịch, chiến lược, audit) ·                │
│           InfluxDB (tick, OHLCV, metric) · Redis (bus, cache)        │
└──────────────────────────────────────────────────────────────────────┘
```

**Nguyên tắc suy giảm mềm (graceful degradation):** thiếu Redis → dùng bus
in-memory; thiếu PostgreSQL → dùng SQLite; thiếu InfluxDB → bỏ qua ghi chuỗi
thời gian; thiếu khoá LLM → dùng bộ sinh mã cục bộ. Hệ thống luôn chạy được,
chỉ mất tính năng phụ trợ.

---

## 4. Cấu hình

### 4.1. Hai lớp cấu hình

1. `config.yaml` — toàn bộ tham số vận hành, hỗ trợ nội suy biến môi trường
   dạng `${BIEN}` hoặc `${BIEN:-giá_trị_mặc_định}`.
2. `.env` — bí mật và thông tin theo môi trường. **Không bao giờ commit `.env`.**

### 4.2. Kết nối tài khoản XMTrading thật

```env
XM_MODE=rest
XM_DEMO=true                       # luôn thử demo trước
XM_ACCOUNT_ID=1234567
XM_PASSWORD=mat_khau_cua_ban
XM_SERVER=XMGlobal-Demo
XM_REST_URL=https://<cong-giao-dich-cua-ban>/api
XM_WS_URL=wss://<cong-giao-dich-cua-ban>/ws
```

### 4.3. Dùng dữ liệu lịch sử thật

```yaml
data:
  default_provider: "alphavantage"   # hoặc "csv"
  providers:
    alphavantage:
      api_key: "${ALPHAVANTAGE_API_KEY}"
    csv:
      directory: "data/csv"          # tệp <SYMBOL>_<TIMEFRAME>.csv
```

Tệp CSV cần các cột `timestamp,open,high,low,close,volume`. Khi nhà cung cấp
chính lỗi, hệ thống tự động lùi về dữ liệu mô phỏng và ghi cảnh báo.

### 4.4. Bật mô hình ngôn ngữ cho Research Agent

```env
LLM_PROVIDER=anthropic       # anthropic | openai | ollama | heuristic
ANTHROPIC_API_KEY=sk-ant-...
```

Không cấu hình khoá thì Research Agent vẫn hoạt động: nó dùng bộ tổng hợp mã
cục bộ (mẫu chiến lược + tham số ngẫu nhiên) thay cho LLM.

---

## 5. Năm tác nhân AI

| Tác nhân | Chu kỳ mặc định | Nhiệm vụ | Đầu ra trên bus |
|---|---|---|---|
| **Research** | 1 giờ | Tiến hoá tham số + sinh chiến lược mới (LLM hoặc mẫu cục bộ), chấm điểm bằng kiểm định nhanh | `RESEARCH_FINDING` |
| **Analysis** | 60 giây | Tính chỉ báo, nhận diện chế độ thị trường, tổng hợp tín hiệu có trọng số theo độ tin cậy | `SIGNAL`, `MARKET_UPDATE` |
| **Execution** | 15 giây | Kiểm soát giới hạn vị thế, tính khối lượng, định tuyến lệnh (immediate/TWAP/VWAP/iceberg) | `EXECUTION_REPORT`, `POSITION_UPDATE` |
| **Risk** | 30 giây | Sụt giảm vốn, VaR/CVaR (lịch sử + Monte-Carlo), mức tiếp xúc, ký quỹ, công tắc ngắt | `RISK_ALERT` |
| **Meta** | 24 giờ | Kiểm định lại chiến lược đang chạy, cập nhật vòng đời, phân bổ vốn, hiệu chuẩn, tinh chỉnh các tác nhân khác | `META_FEEDBACK` |

**Giao thức thông điệp** (JSON qua Redis Pub/Sub):

```json
{
  "message_id": "msg-a1b2c3",
  "agent_id": "analysis",
  "message_type": "SIGNAL",
  "payload": {"symbol": "XAUUSD", "direction": 1, "confidence": 0.72},
  "timestamp": "2026-01-15T10:30:00+00:00",
  "correlation_id": "corr-9f8e7d",
  "target": null
}
```

Một tác nhân lỗi không làm sập hệ thống: lỗi được đếm, tác nhân chuyển sang
`DEGRADED`, và orchestrator tự khởi động lại khi nó `FAILED`.

### An toàn cho mã do AI sinh ra

Mã sinh tự động phải qua ba cửa trước khi được ghi vào
`strategies/ai_generated/`:

1. **Phân tích AST với danh sách cho phép** — chỉ được import `pandas`, `numpy`,
   `typing`, `core.indicators`, `core.strategy_registry`,
   `strategies.base_strategy`. Chặn `eval`/`exec`/`open`/`__import__`/truy cập
   thuộc tính dunder.
2. **Kiểm tra cấu trúc** — bắt buộc có `@register_strategy` và `compute_signals`.
3. **Kiểm thử khói** — nạp module và chạy một backtest thật; lỗi ở bất kỳ bước
   nào thì tệp bị xoá.

---

## 6. Quy trình kiểm định

Đây là phần quan trọng nhất của hệ thống: nó tồn tại để **bác bỏ** chiến lược,
không phải để tán dương chúng.

| Kiểm tra | Câu hỏi trả lời | Ngưỡng mặc định |
|---|---|---|
| **Walk-Forward (WFA)** | Tối ưu trên quá khứ có còn hiệu quả ở tương lai gần không? | hiệu suất ≥ 0.40 |
| **PBO (CSCV)** | Xác suất chiến lược chỉ khớp nhiễu quá khứ? | ≤ 0.50 |
| **Calibration** | Độ tin cậy hệ thống tự công bố có khớp tỷ lệ thắng thật? | sai số ≤ 0.15 |
| **Robustness** | Còn sống khi nhiễu tham số ±20%, khi chi phí gấp đôi, ở mọi chế độ biến động? | phải sống khi chi phí gấp đôi |
| **Deflated Sharpe** | Sharpe còn ý nghĩa sau khi trừ số lần thử? | báo cáo kèm |

Chiến lược chỉ được cấp vốn khi qua **toàn bộ** cửa. Báo cáo luôn liệt kê lý do
trượt cụ thể.

> `pbo.computed = false` nghĩa là **chưa chạy** kiểm tra PBO (chế độ nhanh),
> không phải "PBO = 1.0". Hệ thống phân biệt rõ hai trường hợp này ở mọi nơi:
> khi chưa đo, bộ phân bổ vốn coi PBO là 0.5 (chưa biết) thay vì kết tội.

### Phân bổ vốn — Kelly có phạt bất định

```
Kelly thô        f = p − (1−p)/b
Hệ số chắc chắn  h = [ n/(n+12) · (0.4·PBO + 0.3·WFA + 0.3·điểm) ] ^ 0.5
Phân bổ          a = f × 0.25 × h × hệ_số_vòng_đời   (giới hạn ≤ 20%/chiến lược)
```

Chiến lược có tương quan ≥ 0.7 phải chia sẻ một ngân sách rủi ro chung.

### Vòng đời chiến lược

```
ACTIVE ──Sharpe<0.5──► DEGRADED ──Sharpe<0──► PAUSED ──90 ngày──► RETIRED
   ▲                        │                     │
   └──2 lần Sharpe≥0.75─────┘                     │
                            └──────phục hồi───────┘
```

Có thời gian lưu trú tối thiểu để tránh dao động trạng thái do nhiễu; sụt giảm
vốn ≥ 50% thì tạm dừng ngay bất kể Sharpe.

---

## 7. API

Tài liệu tương tác đầy đủ tại `/docs`.

| Phương thức | Đường dẫn | Mô tả |
|---|---|---|
| GET | `/api/v1/status` | Trạng thái toàn hệ thống |
| GET | `/api/v1/account` | Số dư, vốn thực, ký quỹ, đòn bẩy |
| GET | `/api/v1/positions` | Vị thế đang mở |
| POST | `/api/v1/positions/{id}/close` | Đóng một vị thế |
| POST | `/api/v1/positions/close-all` | Đóng toàn bộ vị thế |
| GET/POST | `/api/v1/orders` | Xem / đặt lệnh (MARKET, LIMIT, STOP) |
| PUT/DELETE | `/api/v1/orders/{id}` | Sửa / huỷ lệnh chờ |
| GET/POST | `/api/v1/strategies` | Danh mục / tạo cấu hình chiến lược |
| PUT/DELETE | `/api/v1/strategies/{id}` | Cập nhật / xoá |
| POST | `/api/v1/strategies/{id}/pause` | Tạm dừng chiến lược |
| POST | `/api/v1/backtest/run` | Chạy một backtest |
| POST | `/api/v1/backtest/matrix` | Ma trận chiến lược × cặp tiền |
| POST | `/api/v1/backtest/portfolio` | Backtest danh mục |
| POST | `/api/v1/validation/run` | Chạy kiểm định đầy đủ |
| GET | `/api/v1/market/{symbol}` | Nến + chỉ báo |
| GET | `/api/v1/market/snapshot` | Bảng giá mọi cặp |
| GET | `/api/v1/agents` | Sức khoẻ các tác nhân |
| POST | `/api/v1/commands` | Gửi lệnh điều khiển tới tác nhân |
| GET | `/api/v1/metrics` | Số liệu tổng hợp |
| WS | `/api/v1/ws` | Luồng thời gian thực |

Ví dụ:

```bash
# Đặt lệnh mua vàng
curl -X POST http://localhost:8000/api/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"XAUUSD","volume":0.10,"direction":"BUY","sl":2025,"tp":2050}'

# Kiểm định chiến lược MACD trên EURUSD
curl -X POST http://localhost:8000/api/v1/validation/run \
  -H 'Content-Type: application/json' \
  -d '{"name":"MACD","symbol":"EURUSD","timeframe":"H1","bars":6000}'
```

WebSocket:

```javascript
const ws = new WebSocket("ws://localhost:8000/api/v1/ws?topics=quotes,risk");
ws.onmessage = (event) => console.log(JSON.parse(event.data));
ws.send(JSON.stringify({action: "subscribe", topics: ["signals"]}));
```

### Hợp đồng cho cổng `XM_MODE=rest`

Nếu tự dựng cổng nối MT5, hãy hiện thực các điểm cuối sau:

| Phương thức | Đường dẫn | Thân yêu cầu / phản hồi |
|---|---|---|
| POST | `/auth/login` | `{account_id, password, server}` → `{token}` |
| GET | `/account` | → `{balance, equity, margin, free_margin, margin_level, leverage}` |
| GET | `/positions` | → danh sách vị thế |
| POST | `/positions/{id}/close` | `{reason}` → vị thế đã đóng |
| GET/POST | `/orders` | liệt kê / đặt lệnh |
| PUT/DELETE | `/orders/{id}` | sửa / huỷ |
| WS | `/ws` | `{action:"subscribe", symbols:[...]}` → `{symbol, bid, ask}` |

---

## 8. Thư viện chiến lược (17)

| Nhóm | Chiến lược |
|---|---|
| Theo xu hướng | `SMA_Cross`, `MACD`, `Ichimoku`, `ADX_Trend`, `Donchian`, `SuperTrend` |
| Hồi quy trung bình | `RSI`, `Bollinger_Bands`, `Stochastic`, `CCI`, `ZScore_Reversion` |
| Động lượng | `Momentum`, `Aroon` |
| Biến động | `Volatility_Breakout`, `Keltner`, `Session_Breakout` |
| Kết hợp | `Ensemble` (bỏ phiếu có trọng số) |
| AI sinh | `strategies/ai_generated/` (tạo lúc chạy) |

Viết chiến lược mới:

```python
from typing import Any, ClassVar, Dict
import pandas as pd
from core.indicators import rsi
from core.strategy import ParameterSpec
from core.strategy_registry import register_strategy
from strategies.base_strategy import BaseStrategy


@register_strategy
class MyStrategy(BaseStrategy):
    """Mô tả ngắn gọn ý tưởng giao dịch."""

    name: ClassVar[str] = "My_Strategy"
    category: ClassVar[str] = "mean_reversion"
    default_params: ClassVar[Dict[str, Any]] = {"period": 14, "threshold": 30}
    param_space: ClassVar[tuple] = (ParameterSpec("period", 5, 50),)

    def compute_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Trả về vị thế mong muốn cho từng nến."""
        values = rsi(df["close"], int(self.params["period"]))
        position = pd.Series(0, index=df.index, dtype="int8")
        position[values < float(self.params["threshold"])] = 1
        position[values > 100 - float(self.params["threshold"])] = -1
        return self.build_frame(df, position)
```

Chỉ cần đặt tệp trong `strategies/`, registry tự phát hiện.

> **Quy ước quan trọng:** cột `signal` là **vị thế mong muốn** của nến kế tiếp
> (`1` mua, `-1` bán, `0` đứng ngoài), không phải "sự kiện vào lệnh". Với chiến
> lược kiểu giao cắt, hãy giữ trạng thái bằng `ffill` như các chiến lược mẫu.

---

## 9. Mô hình khớp lệnh trong backtest

* Tín hiệu tính tại **giá đóng cửa** nến `t`, khớp tại **giá mở cửa** nến `t+1`
  → không có nhìn trước (có bài kiểm thử riêng cho việc này).
* Mỗi lần khớp chịu **nửa spread + trượt giá**; hoa hồng tính cả hai chiều.
* SL/TP kiểm tra theo giá cao/thấp trong nến; nếu một nến chạm cả hai thì
  **giả định chạm SL trước** (thiên về thận trọng).
* Sau khi bị quét SL/TP, hệ thống **không vào lại cùng chiều** cho đến khi tín
  hiệu thay đổi — nếu không, một tín hiệu duy trì sẽ liên tục mở lại vị thế vừa
  thua và đốt sạch tài khoản bằng phí.
* Khối lượng tính từ rủi ro: khoảng cách tới SL và `risk_per_trade`, đã chuẩn
  hoá theo bước lot và kiểm tra ký quỹ.
* Mỗi chiến lược/cặp giữ tối đa một vị thế; tín hiệu ngược chiều sẽ đảo vị thế.

---

## 10. Cấu trúc dự án

```
ea_factory_pro/
├── docker-compose.yml          # toàn bộ hạ tầng
├── Dockerfile.{api,dashboard,worker,postgres,redis,influxdb}
├── config.yaml / .env.example / Makefile / pytest.ini
├── api/                        # FastAPI: main, dependencies, routers/, websocket/
├── dashboard/                  # Streamlit: app.py, views/, components/, api_client.py
├── agents/                     # base_agent, message_bus, orchestrator, 5 tác nhân, llm
├── core/                       # data_manager, indicators, strategy, backtest,
│                               # validation, lifecycle, decision, utils
├── broker/                     # xm_connection/account/orders/positions/websocket,
│                               # simulator, xm_models
├── strategies/                 # base_strategy + 17 chiến lược + ai_generated/
├── models/                     # SQLAlchemy: database, account, order, position,
│                               # trade, strategy, metrics
├── services/                   # market_data, order, position, strategy,
│                               # backtest, validation, notification
├── websocket/                  # manager (client), handler (hub), xm_stream (cầu nối)
├── worker/                     # tiến trình chạy cụm tác nhân
├── scripts/                    # init_db, seed_data, run_pipeline
├── tests/                      # 206 bài kiểm thử
└── docker/                     # cấu hình postgres/redis/influxdb
```

> Thư mục các trang giao diện tên là `dashboard/views/` chứ không phải `pages/`:
> Streamlit coi mọi thư mục `pages/` cạnh tệp khởi chạy là hệ thống điều hướng
> riêng của nó và sẽ chạy thẳng từng module, bỏ qua `app.py` (kết quả là trang
> trắng). Điều hướng do `st.navigation` trong `app.py` đảm nhiệm.

---

## 11. Bảng điều khiển

| Trang | Nội dung |
|---|---|
| **Tổng quan** | Số dư, vốn thực, lãi/lỗ mở, đường vốn, bảng giá, vị thế, lịch sử lệnh |
| **Phân tích thị trường** | Nến tương tác + chỉ báo, bối cảnh thị trường của Analysis Agent, ma trận tương quan |
| **Quản lý chiến lược** | Danh mục, cấu hình, chạy backtest, so sánh, bảng vòng đời |
| **Giám sát rủi ro** | Đồng hồ sụt giảm/VaR/tiếp xúc, lịch sử cảnh báo, nút dừng khẩn cấp |
| **Nghiên cứu & Kiểm định** | Dây chuyền tiến hoá, báo cáo WFA/PBO/hiệu chuẩn, phân bổ vốn |
| **Cấu hình** | Trạng thái hạ tầng, điều khiển tác nhân, đặt lệnh thủ công, luồng thông điệp |

---

## 12. Kiểm thử

```bash
make test                       # toàn bộ
pytest tests/test_backtest.py   # một mô-đun
pytest -m "not slow"            # bỏ qua bài chậm
pytest -m integration           # chỉ bài tích hợp
```

206 bài kiểm thử, chạy hoàn toàn ngoại tuyến (dữ liệu mô phỏng + broker mô
phỏng + SQLite tạm), bao phủ: chỉ báo, chiến lược, engine backtest (gồm bài
kiểm tra không-nhìn-trước), bộ kiểm định, tầng broker, message bus, năm tác
nhân, bộ lọc mã AI, vòng đời, phân bổ vốn và toàn bộ điểm cuối API.

---

## 13. Bảo mật và vận hành

* **Bí mật**: chỉ nằm trong `.env` (đã có trong `.gitignore`); không hardcode.
* **Xác thực API**: đặt `API_AUTH_ENABLED=true`, lấy token qua
  `POST /api/v1/auth/token`, gửi kèm `Authorization: Bearer <token>`.
* **Giới hạn tần suất**: 240 yêu cầu/phút mỗi IP (`api.rate_limit`).
* **Nhật ký kiểm toán**: mọi lệnh và sự kiện hệ thống ghi vào bảng
  `system_events`; log có `correlation_id` xuyên suốt.
* **Container**: chạy bằng người dùng không phải root, có health check.
* **Giám sát**: `/metrics` cho Prometheus, `/health` cho probe.
* **Sao lưu**: `docker exec eafactory-postgres pg_dump -U eafactory eafactory > backup.sql`

### Danh sách kiểm tra trước khi chạy tiền thật

1. Chạy demo tối thiểu 30 ngày, đối chiếu kết quả thực tế với dự báo.
2. Xác nhận `pbo.computed = true` và PBO < 0.5 cho mọi chiến lược được cấp vốn.
3. Kiểm tra hiệu chuẩn: độ tin cậy công bố khớp tỷ lệ thắng thật.
4. Thử công tắc ngắt rủi ro: hạ `kill_switch_drawdown` và xác nhận hệ thống
   dừng và đóng vị thế.
5. Đổi `API_JWT_SECRET`, bật `API_AUTH_ENABLED`, đổi mật khẩu PostgreSQL/Influx.
6. Bắt đầu với `risk_per_trade` rất nhỏ (0.001–0.0025).

> **Cảnh báo rủi ro.** Giao dịch ngoại hối và vàng có đòn bẩy có thể khiến bạn
> mất toàn bộ vốn. Phần mềm này là công cụ nghiên cứu, được cung cấp "nguyên
> trạng", không kèm bảo đảm nào. Kết quả quá khứ — nhất là kết quả trên dữ liệu
> mô phỏng — không dự báo kết quả tương lai. Hãy tự chịu trách nhiệm và chỉ giao
> dịch bằng số tiền bạn có thể mất.

---

## 14. Xử lý sự cố

| Hiện tượng | Nguyên nhân và cách xử lý |
|---|---|
| Bảng điều khiển báo "Mất kết nối API" | API chưa chạy: `docker-compose logs api`; kiểm tra `API_URL`. |
| Không có chiến lược nào được cấp vốn | Hành vi đúng trên dữ liệu mô phỏng (mục 2.2). Chuyển sang dữ liệu thật để có kết luận có ý nghĩa. |
| Sổ lệnh trống dù tác nhân đang chạy | Analysis Agent cần đủ nến và độ đồng thuận; hạ `agents.analysis.min_confidence` hoặc chờ thêm chu kỳ. |
| `Falling back to the in-memory message bus` | Không có Redis. Chạy được bình thường trong một tiến trình; cần Redis khi tách API và worker. |
| `Database unavailable, continuing without persistence` | Không có PostgreSQL; hệ thống dùng SQLite. |
| Cổng bị chiếm | Đổi ánh xạ cổng trong `docker-compose.yml`. |
| Research Agent không sinh mã bằng LLM | Thiếu khoá API; nó tự lùi về bộ mẫu cục bộ (mục 4.4). |

---

## 15. Giấy phép

Phát hành cho mục đích nghiên cứu và giáo dục. Bạn tự chịu trách nhiệm tuân thủ
điều khoản của nhà môi giới và quy định pháp luật tại nơi cư trú.
