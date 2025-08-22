import argparse
import csv
import math
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import torch
from einops import rearrange

sys.path.append(str(Path(__file__).parent.parent.parent.parent))  # add root to path

from src.hardware.control.controller import ArmControllerFactory
from src.data_policies.act.constants import TASK_CONFIGS
from src.data_policies.act.policy import ACTPolicy
from src.data_policies.act.utils import set_seed


def main(args):
    # command line parameters
    ckpt_dir = args["ckpt_dir"]
    policy_class = args["policy_class"]
    task_name = args["task_name"]
    num_epochs = args["num_epochs"]
    set_seed(args["seed"])

    # get task parameters
    task_config = TASK_CONFIGS[task_name]
    episode_len = task_config["episode_len"]
    camera_names = task_config["camera_names"]
    state_dim = task_config["state_dim"]

    # fixed parameters
    lr_backbone = 1e-5
    backbone = "resnet18"

    if policy_class == "ACT":
        enc_layers = 4
        dec_layers = 7
        nheads = 8
        policy_config = {
            "state_dim": state_dim,
            "lr": args["lr"],
            "num_queries": args["chunk_size"],
            "kl_weight": args["kl_weight"],
            "hidden_dim": args["hidden_dim"],
            "dim_feedforward": args["dim_feedforward"],
            "lr_backbone": lr_backbone,
            "backbone": backbone,
            "enc_layers": enc_layers,
            "dec_layers": dec_layers,
            "nheads": nheads,
            "camera_names": camera_names,
        }
    else:
        raise NotImplementedError

    config = {
        "num_epochs": num_epochs,
        "ckpt_dir": ckpt_dir,
        "episode_len": episode_len,
        "state_dim": state_dim,
        "policy_class": policy_class,
        "policy_config": policy_config,
        "task_name": task_name,
        "seed": args["seed"],
        "temporal_agg": args["temporal_agg"],
        "camera_names": camera_names
    }

    # eval phase
    eval_bc(config)


def make_policy(policy_class, policy_config):
    if policy_class == "ACT":
        policy = ACTPolicy(policy_config)
    else:
        raise NotImplementedError
    return policy


def make_optimizer(policy_class, policy):
    if policy_class == "ACT":
        optimizer = policy.configure_optimizers()
    else:
        raise NotImplementedError
    return optimizer


def get_image(img_list, camera_names):
    curr_images = []
    for cam_name in camera_names:
        curr_image = rearrange(img_list[cam_name], "h w c -> c h w")
        curr_images.append(curr_image)
    curr_image = np.stack(curr_images, axis=0)
    curr_image = torch.from_numpy(curr_image / 255.0).float().cuda().unsqueeze(0)
    return curr_image


def eval_bc(config):
    seed = config["seed"]
    ckpt_dir = config["ckpt_dir"]
    state_dim = config["state_dim"]
    policy_class = config["policy_class"]
    policy_config = config["policy_config"]
    camera_names = config["camera_names"]
    max_timesteps = config["episode_len"]
    temporal_agg = config["temporal_agg"]
    num_rollout = 1
    task_name = config["task_name"]
    mode = ["joints", "gripper_state"]  # use joints and gripper_state

    set_seed(seed)

    # load policy and stats
    ckpt_path = os.path.join(ckpt_dir, f"policy_epoch_9900_seed_0.ckpt")
    policy = make_policy(policy_class, policy_config)
    loading_status = policy.load_state_dict(torch.load(ckpt_path))
    print(loading_status)
    policy.cuda()
    policy.eval()
    print(f"Loaded: {ckpt_path}")
    stats_path = os.path.join(ckpt_dir, f"dataset_stats.pkl")
    with open(stats_path, "rb") as f:
        stats = pickle.load(f)

    # preprocess and postprocess
    pre_process = lambda s_qpos: (s_qpos - stats["qpos_mean"]) / stats["qpos_std"]
    post_process = lambda a: a * stats["action_std"] + stats["action_mean"]

    try:
        # load environment
        env = ArmControllerFactory.create_controller("piper")
        env.setup_robots()

        query_frequency = policy_config["num_queries"]  # num_queries == chunk_size
        if temporal_agg:  # temporal aggregation
            query_frequency = 1
            num_queries = policy_config["num_queries"]

        max_timesteps = int(max_timesteps * 2)  # may increase for real-world tasks

        image_history = []
        qpos_history = []
        target_qpos_history = []
        for rollout_id in range(num_rollout):
            input(f"Rollout {rollout_id + 1}/{num_rollout} ready. Press Enter to start...")

            ### reset environment
            obs = env.reset(mode)

            ### evaluation loop
            if temporal_agg:
                all_time_actions = torch.zeros(
                    [max_timesteps, max_timesteps + num_queries, state_dim]
                ).cuda()

            image_list = []
            qpos_list = []
            target_qpos_list = []
            with torch.inference_mode():
                for t in range(max_timesteps):
                    ### process previous timestep to get qpos and image_list
                    qpos_numpy = np.array(obs["qpos"])
                    # debug
                    # 转换为弧度
                    qpos_numpy = np.deg2rad(qpos_numpy)
                    qpos = pre_process(qpos_numpy)
                    qpos = torch.from_numpy(qpos).float().cuda().unsqueeze(0)
                    curr_image = get_image(obs["images"], camera_names)

                    image_list.append(obs["images"]["pikaGripperFisheyeCamera"])
                    qpos_list.append(obs["qpos"])

                    ### query policy
                    if policy_class == "ACT":
                        if t % query_frequency == 0:
                            all_actions = policy(qpos, curr_image)
                        if temporal_agg:
                            all_time_actions[[t], t : t + num_queries] = all_actions
                            actions_for_curr_step = all_time_actions[:, t]
                            actions_populated = torch.all(actions_for_curr_step != 0, axis=1)
                            actions_for_curr_step = actions_for_curr_step[actions_populated]
                            k = 0.01
                            exp_weights = np.exp(-k * np.arange(len(actions_for_curr_step)))
                            exp_weights = exp_weights / exp_weights.sum()
                            exp_weights = torch.from_numpy(exp_weights).cuda().unsqueeze(dim=1)
                            raw_action = (actions_for_curr_step * exp_weights).sum(
                                dim=0, keepdim=True
                            )
                        else:
                            raw_action = all_actions[:, t % query_frequency]
                    else:
                        raise NotImplementedError

                    ### post-process actions
                    raw_action = raw_action.squeeze(0).cpu().numpy()
                    action = post_process(raw_action)
                    target_qpos = action.tolist()

                    # debug
                    # 改为角度
                    target_qpos_deg = target_qpos.copy() 
                    for i in range(6):  # 前6个是关节角
                        target_qpos_deg[i] = math.degrees(target_qpos[i])
                        
                    ### step the environment
                    # debug
                    print("Target qpos:", target_qpos)

                    obs = env.step(target_qpos_deg, mode)
        
                    target_qpos_list.append(target_qpos)

            print(f"Rollout {rollout_id + 1}/{num_rollout} finished")

            image_history.append(image_list)
            qpos_history.append(qpos_list)
            target_qpos_history.append(target_qpos_list)

    finally:
        # close environment
        joints_rad = [
            0.00036632400000000007,
            -0.017112564,
            0.033021492,
            0.0052680879999999998,
            0.093430064000000007,
            0.0083207880000000008,
        ]
        for i in range(6):  # 前6个是关节角
            target_qpos_deg[i] = math.degrees(joints_rad[i])
        env.set_joints(joints_rad)
        env.stop_robots()
        print("Environment closed")

        # save images and qpos
        current_time = datetime.now().strftime("%Y_%m_%d_%H_%M")
        save_path = os.path.join(
            str(Path(__file__).parent.parent.parent.parent),
            f"data/output/{task_name}/{current_time}",
        )
        os.makedirs(save_path, exist_ok=True)
        for i in range(len(image_history)):
            images_path = os.path.join(save_path, f"image_list_{i}")
            os.makedirs(images_path, exist_ok=True)
            video_writer = cv2.VideoWriter(
                os.path.join(save_path, f"video_{i}.mp4"),
                cv2.VideoWriter_fourcc(*"mp4v"),
                20,
                (640, 480),
            )
            for j, image_np in enumerate(image_history[i]):
                video_writer.write(image_np)
                image_path = os.path.join(images_path, f"image_{j}.png")
                cv2.imwrite(image_path, image_np)
            video_writer.release()

        for i in range(len(qpos_history)):
            qpos_path = os.path.join(save_path, f"qpos_{i}.csv")
            with open(qpos_path, "w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(
                    [
                        "joint_0",
                        "joint_1",
                        "joint_2",
                        "joint_3",
                        "joint_4",
                        "joint_5",
                        "gripper width",
                    ]
                )
                for j in range(len(qpos_history[i])):
                    writer.writerow(qpos_history[i][j])

        for i in range(len(target_qpos_history)):
            target_qpos_path = os.path.join(save_path, f"target_qpos_{i}.csv")
            with open(target_qpos_path, "w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(
                    [
                        "joint_0",
                        "joint_1",
                        "joint_2",
                        "joint_3",
                        "joint_4",
                        "joint_5",
                        "gripper width",
                    ]
                )
                for j in range(len(target_qpos_history[i])):
                    writer.writerow(target_qpos_history[i][j])

        print(f"Saved all images and qpos")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ckpt_dir", action="store", type=str, help="ckpt_dir", required=True)
    parser.add_argument(
        "--policy_class", action="store", type=str, help="policy_class, capitalize", required=True
    )
    parser.add_argument("--task_name", action="store", type=str, help="task_name", required=True)
    parser.add_argument("--batch_size", action="store", type=int, help="batch_size", required=True)
    parser.add_argument("--seed", action="store", type=int, help="seed", required=True)
    parser.add_argument("--num_epochs", action="store", type=int, help="num_epochs", required=True)
    parser.add_argument("--lr", action="store", type=float, help="lr", required=True)
    # parser.add_argument("--num_rollout", action="store", type=int, default=1, required=False)

    # for ACT
    parser.add_argument("--kl_weight", action="store", type=int, help="KL Weight", required=False)
    parser.add_argument("--chunk_size", action="store", type=int, help="chunk_size", required=False)
    parser.add_argument("--hidden_dim", action="store", type=int, help="hidden_dim", required=False)
    parser.add_argument(
        "--dim_feedforward", action="store", type=int, help="dim_feedforward", required=False
    )
    parser.add_argument("--temporal_agg", action="store_true")

    main(vars(parser.parse_args()))