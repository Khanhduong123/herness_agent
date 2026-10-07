---
plan_id: [plan_id]
task_id: [task_id]
---
# Sub-Task Specification: [Task Name]

## [ROLE ANCHOR]
**BẠN ĐANG ĐẢM NHIỆM VAI TRÒ CHUYÊN MÔN:** [Role - e.g., Leaf Coder Worker / QA Tester]
**BẠN ĐƯỢC CHỈ ĐỊNH THỰC THI NHIỆM VỤ:** `[[task_id]]` - [Task Name]

## HƯỚNG DẪN THỰC THI CHI TIẾT
<!-- Detailed instructions for this specific subtask -->
1.
2.

## RANH GIỚI PHẠM VI BẮT BUỘC (TUÂN THỦ TUYỆT ĐỐI)
<!-- Scope boundaries to prevent hallucination or over-engineering -->
- **IN SCOPE:**
- **OUT OF SCOPE:**
- **PROHIBITIONS:** Không sử dụng ManageTask, không tạo background loops, không overwrite toàn bộ file (chỉ Patch).

## DỮ LIỆU ĐẦU VÀO ĐƯỢC CẤP PHÁT (Input Artifacts)
- **Files/Mã nguồn tham chiếu:**
- **APIs/Schemas:**

## DANH MỤC CÔNG CỤ ĐƯỢC PHÉP TRUY CẬP
<!-- Permitted tools for this specific worker -->
- Ví dụ: `apply_patch`, `replace_file_content`, `run_command` (cho pytest)
- **CẢNH BÁO:** Tuyệt đối không cố gắng gọi bất kỳ công cụ hoặc hàm nào nằm ngoài danh mục trên. KHÔNG ĐƯỢC gọi `invoke_subagent` hay `define_subagent`.

## TIÊU CHÍ HOÀN THÀNH (DEFINITION OF DONE)
- **Trạng thái hoàn thành:** Pass 100% pytest. Ghi file `.ai/status/[task_id].complete` và xuất thông báo `[WORKER_COMPLETED]` ở cuối để Orchestrator biết.
- **Các quy tắc kiểm định bắt buộc (Validation Rules):**
  1.
  2.

## Edge Cases & Boundary Conditions
<!-- MUST detail at least 3-5 concrete edge cases according to AGENTS.md -->
1. **[Edge Case 1]**: (Missing files / Null inputs) - *Handling Logic & Test Assertions: ...*
2. **[Edge Case 2]**: (Path separator differences / Formatting) - *Handling Logic & Test Assertions: ...*
3. **[Edge Case 3]**: (Race conditions / Permission errors) - *Handling Logic & Test Assertions: ...*

## ĐỊNH DẠNG ĐẦU RA YÊU CẦU
- **Expected Output:** Patch diffs, Passed Test Reports.
- **Lưu ý:** Chỉ xuất nội dung dữ liệu giải quyết trực tiếp nhiệm vụ, không thêm lời chào, nhận xét hoặc văn bản đệm.
