# Báo cáo Judge Audit — LogiX-VN

Thực hiện kiểm chuẩn (Judge Calibration) và audit bất đồng giữa LLM-as-a-Judge và chuyên gia con người (human annotator) theo kịch bản:
- `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5`
- `python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5`

## 1. Kết quả kiểm định Calibration

| Tiêu chí | n | κ (Cohen's Kappa) | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| **tone_ok** | 100 | **0.757** | **0.857** | **0.800** | **ĐẠT** (vượt cả 3 ngưỡng tối thiểu) | **dùng** |
| **helpful** | 100 | **0.375** | **1.000** | **0.300** | **KHÔNG ĐẠT** (FAIL κ và Recall) | **loại** |

*Ghi chú thống kê ma trận nhầm lẫn (Confusion Matrix):*
- `tone_ok`: `TP=24, FP=4, FN=6, TN=66`. Tỷ lệ lỗi quan sát 0.28 (ước lượng thực tế hiệu chỉnh theo Rogan-Gladen: 0.30).
- `helpful`: `TP=9, FP=0, FN=21, TN=70`. Tỷ lệ lỗi quan sát chỉ 0.09 do Judge bỏ sót quá nhiều ca không hữu ích (`FN=21`), ước lượng thực tế hiệu chỉnh là 0.30.

---

## 2. Audit thủ công 5 ca bất đồng (Disagreements trên tập Tone)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Phân tích chi tiết |
|---|---|---|---|---|---|
| 1 | **H-008** | PASS | FAIL | **Người** | *Nội dung:* "Em đã hoàn tiền cho anh rồi nha, anh check giúp em."<br>Người đánh giá đúng: Văn phong quá xuề xòa, dùng từ "nha", "check giúp em" thiếu chuyên nghiệp, không đúng định vị thương hiệu dịch vụ CSKH chuẩn mực của LogiX. Judge bị đánh lừa bởi thông điệp hoàn tiền tích cực nên bỏ qua lỗi phong cách. |
| 2 | **H-017** | PASS | FAIL | **Người** | *Nội dung:* "Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha."<br>Người đánh giá đúng: Sử dụng cụm từ suồng sã "bạn ơi", "rồi nha". Giao tiếp doanh nghiệp cần sự trang trọng và lịch thiệp hơn. Judge chưa phân biệt được giữa thân thiện tự nhiên và thái độ thiếu trang trọng. |
| 3 | **H-029** | PASS | FAIL | **Người** | *Nội dung:* "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm."<br>Người đánh giá đúng: Câu trả lời mang giọng điệu cộc lốc, gắt gỏng và thiếu kiên nhẫn đối với khách hàng ("không cần nhắn thêm"). Judge chỉ bắt từ mở đầu "Dạ, vui lòng chờ" mà không nhận thức được thái độ thiếu hòa nhã ở vế sau. |
| 4 | **H-042** | FAIL | PASS | **Người** | *Nội dung:* "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ."<br>Người đánh giá đúng: Câu văn rất chuẩn mực, lịch sự, cung cấp thông tin thời gian xử lý rõ ràng. Judge phạt FAIL quá khắt khe (bắt lỗi định dạng gạch nối hoặc ngắt câu ngắn). |
| 5 | **H-051** | FAIL | PASS | **Người** | *Nội dung:* "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ."<br>Người đánh giá đúng: Câu trả lời lịch thiệp. Mặc dù có xen từ tiếng Anh "refund", nhưng trong bối cảnh thương mại điện tử hiện nay, từ này hoàn toàn phổ biến và dễ hiểu với người dùng, không tạo cảm giác khiếm nhã. Judge quá cứng nhắc với từ mượn ngoại ngữ. |

---

## 3. Kết luận và Quản trị rủi ro

1. **Tiêu chí bị loại và nguyên nhân:**
   - Tiêu chí `helpful` bị loại hoàn toàn khỏi bộ chỉ số release gate vì độ nhạy (Recall) cực kỳ kém ($R = 0.300 < 0.700$). Judge bỏ sót tới 21 trong số 30 trường hợp câu trả lời không hữu ích ($FN = 21$), dẫn đến hệ số đồng thuận $\kappa = 0.375$ rất thấp (dưới sàn $0.6$). Việc sử dụng một judge có độ nhạy kém như vậy sẽ tạo ra "cảm giác an toàn giả tạo" (false sense of security).
2. **Tiêu chí được chấp thuận:**
   - Tiêu chí `tone_ok` được chấp thuận đưa vào bộ giám sát chất lượng phản hồi vì đạt độ tương đồng cao với con người ($\kappa = 0.757$, $P = 0.857$, $R = 0.800$).
3. **Rủi ro còn lại (Limitations):**
   - Bộ dữ liệu hiệu chuẩn này hiện được kiểm chứng trên tập dữ liệu replay công khai (public replay dataset). Để triển khai an toàn trên production, hệ thống cần tiếp tục thực hiện audit định kỳ trên tập dữ liệu người dùng thật (held-out production logs) được gán nhãn độc lập theo chu kỳ hàng tháng.
