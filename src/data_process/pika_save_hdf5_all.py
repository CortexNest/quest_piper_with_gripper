import os
import re
import subprocess
import argparse

# 创建命令行参数解析器
parser = argparse.ArgumentParser(description='指定数据目录路径')
# 添加命令行参数，--base_dir 为参数名，dest 用于指定变量名，required 表示是否必传
parser.add_argument('--base_dir', dest='base_dir', required=True, help='数据目录路径')

# 解析命令行参数
args = parser.parse_args()

# 此时 args.base_dir 即为命令行输入的路径
base_dir = args.base_dir

# 数据目录
# base_dir = "/home/synk/questVR_ws-master/src/data_collect/bear_v4"

# 正则匹配 episode 文件夹
pattern = re.compile(r"episode(\d+)")

# 搜集 episode 下标
episode_indices = []
for name in os.listdir(base_dir):
    match = pattern.match(name)
    if match:
        episode_indices.append(int(match.group(1)))

# 排序，方便按顺序执行
episode_indices.sort()

print("找到的 episode 下标:", episode_indices)

# 要执行的脚本路径
script_path = "/home/synk/questVR_ws-master/src/data_process/pika_save_hdf5.py"

# 逐个执行
for idx in episode_indices:
    cmd = [
        "python", script_path,
        "--datasetDir", base_dir,
        "--episodeIndex", str(idx),
        "--cameraColorNames", "pikaGripperDepthCameraColor,pikaGripperFisheyeCamera",
        "--cameraDepthNames", "pikaGripperDepthCameraDepth",
        "--cameraPointCloudNames", "",
        "--useCameraPointCloud", "False",
        "--useCameraPointCloudNormalization", "False",
        "--localizationPoseNames", "master",
        "--gripperEncoderNames", "pikaGripper",
    ]
    print(f"\n执行 episode {idx}:")
    subprocess.run(cmd)
