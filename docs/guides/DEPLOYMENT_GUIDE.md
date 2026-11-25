# Hướng Dẫn Triển Khai ViAI-QA (Deployment Guide)

Tài liệu này cung cấp các phương án triển khai hệ thống **ViAI-QA (Vietnamese AI Response QA)** từ môi trường cục bộ (Local Docker) đến các nền tảng đám mây phổ biến nhất (**Render**, **Vercel**).

---

## Lựa chọn phương án triển khai

| Nền tảng | Thành phần | Chi phí | Thời gian thiết lập | Khuyến nghị |
|---|---|---|---|---|
| **Render Blueprint** | Toàn bộ hệ thống: Frontend (SvelteKit) + Backend (FastAPI) + PostgreSQL | Miễn phí (Free Tier) | ~3 phút | **Khuyên dùng**: 1-click deploy toàn bộ hệ thống bằng `render.yaml` |
| **Vercel + Backend** | Frontend trên Vercel, Backend & DB trên Render/Fly.io/Docker | Miễn phí | ~5 phút | Tối ưu CDN toàn cầu & độ mượt của giao diện UI/UX |
| **Docker Compose** | Toàn bộ 13 services trên máy chủ Linux/VPS (port 80) | Tự lưu trữ | 1 lệnh | Cho môi trường phát triển & kiểm thử nội bộ |

---

## Phương án 1: Triển khai 1-Click trên Render (Đầy đủ Frontend + Backend + DB)

Kho lưu trữ đã có sẵn tệp cấu hình Blueprint [`render.yaml`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/render.yaml).

### Các bước thực hiện:
1. Đẩy mã nguồn lên tài khoản GitHub của bạn:
   ```bash
   git push origin feature # hoặc main
   ```
2. Đăng nhập vào [Render Dashboard](https://dashboard.render.com).
3. Nhấp vào **New +** $\rightarrow$ Chọn **Blueprint**.
4. Chọn repository GitHub `vietnamese-llm-hallucination-detection`.
5. Render sẽ tự động đọc tệp `render.yaml` và tạo 3 tài nguyên:
   - **`viai-qa-db`**: Cơ sở dữ liệu PostgreSQL 15 quản lý.
   - **`viai-qa-backend`**: FastAPI Web Service (chạy migrations và phục vụ REST APIs tại `/api/v1/`).
   - **`viai-qa-frontend`**: SvelteKit Web Service (chạy Node.js với UI đã kết nối tự động đến backend).
6. Nhấp **Apply**: Sau khoảng 2-3 phút, Render sẽ cấp tên miền công khai cho bạn (vd: `https://viai-qa-frontend.onrender.com`).

---

## Phương án 2: Triển khai Giao diện UI/UX trên Vercel

SvelteKit trong repository đã được cấu hình tự động nhận diện Vercel thông qua [`frontend/svelte.config.js`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/frontend/svelte.config.js) và [`vercel.json`](file:///home/nguyen-nam/User/nghonamjiwoo/vietnamese-llm-hallucination-detection/vercel.json).

### Các bước thực hiện:
1. Đăng nhập vào [Vercel](https://vercel.com).
2. Nhấp **Add New...** $\rightarrow$ **Project**.
3. Import repository `vietnamese-llm-hallucination-detection`.
4. Trong phần **Project Settings**:
   - **Root Directory**: Chọn `frontend`.
   - **Framework Preset**: Chọn `SvelteKit`.
5. Trong phần **Environment Variables**:
   - Thêm biến môi trường:
     - Tên: `VITE_API_URL`
     - Giá trị: Địa chỉ backend của bạn (vd: `https://viai-qa-backend.onrender.com` hoặc IP VPS).
6. Nhấp **Deploy**: Vercel sẽ tự động build và cấp tên miền toàn cầu (vd: `https://viai-qa.vercel.app`).

---

## Phương án 3: Triển khai cục bộ bằng Docker Compose

Chạy toàn bộ Core stack gồm Gateway NGINX, SvelteKit, FastAPI và PostgreSQL bằng lệnh duy nhất:

```bash
# 1. Khởi động core stack:
docker compose up -d

# 2. Truy cập ứng dụng:
# - Giao diện QA Workspace: http://localhost (hoặc port 80)
# - API Swagger Docs:        http://localhost/docs
# - Health check endpoint:   http://localhost/health

# 3. Kích hoạt thêm các profile nâng cao (tùy chọn):
# Giám sát Prometheus & Grafana:
docker compose --profile monitoring up -d

# Quản lý mô hình MLflow & MinIO:
docker compose --profile mlops up -d

# Tracing Jaeger:
docker compose --profile tracing up -d
```

---

## Kiểm tra sau khi triển khai (Verification Checklist)

- [ ] Truy cập trang chủ Frontend: Giao diện tối hiển thị form kiểm tra và sidebar lịch sử.
- [ ] Gửi một test case mới (Context, Prompt, Response) $\rightarrow$ Kết quả trả về kèm điểm tin cậy và radar phân tích (NLI/NER/Vistral).
- [ ] Nhấp vào một trong các nút **Đánh giá lại (Human-in-the-loop)** $\rightarrow$ Thông báo xác nhận thành công xuất hiện.
- [ ] Sidebar lịch sử tự động cập nhật kết quả vừa chạy và lưu trữ bền vững trong PostgreSQL.
