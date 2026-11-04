# 0.6.0 개발판 구조 편집 API

한글 자동화 엔진에서 HWP와 HWPX를 같은 도구로 처리한다. 파일은 원래 형식의 수정본을 저장하며 열린 창은 사용자가 저장한다. 빌드와 방식별 실제 시험 결과는 [시험 기록](../../../TEST-RESULTS.md)을 참조한다.

## 위치 지정

select_document로 대상을 고른 후 read_document에서 revision을 얻고 요청한 범위를 모두 읽는다. 다음 페이지에 같은 revision을 전달한다. find_targets로 정확한 원문과 후보 위치를 대조한다. 표는 type=table_object와 table 번호를, 사진과 수식은 type=image와 type=equation을 사용한다. 문서 읽기의 caret_target_id, selection_target_id, selected_object_target_id도 사용할 수 있다. 쪽·구역 개체는 regions에 있으며 type=region과 kind로 검색한다. text_complete=false면 검색 결과에서 원문 전체를 읽는다. 쪽 번호만으로 수정 위치를 확정하지 않는다.

## 변경 목록

apply_edits에 document_id, revision, 새 request_id와 edits를 전달한다. 모든 대상은 그 revision에서 얻는다. 구조가 바뀌면 남은 대상을 다시 대조한다. 범위가 바뀌거나 대상을 유일하게 확인할 수 없으면 사본 시험을 중단한다. dry_run은 사용자가 미리보기를 요청할 때 사용한다.

| 편집 | type과 주요 입력 |
|---|---|
| 삽입 | insert_at, target_id, position(before/after), blocks |
| 범위 교체·삭제 | replace_range와 blocks, delete_range |
| 개체 삭제 | delete_object, 지정된 사진·수식·표 ID |
| 복사·이동 | copy_range 또는 move_range, target_id, destination_id, position |
| 표 만들기 | insert_table, rows, columns, cells. cells는 행별 배열이며 각 칸은 블록 배열이다. |
| 표 구조 | table_change, action과 index/count 또는 range. range는 1부터 시작하는 [위 행, 왼쪽 열, 아래 행, 오른쪽 열]이다. |
| 표 서식 | table_format, range, properties(width_mm, height_mm, vertical_align, background, border_color, border_style) |
| 글자·문단 | set_character 또는 set_paragraph, properties. 이름으로 적용할 스타일은 문서에 있어야 한다. |
| 쪽 설정 | set_page, 구역에 속한 본문 target_id, properties(orientation, width_mm, height_mm, left_mm, right_mm, top_mm, bottom_mm) |
| 쪽·구역 나누기 | insert_break, position, break_type(page/section) |
| 머리말·꼬리말·각주·미주·메모·쪽 번호 | region_edit, action(add_header, add_footer, add_footnote, add_endnote, add_memo, replace_text, delete, set_page_number), 작업에 맞는 text 또는 number_position |
| 사진 배치·자르기·캡션 | set_picture(properties), crop_picture(crop), caption_picture(text) |

표의 clear_cells는 내용만 비운다. 행·열 변경에는 insert_rows, insert_columns, delete_rows, delete_columns를 사용한다. merge_cells는 직사각형 전체 셀을 대상으로 한다. split_cell은 병합 셀을 기본 격자로 되돌리고 기존 내용은 왼쪽 위 셀에 둔다. 기존 1×1 셀의 임의 분할은 배포 검증 범위에 남아 있다.

글·수식·사진은 기존 블록 형식을 사용한다. LaTeX는 equation의 format=latex로 전달한다. 사진은 내장하고 기본으로 글자처럼 배치한다. crop은 원본 픽셀 기준 [왼쪽, 위, 오른쪽, 아래]이며 회전·효과·기존 캡션이 있는 사진은 이 작업에 적합하지 않다. 사진 교체는 정확한 사진 ID에 replace_range로 새 사진 한 장을 전달한다.

## 검토

read_document(scope="review")에서 기록 상태와 현재 변경 ID를 읽는다. 검증된 대상은 본문의 단일 문단 글자 삽입·삭제 기록이다. review_change에 target_id와 action(accept/reject)을 전달한다. 전체를 명시한 요청은 target_id="all", all_changes=true를 추가한다.

기록할 글자 교체는 find_targets(type="review_text")로 정확한 글자 구간을 찾은 뒤 review_text에 expected_text, text, tracking(inherit/on_for_request)을 전달한다. 이 경로는 한 문단의 단일 글자 구간을 처리한다. 객체·서식 등 다른 종류의 추적 편집과 메모 답글은 출시 전 검증 항목이다.

## 결과 확인

적용이 실패하거나 대상이 바뀌면 새 요청으로 자동 반복하지 않는다. 열린 창의 LIVE_RECOVERY_REQUIRED에는 부분 수정 가능성과 작업 전 백업을 안내한다. 사용자의 미저장 변경까지 되돌릴 수 있는 반복 실행 취소는 사용하지 않는다.
