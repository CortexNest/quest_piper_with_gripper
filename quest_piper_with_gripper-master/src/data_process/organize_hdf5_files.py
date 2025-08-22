
import os
import shutil

def organize_hdf5_files(source_dir, target_dir):
    """
    遍历源目录，将所有.hdf5文件复制到目标目录并按顺序重命名
    
    参数:
        source_dir: 要搜索的源目录路径
        target_dir: 目标目录路径
    """
    # 确保目标目录存在
    os.makedirs(target_dir, exist_ok=True)
    
    # 计数器
    count = 0
    
    # 遍历源目录及其子目录
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith('.hdf5'):
                # 构建源文件路径
                src_path = os.path.join(root, file)
                
                # 构建目标文件名
                dest_filename = f"episode_{count}.hdf5"
                dest_path = os.path.join(target_dir, dest_filename)
                
                # 复制文件
                shutil.copy2(src_path, dest_path)
                print(f"已复制: {src_path} -> {dest_path}")
                
                # 增加计数器
                count += 1
    
    print(f"完成! 共复制了 {count} 个.hdf5文件")

# 使用示例
source_directory = "/home/synk/questVR_ws-master/src/data_collect/bear_v4"  # 替换为您的源目录路径
target_directory = "/home/synk/questVR_ws-master/src/act_input/bear_v4"  # 替换为目标目录路径

organize_hdf5_files(source_directory, target_directory)
