import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from "react";
import {
  createFixtureSnapshot,
  DECISION_STATUS,
  NAVIGATION_VIEW,
  RUN_PHASE,
  RUN_STATUS,
} from "../data/fixtures";

export const PROTOTYPE_ACTION = Object.freeze({
  NAVIGATE: "navigation/navigate",
  SELECT_TASK: "navigation/selectTask",
  SELECT_TEMPLATE: "navigation/selectTemplate",
  SELECT_EXECUTION: "navigation/selectExecution",
  OPEN_EVIDENCE: "navigation/openEvidence",
  CLOSE_EVIDENCE: "navigation/closeEvidence",
  OPEN_ISSUE: "navigation/openIssue",
  CLEAR_NOTICE: "ui/clearNotice",
  DECISION_APPROVED: "run/decisionApproved",
  DECISION_DEFERRED: "run/decisionDeferred",
  DECISION_REOPENED: "run/decisionReopened",
  RUN_PAUSED: "run/paused",
  RUN_RESUMED: "run/resumed",
  TAKEOVER_STARTED: "run/takeoverStarted",
  TAKEOVER_ENDED: "run/takeoverEnded",
  SAVE_COMPLETED: "run/saveCompleted",
  UNPUBLISHED_VERIFIED: "run/unpublishedVerified",
  RESET: "prototype/reset",
});

export const DEFAULT_SCENARIO_DELAYS = Object.freeze({
  saveCompleted: 1500,
  unpublishedVerified: 3300,
  unpublishedVerifiedFromResume: 1800,
});

const VALID_VIEWS = new Set(Object.values(NAVIGATION_VIEW));
const PrototypeContext = createContext(null);

function indexById(items) {
  return Object.fromEntries(items.map((item) => [item.id, item]));
}

function uniqueAppend(items, id) {
  return items.includes(id) ? items : [...items, id];
}

function last(items) {
  return items[items.length - 1];
}

function taskStatusFromRunStatus(status) {
  if (status === RUN_STATUS.WAITING_DECISION) return "waiting_decision";
  if (status === RUN_STATUS.PAUSED) return "paused";
  if (status === RUN_STATUS.MANUAL_TAKEOVER) return "manual_takeover";
  if (status === RUN_STATUS.COMPLETED) return "completed";
  if (status === RUN_STATUS.FAILED) return "failed";
  return "running";
}

function mergeInitialState(base, overrides) {
  if (!overrides) return base;

  return {
    ...base,
    ...overrides,
    navigation: { ...base.navigation, ...overrides.navigation },
    entities: { ...base.entities, ...overrides.entities },
    collections: { ...base.collections, ...overrides.collections },
    run: {
      ...base.run,
      ...overrides.run,
      decision: { ...base.run.decision, ...overrides.run?.decision },
      interruptions: overrides.run?.interruptions
        ? [...overrides.run.interruptions]
        : [...base.run.interruptions],
    },
    ui: { ...base.ui, ...overrides.ui },
  };
}

export function createInitialPrototypeState(overrides) {
  const fixtures = createFixtureSnapshot();
  const currentTask = fixtures.tasks.find((task) => task.id === fixtures.initialRun.taskId);

  const base = {
    navigation: {
      activeView: NAVIGATION_VIEW.TASK,
      activeTaskId: currentTask.id,
      activeProductId: currentTask.productId,
      activeTemplateId: currentTask.templateId,
      activeExecutionId: currentTask.executionId,
      activeEvidenceId: null,
      activeIssueId: currentTask.issueIds[0] ?? null,
    },
    entities: {
      products: indexById(fixtures.products),
      templates: indexById(fixtures.templates),
      tasks: indexById(fixtures.tasks),
      executionRecords: indexById(fixtures.executionRecords),
      evidence: indexById(fixtures.evidence),
      issues: indexById(fixtures.issues),
      runtimeIdentities: indexById(fixtures.runtimeIdentities),
    },
    collections: {
      productIds: fixtures.products.map((item) => item.id),
      unclaimedProductIds: fixtures.unclaimedProducts.map((item) => item.id),
      templateIds: fixtures.templates.map((item) => item.id),
      taskIds: fixtures.tasks.map((item) => item.id),
      executionRecordIds: fixtures.executionRecords.map((item) => item.id),
      evidenceIds: fixtures.evidence.map((item) => item.id),
      issueIds: fixtures.issues.map((item) => item.id),
      runtimeIdentityIds: fixtures.runtimeIdentities.map((item) => item.id),
    },
    run: fixtures.initialRun,
    ui: {
      evidenceDrawerOpen: false,
      evidenceFocus: "all",
      notice: null,
    },
  };

  return mergeInitialState(base, overrides);
}

function appendExecutionEvent(state, event, executionPatch = {}) {
  const executionId = state.run.executionId;
  const current = state.entities.executionRecords[executionId];
  if (!current) return state.entities.executionRecords;

  return {
    ...state.entities.executionRecords,
    [executionId]: {
      ...current,
      ...executionPatch,
      events: [...current.events, event],
    },
  };
}

function updateActiveTask(state, patch) {
  const task = state.entities.tasks[state.run.taskId];
  if (!task) return state.entities.tasks;

  return {
    ...state.entities.tasks,
    [task.id]: { ...task, ...patch },
  };
}

function appendEvidence(state, item, event, executionPatch) {
  const execution = state.entities.executionRecords[state.run.executionId];
  const task = state.entities.tasks[state.run.taskId];

  return {
    entities: {
      ...state.entities,
      evidence: { ...state.entities.evidence, [item.id]: item },
      executionRecords: {
        ...state.entities.executionRecords,
        [execution.id]: {
          ...execution,
          ...executionPatch,
          evidenceIds: uniqueAppend(execution.evidenceIds, item.id),
          events: [...execution.events, event],
        },
      },
      tasks: {
        ...state.entities.tasks,
        [task.id]: {
          ...task,
          status: executionPatch.status,
          updatedAt: executionPatch.updatedAt,
          completedAt: executionPatch.completedAt ?? task.completedAt,
          evidenceIds: uniqueAppend(task.evidenceIds, item.id),
        },
      },
    },
    collections: {
      ...state.collections,
      evidenceIds: uniqueAppend(state.collections.evidenceIds, item.id),
    },
  };
}

export function prototypeReducer(state, action) {
  switch (action.type) {
    case PROTOTYPE_ACTION.NAVIGATE: {
      if (!VALID_VIEWS.has(action.view)) return state;
      return {
        ...state,
        navigation: { ...state.navigation, activeView: action.view },
      };
    }

    case PROTOTYPE_ACTION.SELECT_TASK: {
      const task = state.entities.tasks[action.taskId];
      if (!task) return state;
      return {
        ...state,
        navigation: {
          ...state.navigation,
          activeView: NAVIGATION_VIEW.TASK,
          activeTaskId: task.id,
          activeProductId: task.productId,
          activeTemplateId: task.templateId,
          activeExecutionId: task.executionId,
          activeEvidenceId: null,
          activeIssueId: task.issueIds.find((id) => state.entities.issues[id]?.status !== "resolved") ?? null,
        },
        ui: { ...state.ui, evidenceDrawerOpen: false, evidenceFocus: "all" },
      };
    }

    case PROTOTYPE_ACTION.SELECT_TEMPLATE: {
      if (!state.entities.templates[action.templateId]) return state;
      return {
        ...state,
        navigation: {
          ...state.navigation,
          activeView: NAVIGATION_VIEW.TEMPLATE,
          activeTemplateId: action.templateId,
        },
      };
    }

    case PROTOTYPE_ACTION.SELECT_EXECUTION: {
      const execution = state.entities.executionRecords[action.executionId];
      const task = execution ? state.entities.tasks[execution.taskId] : null;
      if (!execution || !task) return state;
      return {
        ...state,
        navigation: {
          ...state.navigation,
          activeView: NAVIGATION_VIEW.HISTORY,
          activeExecutionId: execution.id,
          activeTaskId: task.id,
          activeProductId: task.productId,
          activeTemplateId: task.templateId,
          activeIssueId: execution.issueIds[0] ?? null,
        },
      };
    }

    case PROTOTYPE_ACTION.OPEN_EVIDENCE: {
      const focusAliases = new Set(["all", "result", "category", "blocked"]);
      const isFocusAlias = focusAliases.has(action.evidenceId);
      const item = isFocusAlias ? null : state.entities.evidence[action.evidenceId];
      if (!isFocusAlias && !item) return state;
      return {
        ...state,
        navigation: {
          ...state.navigation,
          activeEvidenceId: item?.id ?? null,
          activeTaskId: item?.taskId ?? state.navigation.activeTaskId,
          activeExecutionId: item?.executionId ?? state.navigation.activeExecutionId,
        },
        ui: {
          ...state.ui,
          evidenceDrawerOpen: true,
          evidenceFocus: item?.id ?? action.evidenceId,
        },
      };
    }

    case PROTOTYPE_ACTION.CLOSE_EVIDENCE:
      return {
        ...state,
        navigation: { ...state.navigation, activeEvidenceId: null },
        ui: { ...state.ui, evidenceDrawerOpen: false },
      };

    case PROTOTYPE_ACTION.OPEN_ISSUE: {
      const issue = state.entities.issues[action.issueId];
      if (!issue) return state;
      return {
        ...state,
        navigation: {
          ...state.navigation,
          activeView: NAVIGATION_VIEW.TASK,
          activeIssueId: issue.id,
          activeTaskId: issue.taskId,
          activeExecutionId: issue.executionId,
        },
      };
    }

    case PROTOTYPE_ACTION.CLEAR_NOTICE:
      return { ...state, ui: { ...state.ui, notice: null } };

    case PROTOTYPE_ACTION.DECISION_APPROVED: {
      if (
        state.run.status !== RUN_STATUS.WAITING_DECISION ||
        ![DECISION_STATUS.PENDING, DECISION_STATUS.DEFERRED].includes(state.run.decision.status)
      ) return state;

      const issue = state.entities.issues[state.run.decision.issueId];
      const event = action.event;
      return {
        ...state,
        entities: {
          ...state.entities,
          issues: issue
            ? {
                ...state.entities.issues,
                [issue.id]: {
                  ...issue,
                  status: "accepted",
                  resolution: "approved_template_normalization",
                  resolvedAt: action.at,
                  resolvedByIdentityId: action.actorIdentityId,
                },
              }
            : state.entities.issues,
          tasks: updateActiveTask(state, { status: "running", updatedAt: action.at }),
          executionRecords: appendExecutionEvent(state, event, {
            status: RUN_STATUS.RUNNING,
            phase: RUN_PHASE.EDIT_SAVE,
            updatedAt: action.at,
          }),
        },
        run: {
          ...state.run,
          runId: action.runId,
          phase: RUN_PHASE.EDIT_SAVE,
          status: RUN_STATUS.RUNNING,
          decision: {
            ...state.run.decision,
            status: DECISION_STATUS.APPROVED,
            decidedAt: action.at,
            decidedByIdentityId: action.actorIdentityId,
          },
          interruptions: [],
          updatedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "success", message: "审批已记录，开始只保存加工" },
        },
      };
    }

    case PROTOTYPE_ACTION.DECISION_DEFERRED: {
      if (
        state.run.status !== RUN_STATUS.WAITING_DECISION ||
        state.run.decision.status === DECISION_STATUS.APPROVED
      ) return state;

      const issue = state.entities.issues[state.run.decision.issueId];
      return {
        ...state,
        entities: {
          ...state.entities,
          issues: issue
            ? {
                ...state.entities.issues,
                [issue.id]: { ...issue, status: "deferred", resolution: "deferred_by_operator" },
              }
            : state.entities.issues,
          tasks: updateActiveTask(state, { status: "waiting_decision", updatedAt: action.at }),
          executionRecords: appendExecutionEvent(state, action.event, {
            status: RUN_STATUS.WAITING_DECISION,
            phase: state.run.phase,
            updatedAt: action.at,
          }),
        },
        run: {
          ...state.run,
          runId: action.runId,
          status: RUN_STATUS.WAITING_DECISION,
          decision: { ...state.run.decision, status: DECISION_STATUS.DEFERRED },
          updatedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "warning", message: "决定已暂缓，任务不会继续推进" },
        },
      };
    }

    case PROTOTYPE_ACTION.DECISION_REOPENED: {
      if (
        state.run.status !== RUN_STATUS.WAITING_DECISION ||
        state.run.decision.status !== DECISION_STATUS.DEFERRED
      ) return state;
      return {
        ...state,
        run: {
          ...state.run,
          runId: action.runId,
          decision: { ...state.run.decision, status: DECISION_STATUS.PENDING },
          updatedAt: action.at,
        },
        ui: { ...state.ui, notice: null },
      };
    }

    case PROTOTYPE_ACTION.RUN_PAUSED: {
      if (
        [RUN_STATUS.PAUSED, RUN_STATUS.MANUAL_TAKEOVER, RUN_STATUS.COMPLETED].includes(state.run.status)
      ) return state;
      const interruption = {
        kind: "pause",
        previousStatus: state.run.status,
        phase: state.run.phase,
        at: action.at,
      };
      return {
        ...state,
        entities: {
          ...state.entities,
          tasks: updateActiveTask(state, { status: "paused", updatedAt: action.at }),
          executionRecords: appendExecutionEvent(state, action.event, {
            status: RUN_STATUS.PAUSED,
            phase: state.run.phase,
            updatedAt: action.at,
          }),
        },
        run: {
          ...state.run,
          runId: action.runId,
          status: RUN_STATUS.PAUSED,
          interruptions: [...state.run.interruptions, interruption],
          updatedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "warning", message: "任务已安全暂停" },
        },
      };
    }

    case PROTOTYPE_ACTION.RUN_RESUMED: {
      const interruption = last(state.run.interruptions);
      if (state.run.status !== RUN_STATUS.PAUSED || interruption?.kind !== "pause") return state;
      const restoredStatus = interruption.previousStatus;
      return {
        ...state,
        entities: {
          ...state.entities,
          tasks: updateActiveTask(state, {
            status: taskStatusFromRunStatus(restoredStatus),
            updatedAt: action.at,
          }),
          executionRecords: appendExecutionEvent(state, action.event, {
            status: restoredStatus,
            phase: state.run.phase,
            updatedAt: action.at,
          }),
        },
        run: {
          ...state.run,
          runId: action.runId,
          status: restoredStatus,
          interruptions: state.run.interruptions.slice(0, -1),
          updatedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "info", message: "任务已从原阶段恢复" },
        },
      };
    }

    case PROTOTYPE_ACTION.TAKEOVER_STARTED: {
      if ([RUN_STATUS.MANUAL_TAKEOVER, RUN_STATUS.COMPLETED].includes(state.run.status)) return state;
      const interruption = {
        kind: "manual_takeover",
        previousStatus: state.run.status,
        phase: state.run.phase,
        at: action.at,
      };
      return {
        ...state,
        entities: {
          ...state.entities,
          tasks: updateActiveTask(state, { status: "manual_takeover", updatedAt: action.at }),
          executionRecords: appendExecutionEvent(state, action.event, {
            status: RUN_STATUS.MANUAL_TAKEOVER,
            phase: state.run.phase,
            updatedAt: action.at,
          }),
        },
        run: {
          ...state.run,
          runId: action.runId,
          status: RUN_STATUS.MANUAL_TAKEOVER,
          interruptions: [...state.run.interruptions, interruption],
          updatedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "warning", message: "已进入人工接管模式" },
        },
      };
    }

    case PROTOTYPE_ACTION.TAKEOVER_ENDED: {
      const interruption = last(state.run.interruptions);
      if (
        state.run.status !== RUN_STATUS.MANUAL_TAKEOVER ||
        interruption?.kind !== "manual_takeover"
      ) return state;
      const restoredStatus = interruption.previousStatus;
      return {
        ...state,
        entities: {
          ...state.entities,
          tasks: updateActiveTask(state, {
            status: taskStatusFromRunStatus(restoredStatus),
            updatedAt: action.at,
          }),
          executionRecords: appendExecutionEvent(state, action.event, {
            status: restoredStatus,
            phase: state.run.phase,
            updatedAt: action.at,
          }),
        },
        run: {
          ...state.run,
          runId: action.runId,
          status: restoredStatus,
          interruptions: state.run.interruptions.slice(0, -1),
          updatedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "info", message: "操作权已交还给 Agent" },
        },
      };
    }

    case PROTOTYPE_ACTION.SAVE_COMPLETED: {
      if (
        action.runId !== state.run.runId ||
        state.run.status !== RUN_STATUS.RUNNING ||
        state.run.phase !== RUN_PHASE.EDIT_SAVE
      ) return state;

      const evidenceUpdate = appendEvidence(state, action.evidence, action.event, {
        status: RUN_STATUS.RUNNING,
        phase: RUN_PHASE.UNPUBLISHED_VERIFY,
        updatedAt: action.at,
      });
      return {
        ...state,
        ...evidenceUpdate,
        run: {
          ...state.run,
          phase: RUN_PHASE.UNPUBLISHED_VERIFY,
          updatedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "success", message: "草稿已单次保存并读回" },
        },
      };
    }

    case PROTOTYPE_ACTION.UNPUBLISHED_VERIFIED: {
      if (
        action.runId !== state.run.runId ||
        state.run.status !== RUN_STATUS.RUNNING ||
        state.run.phase !== RUN_PHASE.UNPUBLISHED_VERIFY
      ) return state;

      const evidenceUpdate = appendEvidence(state, action.evidence, action.event, {
        status: RUN_STATUS.COMPLETED,
        phase: RUN_PHASE.COMPLETE,
        updatedAt: action.at,
        completedAt: action.at,
      });
      return {
        ...state,
        ...evidenceUpdate,
        run: {
          ...state.run,
          phase: RUN_PHASE.COMPLETE,
          status: RUN_STATUS.COMPLETED,
          updatedAt: action.at,
          completedAt: action.at,
        },
        ui: {
          ...state.ui,
          notice: { id: action.event.id, tone: "success", message: "任务完成：已保存且确认未发布" },
        },
      };
    }

    case PROTOTYPE_ACTION.RESET:
      return action.state;

    default:
      return state;
  }
}

function legacyFlowFromRun(run) {
  if (run.status === RUN_STATUS.PAUSED) return "paused";
  if (run.status === RUN_STATUS.MANUAL_TAKEOVER) return "manual";
  if (run.status === RUN_STATUS.COMPLETED) return "complete";
  if (run.decision.status === DECISION_STATUS.DEFERRED) return "deferred";
  if (run.phase === RUN_PHASE.EDIT_SAVE) return "editing";
  if (run.phase === RUN_PHASE.UNPUBLISHED_VERIFY) return "verifying";
  return "approval";
}

function defaultNow() {
  return new Date().toISOString();
}

export function PrototypeProvider({
  children,
  initialState,
  scenarioDelays,
  now = defaultNow,
}) {
  const [state, dispatch] = useReducer(
    prototypeReducer,
    initialState,
    createInitialPrototypeState,
  );
  const stateRef = useRef(state);
  const timersRef = useRef(new Set());
  const idSequenceRef = useRef(0);
  stateRef.current = state;

  const delays = useMemo(
    () => ({ ...DEFAULT_SCENARIO_DELAYS, ...scenarioDelays }),
    [scenarioDelays],
  );

  const clearScenarioTimers = useCallback(() => {
    for (const timer of timersRef.current) globalThis.clearTimeout(timer);
    timersRef.current.clear();
  }, []);

  useEffect(() => clearScenarioTimers, [clearScenarioTimers]);

  const makeId = useCallback((prefix) => {
    idSequenceRef.current += 1;
    return `${prefix}-${Date.now()}-${idSequenceRef.current}`;
  }, []);

  const enqueue = useCallback((runId, delay, buildAction) => {
    const timer = globalThis.setTimeout(() => {
      timersRef.current.delete(timer);
      if (stateRef.current.run.runId !== runId) return;
      dispatch(buildAction());
    }, delay);
    timersRef.current.add(timer);
  }, []);

  const scheduleProgression = useCallback((runId, phase) => {
    if (phase === RUN_PHASE.EDIT_SAVE) {
      enqueue(runId, delays.saveCompleted, () => {
        const current = stateRef.current;
        const at = now();
        const id = makeId("evidence-save");
        return {
          type: PROTOTYPE_ACTION.SAVE_COMPLETED,
          runId,
          at,
          evidence: {
            id,
            taskId: current.run.taskId,
            executionId: current.run.executionId,
            productId: current.entities.tasks[current.run.taskId].productId,
            type: "draft_save_readback",
            title: "草稿单次保存读回成功",
            skill: "controlled_single_save@2.0.1",
            status: "passed",
            result: "保存回包、草稿 ID 与字段读回一致",
            detail: "场景运行器只提交一次保存动作，并读回相同草稿与模板字段。",
            capturedAt: at,
            actorIdentityId: "identity-agent-runtime",
            artifactRef: `prototype://evidence/${current.run.taskId}/save`,
            fingerprint: `mock:${id}`,
          },
          event: {
            id: makeId("event-save"),
            type: "phase.completed",
            phase: RUN_PHASE.EDIT_SAVE,
            at,
            actorIdentityId: "identity-agent-runtime",
            summary: "草稿单次保存并读回",
          },
        };
      });

      enqueue(runId, delays.unpublishedVerified, () => {
        const current = stateRef.current;
        const at = now();
        const id = makeId("evidence-unpublished");
        return {
          type: PROTOTYPE_ACTION.UNPUBLISHED_VERIFIED,
          runId,
          at,
          evidence: {
            id,
            taskId: current.run.taskId,
            executionId: current.run.executionId,
            productId: current.entities.tasks[current.run.taskId].productId,
            type: "unpublished_verification",
            title: "未发布验证通过",
            skill: "verify_unpublished_state@1.5.0",
            status: "passed",
            result: "商品仍为店小秘内部草稿，发布动作计数为 0",
            detail: "独立读取草稿状态与动作账本，未发现发布、定时发布或批量发布事件。",
            capturedAt: at,
            actorIdentityId: "identity-agent-runtime",
            artifactRef: `prototype://evidence/${current.run.taskId}/unpublished`,
            fingerprint: `mock:${id}`,
          },
          event: {
            id: makeId("event-unpublished"),
            type: "run.completed",
            phase: RUN_PHASE.UNPUBLISHED_VERIFY,
            at,
            actorIdentityId: "identity-agent-runtime",
            summary: "未发布验证通过，任务安全结束",
          },
        };
      });
    }

    if (phase === RUN_PHASE.UNPUBLISHED_VERIFY) {
      enqueue(runId, delays.unpublishedVerifiedFromResume, () => {
        const current = stateRef.current;
        const at = now();
        const id = makeId("evidence-unpublished");
        return {
          type: PROTOTYPE_ACTION.UNPUBLISHED_VERIFIED,
          runId,
          at,
          evidence: {
            id,
            taskId: current.run.taskId,
            executionId: current.run.executionId,
            productId: current.entities.tasks[current.run.taskId].productId,
            type: "unpublished_verification",
            title: "未发布验证通过",
            skill: "verify_unpublished_state@1.5.0",
            status: "passed",
            result: "商品仍为店小秘内部草稿，发布动作计数为 0",
            detail: "恢复后重新读取草稿状态与动作账本，未发现任何发布动作。",
            capturedAt: at,
            actorIdentityId: "identity-agent-runtime",
            artifactRef: `prototype://evidence/${current.run.taskId}/unpublished`,
            fingerprint: `mock:${id}`,
          },
          event: {
            id: makeId("event-unpublished"),
            type: "run.completed",
            phase: RUN_PHASE.UNPUBLISHED_VERIFY,
            at,
            actorIdentityId: "identity-agent-runtime",
            summary: "恢复后完成未发布验证",
          },
        };
      });
    }
  }, [delays, enqueue, makeId, now]);

  const navigate = useCallback((view) => {
    dispatch({ type: PROTOTYPE_ACTION.NAVIGATE, view });
  }, []);

  const selectTask = useCallback((taskId) => {
    dispatch({ type: PROTOTYPE_ACTION.SELECT_TASK, taskId });
  }, []);

  const selectTemplate = useCallback((templateId) => {
    dispatch({ type: PROTOTYPE_ACTION.SELECT_TEMPLATE, templateId });
  }, []);

  const selectExecution = useCallback((executionId) => {
    dispatch({ type: PROTOTYPE_ACTION.SELECT_EXECUTION, executionId });
  }, []);

  const openEvidence = useCallback((evidenceId = "all") => {
    dispatch({ type: PROTOTYPE_ACTION.OPEN_EVIDENCE, evidenceId });
  }, []);

  const closeEvidence = useCallback(() => {
    dispatch({ type: PROTOTYPE_ACTION.CLOSE_EVIDENCE });
  }, []);

  const openIssue = useCallback((issueId) => {
    dispatch({ type: PROTOTYPE_ACTION.OPEN_ISSUE, issueId });
  }, []);

  const clearNotice = useCallback(() => {
    dispatch({ type: PROTOTYPE_ACTION.CLEAR_NOTICE });
  }, []);

  const approveDecision = useCallback(() => {
    const current = stateRef.current.run;
    if (
      current.status !== RUN_STATUS.WAITING_DECISION ||
      ![DECISION_STATUS.PENDING, DECISION_STATUS.DEFERRED].includes(current.decision.status)
    ) return false;

    clearScenarioTimers();
    const runId = makeId("scenario-approved");
    const at = now();
    dispatch({
      type: PROTOTYPE_ACTION.DECISION_APPROVED,
      runId,
      at,
      actorIdentityId: "identity-approver-markes",
      event: {
        id: makeId("event-approved"),
        type: "decision.approved",
        phase: RUN_PHASE.TEMPLATE_VALIDATION,
        at,
        actorIdentityId: "identity-approver-markes",
        summary: "批准按模板规范化类目，授权范围仍为单商品只保存",
      },
    });
    scheduleProgression(runId, RUN_PHASE.EDIT_SAVE);
    return true;
  }, [clearScenarioTimers, makeId, now, scheduleProgression]);

  const deferDecision = useCallback(() => {
    const current = stateRef.current.run;
    if (
      current.status !== RUN_STATUS.WAITING_DECISION ||
      current.decision.status === DECISION_STATUS.APPROVED
    ) return false;

    clearScenarioTimers();
    const runId = makeId("scenario-deferred");
    const at = now();
    dispatch({
      type: PROTOTYPE_ACTION.DECISION_DEFERRED,
      runId,
      at,
      event: {
        id: makeId("event-deferred"),
        type: "decision.deferred",
        phase: current.phase,
        at,
        actorIdentityId: "identity-approver-markes",
        summary: "运营暂缓模板校验决定，后续阶段保持锁定",
      },
    });
    return true;
  }, [clearScenarioTimers, makeId, now]);

  const reopenDecision = useCallback(() => {
    const current = stateRef.current.run;
    if (
      current.status !== RUN_STATUS.WAITING_DECISION ||
      current.decision.status !== DECISION_STATUS.DEFERRED
    ) return false;
    clearScenarioTimers();
    dispatch({
      type: PROTOTYPE_ACTION.DECISION_REOPENED,
      runId: makeId("scenario-reopened"),
      at: now(),
    });
    return true;
  }, [clearScenarioTimers, makeId, now]);

  const pauseRun = useCallback(() => {
    const current = stateRef.current.run;
    if ([RUN_STATUS.PAUSED, RUN_STATUS.MANUAL_TAKEOVER, RUN_STATUS.COMPLETED].includes(current.status)) {
      return false;
    }
    clearScenarioTimers();
    const runId = makeId("scenario-paused");
    const at = now();
    dispatch({
      type: PROTOTYPE_ACTION.RUN_PAUSED,
      runId,
      at,
      event: {
        id: makeId("event-paused"),
        type: "run.paused",
        phase: current.phase,
        at,
        actorIdentityId: "identity-operator-local",
        summary: "用户暂停任务，自动推进已取消",
      },
    });
    return true;
  }, [clearScenarioTimers, makeId, now]);

  const resumeRun = useCallback(() => {
    const current = stateRef.current.run;
    const interruption = last(current.interruptions);
    if (current.status !== RUN_STATUS.PAUSED || interruption?.kind !== "pause") return false;

    clearScenarioTimers();
    const runId = makeId("scenario-resumed");
    const at = now();
    dispatch({
      type: PROTOTYPE_ACTION.RUN_RESUMED,
      runId,
      at,
      event: {
        id: makeId("event-resumed"),
        type: "run.resumed",
        phase: current.phase,
        at,
        actorIdentityId: "identity-operator-local",
        summary: "任务从暂停前阶段恢复",
      },
    });
    if (interruption.previousStatus === RUN_STATUS.RUNNING) {
      scheduleProgression(runId, current.phase);
    }
    return true;
  }, [clearScenarioTimers, makeId, now, scheduleProgression]);

  const startTakeover = useCallback(() => {
    const current = stateRef.current.run;
    if ([RUN_STATUS.MANUAL_TAKEOVER, RUN_STATUS.COMPLETED].includes(current.status)) return false;
    clearScenarioTimers();
    const runId = makeId("scenario-manual");
    const at = now();
    dispatch({
      type: PROTOTYPE_ACTION.TAKEOVER_STARTED,
      runId,
      at,
      event: {
        id: makeId("event-manual"),
        type: "run.manual_takeover_started",
        phase: current.phase,
        at,
        actorIdentityId: "identity-operator-local",
        summary: "Agent 已让出操作权并取消自动推进",
      },
    });
    return true;
  }, [clearScenarioTimers, makeId, now]);

  const returnToAgent = useCallback(() => {
    const current = stateRef.current.run;
    const interruption = last(current.interruptions);
    if (
      current.status !== RUN_STATUS.MANUAL_TAKEOVER ||
      interruption?.kind !== "manual_takeover"
    ) return false;

    clearScenarioTimers();
    const runId = makeId("scenario-agent-returned");
    const at = now();
    dispatch({
      type: PROTOTYPE_ACTION.TAKEOVER_ENDED,
      runId,
      at,
      event: {
        id: makeId("event-agent-returned"),
        type: "run.manual_takeover_ended",
        phase: current.phase,
        at,
        actorIdentityId: "identity-operator-local",
        summary: "操作权已交还给 Agent",
      },
    });
    if (interruption.previousStatus === RUN_STATUS.RUNNING) {
      scheduleProgression(runId, current.phase);
    }
    return true;
  }, [clearScenarioTimers, makeId, now, scheduleProgression]);

  const togglePause = useCallback(() => {
    return stateRef.current.run.status === RUN_STATUS.PAUSED ? resumeRun() : pauseRun();
  }, [pauseRun, resumeRun]);

  const resetScenario = useCallback(() => {
    clearScenarioTimers();
    dispatch({ type: PROTOTYPE_ACTION.RESET, state: createInitialPrototypeState(initialState) });
  }, [clearScenarioTimers, initialState]);

  const tasks = state.collections.taskIds.map((id) => state.entities.tasks[id]);
  const unclaimedProducts = state.collections.unclaimedProductIds.map((id) => state.entities.products[id]);
  const templates = state.collections.templateIds.map((id) => state.entities.templates[id]);
  const executionRecords = state.collections.executionRecordIds.map((id) => state.entities.executionRecords[id]);
  const evidence = state.collections.evidenceIds.map((id) => state.entities.evidence[id]);
  const issues = state.collections.issueIds.map((id) => state.entities.issues[id]);
  const runtimeIdentities = state.collections.runtimeIdentityIds.map((id) => state.entities.runtimeIdentities[id]);
  const currentTask = state.entities.tasks[state.navigation.activeTaskId] ?? null;

  const actions = useMemo(() => ({
    navigate,
    selectTask,
    selectTemplate,
    selectExecution,
    openEvidence,
    closeEvidence,
    openIssue,
    clearNotice,
    approveDecision,
    deferDecision,
    reopenDecision,
    pauseRun,
    resumeRun,
    togglePause,
    startTakeover,
    returnToAgent,
    resetScenario,
  }), [
    approveDecision,
    clearNotice,
    closeEvidence,
    deferDecision,
    navigate,
    openEvidence,
    openIssue,
    pauseRun,
    reopenDecision,
    resetScenario,
    resumeRun,
    returnToAgent,
    selectExecution,
    selectTask,
    selectTemplate,
    startTakeover,
    togglePause,
  ]);

  const value = useMemo(() => ({
    state,
    navigation: state.navigation,
    entities: state.entities,
    run: state.run,
    flow: legacyFlowFromRun(state.run),
    tasks,
    unclaimedProducts,
    templates,
    executionRecords,
    evidence,
    issues,
    runtimeIdentities,
    currentTask,
    currentProduct: currentTask ? state.entities.products[currentTask.productId] : null,
    currentTemplate: currentTask ? state.entities.templates[currentTask.templateId] : null,
    currentExecution: currentTask ? state.entities.executionRecords[currentTask.executionId] : null,
    currentIssue: state.navigation.activeIssueId
      ? state.entities.issues[state.navigation.activeIssueId]
      : null,
    activeEvidence: state.navigation.activeEvidenceId
      ? state.entities.evidence[state.navigation.activeEvidenceId]
      : null,
    canControlRun: state.navigation.activeTaskId === state.run.taskId,
    actions,
  }), [
    actions,
    currentTask,
    evidence,
    executionRecords,
    issues,
    runtimeIdentities,
    state,
    tasks,
    templates,
    unclaimedProducts,
  ]);

  return <PrototypeContext.Provider value={value}>{children}</PrototypeContext.Provider>;
}

export function usePrototype() {
  const context = useContext(PrototypeContext);
  if (!context) throw new Error("usePrototype must be used inside <PrototypeProvider>");
  return context;
}
