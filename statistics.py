import os

def count_lines_in_directory(directory):
    total_lines = 0
    # 遍历目录
    for root, dirs, files in os.walk(directory):
        # 筛选 .py 文件
        for file in files:
            if file.endswith(".html"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        # 统计文件中的行数
                        lines = f.readlines()
                        total_lines += len(lines)
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")
    return total_lines

if __name__ == "__main__":
    project_directory = input("请输入项目目录路径: ")
    total = count_lines_in_directory(project_directory)
    print(f"项目中 .py 源码总行数: {total}")