"""
CSV 파일 축소 기능

불필요한 행 삭제 및 비율 기반 행 삭제 기능을 제공합니다.
"""

import polars as pl
from pathlib import Path
from typing import Optional, List, Tuple
from io import StringIO
import re
from .csv_utils import load_csv, save_csv


def _detect_metadata_rows(input_file: str, max_scan_rows: int = 50) -> Tuple[List[str], int]:
    """
    파일의 메타데이터 행들을 자동 감지합니다.

    처음 max_scan_rows 줄을 읽고, 실제 데이터가 시작되는 지점까지의 줄들을 메타데이터로 식별합니다.

    Args:
        input_file: CSV 파일 경로
        max_scan_rows: 스캔할 최대 행 수 (기본값: 50)

    Returns:
        (메타데이터 줄 리스트, 데이터 시작 행 번호)
    """
    metadata_lines = []
    data_start_row = 0

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for row_num, line in enumerate(f):
                if row_num >= max_scan_rows:
                    break

                stripped_line = line.rstrip('\n\r')

                # 빈 줄은 메타데이터
                if not stripped_line.strip():
                    metadata_lines.append(stripped_line)
                    continue

                # #로 시작하는 줄은 메타데이터
                if stripped_line.strip().startswith('#'):
                    metadata_lines.append(stripped_line)
                    continue

                # 과학 기기 포맷 메타데이터 감지 (textdatetime 또는 특수 기기 포맷)
                if any(keyword in stripped_line for keyword in ['WaveRunner', 'Segments', 'Segment', 'TrigTime']):
                    metadata_lines.append(stripped_line)
                    continue

                # 콤마 분리된 필드 분석
                fields = stripped_line.split(',')

                # 데이터인지 판단: 주로 숫자로 이루어진 필드들
                is_data = True
                numeric_field_count = 0

                for field in fields:
                    field_stripped = field.strip()
                    if not field_stripped:
                        continue

                    # 숫자 또는 음수로 시작하는지 확인
                    try:
                        float(field_stripped)
                        numeric_field_count += 1
                    except ValueError:
                        # 숫자가 아님 - 텍스트 필드 감지
                        is_data = False
                        break

                # 필드의 대부분이 숫자면 데이터 시작
                if numeric_field_count > 0 and numeric_field_count >= len(fields) - 1:
                    # 데이터 시작점 발견
                    data_start_row = row_num
                    break
                else:
                    # 아직 메타데이터
                    metadata_lines.append(stripped_line)

    except Exception as e:
        print(f"메타데이터 감지 중 오류: {e}")
        return [], 0

    return metadata_lines, data_start_row


def reduce_csv(
    input_file: str,
    output_file: str,
    reduction_ratio: float = 50.0,
    start_row: int = 1,
) -> None:
    """
    CSV 파일의 크기를 줄입니다.

    메타데이터(헤더 또는 특수 포맷)를 자동 감지하여 보존합니다.

    Args:
        input_file: 입력 CSV 파일 경로
        output_file: 출력 CSV 파일 경로
        reduction_ratio: 삭제 비율 (0-100). 예: 50 = 50% 삭제
        start_row: 시작 행 (헤더 다음)

    Example:
        reduce_csv('data.csv', 'reduced.csv', reduction_ratio=50)
        # 짝수 행을 삭제하여 데이터의 50%를 제거합니다.
    """
    if reduction_ratio <= 0 or reduction_ratio >= 100:
        raise ValueError("reduction_ratio는 0~100 사이의 값이어야 합니다.")

    # 메타데이터 자동 감지
    metadata_lines, data_start_row = _detect_metadata_rows(input_file)

    # 전체 파일에서 메타데이터 이후의 모든 행을 읽기
    with open(input_file, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    # 메타데이터 이후의 CSV 데이터 부분
    csv_data_lines = all_lines[data_start_row:]

    # CSV 데이터 부분을 StringIO로 변환하여 Polars에서 읽기
    csv_text = ''.join(csv_data_lines)
    df = pl.read_csv(StringIO(csv_text),
                     infer_schema_length=10000,
                     ignore_errors=True,
                     truncate_ragged_lines=True)

    # 삭제 간격 계산
    # 50% -> 매 2번째 행 (간격: 2)
    # 25% -> 매 4번째 행 (간격: 4)
    # 75% -> 매 1.33번째 행 (간격: 1.33)
    delete_interval = 100 / reduction_ratio

    # 유지할 행의 인덱스 선택
    total_rows = len(df)
    indices_to_keep = []
    next_delete_idx = delete_interval - 1

    for i in range(total_rows):
        if i < next_delete_idx:
            indices_to_keep.append(i)
        else:
            next_delete_idx += delete_interval

    # 선택한 행만 유지
    reduced_df = df[indices_to_keep]

    # 메타데이터 + 축소된 데이터를 파일에 저장
    with open(output_file, 'w', encoding='utf-8') as f:
        # 메타데이터 작성
        for metadata_line in metadata_lines:
            f.write(metadata_line + '\n')

        # CSV 헤더 작성 (첫 줄 - 원본 파일의 헤더)
        if csv_data_lines:
            f.write(csv_data_lines[0])

        # 축소된 데이터 작성 (헤더 제외, 쉼표 없음)
        csv_output = reduced_df.write_csv(file=None, quote_style='necessary')
        # 축소된 데이터에서 헤더 행 제외 (처음 줄)
        csv_lines = csv_output.split('\n')
        for line in csv_lines[1:]:
            if line.strip():
                f.write(line + '\n')

    print(f"✓ 축소 완료: {total_rows} → {len(reduced_df)} 행")
    print(f"  입력: {input_file}")
    print(f"  출력: {output_file}")
    print(f"  감소 비율: {reduction_ratio}%")
    if metadata_lines:
        print(f"  메타데이터: {len(metadata_lines)}줄 보존")


def remove_rows_by_pattern(
    input_file: str,
    output_file: str,
    column: str,
    pattern: str,
    mode: str = "exclude"
) -> None:
    """
    특정 패턴을 가진 행을 삭제합니다.

    Args:
        input_file: 입력 CSV 파일 경로
        output_file: 출력 CSV 파일 경로
        column: 검사할 컬럼 이름
        pattern: 검사할 패턴 (정규표현식)
        mode: "exclude" (패턴 제외), "include" (패턴만 유지)

    Example:
        remove_rows_by_pattern('data.csv', 'cleaned.csv',
                              column='status', pattern='error', mode='exclude')
    """
    df = load_csv(input_file)

    # 정규표현식 필터링
    if mode == "exclude":
        filtered_df = df.filter(~pl.col(column).str.contains(pattern))
    elif mode == "include":
        filtered_df = df.filter(pl.col(column).str.contains(pattern))
    else:
        raise ValueError("mode는 'exclude' 또는 'include'여야 합니다.")

    save_csv(filtered_df, output_file)

    removed_count = len(df) - len(filtered_df)
    print(f"✓ 행 제거 완료: {removed_count}개 행 제거")
    print(f"  남은 행: {len(filtered_df)}/{len(df)}")


def remove_duplicates(
    input_file: str,
    output_file: str,
    subset: Optional[List[str]] = None
) -> None:
    """
    중복된 행을 제거합니다.

    Args:
        input_file: 입력 CSV 파일 경로
        output_file: 출력 CSV 파일 경로
        subset: 중복 검사 컬럼 목록. None이면 모든 컬럼 검사

    Example:
        remove_duplicates('data.csv', 'deduped.csv', subset=['id', 'timestamp'])
    """
    df = load_csv(input_file)

    deduped_df = df.unique(subset=subset, keep='first')
    save_csv(deduped_df, output_file)

    removed_count = len(df) - len(deduped_df)
    print(f"✓ 중복 제거 완료: {removed_count}개 행 제거")
    print(f"  남은 행: {len(deduped_df)}/{len(df)}")


def batch_reduce_csv(
    input_folder: str,
    output_folder: str,
    reduction_ratio: float = 50.0
) -> None:
    """
    폴더 내 모든 CSV 파일을 축소합니다.

    Args:
        input_folder: 입력 폴더 경로
        output_folder: 출력 폴더 경로
        reduction_ratio: 삭제 비율 (0-100)

    Example:
        batch_reduce_csv('./input', './output', reduction_ratio=50)
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_files = list(input_path.glob("*.csv"))
    print(f"발견된 파일: {len(csv_files)}개")

    if not csv_files:
        print("처리할 CSV 파일이 없습니다.")
        return

    success_count = 0
    for csv_file in csv_files:
        output_file = output_path / f"reduced_{csv_file.name}"
        try:
            reduce_csv(str(csv_file), str(output_file), reduction_ratio=reduction_ratio)
            success_count += 1
        except Exception as e:
            print(f"✗ 오류: {csv_file.name} - {str(e)}")

    print(f"✓ 배치 처리 완료: {success_count}/{len(csv_files)} 파일 성공")


def batch_remove_duplicates(
    input_folder: str,
    output_folder: str,
    subset: Optional[List[str]] = None
) -> None:
    """
    폴더 내 모든 CSV 파일의 중복을 제거합니다.

    Args:
        input_folder: 입력 폴더 경로
        output_folder: 출력 폴더 경로
        subset: 중복 검사 컬럼 목록

    Example:
        batch_remove_duplicates('./input', './output')
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_files = list(input_path.glob("*.csv"))
    print(f"발견된 파일: {len(csv_files)}개")

    if not csv_files:
        print("처리할 CSV 파일이 없습니다.")
        return

    success_count = 0
    for csv_file in csv_files:
        output_file = output_path / f"dedup_{csv_file.name}"
        try:
            remove_duplicates(str(csv_file), str(output_file), subset=subset)
            success_count += 1
        except Exception as e:
            print(f"✗ 오류: {csv_file.name} - {str(e)}")

    print(f"✓ 배치 처리 완료: {success_count}/{len(csv_files)} 파일 성공")


if __name__ == "__main__":
    # 테스트 코드
    print("CSV Reducer 모듈 테스트")
