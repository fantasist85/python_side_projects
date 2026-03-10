"""
CSV 파일 병합 기능

서로 다른 시간 스케일의 데이터를 병합하고, 시계열 데이터를 정렬합니다.
"""

import polars as pl
from pathlib import Path
from typing import List, Optional
from .csv_utils import load_csv, save_csv


def merge_csv_files(
    input_files: List[str],
    output_file: str,
    time_column: Optional[str] = None,
    how: str = "outer",
    interpolate: bool = True
) -> None:
    """
    여러 CSV 파일을 병합합니다.

    Args:
        input_files: 입력 CSV 파일 경로 리스트
        output_file: 출력 CSV 파일 경로
        time_column: 시간 컬럼 이름 (타임 시리즈 병합 시 사용)
        how: 병합 방식 ("inner", "outer", "left", "right")
        interpolate: 누락된 값 보간 여부

    Example:
        merge_csv_files(['data_a.csv', 'data_b.csv'],
                       output='merged.csv',
                       time_column='timestamp')
    """
    if not input_files:
        raise ValueError("최소 1개 이상의 입력 파일이 필요합니다.")

    # 첫 번째 파일 로드
    df_merged = load_csv(input_files[0])
    print(f"로드: {input_files[0]} ({len(df_merged)} 행)")

    # 나머지 파일 병합
    for input_file in input_files[1:]:
        df = load_csv(input_file)
        print(f"로드: {input_file} ({len(df)} 행)")

        if time_column and time_column in df_merged.columns and time_column in df.columns:
            # 시간 기반 병합
            df_merged = merge_by_time(
                df_merged, df,
                time_column=time_column,
                how=how
            )
        else:
            # 행 단위 병합 (같은 구조의 파일들을 연결)
            df_merged = pl.concat([df_merged, df])

    # 보간 처리
    if interpolate and time_column:
        df_merged = interpolate_data(df_merged, time_column)

    # 중복 제거
    df_merged = df_merged.unique()

    # 결과 저장
    save_csv(df_merged, output_file)
    print(f"\n✓ 병합 완료: {len(df_merged)} 행")
    print(f"  출력: {output_file}")


def merge_by_time(
    df1: pl.DataFrame,
    df2: pl.DataFrame,
    time_column: str,
    how: str = "outer"
) -> pl.DataFrame:
    """
    시간 컬럼 기준으로 두 데이터프레임을 병합합니다.

    Args:
        df1: 첫 번째 데이터프레임
        df2: 두 번째 데이터프레임
        time_column: 시간 컬럼 이름
        how: 병합 방식

    Returns:
        병합된 데이터프레임
    """
    # 시간 컬럼 기준 정렬
    df1 = df1.sort(time_column)
    df2 = df2.sort(time_column)

    # 병합
    merged = df1.join(df2, on=time_column, how=how, suffix="_b")

    return merged.sort(time_column)


def interpolate_data(
    df: pl.DataFrame,
    time_column: str
) -> pl.DataFrame:
    """
    누락된 값을 선형 보간으로 채웁니다.

    Args:
        df: 데이터프레임
        time_column: 시간 컬럼 이름

    Returns:
        보간된 데이터프레임
    """
    # 숫자 컬럼만 보간
    numeric_cols = df.select(pl.col(pl.Float64, pl.Int64, pl.Int32)).columns

    for col in numeric_cols:
        # 선형 보간
        df = df.with_columns(
            pl.col(col).fill_null(strategy="forward")
            .fill_null(strategy="backward")
        )

    return df


def merge_and_synchronize(
    df_a: pl.DataFrame,
    df_b: pl.DataFrame,
    time_col_a: str,
    time_col_b: str,
    sync_method: str = "resample"
) -> pl.DataFrame:
    """
    서로 다른 시간 스케일의 데이터를 동기화합니다.

    Args:
        df_a: 데이터프레임 A
        df_b: 데이터프레임 B
        time_col_a: A의 시간 컬럼
        time_col_b: B의 시간 컬럼
        sync_method: 동기화 방법 ("resample", "merge", "interpolate")

    Returns:
        동기화된 데이터프레임

    Example:
        # A: 1초 간격, B: 10초 간격 데이터
        merged = merge_and_synchronize(df_a, df_b,
                                      time_col_a='timestamp',
                                      time_col_b='time')
    """
    if sync_method == "resample":
        # 더 큰 간격의 데이터를 작은 간격으로 리샘플링
        df_a = df_a.sort(time_col_a)
        df_b = df_b.sort(time_col_b)

        # 시간 컬럼 정규화
        df_a = df_a.rename({time_col_a: "time"})
        df_b = df_b.rename({time_col_b: "time"})

        # 병합
        merged = df_a.join(df_b, on="time", how="outer", suffix="_b")
        merged = merged.sort("time")

        # 보간
        numeric_cols = merged.select(
            pl.col(pl.Float64, pl.Int64, pl.Int32)
        ).columns
        for col in numeric_cols:
            merged = merged.with_columns(
                pl.col(col).fill_null(strategy="forward")
                .fill_null(strategy="backward")
            )

        return merged

    elif sync_method == "merge":
        return merge_by_time(df_a, df_b, "time", how="outer")

    else:
        raise ValueError(f"미지원 동기화 방법: {sync_method}")


def batch_merge_csv(
    input_folder: str,
    output_file: str,
    time_column: Optional[str] = None
) -> None:
    """
    폴더 내 모든 CSV 파일을 하나의 파일로 병합합니다.

    Args:
        input_folder: 입력 폴더 경로
        output_file: 출력 CSV 파일 경로
        time_column: 시간 컬럼 이름 (시계열 병합 시 사용)

    Example:
        batch_merge_csv('./input', './merged.csv', time_column='timestamp')
    """
    input_path = Path(input_folder)
    csv_files = sorted(list(input_path.glob("*.csv")))

    print(f"발견된 파일: {len(csv_files)}개")

    if not csv_files:
        print("처리할 CSV 파일이 없습니다.")
        return

    # 모든 CSV 파일 경로를 문자열 리스트로 변환
    input_files = [str(f) for f in csv_files]

    try:
        merge_csv_files(input_files, output_file, time_column=time_column)
        print(f"✓ 배치 병합 완료: {len(csv_files)}개 파일 통합")
    except Exception as e:
        print(f"✗ 오류: 병합 실패 - {str(e)}")


if __name__ == "__main__":
    print("CSV Merger 모듈 테스트")
