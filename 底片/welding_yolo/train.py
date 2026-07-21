from ultralytics import YOLO

if __name__ == '__main__':
    model = YOLO('yolo26l.pt')

    model.train(
        data='data.yaml',

        # 基础训练
        epochs=150,
        imgsz=640,
        batch=16,

        # 计算资源
        device=0,          # Windows NVIDIA / 改 mps / cpu
        workers=2,         # 提升数据加载
        amp=True,          # 混合精度

        cache=False,

        # 收敛控制
        patience=30, 

        # 训练策略
        optimizer='AdamW',
        lr0=0.01,
        cos_lr=True,

        # 数据增强 
        mosaic=1.0,
        mixup=0.1,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
 
        name='weld_final_v2',
        save=True
    )