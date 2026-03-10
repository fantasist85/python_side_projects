"""
CSV 파일 시각화 기능

이미지로 변환하고, 다양한 그래프를 생성합니다.
"""

import polars as pl
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import List, Optional, Tuple
from .csv_utils import load_csv


def csv_to_image(
    input_file: str,
    output_file: str,
    x_column: str,
    y_columns: List[str],
    chart_type: str = "line",
    title: Optional[str] = None,
    figsize: Tuple[int, int] = (12, 6),
    dpi: int = 100
) -> None:
    """
    CSV 파일을 이미지로 변환합니다.

    Args:
        input_file: 입력 CSV 파일 경로
        output_file: 출력 이미지 파일 경로
        x_column: X축 컬럼 이름
        y_columns: Y축 컬럼 이름 리스트
        chart_type: 차트 유형 ("line", "scatter", "bar", "box")
        title: 차트 제목
        figsize: 그림 크기 (가로, 세로)
        dpi: 해상도

    Example:
        csv_to_image('data.csv', 'chart.png',
                     x_column='time',
                     y_columns=['temp', 'humidity'],
                     chart_type='line')
    """
    # CSV 파일 읽기
    df = load_csv(input_file)

    # 그림 생성
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    if chart_type == "line":
        plot_line_chart(ax, df, x_column, y_columns)
    elif chart_type == "scatter":
        plot_scatter_chart(ax, df, x_column, y_columns)
    elif chart_type == "bar":
        plot_bar_chart(ax, df, x_column, y_columns)
    elif chart_type == "box":
        plot_box_chart(ax, df, y_columns)
    else:
        raise ValueError(f"미지원 차트 유형: {chart_type}")

    # 제목 설정
    if title:
        ax.set_title(title, fontsize=16, fontweight='bold')
    else:
        ax.set_title(f"{chart_type.capitalize()} Chart", fontsize=16, fontweight='bold')

    # X축 레이블 설정 (박스플롯 제외)
    if chart_type != "box":
        ax.set_xlabel(x_column, fontsize=12)

    # 범례 추가
    ax.legend(loc='best', fontsize=10)

    # 레이아웃 최적화
    plt.tight_layout()

    # 이미지 저장
    plt.savefig(output_file, dpi=dpi, bbox_inches='tight')
    plt.close()

    print(f"✓ 이미지 생성 완료: {output_file}")


def plot_line_chart(ax, df: pl.DataFrame, x_column: str, y_columns: List[str]) -> None:
    """선 그래프를 그립니다."""
    for y_col in y_columns:
        ax.plot(df[x_column], df[y_col], marker='o', label=y_col, linewidth=2)

    ax.set_ylabel('Value', fontsize=12)
    ax.grid(True, alpha=0.3)


def plot_scatter_chart(ax, df: pl.DataFrame, x_column: str, y_columns: List[str]) -> None:
    """산점도를 그립니다."""
    for y_col in y_columns:
        ax.scatter(df[x_column], df[y_col], label=y_col, s=50, alpha=0.7)

    ax.set_ylabel('Value', fontsize=12)
    ax.grid(True, alpha=0.3)


def plot_bar_chart(ax, df: pl.DataFrame, x_column: str, y_columns: List[str]) -> None:
    """막대 그래프를 그립니다."""
    x = range(len(df))
    width = 0.8 / len(y_columns)

    for i, y_col in enumerate(y_columns):
        offset = (i - len(y_columns) / 2) * width
        ax.bar([pos + offset for pos in x], df[y_col], width=width, label=y_col)

    ax.set_ylabel('Value', fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(df[x_column], rotation=45, ha='right')
    ax.grid(True, alpha=0.3, axis='y')


def plot_box_chart(ax, df: pl.DataFrame, y_columns: List[str]) -> None:
    """박스플롯을 그립니다."""
    data_to_plot = [df[col].to_numpy() for col in y_columns]
    ax.boxplot(data_to_plot, labels=y_columns)
    ax.set_ylabel('Value', fontsize=12)
    ax.grid(True, alpha=0.3, axis='y')


def create_heatmap(
    input_file: str,
    output_file: str,
    title: Optional[str] = None,
    figsize: Tuple[int, int] = (10, 8),
    dpi: int = 100
) -> None:
    """
    CSV 파일을 히트맵으로 표현합니다.

    Args:
        input_file: 입력 CSV 파일 경로
        output_file: 출력 이미지 파일 경로
        title: 차트 제목
        figsize: 그림 크기
        dpi: 해상도
    """
    df = load_csv(input_file)

    # 숫자 컬럼만 선택
    numeric_df = df.select(pl.col(pl.Float64, pl.Int64, pl.Int32))

    # 히트맵 생성
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    sns.heatmap(numeric_df.to_numpy(), annot=True, fmt='.2f', cmap='coolwarm', ax=ax)

    if title:
        ax.set_title(title, fontsize=14, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_file, dpi=dpi, bbox_inches='tight')
    plt.close()

    print(f"✓ 히트맵 생성 완료: {output_file}")


def batch_convert_to_images(
    input_folder: str,
    output_folder: str,
    x_column: str,
    y_columns: List[str],
    chart_type: str = "line"
) -> None:
    """
    폴더 내 모든 CSV 파일을 이미지로 변환합니다.

    Args:
        input_folder: 입력 폴더 경로
        output_folder: 출력 폴더 경로
        x_column: X축 컬럼
        y_columns: Y축 컬럼
        chart_type: 차트 유형
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_files = list(input_path.glob("*.csv"))
    print(f"발견된 파일: {len(csv_files)}개")

    for csv_file in csv_files:
        output_file = output_path / f"{csv_file.stem}.png"
        try:
            csv_to_image(str(csv_file), str(output_file),
                        x_column, y_columns, chart_type)
        except Exception as e:
            print(f"✗ 오류: {csv_file} - {str(e)}")

    print(f"✓ 배치 변환 완료: {len(csv_files)}개 파일 처리")


def batch_create_heatmap(
    input_folder: str,
    output_folder: str
) -> None:
    """
    폴더 내 모든 CSV 파일의 히트맵을 생성합니다.

    Args:
        input_folder: 입력 폴더 경로
        output_folder: 출력 폴더 경로

    Example:
        batch_create_heatmap('./input', './output')
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
        output_file = output_path / f"{csv_file.stem}.png"
        try:
            create_heatmap(str(csv_file), str(output_file))
            success_count += 1
        except Exception as e:
            print(f"✗ 오류: {csv_file.name} - {str(e)}")

    print(f"✓ 배치 히트맵 생성 완료: {success_count}/{len(csv_files)} 파일 성공")


if __name__ == "__main__":
    print("CSV Visualizer 모듈 테스트")
