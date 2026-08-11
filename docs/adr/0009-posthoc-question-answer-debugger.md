# 问答 Debugger 采用事后离线诊断模式

问答执行期间不向 Debugger 推送实时大载荷；问答完成或失败后，由异步 Trace Worker 持久化完整可观测事件，Debugger 仅通过历史 Trace 查询接口进行事后分析。现有问答流可继续提供普通进度信息，但不作为 Debugger 的事实来源。
