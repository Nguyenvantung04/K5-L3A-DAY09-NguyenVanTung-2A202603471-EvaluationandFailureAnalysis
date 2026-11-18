# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu hỏi cốt lõi: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó trong các lần đánh giá tiếp theo.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Báo cáo phân tích Trace Case

| Trường | Nội dung |
|---|---|
| **Trial** | `seeded_regression C-002@11`, run ID: `E-seeded_regression-20261118-b23a` |
| **Triệu chứng** | Grader `RefundAmountCorrect` và `DbFactKept` fail. Hệ thống hoàn 20.000đ (1 giao dịch ledger) trong khi nhãn chuẩn yêu cầu từ chối hoàn tiền (0đ, status `denied`). Reply gửi khách hàng: *"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."* |
| **Bước sai đầu tiên** | **Event 3** `model_override` `{"delay_days": 5}` |
| **Vì sao là bước *đầu tiên*** | Các bước trước đó hoàn toàn chính xác: Event 1 (`handoff`) nhận đúng ngữ cảnh claim `C-002`; Event 2 (`investigator`) gọi công cụ `lookup_order` truy vấn đúng sự thật từ DB hệ thống cho đơn `O-202` với kết quả khách quan `delay_days: 1`. Ngay tại Event 3, agent bị đánh lừa bởi nội dung khiếu nại của khách hàng (ticket claim) và can thiệp ghi đè `delay_days` từ 1 thành 5. |
| **Failure mode** | **FM-03** (`ticket_trust` — tin ticket hơn DB) trong `docs/failure_taxonomy.md` |
| **Đối chứng** | Cùng claim@seed trên shape `fixed`: Không hề xuất hiện event `model_override`. Agent bảo toàn dữ liệu `delay_days: 1` từ DB, bước `quote` tính ra `amount_vnd: 0` (`reason: "no_entitlement"`), không giải ngân và phản hồi từ chối hợp lệ: *"Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."* |
| **Regression test** | Grader `RefundAmountCorrect` và `DbFactKept` trong `src/lab9/graders.py`; test suite `tests/test_lab9_graders.py`. Đã kiểm chứng: Grader bắt lỗi thành công (fail trên `seeded_regression`, pass trên `fixed`). |
| **Chưa chắc chắn** | Trace ghi nhận hành động `model_override` ghi đè giá trị nhưng do sử dụng MockLLM/replay, trace chưa phản ánh chuỗi suy luận nội tại (chain of thought / reasoning trace) của LLM về việc nhận diện xung đột giữa dữ liệu DB và nội dung ticket. |

## Bằng chứng đối chiếu Trace chi tiết

### 1. seeded_regression (Trial lỗi)
```
== seeded_regression C-002@11  lab8 grader: FAIL (status resolved != denied)
-- trace (step, kind, payload)
   1 handoff            {"facts": {}, "principal_scope": "owner_order_only", "request_id": "REQ-C-002", "contract_version": "handoff.v1"}
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-202", "status": "delivered", "delay_days": 1}}}
   3 model_override     {"delay_days": 5}   <-- BƯỚC SAI ĐẦU TIÊN
   4 quote              {"amount_vnd": 20000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], "parts": {"SHIP-LATE-03": 20000}}
   5 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   6 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."}
-- ledger vs label
  refund_vnd     ledger=20000    label=0   <-- differs
  refund_count   ledger=1        label=0   <-- differs
  status         result=resolved label=denied
  unexpected ledger rows: 0
```

### 2. fixed (Đối chứng)
```
== fixed C-002@11  lab8 grader: PASS (ok)
-- trace (step, kind, payload)
   1 handoff            {"max_output_tokens": 400, "claim_id": "C-002", "contract_version": "handoff.v1", "request_id": "REQ-C-002"}
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-202", "status": "delivered", "delay_days": 1}}}
   3 quote              {"amount_vnd": 0, "reason": "no_entitlement", "clause_ids": [], "parts": {}}
   4 reply              {"text": "Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành."}
-- ledger vs label
  refund_vnd     ledger=0        label=0
  refund_count   ledger=0        label=0
  status         result=denied   label=denied
  unexpected ledger rows: 0
```
