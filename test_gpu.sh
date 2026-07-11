#!/bin/bash
LD_LIBRARY_PATH=/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/cublas/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/cudnn/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/cufft/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/curand/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/cusolver/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/cusparse/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/nccl/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/nvjitlink/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:\
/home/alejandro/miniconda/envs/tf/lib/python3.12/site-packages/nvidia/cuda_runtime/lib

export LD_LIBRARY_PATH

/home/alejandro/miniconda/envs/tf/bin/python -c "import tensorflow as tf; print('GPU:', tf.config.list_physical_devices('GPU'))"
