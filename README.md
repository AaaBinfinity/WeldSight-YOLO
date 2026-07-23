# WeldSight-YOLO

焊缝射线底片缺陷检测系统。YOLO 负责定位裂纹、气孔和未熔合候选目标，Kimi
视觉模型可对原始图片与 YOLO 标注图进行二次复核，并向用户输出结构化 JSON 报告。

## 配置 Kimi 复核

不要把 API Key 写入代码或提交到 Git。先复制示例配置：

```powershell
Copy-Item .env.example .env
```

然后编辑项目根目录的 `.env`：

```dotenv
MOONSHOT_API_KEY=替换为新生成的_API_Key
KIMI_VISION_MODEL=kimi-k3
KIMI_FALLBACK_MODELS=moonshot-v1-32k-vision-preview,kimi-k2.6
KIMI_REVIEW_ENABLED=true
```

启动服务时会自动加载 `.env`：

```powershell
python .\v-app\run.py
```

可选配置：

- `KIMI_REVIEW_ENABLED=false`：关闭 AI 复核，只运行 YOLO。
- `KIMI_BASE_URL`：默认 `https://api.moonshot.cn/v1`。
- `KIMI_TIMEOUT_SECONDS`：默认 60 秒。
- `KIMI_MAX_RETRIES`：单个模型遇到过载或临时网络错误时的重试次数，默认 2。
- `KIMI_FALLBACK_MODELS`：主模型持续过载时依次尝试的视觉模型。

打开 `http://localhost:5098/img.html`，上传图片后可查看检测结果、AI 复核意见，
并下载 JSON 报告。未配置 `MOONSHOT_API_KEY` 时接口会自动降级，仍返回 YOLO 报告。
