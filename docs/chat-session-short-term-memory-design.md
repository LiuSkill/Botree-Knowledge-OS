# 会话级短期记忆模块设计

本文定义问答模块“会话级短期记忆”的首版设计。该模块服务于 `project_chat` 与 `base_chat` 的多轮承接、代词消解、条件延续和检索前上下文化，但它不是新的证据层，也不能替代知识库引用。

## 1. 目标与非目标

### 1.1 目标

- 让同一会话内的追问、简称、代词和省略表达能够被稳定承接。
- 在不放松现有证据与权限边界的前提下，提升检索前的问题完整度。
- 以低时延方式直接进入线上链路，不明显拉长检索主路径。
- 保留可审计性：记忆是否触发、如何改写、引用了哪些记忆项，都要进入 trace。

### 1.2 非目标

- 不做长期记忆，不跨会话保留用户语义画像。
- 不把记忆作为回答事实来源，不把记忆内容直接展示为引用。
- 首版不做用户可见的记忆管理 UI 或显式操作。
- 首版不把同步 LLM 提炼、同步 LLM 改写、真正双轨检索放进热路径。

## 2. 总体决策

1. 短期记忆是“会话状态增强层”，不是“证据层”。
2. 记忆采用“最近 3 轮原文窗口 + 持久化结构化快照”的混合模型。
3. 结构化记忆先挂在 `chat_sessions`，不新建独立 memory 表。
4. 记忆只参与检索前上下文化和少量安全回答提示，不改变 `chat_type`、`project_id`、答案策略或知识范围。
5. `project_chat` 的最终结论仍必须受项目资料证据约束；`base_chat` 的无证据路径仍走现有通用知识确认流程。
6. 首版按低时延约束设计：规则触发、单路检索、best-effort 写回、失败放行。

## 3. 模块形状与 seam

短期记忆应作为 Service 层的深模块落地，外部只暴露两个入口：

```python
prepare_turn_context(...) -> TurnContext
finalize_turn_memory(..., turn_outcome: TurnOutcome) -> MemoryFinalizeResult
```

推荐模块名：`ChatMemoryService`

### 3.1 外部 interface

#### `prepare_turn_context(...) -> TurnContext`

职责：

- 读取会话记忆快照
- 读取最近原文窗口
- 判断是否发生话题切换
- 判断本轮是否触发记忆改写
- 产出检索链路要消费的统一上下文对象

接口约束：

- 不调用同步 LLM
- 不做数据库提交
- 失败时返回“无记忆上下文”的降级结果，而不是抛出阻断主流程的异常

#### `finalize_turn_memory(..., turn_outcome: TurnOutcome) -> MemoryFinalizeResult`

职责：

- 基于本轮原始消息、最终回答、证据状态、引用锚点和 trace 更新结构化记忆
- 处理 pending/confirmed 的提升、降级、过期和冲突清理
- best-effort 写回 `chat_sessions`

接口约束：

- 不阻断回答主流程
- 不依赖旧 `memory_state_json` 作为真相源重建事实
- 失败仅记录日志并尽力打上内部重建标记

### 3.2 内部实现建议

`ChatMemoryService` 的实现内部可以继续拆分，但这些拆分不应暴露给调用方：

- `ChatMemoryConfigProvider`
- `ChatMemorySnapshotSerializer`
- `ChatMemoryWindowLoader`
- `MemoryTriggerPolicy`
- `TopicShiftPolicy`
- `MemoryUpdatePolicy`
- `MemoryTraceBuilder`

这样可以把规则、冲突处理、TTL、trace 组织、配置读取都收拢在一个深实现里，而不是散落到 `ChatService + RetrievalGraph + Repository`。

## 4. 会话存储模型

## 4.1 `chat_sessions` 字段扩展

建议新增以下字段：

- `memory_state_json`: LONGTEXT/JSON，保存固定 schema 的结构化记忆快照
- `memory_state_version`: int，结构版本号，首版为 `1`
- `memory_updated_at`: datetime，最近一次成功写回时间
- `memory_rebuild_needed`: bool，内部重建标记

并发策略采用“最后一次提交覆盖”，不做强一致合并。短期记忆是增强层，不要求像业务主数据那样做严格并发控制。

## 4.2 固定 schema

`memory_state_json` 使用固定 schema，不允许任意 key/value 漫游：

```json
{
  "schema_version": 1,
  "stable_context": {},
  "topic_context": {},
  "confirmed_contexts": [],
  "pending_contexts": [],
  "user_constraints": {},
  "last_turn_summary": {},
  "topic_shift_signals": {}
}
```

### 4.2.1 `stable_context`

跨话题仍可保留的小型稳定上下文，仅允许白名单字段：

- `chat_type`
- `project_id`
- `answer_preferences`
- `conversation_state`

不允许把当前设备、当前参数、上轮结论、临时假设放进 `stable_context`。

### 4.2.2 `topic_context`

只服务当前讨论主题的短期上下文，建议字段：

- `topic_key`
- `topic_label`
- `current_objects`
- `current_problem_chain_summary`
- `last_active_user_message_id`

其中 `current_objects` 建议最多保留 5 个对象标签。

### 4.2.3 `confirmed_contexts`

只允许保存“已被系统信息或知识库证据支持”的上下文项。每项至少包含：

- `id`
- `kind`
- `scope` (`stable` / `topic`)
- `summary`
- `anchor`

`anchor` 固定包含：

- `source_message_id`
- `source_kind` (`system_field` / `retrieval_supported` / `assistant_final_with_citation`)
- `citation_ids`
- `confirmed_at`
- `updated_at`

首版建议总上限 8 条，其中 topic 级优先淘汰。

### 4.2.4 `pending_contexts`

保存尚未被证据确认、但对追问理解有帮助的临时上下文。每项至少包含：

- `id`
- `kind`
- `summary`
- `anchor`
- `pending_turn_ttl`

规则：

- 默认 TTL 为 2 个用户回合
- 被证据支持则提升为 `confirmed_contexts`
- 被新证据冲突则降级或删除
- 明显话题切换时清空 topic 相关 pending

首版建议上限 4 条。

### 4.2.5 `user_constraints`

只保留小而白名单化的回答约束，例如：

- `language`
- `format_preference`
- `must_use_project_docs`
- `avoid_general_knowledge`

### 4.2.6 `last_turn_summary`

只保留受控摘要，不保留长文本：

- `user_intent`
- `assistant_action`
- `evidence_status`
- `problem_chain_summary`

每个摘要字段应有长度上限，首版建议 120~160 字。

### 4.2.7 `topic_shift_signals`

建议字段：

- `topic_signature`
- `last_shift_at`
- `last_shift_reason`

该结构用于解释“为什么旧 topic context 被降级/清理”，而不是作为事实来源。

## 5. 原始窗口模型

原始窗口按“轮”而不是按“消息条数”计数。首版默认读取最近 3 轮，且支持平台级配置动态调整：

- 默认值：`3`
- 最小值：`1`
- 最大值：`8`

这里的“轮”指用户消息及其对应助手回复。若某轮尚未形成完整答复，则按现有消息序列尽力回看。

## 6. 配置模型

首版建议至少提供两个平台级配置项：

- `chat_memory_enabled`：总开关，默认 `true`
- `chat_memory_raw_window_rounds`：原文窗口轮数，默认 `3`

配置来源仍为 `system_configs`，但不应在每轮链路里无缓存读取。建议在 `ChatMemoryConfigProvider` 内做进程内短 TTL 缓存，避免为记忆模块额外引入稳定的数据库热读。

## 7. 接入当前问答链路的位置

## 7.1 ChatService 接入点

同步问答链路：

1. `ChatService.complete()` 获取或创建 `session`
2. 写入用户消息并拿到 `user_message_id`
3. 调用 `prepare_turn_context(...)`
4. 将 `TurnContext` 传入 `AgentExecutor.run(...)`
5. 回答完成后，在 `_persist_agent_result(...)` 中调用 `finalize_turn_memory(...)`

流式问答链路：

1. `ChatService.complete_stream()` 获取或创建 `session`
2. 写入用户消息并提交，保留现有流式行为
3. 调用 `prepare_turn_context(...)`
4. 将 `TurnContext` 传入 `RetrievalGraph.prepare_stream(...)`
5. 在最终持久化阶段调用 `finalize_turn_memory(...)`

## 7.2 RetrievalGraph 接入点

首版新增一个轻量节点，建议位于：

`answer_policy_router` 之后，`query_decompose` 之前。

原因：

- 问候、身份、明显常识等直答路径可直接跳过记忆处理
- 记忆仍然发生在检索前，满足“上下文化层”定位
- 可以利用已有 route/policy 信息，确保记忆不会越权扩 scope

建议节点名：

- trace key：`session_memory`
- step 文案：`会话短期记忆上下文化`
- implementation：`chat_memory`

该节点本身不做数据库或 LLM 工作，只消费 `TurnContext`，并把以下内容写入状态：

- `effective_question`
- `memory_trace`
- `answer_memory_context`
- `memory_trigger_mode`
- `memory_referenced_context_ids`

## 8. 检索改写与触发策略

## 8.1 判断依据

触发判断基于四类信号：

1. `上文依赖度`
2. `问题完整度`
3. `话题切换度`
4. `记忆可信度`

### 8.1.1 上文依赖度高的典型信号

- 明显代词：这个、那个、它、前者、后者、上面那个
- 追问承接：继续、那如果、为什么会这样、这个怎么处理
- 省略对象：只剩动作词或判断词，没有主语对象

### 8.1.2 问题完整度高的典型信号

- 句内已出现明确对象、动作、范围
- 不依赖上一轮对象也可以独立检索

### 8.1.3 话题切换度高的典型信号

- 新出现的核心对象与现有 `topic_signature` 几乎无重合
- 新实体明显占主导
- 用户语气表现为开启新问题，而不是延续旧问题

### 8.1.4 记忆可信度高的典型信号

- 引用的是 `confirmed_contexts`
- 或引用的是最近一轮内、未过期且对象清晰的 `pending_contexts`

## 8.2 三档判定

### 必触发

满足以下组合时触发单路改写：

- 上文依赖度高
- 话题切换度低
- 记忆可信度高

### 禁触发

满足以下任一条件时不触发：

- 问题完整度高
- 话题切换度高
- 没有可用记忆
- 只有低可信度 pending 且无法形成唯一指向

### 灰区

灰区代表“存在承接可能，但改写收益和误改写风险都不低”。

原始设计中灰区可进入双轨检索；但基于直接上线与时延约束，首版执行策略收敛为：

- 记录候选改写
- trace 中保留判断依据
- 实际检索仍走原问题

这样保留后续升级到真正双轨检索的观测基础，但不把双路召回与双路 rerank 放进首版热路径。

## 8.3 首版改写执行策略

首版只允许两种实际执行模式：

- `skip`：不改写，直接使用原问题
- `rewrite_single`：使用单路上下文化后的 `effective_question`

不执行：

- 同步 LLM 改写
- 双路并行检索
- 两路答案分支竞争

## 8.4 改写边界

记忆改写必须遵守以下硬约束：

- 不改变 `chat_type`
- 不改变 `project_id`
- 不扩大知识范围
- 不放宽 `project_chat` 的证据约束
- 不把 pending 内容改写成确定事实语气

## 9. 话题切换与记忆生命周期

### 9.1 话题切换时保留项

仅保留白名单稳定上下文：

- `chat_type`
- `project_id`
- 显式回答偏好
- 系统会话状态

### 9.2 话题切换时降级项

以下内容在明显切换时应降级或清空：

- 当前设备/文档/图纸对象
- 当前参数和值
- 当前问题链摘要
- topic 级 confirmed
- 所有 topic 级 pending

### 9.3 confirmed 提升来源

只允许从以下来源提升到 `confirmed_contexts`：

- 系统确定信息
- 带明确 citation 支持的最终回答结论
- 被后续检索再次命中且与证据一致的历史上下文

以下来源禁止直接提升：

- 纯用户断言
- LLM 猜测
- 无引用的助手陈述
- 只出现一次的临时 pending

## 10. 回答阶段可读记忆子集

回答生成可读取一个受控且很小的记忆子集，但该子集不能成为第二事实源：

- `user_constraints`
- `topic_context.current_objects`
- `last_turn_summary.problem_chain_summary`
- 本轮代词消解结果

禁止直接把 `confirmed_contexts` 或 `pending_contexts` 原样注入 AnswerGenerator prompt 作为事实陈述。

## 11. 写回策略

## 11.1 时机

`finalize_turn_memory(...)` 建议在助手消息和 citation 已经 `flush` 后、事务 `commit` 前执行。这样写回可以使用：

- `user_message_id`
- `assistant_message_id`
- `citation_ids`
- 本轮 `trace`

## 11.2 失败策略

写回失败不阻断主回答流程：

- 记录 warning 日志
- 尽力设置 `memory_rebuild_needed=true`
- 本轮回答照常返回
- 下一轮即使读不到最新记忆也不额外补偿

## 11.3 重建策略

若需要重建，真相源只允许来自：

- `chat_messages`
- `chat_citations`
- `retrieval_traces`

旧 `memory_state_json` 只能作为调试参考，不能作为重建输入。

## 12. Trace 与可观测性

首版新增以下 trace / raw 字段：

- `memory_prepare_ms`
- `memory_trigger_mode`
- `memory_decision_reason`
- `memory_original_question`
- `memory_effective_question`
- `memory_topic_shift`
- `memory_referenced_context_ids`
- `memory_writeback_ms`
- `memory_writeback_status`

其中：

- `memory_prepare_ms` 进入阶段耗时汇总
- `memory_effective_question` 必须进入检索审计，满足“改写可审计”
- `memory_writeback_status` 只用于内部排障，不对前端做新展示

首版不要求把短期记忆作为新的用户可见 progress stage。

## 13. 性能约束

为满足直接上线的时延要求，首版必须满足以下约束：

1. `prepare_turn_context(...)` 不调用同步 LLM
2. `finalize_turn_memory(...)` 不调用同步 LLM
3. 灰区不执行双轨检索
4. 不额外放大 `candidate_k / rerank_top_k / eval_top_k`
5. 配置读取必须缓存，避免每轮增加固定 DB 热读

性能预期：

- 读路径主要成本是最近窗口查询、JSON 解析、规则判断
- 写路径主要成本是 session 行更新和 JSON 序列化
- 额外耗时应显著低于 planner / reranker 的现有重成本阶段

工程目标：

- 常规回合中，记忆模块新增时延保持在“小于一个 planner LLM 调用、远小于一次 rerank”的量级
- 不让记忆模块成为 P95 主导项

## 14. 实现建议的值对象

```python
class TurnContext(BaseModel):
    session_id: int
    raw_recent_rounds: list[RecentRound]
    session_memory: SessionMemorySnapshot | None
    effective_question: str
    memory_trigger_mode: str
    answer_memory_context: dict[str, Any]
    memory_trace: dict[str, Any]


class TurnOutcome(BaseModel):
    session_id: int
    user_message_id: int
    assistant_message_id: int | None
    user_message: str
    answer: str
    answer_type: str
    evidence_status: str
    chat_type: str
    project_id: int | None
    citations: list[MemoryCitationAnchor]
    trace_steps: list[dict[str, Any]]
    raw: dict[str, Any]
    turn_context: TurnContext | None
```

## 15. 首版实现顺序

1. 扩展 `chat_sessions` 持久化字段
2. 新建 `ChatMemoryService`
3. 补 `ChatRepository` 最近窗口读取方法
4. 在 `ChatService.complete/complete_stream` 中接入 `prepare_turn_context`
5. 在 `RetrievalGraph` 中增加 `session_memory` 节点并消费 `effective_question`
6. 在 `_persist_agent_result(...)` 中接入 `finalize_turn_memory`
7. 增加 trace、日志和回归测试

## 16. 首版不做的事

- 用户可见记忆管理入口
- 独立 memory 表
- 同步 LLM 提炼/改写
- 灰区真实双轨检索
- 跨会话长期记忆
- 把记忆内容直接当成回答引用
