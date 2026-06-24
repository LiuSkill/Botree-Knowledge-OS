import type { AgentTraceStep } from '@/types/api';

const HIDDEN_TRACE_IMPLEMENTATIONS = new Set([
  'chat_policy',
  'confirm_state',
  'pre_intent_gate',
  'intent',
  'answer_policy_router',
  'query_decompose',
  'query_profile',
  'evidence_decision',
  'answer_policy_gate',
  '_chat_policy_node',
  '_confirm_state_node',
  '_pre_intent_gate_node',
  '_intent_node',
  '_answer_policy_router_node',
  '_query_decompose_node',
  '_query_profile_node',
  '_evidence_decision_node',
  '_answer_policy_gate_node',
]);

const HIDDEN_TRACE_STEPS = new Set([
  '\u95ee\u7b54\u6a21\u5f0f\u7b56\u7565',
  '\u95ee\u7b54\u7b56\u7565',
  '\u901a\u7528\u56de\u7b54\u786e\u8ba4\u72b6\u6001',
  '\u786e\u8ba4\u72b6\u6001',
  '\u5feb\u901f\u610f\u56fe\u95e8\u63a7',
  '\u7528\u6237\u610f\u56fe\u8bc6\u522b',
  '\u610f\u56fe\u8bc6\u522b',
  '\u4efb\u52a1\u62c6\u89e3',
  '\u67e5\u8be2\u753b\u50cf\u751f\u6210',
  '\u67e5\u8be2\u753b\u50cf',
  '\u7b54\u6848\u7b56\u7565\u8def\u7531',
  '\u7b54\u6848\u7b56\u7565',
  '\u8bc1\u636e\u72b6\u6001\u5224\u65ad',
  '\u8bc1\u636e\u72b6\u6001',
  '\u7b54\u6848\u7b56\u7565\u95e8\u63a7',
  '\u7b54\u6848\u95e8\u63a7',
]);

export function isHiddenTraceStep(step: AgentTraceStep): boolean {
  const implementation = step.implementation?.trim();
  if (implementation && HIDDEN_TRACE_IMPLEMENTATIONS.has(implementation)) return true;
  if (isNoopRetryStep(step)) return true;
  return HIDDEN_TRACE_STEPS.has(step.step.trim());
}

export function visibleTraceSteps(steps: AgentTraceStep[]): AgentTraceStep[] {
  return steps.filter((step) => !isHiddenTraceStep(step));
}

function isNoopRetryStep(step: AgentTraceStep): boolean {
  const name = step.step.trim();
  if (!name.includes('\u8865\u5145\u68c0\u7d22')) return false;
  const summary = [step.display_text, step.result]
    .filter(Boolean)
    .join('\n');
  if (summary.includes('\u672a\u6267\u884c\u8865\u5145\u68c0\u7d22')) return true;
  const details = step.details || {};
  const retryCount = Number(details.retry_count ?? details.retry_query_count ?? 0);
  const retrievers = details.retry_retrievers;
  return retryCount <= 0 && (!Array.isArray(retrievers) || retrievers.length === 0);
}
