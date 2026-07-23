import torch
print(torch.__version__)        # 版本号，如 2.5.1+cpu 或 2.5.1+cu124
print(torch.version.cuda)       # 如果是 CPU 版，这里会是 None