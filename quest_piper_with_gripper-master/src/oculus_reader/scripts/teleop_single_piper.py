#!/usr/bin/env python3
import signal

import pexpect
import rospy
import tf2_ros
import rospkg
import geometry_msgs.msg
from tf.transformations import quaternion_from_matrix
from tf.transformations import quaternion_from_euler, quaternion_from_matrix

import casadi
import meshcat.geometry as mg
import pinocchio as pin
from pinocchio import casadi as cpin
from pinocchio.visualize import MeshcatVisualizer
from oculus_reader import OculusReader
from pathlib import Path

import os
import numpy as np
import math
import time
import re
import subprocess

from tools import MATHTOOLS
from piper_control import PIPER

import argparse

def matrix_to_xyzrpy(matrix):
    x = matrix[0, 3]
    y = matrix[1, 3]
    z = matrix[2, 3]
    roll = math.atan2(matrix[2, 1], matrix[2, 2])
    pitch = math.asin(-matrix[2, 0])
    yaw = math.atan2(matrix[1, 0], matrix[0, 0])
    return [x, y, z, roll, pitch, yaw]

def create_transformation_matrix(x, y, z, roll, pitch, yaw):
    transformation_matrix = np.eye(4)
    A = np.cos(yaw)
    B = np.sin(yaw)
    C = np.cos(pitch)
    D = np.sin(pitch)
    E = np.cos(roll)
    F = np.sin(roll)
    DE = D * E
    DF = D * F
    transformation_matrix[0, 0] = A * C
    transformation_matrix[0, 1] = A * DF - B * E
    transformation_matrix[0, 2] = B * F + A * DE
    transformation_matrix[0, 3] = x
    transformation_matrix[1, 0] = B * C
    transformation_matrix[1, 1] = A * E + B * DF
    transformation_matrix[1, 2] = B * DE - A * F
    transformation_matrix[1, 3] = y
    transformation_matrix[2, 0] = -D
    transformation_matrix[2, 1] = C * F
    transformation_matrix[2, 2] = C * E
    transformation_matrix[2, 3] = z
    transformation_matrix[3, 0] = 0
    transformation_matrix[3, 1] = 0
    transformation_matrix[3, 2] = 0
    transformation_matrix[3, 3] = 1
    return transformation_matrix

def calc_pose_incre(base_pose, pose_data):
    begin_matrix = create_transformation_matrix(base_pose[0], base_pose[1], base_pose[2],
                                                base_pose[3], base_pose[4], base_pose[5])
    zero_matrix = create_transformation_matrix(0.19, 0.0, 0.2, 0, 0, 0)
    end_matrix = create_transformation_matrix(pose_data[0], pose_data[1], pose_data[2],
                                            pose_data[3], pose_data[4], pose_data[5])
    result_matrix = np.dot(zero_matrix, np.dot(np.linalg.inv(begin_matrix), end_matrix))
    xyzrpy = matrix_to_xyzrpy(result_matrix)
    return xyzrpy

class Arm_IK:
    def __init__(self):
        np.set_printoptions(precision=5, suppress=True, linewidth=200)

        rospack = rospkg.RosPack()
        package_path = rospack.get_path('piper_description') 

        urdf_path = os.path.join(package_path, 'urdf', 'piper_description.urdf')
        
        self.robot = pin.RobotWrapper.BuildFromURDF(urdf_path)

        self.mixed_jointsToLockIDs = ["joint7",
                                      "joint8"
                                      ]

        self.reduced_robot = self.robot.buildReducedRobot(
            list_of_joints_to_lock=self.mixed_jointsToLockIDs,
            reference_configuration=np.array([0] * self.robot.model.nq),
        )

        self.first_matrix = create_transformation_matrix(0, 0, 0, 0, -1.57, 0)
        self.second_matrix = create_transformation_matrix(0.13, 0.0, 0.0, 0, 0, 0)  #第六轴到末端夹爪坐标的变换矩阵
        self.last_matrix = np.dot(self.first_matrix, self.second_matrix)
        q = quaternion_from_matrix(self.last_matrix)
        self.reduced_robot.model.addFrame(
            pin.Frame('ee',
                      self.reduced_robot.model.getJointId('joint6'),
                      pin.SE3(
                          # pin.Quaternion(1, 0, 0, 0),
                          pin.Quaternion(q[3], q[0], q[1], q[2]),
                          np.array([self.last_matrix[0, 3], self.last_matrix[1, 3], self.last_matrix[2, 3]]),  # -y
                      ),
                      pin.FrameType.OP_FRAME)
        )

        self.geom_model = pin.buildGeomFromUrdf(self.robot.model, urdf_path, pin.GeometryType.COLLISION)
        for i in range(4, 9):
            for j in range(0, 3):
                self.geom_model.addCollisionPair(pin.CollisionPair(i, j))
        self.geometry_data = pin.GeometryData(self.geom_model)

        self.init_data = np.zeros(self.reduced_robot.model.nq)
        self.history_data = np.zeros(self.reduced_robot.model.nq)

        # # Initialize the Meshcat visualizer  for visualization
        self.vis = MeshcatVisualizer(self.reduced_robot.model, self.reduced_robot.collision_model, self.reduced_robot.visual_model)
        self.vis.initViewer(open=True)
        self.vis.loadViewerModel("pinocchio")
        self.vis.displayFrames(True, frame_ids=[113, 114], axis_length=0.15, axis_width=5)
        self.vis.display(pin.neutral(self.reduced_robot.model))

        # Enable the display of end effector target frames with short axis lengths and greater width.
        frame_viz_names = ['ee_target']
        FRAME_AXIS_POSITIONS = (
            np.array([[0, 0, 0], [1, 0, 0],
                      [0, 0, 0], [0, 1, 0],
                      [0, 0, 0], [0, 0, 1]]).astype(np.float32).T
        )
        FRAME_AXIS_COLORS = (
            np.array([[1, 0, 0], [1, 0.6, 0],
                      [0, 1, 0], [0.6, 1, 0],
                      [0, 0, 1], [0, 0.6, 1]]).astype(np.float32).T
        )
        axis_length = 0.1
        axis_width = 10
        for frame_viz_name in frame_viz_names:
            self.vis.viewer[frame_viz_name].set_object(
                mg.LineSegments(
                    mg.PointsGeometry(
                        position=axis_length * FRAME_AXIS_POSITIONS,
                        color=FRAME_AXIS_COLORS,
                    ),
                    mg.LineBasicMaterial(
                        linewidth=axis_width,
                        vertexColors=True,
                    ),
                )
            )

        # Creating Casadi models and data for symbolic computing
        self.cmodel = cpin.Model(self.reduced_robot.model)
        self.cdata = self.cmodel.createData()

        # Creating symbolic variables
        self.cq = casadi.SX.sym("q", self.reduced_robot.model.nq, 1)
        self.cTf = casadi.SX.sym("tf", 4, 4)
        cpin.framesForwardKinematics(self.cmodel, self.cdata, self.cq)

        # # Get the hand joint ID and define the error function
        self.gripper_id = self.reduced_robot.model.getFrameId("ee")
        self.error = casadi.Function(
            "error",
            [self.cq, self.cTf],
            [
                casadi.vertcat(
                    cpin.log6(
                        self.cdata.oMf[self.gripper_id].inverse() * cpin.SE3(self.cTf)
                    ).vector,
                )
            ],
        )

        # Defining the optimization problem
        self.opti = casadi.Opti()
        self.var_q = self.opti.variable(self.reduced_robot.model.nq)
        # self.var_q_last = self.opti.parameter(self.reduced_robot.model.nq)   # for smooth
        self.param_tf = self.opti.parameter(4, 4)

        # self.totalcost = casadi.sumsqr(self.error(self.var_q, self.param_tf))
        # self.regularization = casadi.sumsqr(self.var_q)

        error_vec = self.error(self.var_q, self.param_tf)
        pos_error = error_vec[:3]  
        ori_error = error_vec[3:]  
        weight_position = 1.0  
        weight_orientation = 0.1  
        self.totalcost = casadi.sumsqr(weight_position * pos_error) + casadi.sumsqr(weight_orientation * ori_error)
        self.regularization = casadi.sumsqr(self.var_q)

        # Setting optimization constraints and goals
        self.opti.subject_to(self.opti.bounded(
            self.reduced_robot.model.lowerPositionLimit,
            self.var_q,
            self.reduced_robot.model.upperPositionLimit)
        )
        # print("self.reduced_robot.model.lowerPositionLimit:", self.reduced_robot.model.lowerPositionLimit)
        # print("self.reduced_robot.model.upperPositionLimit:", self.reduced_robot.model.upperPositionLimit)
        self.opti.minimize(20 * self.totalcost + 0.01 * self.regularization)
        # self.opti.minimize(20 * self.totalcost + 0.01 * self.regularization + 0.1 * self.smooth_cost) # for smooth

        opts = {
            'ipopt': {
                'print_level': 0,
                'max_iter': 50,
                'tol': 1e-4
            },
            'print_time': False
        }
        self.opti.solver("ipopt", opts)

    def ik_fun(self, target_pose, gripper=0, motorstate=None, motorV=None):
        gripper = np.array([gripper/2.0, -gripper/2.0])
        if motorstate is not None:
            self.init_data = motorstate
        self.opti.set_initial(self.var_q, self.init_data)

        self.vis.viewer['ee_target'].set_transform(target_pose)     # for visualization

        self.opti.set_value(self.param_tf, target_pose)
        # self.opti.set_value(self.var_q_last, self.init_data) # for smooth

        try:
            # sol = self.opti.solve()
            sol = self.opti.solve_limited()
            sol_q = self.opti.value(self.var_q)

            if self.init_data is not None:
                max_diff = max(abs(self.history_data - sol_q))
                # print("max_diff:", max_diff)
                self.init_data = sol_q
                if max_diff > 30.0/180.0*3.1415:
                    # print("Excessive changes in joint angle:", max_diff)
                    self.init_data = np.zeros(self.reduced_robot.model.nq)
            else:
                self.init_data = sol_q
            self.history_data = sol_q

            self.vis.display(sol_q)  # for visualization

            if motorV is not None:
                v = motorV * 0.0
            else:
                v = (sol_q - self.init_data) * 0.0

            tau_ff = pin.rnea(self.reduced_robot.model, self.reduced_robot.data, sol_q, v,
                              np.zeros(self.reduced_robot.model.nv))

            is_collision = self.check_self_collision(sol_q, gripper)
            dist = self.get_dist(sol_q, target_pose[:3, 3])

            # print("dist:", dist)

            return sol_q, tau_ff, not is_collision

        except Exception as e:
            print(f"ERROR in convergence, plotting debug info.{e}")
            # sol_q = self.opti.debug.value(self.var_q)   # return original value
            return None, '', False

    def check_self_collision(self, q, gripper=np.array([0, 0])):
        pin.forwardKinematics(self.robot.model, self.robot.data, np.concatenate([q, gripper], axis=0))
        pin.updateGeometryPlacements(self.robot.model, self.robot.data, self.geom_model, self.geometry_data)
        collision = pin.computeCollisions(self.geom_model, self.geometry_data, False)
        # print("collision:", collision)
        return collision

    def get_dist(self, q, xyz):
        # print("q:", q)
        pin.forwardKinematics(self.reduced_robot.model, self.reduced_robot.data, np.concatenate([q], axis=0))
        dist = math.sqrt(pow((xyz[0] - self.reduced_robot.data.oMi[6].translation[0]), 2) + pow((xyz[1] - self.reduced_robot.data.oMi[6].translation[1]), 2) + pow((xyz[2] - self.reduced_robot.data.oMi[6].translation[2]), 2))
        return dist

    def get_pose(self, q):
        index = 6
        pin.forwardKinematics(self.reduced_robot.model, self.reduced_robot.data, np.concatenate([q], axis=0))
        end_pose = create_transformation_matrix(self.reduced_robot.data.oMi[index].translation[0], self.reduced_robot.data.oMi[index].translation[1], self.reduced_robot.data.oMi[index].translation[2],
                                                math.atan2(self.reduced_robot.data.oMi[index].rotation[2, 1], self.reduced_robot.data.oMi[index].rotation[2, 2]),
                                                math.asin(-self.reduced_robot.data.oMi[index].rotation[2, 0]),
                                                math.atan2(self.reduced_robot.data.oMi[index].rotation[1, 0], self.reduced_robot.data.oMi[index].rotation[0, 0]))
        end_pose = np.dot(end_pose, self.last_matrix)
        return matrix_to_xyzrpy(end_pose)

class VR:
    def __init__(self):
        rospy.init_node('oculus_reader')
        self.piper_control = PIPER()
        self.tools = MATHTOOLS()
        self.inverse_solution = Arm_IK()
        self.piper_control.init_pose()

        # 初始化记录上一个平滑后的值
        self.last_valid_pose = None
        
        # # debug
        # self.cnt = 0
    
        # 注册退出回调函数：程序退出时自动执行
        rospy.on_shutdown(self.shutdown_hook)  # 新增：注册回调

        # 采集终端是否打开 (好像不需要了，采集完按enter，关掉终端，然后再按下A键打开一个新的终端，)
        # self.is_capture_terminal_open = False

    # 退出回 函数，负责失能机械臂和夹爪
    def shutdown_hook(self):
        rospy.loginfo("开始关闭设备，发送失能指令...")
        # 1. 失能夹爪（关闭夹爪电机）
        self.piper_control.gripper_control(1.5,False)
        # 2. 失能机械臂关节（关闭电机）
        # 调用PIPER类中已有的失能方法（参考piper_control.py中的实现）
        self.piper_control.init_pose()
        # self.piper_control.DisableArm(motor_num=0xFF, enable_flag=0x01)
        
        rospy.loginfo("失能指令发送完成，等待设备关闭...")
        rospy.sleep(0.5)  # 等待指令生效
        rospy.loginfo("设备已关闭，程序退出")

    # 滑动平均函数
    def smooth_pose(self, new_pose):
        """
        平滑函数：遇到突变（瞬移）直接忽略，用上次的值
        """
        if self.last_valid_pose is None:
            # 第一次直接用
            self.last_valid_pose = new_pose
            return new_pose

        # 计算位置差
        last_pos = self.last_valid_pose[:3, 3]
        new_pos = new_pose[:3, 3]
        pos_diff = np.linalg.norm(new_pos - last_pos)

        # 计算旋转差：用 trace 求近似角度差
        delta_R = new_pose[:3, :3] @ self.last_valid_pose[:3, :3].T
        trace = np.clip(np.trace(delta_R), -1.0, 3.0)  # 避免数值误差
        angle_diff = math.acos((trace - 1) / 2)  # 弧度

        # 设置阈值：比如位置 > 0.05 m 或角度 > 10°
        if pos_diff > 0.05 or angle_diff > np.deg2rad(10):
            # 认定是瞬移 → 忽略

            print("[WARN] Detected jump, ignoring this frame.")
            
            # print(self.cnt)
            # self.cnt+=1

            return self.last_valid_pose
        else:
            # 正常情况：更新
            self.last_valid_pose = new_pose
            return new_pose
    
    def adjustment_matrix(self,transform):

        if transform.shape != (4, 4):
            raise ValueError("Input transform must be a 4x4 numpy array.")
        
        adj_mat = np.array([
            [0,0,-1,0],
            [-1,0,0,0],
            [0,1,0,0],
            [0,0,0,1]
        ])
        
        r_adj = self.tools.xyzrpy2Mat(0,0,0,   -np.pi , 0, -np.pi/2)

        transform = adj_mat @ transform  
        
        transform = np.dot(transform, r_adj)  
        
        return transform

    def publish_transform(self,transform, name):
        translation = transform[:3, 3]

        br = tf2_ros.TransformBroadcaster()
        t = geometry_msgs.msg.TransformStamped()

        t.header.stamp = rospy.Time.now()
        t.header.frame_id = 'vr_device'
        t.child_frame_id = name
        t.transform.translation.x = translation[0]
        t.transform.translation.y = translation[1]
        t.transform.translation.z = translation[2]

        quat = quaternion_from_matrix(transform)
        t.transform.rotation.x = quat[0]
        t.transform.rotation.y = quat[1]
        t.transform.rotation.z = quat[2]
        t.transform.rotation.w = quat[3]

        br.sendTransform(t)
       
    def get_ik_solution(self, x,y,z,roll,pitch,yaw,gripper_angle,b):
        
        q = quaternion_from_euler(roll, pitch, yaw)
        target = pin.SE3(
            pin.Quaternion(q[3], q[0], q[1], q[2]),
            np.array([x, y, z]),
        )

        # ? 0？
        sol_q, tau_ff, is_collision = self.inverse_solution.ik_fun(target.homogeneous,0)
        # print("result:", sol_q)
        if  b :
            # only-smi 注释下面两行
            # 控制机械臂关节
            self.piper_control.joint_control_piper(sol_q[0],sol_q[1],sol_q[2],sol_q[3],sol_q[4],sol_q[5],gripper_angle)
            print("ctrolling!!!")
        # else :
        #     print("collision!!!")
        
        # 单独控制夹爪
        self.piper_control.gripper_control(angle=gripper_angle)
    
    def get_episode_index(self):
        self.save_dir: Path = Path("/home/synk/questVR_ws-master/src/data_collect")
        suffix_list = []
        for foldername in os.listdir(self.save_dir):
            match = re.match(r"episode(\d+)", foldername)
            if match:
                suffix_list.append(int(match.group(1)))

        next_suffix = max(suffix_list) + 1 if suffix_list else 0

        return next_suffix

    def Run(self):
        # 这里可选为 WIFI连接 或 USB连接
        # oculus_reader = OculusReader(ip_address='10.12.11.14')    #  WIFI连接
        oculus_reader = OculusReader()                              #  USB连接
        rate = rospy.Rate(50)
        # 夹爪坐标系到到基坐标系的变换
        base_RR = [0.19, 0.0, 0.2, 0, 0, 0]
        # 数据集目录
        dataset_dir = "/home/synk/Downloads/quest_piper_with_gripper-master/src/data_collect"

        while not rospy.is_shutdown():
            rate.sleep()

            while True:
                transformations, buttons = oculus_reader.get_transformations_and_buttons()
                if transformations is None:
                    time.sleep(0.005)
                    continue
                if 'r' not in transformations:
                    time.sleep(0.005)
                    continue
                break
            
            transformations['r'] = self.adjustment_matrix(transformations['r'])

            if buttons['A'] == True :
                # 按下A键后，机械臂回到初始点位并且记录右坐标原点
                self.piper_control.init_pose()
                # 发送夹爪初始角度，最大张开
                self.piper_control.gripper_control(angle=1.5)
                base_RR = self.tools.matrix2Pose(transformations['r'])
                # 同步重置平滑基准
                self.last_valid_pose = transformations['r']  
                index = self.get_episode_index()

                # roslaunch 命令
                launch_cmd = (
                    f"roslaunch data_tools run_data_capture.launch "
                    f"type:=single_piper_with_gripper "
                    f"datasetDir:=/home/synk/questVR_ws-master/src/data_collect/{dataset_dir} "
                    f"episodeIndex:={index}"
                )
                # 启动一个新的 GNOME 终端并执行命令
                subprocess.Popen([
                    "gnome-terminal",
                    "--",
                    "bash",
                    "-c",
                    f"{launch_cmd}; exec bash"
                ])

            
            # 平滑处理
            transformations['r'] = self.smooth_pose(transformations['r'])
            right_controller_pose = transformations['r']
            self.publish_transform(right_controller_pose, 'right_hand')
            
            RR = self.tools.matrix2Pose(transformations['r'])
            RR_ = calc_pose_incre(base_RR,RR)
            # rightTrig取值0~1，按下时为1，没按时为0
            trigger_val = buttons['rightTrig'][0]
            # 计算夹爪角度，按下时从1.5逐渐减小到0，没按时保持1.5
            r_gripper_value = 1.5 * (1 - trigger_val)
            # 按下B键后，开始遥操作
            self.get_ik_solution(RR_[0],RR_[1],RR_[2],RR_[3],RR_[4],RR_[5],r_gripper_value,buttons['B'])

if __name__ == '__main__':
    vr = VR()
    vr.Run()