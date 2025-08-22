### Task parameters
DATA_DIR = "data/input"
IMG_H = 360
IMG_W = 640
TASK_CONFIGS = {
    "grasp_corn": {
        "dataset_dir": DATA_DIR + "/bear_v4",
        "num_episodes": 30,
        "episode_len": 180,
        "camera_names": ["front"],
        "state_dim": 8,
    },
    "grasp_cube": {
        "dataset_dir": DATA_DIR + "/bear_v4",
        "num_episodes": 30,
        "episode_len": 180,
        "camera_names": ["front"],
        "state_dim": 8,
    },
    "bear": {
        "dataset_dir": "/home/synk/questVR_ws-master/src/act_input/bear_v4",  # tip: 这里的路径要改成你自己的数据集的路径
        "num_episodes": 10,  # 实际采集的 eposide 的数量
        "episode_len": 198,  # 每个 episode 的长度
        "camera_names": ["pikaGripperFisheyeCamera"],
        "state_dim": 7,
    },
}
