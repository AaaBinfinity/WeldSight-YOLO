from app import create_app

# 创建Flask应用实例
app = create_app()

if __name__ == '__main__':
    # 开发环境配置： threaded=True支持多线程（处理摄像头+API并发）
    app.run(
        host='0.0.0.0',
        port=5098,
        threaded=True,
        debug=False  # 生产环境必须关闭debug
    )