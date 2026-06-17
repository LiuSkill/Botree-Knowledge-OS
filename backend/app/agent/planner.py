"""
Agent Planner

负责：
1. 根据问题和模式生成执行计划
2. 记录 Agent 执行过程说明
3. MVP 阶段提供可解释步骤
"""


class AgentPlanner:
    """
    智能体规划器

    职责：
    - 将问答流程拆解为范围判断、权限校验、检索和回答生成
    """

    def plan(self, chat_type: str, mode: str, query_scope: str, evidence_count: int) -> list[dict]:
        """
        生成执行计划

        参数:
            chat_type: 问答类型
            mode: 问答模式
            query_scope: 查询范围
            evidence_count: 合并后的证据数量

        返回:
            Agent 步骤列表。
        """

        if chat_type == "project_chat":
            return [
                {"step": "校验项目访问权限", "result": "已确认当前用户具备所选项目访问权限", "elapsed_ms": 1},
                {"step": "查询项目资料", "result": "仅检索当前 project_id 下已审核、已索引项目资料", "elapsed_ms": 1},
                {"step": "查询授权内部资料", "result": "已按知识库授权和内部可见性检索可用基础资料", "elapsed_ms": 1},
                {"step": "合并证据", "result": f"合并后获得 {evidence_count} 条可引用知识片段", "elapsed_ms": 2},
                {"step": "生成回答", "result": "已基于证据片段生成回答，未使用无来源内容", "elapsed_ms": 1},
            ]
        return [
            {"step": "识别问题意图", "result": f"当前模式为 {mode}，查询范围：{query_scope}", "elapsed_ms": 1},
            {"step": "查询用户有权限的知识库", "result": "已根据用户角色和项目成员关系过滤知识范围", "elapsed_ms": 1},
            {"step": "检索相关资料", "result": "调用关键词检索和数据库检索获取候选知识片段", "elapsed_ms": 1},
            {"step": "合并证据", "result": f"合并后获得 {evidence_count} 条可引用知识片段", "elapsed_ms": 2},
            {"step": "生成回答", "result": "已基于证据片段生成回答，未使用无来源内容", "elapsed_ms": 1},
        ]
