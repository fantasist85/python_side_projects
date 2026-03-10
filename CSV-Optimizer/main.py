"""
CSV-Optimizer 메인 실행 파일

CLI 인터페이스를 제공합니다.
"""

import argparse
import sys
from pathlib import Path

from src.csv_reducer import reduce_csv, remove_duplicates, batch_reduce_csv, batch_remove_duplicates
from src.csv_merger import merge_csv_files, batch_merge_csv
from src.csv_visualizer import csv_to_image, create_heatmap, batch_convert_to_images, batch_create_heatmap
from src.csv_utils import get_csv_info, get_statistics, split_csv, load_csv, batch_split_csv


def main():
    parser = argparse.ArgumentParser(
        description='CSV-Optimizer: CSV 파일 편집 및 가공 도구',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
사용 예제:
  # 단일 파일 작업
  python main.py reduce -i data.csv -r 50
  python main.py merge -i file1.csv file2.csv -t timestamp
  python main.py visualize -i data.csv -x time -y temp humidity
  python main.py info -i data.csv

  # 폴더 내 일괄작업 (배치)
  python main.py batch reduce -i ./input -o ./output -r 25
  python main.py batch merge -i ./input -o ./merged.csv
  python main.py batch visualize -i ./input -o ./output -x time -y value
  python main.py batch dedup -i ./input -o ./output
  python main.py batch split -i ./input -o ./output --chunk-size 5000
  python main.py batch heatmap -i ./input -o ./output
        '''
    )

    subparsers = parser.add_subparsers(dest='command', help='실행할 명령어')

    # 축소 명령어
    reduce_parser = subparsers.add_parser('reduce', help='CSV 파일 축소')
    reduce_parser.add_argument('-i', '--input', required=True, help='입력 CSV 파일')
    reduce_parser.add_argument('-o', '--output', help='출력 파일 (기본값: reduced_<input>)')
    reduce_parser.add_argument('-r', '--ratio', type=float, default=50,
                             help='삭제 비율 (0-100, 기본값: 50)')

    # 병합 명령어
    merge_parser = subparsers.add_parser('merge', help='CSV 파일 병합')
    merge_parser.add_argument('-i', '--input', nargs='+', required=True,
                            help='입력 CSV 파일 (2개 이상)')
    merge_parser.add_argument('-o', '--output', required=True, help='출력 파일')
    merge_parser.add_argument('-t', '--time-column', help='시간 컬럼 이름')

    # 시각화 명령어
    viz_parser = subparsers.add_parser('visualize', help='CSV를 이미지로 변환')
    viz_parser.add_argument('-i', '--input', required=True, help='입력 CSV 파일')
    viz_parser.add_argument('-o', '--output', help='출력 이미지 파일')
    viz_parser.add_argument('-x', '--x-column', required=True, help='X축 컬럼')
    viz_parser.add_argument('-y', '--y-columns', nargs='+', required=True, help='Y축 컬럼들')
    viz_parser.add_argument('--chart-type', default='line', choices=['line', 'scatter', 'bar'],
                           help='차트 유형 (기본값: line)')

    # 정보 조회 명령어
    info_parser = subparsers.add_parser('info', help='CSV 파일 정보 조회')
    info_parser.add_argument('-i', '--input', required=True, help='입력 CSV 파일')
    info_parser.add_argument('--stats', action='store_true', help='통계 정보도 표시')

    # 중복 제거 명령어
    dedup_parser = subparsers.add_parser('dedup', help='중복 제거')
    dedup_parser.add_argument('-i', '--input', required=True, help='입력 CSV 파일')
    dedup_parser.add_argument('-o', '--output', required=True, help='출력 파일')

    # 파일 분할 명령어
    split_parser = subparsers.add_parser('split', help='CSV 파일 분할')
    split_parser.add_argument('-i', '--input', required=True, help='입력 CSV 파일')
    split_parser.add_argument('-o', '--output', required=True, help='출력 폴더')
    split_parser.add_argument('--chunk-size', type=int, default=10000, help='청크 크기')

    # 히트맵 명령어
    heatmap_parser = subparsers.add_parser('heatmap', help='히트맵 생성')
    heatmap_parser.add_argument('-i', '--input', required=True, help='입력 CSV 파일')
    heatmap_parser.add_argument('-o', '--output', required=True, help='출력 이미지 파일')

    # 배치 작업 명령어
    batch_parser = subparsers.add_parser('batch', help='폴더 내 일괄작업')
    batch_subparsers = batch_parser.add_subparsers(dest='batch_command', required=True, help='배치 작업 유형')

    # batch reduce
    batch_reduce_parser = batch_subparsers.add_parser('reduce', help='폴더 내 모든 CSV 축소')
    batch_reduce_parser.add_argument('-i', '--input', required=True, help='입력 폴더')
    batch_reduce_parser.add_argument('-o', '--output', required=True, help='출력 폴더')
    batch_reduce_parser.add_argument('-r', '--ratio', type=float, default=50,
                                   help='삭제 비율 (0-100, 기본값: 50)')

    # batch merge
    batch_merge_parser = batch_subparsers.add_parser('merge', help='폴더 내 모든 CSV 병합')
    batch_merge_parser.add_argument('-i', '--input', required=True, help='입력 폴더')
    batch_merge_parser.add_argument('-o', '--output', required=True, help='출력 파일')
    batch_merge_parser.add_argument('-t', '--time-column', help='시간 컬럼 이름')

    # batch visualize
    batch_viz_parser = batch_subparsers.add_parser('visualize', help='폴더 내 모든 CSV를 이미지로 변환')
    batch_viz_parser.add_argument('-i', '--input', required=True, help='입력 폴더')
    batch_viz_parser.add_argument('-o', '--output', required=True, help='출력 폴더')
    batch_viz_parser.add_argument('-x', '--x-column', required=True, help='X축 컬럼')
    batch_viz_parser.add_argument('-y', '--y-columns', nargs='+', required=True, help='Y축 컬럼들')
    batch_viz_parser.add_argument('--chart-type', default='line', choices=['line', 'scatter', 'bar'],
                                 help='차트 유형 (기본값: line)')

    # batch dedup
    batch_dedup_parser = batch_subparsers.add_parser('dedup', help='폴더 내 모든 CSV 중복 제거')
    batch_dedup_parser.add_argument('-i', '--input', required=True, help='입력 폴더')
    batch_dedup_parser.add_argument('-o', '--output', required=True, help='출력 폴더')

    # batch split
    batch_split_parser = batch_subparsers.add_parser('split', help='폴더 내 모든 CSV 분할')
    batch_split_parser.add_argument('-i', '--input', required=True, help='입력 폴더')
    batch_split_parser.add_argument('-o', '--output', required=True, help='출력 폴더')
    batch_split_parser.add_argument('--chunk-size', type=int, default=10000, help='청크 크기')

    # batch heatmap
    batch_heatmap_parser = batch_subparsers.add_parser('heatmap', help='폴더 내 모든 CSV 히트맵 생성')
    batch_heatmap_parser.add_argument('-i', '--input', required=True, help='입력 폴더')
    batch_heatmap_parser.add_argument('-o', '--output', required=True, help='출력 폴더')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == 'reduce':
            output = args.output or f"reduced_{Path(args.input).name}"
            reduce_csv(args.input, output, reduction_ratio=args.ratio)

        elif args.command == 'merge':
            if len(args.input) < 2:
                print("오류: 최소 2개 이상의 파일을 지정해주세요.")
                sys.exit(1)
            merge_csv_files(args.input, args.output, time_column=args.time_column)

        elif args.command == 'visualize':
            output = args.output or f"{Path(args.input).stem}.png"
            csv_to_image(args.input, output, args.x_column, args.y_columns,
                        chart_type=args.chart_type)

        elif args.command == 'info':
            info = get_csv_info(args.input)
            print(f"\n파일: {info['file_path']}")
            print(f"크기: {info['file_size_mb']:.2f} MB")
            print(f"행: {info['rows']:,}, 컬럼: {info['columns']}")
            print(f"컬럼 목록: {', '.join(info['column_names'])}")

            if args.stats:
                df = load_csv(args.input)
                stats = get_statistics(df)
                print("\n통계:")
                for col, stat in stats.items():
                    print(f"  {col}: mean={stat.get('mean', 'N/A')}, "
                         f"std={stat.get('std', 'N/A')}")

        elif args.command == 'dedup':
            remove_duplicates(args.input, args.output)

        elif args.command == 'split':
            split_csv(args.input, args.output, chunk_size=args.chunk_size)

        elif args.command == 'heatmap':
            create_heatmap(args.input, args.output)

        elif args.command == 'batch':
            # 배치 작업 처리
            if args.batch_command == 'reduce':
                batch_reduce_csv(args.input, args.output, reduction_ratio=args.ratio)

            elif args.batch_command == 'merge':
                batch_merge_csv(args.input, args.output, time_column=args.time_column)

            elif args.batch_command == 'visualize':
                batch_convert_to_images(args.input, args.output,
                                      args.x_column, args.y_columns,
                                      chart_type=args.chart_type)

            elif args.batch_command == 'dedup':
                batch_remove_duplicates(args.input, args.output)

            elif args.batch_command == 'split':
                batch_split_csv(args.input, args.output, chunk_size=args.chunk_size)

            elif args.batch_command == 'heatmap':
                batch_create_heatmap(args.input, args.output)

    except Exception as e:
        print(f"오류: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
