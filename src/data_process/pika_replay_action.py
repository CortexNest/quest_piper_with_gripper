from Robotic_Arm.rm_robot_interface import *
import numpy as np
import h5py
import time
from scipy.spatial.transform import Rotation as R
from piper_sdk import *
from src.hardware.sensors.pika_sensor import PikaPublisher,PikaRecorder
from tqdm import tqdm

def enable_fun(piper: C_PiperInterface_V2, enable: bool) -> bool:
    """
    使能机械臂并检测使能状态,尝试5s,如果使能超时则退出程序
    Args:
        piper: 机械臂控制接口
        enable: True-使能, False-禁用
    Returns:
        bool: 操作是否成功
    """
    timeout = 5  # 设置超时时间（sec）
    start_time = time.time()
    while True:
        enable_status = [
            piper.GetArmLowSpdInfoMsgs().motor_1.foc_status.driver_enable_status,
            piper.GetArmLowSpdInfoMsgs().motor_2.foc_status.driver_enable_status,
            piper.GetArmLowSpdInfoMsgs().motor_3.foc_status.driver_enable_status,
            piper.GetArmLowSpdInfoMsgs().motor_4.foc_status.driver_enable_status,
            piper.GetArmLowSpdInfoMsgs().motor_5.foc_status.driver_enable_status,
            piper.GetArmLowSpdInfoMsgs().motor_6.foc_status.driver_enable_status,
        ]
        current_state = all(enable_status) if enable else not any(enable_status)
        if current_state:
            return True
        if enable:
            piper.EnableArm(7)
            piper.GripperCtrl(0, 1000, 0x01, 0)
        else:
            piper.DisableArm(7)
            piper.GripperCtrl(0, 1000, 0x02, 0)
        if time.time() - start_time > timeout:
            print(
                f"enable / disable piper timeout, target state: {'enable' if enable else 'disable'}"
            )
            return False
        time.sleep(0.5)


import math

def set_joints(arm: C_PiperInterface_V2, joint_rad):
    """
    输入关节角度单位为弧度(rad)，内部转换为度(deg)后发送给机械臂
    
    Args:
        arm: 机械臂接口实例
        joint_rad: 长度为6的列表，每个元素为关节角度（弧度）
    """
    # 将弧度转换为度（乘以180/pi）
    joint_deg = [math.degrees(rad) for rad in joint_rad]
    
    arm.MotionCtrl_2(
        ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=20, is_mit_mode=0x00
    )
    arm.JointCtrl(
        round(joint_deg[0] * 1000),  
        round(joint_deg[1] * 1000),
        round(joint_deg[2] * 1000),
        round(joint_deg[3] * 1000),
        round(joint_deg[4] * 1000),
        round(joint_deg[5] * 1000),
    )


import math  # 确保导入math模块用于单位转换

def set_joints_canfd(arm: C_PiperInterface_V2, joint_rad):
    """
    输入关节角度单位为弧度(rad)，内部转换为度(deg)后发送给机械臂
    
    Args:
        arm: 机械臂接口实例
        joint_rad: 长度为6的列表，每个元素为关节角度（弧度）
    """
    # 将弧度转换为度（乘以180/pi）
    joint_deg = [math.degrees(rad) for rad in joint_rad]
    
    arm.MotionCtrl_2(
        ctrl_mode=0x01, move_mode=0x01, move_spd_rate_ctrl=100, is_mit_mode=0x00
    )
    arm.JointCtrl(
        round(joint_deg[0] * 1000),
        round(joint_deg[1] * 1000),
        round(joint_deg[2] * 1000),
        round(joint_deg[3] * 1000),
        round(joint_deg[4] * 1000),
        round(joint_deg[5] * 1000),
    )

import argparse

# 创建命令行参数解析器
parser = argparse.ArgumentParser(description='指定数据目录路径')
# 添加命令行参数，--input_file 为参数名，dest 用于指定变量名，required 表示是否必传
parser.add_argument('--input_file', dest='input_file', required=True, help='数据目录路径')

# 解析命令行参数
args = parser.parse_args()

# 此时 args.input_file 即为命令行输入的路径
input_file = args.input_file

arm = C_PiperInterface_V2()
arm.ConnectPort()
# # 设置机械臂重置，从mit或者示教模式切换为位置速度控制模式待机
# arm.MotionCtrl_1(
#     emergency_stop=0x02,
#     track_ctrl=0,
#     grag_teach_ctrl=0
# )
# arm.MotionCtrl_2(
#     ctrl_mode=0, 
#     move_mode=0, 
#     move_spd_rate_ctrl=0, 
#     is_mit_mode=0x00
# )

# 机械臂使能
if enable_fun(piper=arm, enable=True):
    print("enable piper success")
else:
    raise Exception("enable piper failed")

# # 设置机械臂默认参数
# arm.ArmParamEnquiryAndConfig(
#     param_enquiry=0x01,
#     param_setting=0x02,
#     data_feedback_0x48x=0,
#     end_load_param_setting_effective=0,
#     set_end_load=0x02
# )

# 输入弧度值（你的数据）
joints_rad = [
    0.00036632400000000007,
    -0.017112564,
    0.033021492,
    0.0052680879999999998,
    0.093430064000000007,
    0.0083207880000000008,
]

# 调用函数（此时输入单位为弧度）
set_joints(arm, joints_rad)
print("Set initial joint angles to:", [
    0.00036632400000000007,
    -0.017112564,
    0.033021492,
    0.0052680879999999998,
    0.093430064000000007,
    0.0083207880000000008,
])

time.sleep(1)

pub = PikaPublisher()
recorder = PikaRecorder()

pub.enable_gripper()
pub.set_gripper_angle(1.5)    

with h5py.File(input_file, 'r') as f_in:
    action_data = f_in['action'][:]
    for i in tqdm(range(len(action_data)), desc="Replaying actions"):
        set_joints_canfd(arm, action_data[i][:6])
        pub.set_gripper_angle(action_data[i][6])
        time.sleep(0.05)

set_joints(arm, joints_rad)
pub.disable_gripper()