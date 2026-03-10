"""
CSV 처리 공통 유틸리티 함수
"""

import polars as pl
from pathlib import Path
from typing import List, Optional, Dict, Any
from .config import CSV_READ_OPTIONS, CSV_WRITE_OPTIONS


def load_csv(file_path: str, **kwargs) -> pl.DataFrame:
    """
    CSV 파일을 로드합니다.

    Args:
        file_path: CSV 파일 경로
        **kwargs: polars.read_csv() 추가 인자

    Returns:
        Polars DataFrame
    """
    # config의 옵션을 기본값으로 설정
    options = {**CSV_READ_OPTIONS, **kwargs}
    return pl.read_csv(file_path, **options)


def save_csv(df: pl.DataFrame, file_path: str, **kwargs) -> None:
    """
    DataFrame을 CSV 파일로 저장합니다.

    Args:
        df: Polars DataFrame
        file_path: 저장할 파일 경로
        **kwargs: polars.write_csv() 추가 인자
    """
    # config의 옵션을 기본값으로 설정
    options = {**CSV_WRITE_OPTIONS, **kwargs}
    df.write_csv(file_path, **options)


def get_csv_info(file_path: str) -> Dict[str, Any]:
    """
    CSV 파일의 정보를 반환합니다.

    Args:
        file_path: CSV 파일 경로

    Returns:
        파일 정보 딕셔너리
    """
    df = load_csv(file_path)
    file_size = Path(file_path).stat().st_size

    return {
        'file_path': file_path,
        'file_size_mb': file_size / (1024 * 1024),
        'rows': len(df),
        'columns': len(df.columns),
        'column_names': df.columns,
        'data_types': dict(zip(df.columns, df.dtypes)),
    }


def filter_columns(df: pl.DataFrame, columns: List[str]) -> pl.DataFrame:
    """
    지정한 컬럼만 추출합니다.

    Args:
        df: Polars DataFrame
        columns: 추출할 컬럼 이름 리스트

    Returns:
        필터링된 DataFrame
    """
    valid_cols = [col for col in columns if col in df.columns]
    if not valid_cols:
        raise ValueError(f"유효한 컬럼이 없습니다. 가능한 컬럼: {df.columns}")

    return df.select(valid_cols)


def remove_empty_rows(df: pl.DataFrame) -> pl.DataFrame:
    """
    빈 행을 제거합니다.

    Args:
        df: Polars DataFrame

    Returns:
        빈 행이 제거된 DataFrame
    """
    # 모든 값이 null인 행 제거
    return df.filter(~pl.all_horizontal(pl.col("*").is_null()))


def remove_empty_columns(df: pl.DataFrame) -> pl.DataFrame:
    """
    빈 컬럼을 제거합니다.

    Args:
        df: Polars DataFrame

    Returns:
        빈 컬럼이 제거된 DataFrame
    """
    # 모든 값이 null인 컬럼 제거
    non_empty_cols = [col for col in df.columns
                      if df[col].null_count() < len(df)]
    return df.select(non_empty_cols)


def get_statistics(df: pl.DataFrame) -> Dict[str, Any]:
    """
    DataFrame의 기본 통계를 반환합니다.

    Args:
        df: Polars DataFrame

    Returns:
        통계 정보 딕셔너리
    """
    numeric_cols = df.select(pl.col(pl.Float64, pl.Int64, pl.Int32)).columns

    stats = {}
    for col in numeric_cols:
        col_data = df[col]
        stats[col] = {
            'mean': col_data.mean(),
            'median': col_data.median(),
            'std': col_data.std(),
            'min': col_data.min(),
            'max': col_data.max(),
            'null_count': col_data.null_count(),
        }

    return stats


def split_csv(
    input_file: str,
    output_folder: str,
    chunk_size: int = 10000
) -> None:
    """
    CSV 파일을 여러 개로 분할합니다.

    Args:
        input_file: 입력 CSV 파일 경로
        output_folder: 출력 폴더 경로
        chunk_size: 각 파일당 행 수

    Example:
        split_csv('large_file.csv', './chunks', chunk_size=10000)
    """
    df = load_csv(input_file)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    total_rows = len(df)
    file_count = (total_rows + chunk_size - 1) // chunk_size

    for i in range(file_count):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, total_rows)

        chunk_df = df[start_idx:end_idx]
        output_file = output_path / f"chunk_{i+1:03d}.csv"
        chunk_df.write_csv(str(output_file))

        print(f"생성: {output_file.name} ({len(chunk_df)} 행)")

    print(f"✓ 분할 완료: {file_count}개 파일 생성")


def convert_column_types(
    df: pl.DataFrame,
    type_mapping: Dict[str, str]
) -> pl.DataFrame:
    """
    컬럼의 데이터 타입을 변환합니다.

    Args:
        df: Polars DataFrame
        type_mapping: {컬럼명: 타입} 딕셔너리

    Example:
        df = convert_column_types(df, {'age': 'int32', 'price': 'float64'})
    """
    type_map = {
        'int32': pl.Int32,
        'int64': pl.Int64,
        'float32': pl.Float32,
        'float64': pl.Float64,
        'string': pl.Utf8,
        'bool': pl.Boolean,
    }

    for col, type_name in type_mapping.items():
        if col in df.columns:
            polars_type = type_map.get(type_name.lower())
            if polars_type:
                df = df.with_columns(pl.col(col).cast(polars_type))

    return df


def batch_split_csv(
    input_folder: str,
    output_folder: str,
    chunk_size: int = 10000
) -> None:
    """
    폴더 내 모든 CSV 파일을 분할합니다.

    각 CSV 파일마다 하위 폴더가 생성되고, 그 안에 청크 파일들이 저장됩니다.

    Args:
        input_folder: 입력 폴더 경로
        output_folder: 출력 폴더 경로
        chunk_size: 각 청크의 행 수

    Example:
        batch_split_csv('./input', './output', chunk_size=5000)
        # output/file1/, output/file2/ 등 하위폴더 생성
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(list(input_path.glob("*.csv")))
    print(f"발견된 파일: {len(csv_files)}개")

    if not csv_files:
        print("처리할 CSV 파일이 없습니다.")
        return

    success_count = 0
    for csv_file in csv_files:
        # 각 파일마다 하위 폴더 생성
        file_output_folder = output_path / csv_file.stem
        try:
            split_csv(str(csv_file), str(file_output_folder), chunk_size=chunk_size)
            success_count += 1
        except Exception as e:
            print(f"✗ 오류: {csv_file.name} - {str(e)}")

    print(f"✓ 배치 분할 완료: {success_count}/{len(csv_files)} 파일 성공")
