"""
Background Tasks

负责：
1. 暴露 RQ worker 可导入的任务函数
2. 将后台任务与 API 请求生命周期解耦
3. 保持任务实现只调用 Service 层
"""
