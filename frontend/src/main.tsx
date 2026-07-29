import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles/index.css";
import {
  activateScreeningProtocol,
  exportScreeningPrisma,
  getScreening,
  recordScreeningDecision,
  saveScreeningProtocol,
  type ScreeningState,
} from "./api";
import {
  advanceResearchRunStep,
  api,
  approveNarrativeMap,
  cancelAgentTask,
  cancelResearchRun,
  createClaimEvidenceLink,
  createClaimExperimentLink,
  createHypothesis,
  createProject,
  download,
  executeExperiment,
  generateDraft,
  getAssurance,
  getClaimEvidenceGraph,
  getInnovationCheck,
  getModelProfiles,
  getResearchRun,
  getWorkflowRunCenter,
  listResearchRuns,
  listWorkflowInputs,
  listAdversarialReviews,
  listAgentCollaborations,
  listAgentTasks,
  listExperiments,
  listWorkflows,
  localSessionToken,
  replayExperiment,
  resumeResearchRun,
  retryResearchRunStep,
  reviseHypothesis,
  resolveWorkflowCheckpoint,
  syncWorkflowEvidence,
  retryAgentTask,
  reviewClaimEvidenceLink,
  reviewClaimExperimentLink,
  reviewClaimSupport,
  reviewEvidenceCard,
  runAdversarialReview,
  runInnovationCheck,
  saveDraft,
  saveEvidenceCard,
  saveModelProfile,
  saveNarrativeMap,
  searchLiterature,
  startAgentCollaboration,
  startAgentTask,
  startResearchRun,
  testModelProfile,
  transitionHypothesis,
  uploadWorkflowInputs,
  uploadWorkflowRequirements,
  type AdversarialReview,
  type AgentCollaboration,
  type AgentTask,
  type AssuranceEnvelope,
  type ClaimEvidenceGraph,
  type ExperimentRun,
  type InnovationCheck,
  type HypothesisVersion,
  type HypothesisWrite,
  type LiteratureRecord,
  type ModelProfile,
  type ModelProfileTest,
  type ModelProfileUpdate,
  type NarrativeMap,
  type Project,
  type ResearchRun,
  type Workflow,
  type WorkflowInput,
  type WorkflowRunCenter,
  type WorkflowTemplate,
} from "./api";
import {
  WorkflowConfiguration,
  type WorkflowDraft,
} from "./workflow-config";
import { WorkflowOperationsPage } from "./workflow-operations";
import {
  FEATURE_ROUTES,
  ROUTE_LABELS,
  navigateToRoute,
  routeFromLocation,
  type FeatureRoute,
} from "./feature-routes";
import { ResearchCockpit, type CockpitNavTarget } from "./cockpit";
import { ResearchMapPage } from "./research-map";
import { EvidencePage } from "./evidence-page";
import {
  errorText,
  evidenceReview,
  inputStatusText,
  machineCitationLabel,
  researchStepLabel,
  statusText,
} from "./research-helpers";
import { Field, Panel, Empty } from "./ui";
import {
  pageFromFeatureRoute,
  featureRouteForPage as featureRouteForShellPage,
  type ShellPage,
} from "./route-boundary";

// ── Extracted page components ──
import { EditorCompilePage, DrawioExportPanel, MermaidExportPanel } from "./pages/editor-compile";
import { ScreeningPage } from "./pages/screening";
import { RunCenterPage, LegacyRunCenterPage, ProjectCard, HypothesisWorkbench } from "./pages/run-center";
import { AuditReviewPage } from "./pages/audit-review";
import { SettingsConnection } from "./pages/settings";
import { fmtTime } from "./lib/format";

type ThemePreset = "warm" | "bright" | "bean" | "custom";
type ThemeColors = { background: string; text: string; accent: string };
const THEME_COLORS: Record<Exclude<ThemePreset, "custom">, ThemeColors> = {
  warm: { background: "#f7f1e6", text: "#342f29", accent: "#9a6b3f" },
  bright: { background: "#f6f8fa", text: "#102b3b", accent: "#00a99d" },
  bean: { background: "#edf4eb", text: "#1e3524", accent: "#2e7d32" },
};
const safeThemeColor = (value: string, fallback: string) =>
  /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
function applyTheme(preset: ThemePreset, custom?: ThemeColors) {
  if (typeof document === "undefined") return;
  const colors = preset === "custom"
    ? {
        background: safeThemeColor(custom?.background || "", "#c7e6c9"),
        text: safeThemeColor(custom?.text || "", "#1e3524"),
        accent: safeThemeColor(custom?.accent || "", "#2e7d32"),
      }
    : THEME_COLORS[preset];
  const root = document.documentElement;
  root.dataset.theme = preset;
  root.style.colorScheme = "light";
  root.style.setProperty("--canvas", colors.background);
  root.style.setProperty("--ink", colors.text);
  root.style.setProperty("--teal", colors.accent);
  root.style.setProperty("--teal-dark", colors.accent);
  root.style.setProperty("--surface", preset === "bright" ? "#ffffff" : `color-mix(in srgb, ${colors.background} 30%, white)`);
  root.style.setProperty("--navy", preset === "warm" ? "#302a25" : preset === "bright" ? "#071827" : colors.text);
}
function restoreLocalTheme() {
  if (typeof window === "undefined") return;
  const preset = (window.localStorage.getItem("vibe-theme-preset") || "bright") as ThemePreset;
  let custom: ThemeColors | undefined;
  try {
    custom = JSON.parse(window.localStorage.getItem("vibe-theme-custom") || "null") || undefined;
  } catch {
    custom = undefined;
  }
  applyTheme(["warm", "bright", "bean", "custom"].includes(preset) ? preset : "bright", custom);
}

type Page =
  | "工作台"
  | "研究项目"
  | "研究地图"
  | "智能工作流"
  | "全局运营台"
  | "执行与产物"
  | "编辑与编译"
  | "文献与证据"
  | "筛选协议"
  | "实验与复现"
  | "科学写作"
  | "审批与审计"
  | "设置与连接";
const pages: Page[] = [
  "工作台",
  "研究项目",
  "研究地图",
  "智能工作流",
  "全局运营台",
  "执行与产物",
  "编辑与编译",
  "文献与证据",
  "筛选协议",
  "实验与复现",
  "科学写作",
  "审批与审计",
  "设置与连接",
];
const pageIcons: Partial<Record<Page, string>> = {
  工作台: "⌂",
  研究项目: "◇",
  研究地图: "◎",
  智能工作流: "✦",
  全局运营台: "⌁",
  执行与产物: "▤",
  编辑与编译: "✎",
  文献与证据: "◎",
  筛选协议: "✓",
  实验与复现: "◌",
  科学写作: "≡",
  审批与审计: "▣",
  设置与连接: "⚙",
};
const navGroups: { label: string; items: Page[] }[] = [
  { label: "工作区", items: ["工作台", "研究项目", "研究地图"] },
  { label: "流程与任务", items: ["智能工作流", "全局运营台", "执行与产物", "编辑与编译"] },
  {
    label: "证据与质量",
    items: ["文献与证据", "筛选协议", "实验与复现", "科学写作", "审批与审计"],
  },
  { label: "系统", items: ["设置与连接"] },
];


/** The compact rail is an orientation aid, not a second complete navigation tree. */
const researchJourneyRoutes = [
  "dashboard",
  "research-map",
  "evidence",
  "experiments",
  "claims",
  "manuscript",
] as const;

const workflowNames: Record<string, string> = {
  idea_discovery: "选题与创新点",
  experiment_bridge: "实验方案",
  auto_review: "多轮审稿",
  paper_writing: "论文写作",
  paper_writing_zh: "论文写作",
  nature_writing: "Nature 风格论文",
  full_pipeline: "完整科研流程",
  thesis_proposal: "开题报告",
  literature_review: "文献综述",
  course_paper: "课程论文",
  course_report: "课程报告",
  paper_from_assets: "已有资料写论文",
  paper_slides: "论文 → 会议幻灯片",
  paper_poster: "论文 → 会议海报",
  one_sentence_project: "一句话生成项目",
  grad_project: "一句话生成项目",
  software_copyright: "软件著作权材料",
  copyright_material: "生成软著申请资料",
  humanities_paper: "人文社科论文",
  patent_disclosure: "专利交底书",
};
type TemplateCategory =
  | "research"
  | "academic"
  | "competition"
  | "assets"
  | "communication"
  | "one_sentence"
  | "ip";
const templateCategories: {
  id: TemplateCategory;
  label: string;
  detail: string;
  icon: string;
  templates: string[];
}[] = [
  {
    id: "research",
    label: "科研工作流",
    detail: "从选题、实验到审稿的完整研究闭环。",
    icon: "✦",
    templates: [
      "idea_discovery",
      "experiment_bridge",
      "auto_review",
      "full_pipeline",
    ],
  },
  {
    id: "academic",
    label: "学术写作",
    detail: "论文、综述、开题与课程成果。",
    icon: "≡",
    // 统一写作入口卡为 paper_writing，配置页内再切通用/Nature/人文与中英文。
    templates: [
      "paper_writing",
      "thesis_proposal",
      "literature_review",
      "course_paper",
      "course_report",
    ],
  },
  {
    id: "competition",
    label: "竞赛工作流",
    detail: "按赛事规则组织建模、代码、图表与提交文档。",
    icon: "◈",
    // 中文赛事后接英文赛事，保持既有入口顺序。
    templates: [
      "comp_tianfu",
      "comp_certcup",
      "comp_mathorcup",
      "comp_teddy",
      "comp_huadong",
      "comp_huazhong",
      "comp_wuyi",
      "comp_zhongqing",
      "comp_yangtze",
      "comp_stats",
      "comp_shuwei",
      "comp_diangong",
      "comp_liaoning",
      "comp_apmcm_zh",
      "comp_shenzhen",
      "comp_huashu",
      "comp_cumcm",
      "comp_huawei",
      "comp_mcm",
      "comp_shuwei_en",
      "comp_apmcm",
      "comp_certcup_en",
    ],
  },
  {
    id: "assets",
    label: "已有资料写论文",
    detail: "先清点代码、数据、图表和已有文本，再补齐论文。",
    icon: "▤",
    templates: ["paper_from_assets"],
  },
  {
    id: "communication",
    label: "幻灯片 · 海报",
    detail: "从已编译论文生成会议报告幻灯片与 A0/A1 海报，并导出可编辑 PPTX。",
    icon: "▣",
    templates: ["paper_slides", "paper_poster"],
  },
  {
    id: "one_sentence",
    label: "一句话生成项目",
    detail: "把一句构想转为研究合同、项目蓝图与里程碑。",
    icon: "➜",
    templates: ["grad_project"],
  },
  {
    id: "ip",
    label: "软著 · 专利",
    detail: "从真实代码与技术材料生成可复核的知识产权草稿。",
    icon: "▣",
    // software_copyright: inventory four-pack from real code; copyright_material: form pack; patent_disclosure: 交底书.
    templates: ["software_copyright", "copyright_material", "patent_disclosure"],
  },
];
const workflowDescriptions: Record<string, string> = {
  full_pipeline: "文献、创新点、实验、写作、编译与改进循环。",
  idea_discovery: "定位研究空白，形成可验证假设与实验计划。",
  experiment_bridge: "把实验方案连接到代码、结果和图表产物。",
  auto_review: "运行多轮审稿、修改和质量复核。",
  paper_writing: "通用学术 / Nature 顶刊 / 人文社科 — 卡片内切换分支，各有专属规划与撰写 skill。",
  paper_writing_zh: "中文论文规划、分析、图表、写作与编译。",
  nature_writing: "按高水平期刊叙事组织图表、方法和正文。",
  literature_review: "检索、筛选并形成带来源的结构化综述。",
  thesis_proposal: "生成开题正文、技术路线与 Word 产物。",
  course_paper: "完成课程论文的分析、图表、写作与导出。",
  course_report: "从事实清点到课程报告与 Word 导出。",
  paper_from_assets: "以已有材料为事实边界，清点冲突并补齐论文。",
  paper_slides: "从 paper/ 编译结果生成 Beamer PDF、演讲稿与可编辑 PPTX。",
  paper_poster: "从 paper/ 编译结果生成 A0/A1 海报 PDF、讲解稿与可编辑 PPTX。",
  one_sentence_project: "生成项目蓝图、研究合同草案和可验收里程碑。",
  grad_project: "从一句想法完成需求、设计、真实编码、自测和可选项目报告。",
  software_copyright: "扫描真实代码与截图，生成说明书、代码索引和申请清单。",
  copyright_material: "起草申请表、操作手册与代码材料，并生成正式 Word/TXT。",
  humanities_paper: "以文本细读、理论框架和真实文献对话完成纯文字论证论文。",
  patent_disclosure: "形成发明交底、权利要求骨架、检索与附图计划。",
};
const workflowInputRequirements: Record<string, string> = {
  paper_from_assets: "请先上传论文素材、数据或已有文稿。",
  paper_slides: "请先上传已编译论文目录（paper/main.tex 或 main.pdf，以及 figures/）。",
  paper_poster: "请先上传已编译论文目录（paper/main.tex 或 main.pdf，以及 figures/）。",
  software_copyright: "请先上传源代码、界面截图或现有产品材料。",
};
/** Format an ISO timestamp for display (e.g. "2026-07-27 15:21"). Falls back to the raw string if the date is invalid. */

const emptyNarrative = (): NarrativeMap => ({
  question: "",
  tension: "",
  mechanism: "",
  hypotheses: [""],
  claims: ["C1"],
  competing_explanations: [""],
  boundaries: [""],
  limitations: [""],
});

export function App() {
  const featureRouteForPage = (value: Page): FeatureRoute | "dashboard" =>
    featureRouteForShellPage(value as ShellPage);
  const goToFeatureRoute = (route: FeatureRoute | "dashboard" | CockpitNavTarget) => {
    const normalized: FeatureRoute | "dashboard" =
      route === "dashboard" || (FEATURE_ROUTES as readonly string[]).includes(route)
        ? (route as FeatureRoute | "dashboard")
        : "dashboard";
    setPage(pageFromFeatureRoute(normalized) as Page);
    navigateToRoute(normalized);
  };
  const goToPage = (value: Page) => {
    setPage(value);
    navigateToRoute(featureRouteForPage(value));
  };
  const [page, setPage] = useState<Page>(() => pageFromFeatureRoute(routeFromLocation()) as Page),
    [connected, setConnected] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [title, setTitle] = useState(""),
    [question, setQuestion] = useState(""),
    [criteria, setCriteria] = useState(""),
    [projects, setProjects] = useState<Project[]>([]),
    [project, setProject] = useState<Project>();
  const [records, setRecords] = useState<LiteratureRecord[]>([]),
    [provider, setProvider] = useState("openalex"),
    [evidenceNotice, setEvidenceNotice] = useState("");
  const [templateCategory, setTemplateCategory] =
      useState<TemplateCategory>("research"),
    [oneSentenceIdea, setOneSentenceIdea] = useState(""),
    [configTemplate, setConfigTemplate] = useState("");
  const [templates, setTemplates] = useState<Record<string, WorkflowTemplate>>(
      {},
    ),
    [workflows, setWorkflows] = useState<Workflow[]>([]),
    [selectedId, setSelectedId] = useState(""),
    [editorFiles, setEditorFiles] = useState<string[]>([]),
    [editorPath, setEditorPath] = useState(""),
    [editorContent, setEditorContent] = useState("");
  const [doctor, setDoctor] = useState<Record<string, unknown>>(),
    [agentManifest, setAgentManifest] = useState<Record<string, unknown>>(),
    [run, setRun] = useState<ResearchRun>(),
    [researchRuns, setResearchRuns] = useState<
      Array<Pick<ResearchRun, "id" | "project_id" | "status" | "current_step" | "created_at" | "updated_at">>
    >([]);
  const [draft, setDraft] = useState(""),
    [draftHash, setDraftHash] = useState("");
  const [controlValues, setControlValues] = useState("1, 2, 3"),
    [treatmentValues, setTreatmentValues] = useState("2, 4, 6"),
    [metric, setMetric] = useState("outcome"),
    [seeds, setSeeds] = useState(3),
    [experiments, setExperiments] = useState<ExperimentRun[]>([]),
    [analysisMode, setAnalysisMode] = useState<"exploratory" | "confirmatory">(
      "confirmatory",
    ),
    [experimentHypothesisId, setExperimentHypothesisId] = useState("");
  const [agentAdapter, setAgentAdapter] = useState("codex"),
    [agentPrompt, setAgentPrompt] = useState(
      "只读检查当前项目，并用三条要点总结可验证的下一步。",
    ),
    [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  const [collabGoal, setCollabGoal] = useState(
      "协调执行、独立审稿与编辑角色，产出可审计的多 Agent 协作报告。",
    ),
    [collaborations, setCollaborations] = useState<AgentCollaboration[]>([]);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]),
    [modelProfileTests, setModelProfileTests] = useState<
      Record<string, ModelProfileTest>
    >({});
  const [adversarialReviews, setAdversarialReviews] = useState<
      AdversarialReview[]
    >([]),
    [assurance, setAssurance] = useState<AssuranceEnvelope>(),
    [innovationCheck, setInnovationCheck] = useState<InnovationCheck>(),
    [innovationOverride, setInnovationOverride] = useState(""),
    [runCenter, setRunCenter] = useState<WorkflowRunCenter>(),
    [workflowInputs, setWorkflowInputs] = useState<WorkflowInput[]>([]),
    [checkpointFeedback, setCheckpointFeedback] = useState("");
  const [narrative, setNarrative] = useState<NarrativeMap>(emptyNarrative);
  const [claimGraph, setClaimGraph] = useState<ClaimEvidenceGraph>();
  const selected = useMemo(
    () => workflows.find((w) => w.id === selectedId),
    [workflows, selectedId],
  );
  const currentHypotheses = useMemo(
    () => (project?.hypotheses || []).filter((item) => item.is_current),
    [project],
  );
  const frozenHypotheses = useMemo(
    () => currentHypotheses.filter((item) => item.status === "frozen"),
    [currentHypotheses],
  );
  const savedRecordUrls = useMemo(
    () =>
      new Set(
        (project?.evidence_cards || []).map((card) => card.canonical_url),
      ),
    [project],
  );
  const runSafe = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const refreshWorkflows = async (projectId = project?.id) => {
    if (!projectId) {
      setWorkflows([]);
      setSelectedId("");
      return;
    }
    const list = await listWorkflows(projectId);
    setWorkflows(list);
    setSelectedId((current) =>
      list.some((item) => item.id === current) ? current : list[0]?.id || "",
    );
  };
  const loadDoctor = async () =>
    setDoctor(await api<Record<string, unknown>>("/api/environment/doctor"));
  const loadClaimGraph = async (projectId: string) =>
    setClaimGraph(await getClaimEvidenceGraph(projectId));
  const loadModelProfiles = async () =>
    setModelProfiles((await getModelProfiles()).profiles);
  const loadAdversarialReviews = async (projectId: string) =>
    setAdversarialReviews(await listAdversarialReviews(projectId));
  const loadAssurance = async (projectId: string) =>
    setAssurance(await getAssurance(projectId));
  const loadInnovationCheck = async (projectId: string) =>
    setInnovationCheck(await getInnovationCheck(projectId));
  const loadProjectContext = async (value: Project) => {
    setProject(value);
    setTitle(value.title);
    setQuestion(value.research_question);
    setCriteria(value.inclusion_criteria);
    setDraft("");
    setDraftHash("");
    setRun(undefined);
    setRunCenter(undefined);
    setWorkflowInputs([]);
    setCheckpointFeedback("");
    const frozen = (value.hypotheses || []).filter(
      (item) => item.is_current && item.status === "frozen",
    );
    setExperimentHypothesisId((current) =>
      frozen.some((item) => item.id === current) ? current : frozen[0]?.id || "",
    );
    window.localStorage.setItem("vibe-active-project", value.id);
    const [
      experimentItems,
      taskItems,
      collabItems,
      workflowItems,
      narrativeValue,
      draftValue,
      researchRunList,
    ] = await Promise.all([
      listExperiments(value.id),
      listAgentTasks(value.id),
      listAgentCollaborations(value.id).catch(() => []),
      listWorkflows(value.id),
      api<NarrativeMap>(`/api/research-projects/${value.id}/narrative`).catch(
        () => undefined,
      ),
      api<{ content: string; sha256: string }>(
        `/api/research-projects/${value.id}/draft`,
      ).catch(() => undefined),
      listResearchRuns(value.id).catch(() => undefined),
    ]);
    setExperiments(experimentItems);
    setAgentTasks(taskItems);
    setCollaborations(collabItems);
    setWorkflows(workflowItems);
    setResearchRuns(researchRunList?.runs || []);
    setRun(researchRunList?.active || undefined);
    setSelectedId((current) =>
      workflowItems.some((item) => item.id === current)
        ? current
        : workflowItems[0]?.id || "",
    );
    setNarrative(narrativeValue || emptyNarrative());
    if (draftValue) {
      setDraft(draftValue.content);
      setDraftHash(draftValue.sha256);
    }
    // Non-critical secondary loads: failures must not abort project selection.
    await Promise.all([
      loadClaimGraph(value.id).catch(() => {}),
      loadAdversarialReviews(value.id).catch(() => {}),
      loadAssurance(value.id).catch(() => {}),
      loadInnovationCheck(value.id).catch(() => {}),
    ]);
  };
  useEffect(() => {
    const handlePopState = () => {
      const route = routeFromLocation();
      setPage(pageFromFeatureRoute(route) as Page);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [page]);
  useEffect(() => {
    document.documentElement.lang = "zh-CN";
    document.title = "Vibe Research";
    restoreLocalTheme();
    localSessionToken()
      .then((t) => {
        // In desktop mode a real token means connected; in web/dev mode,
        // fall back to a health-check so the UI doesn't show "disconnected"
        // just because localStorage has no token.
        if (t) { setConnected(true); return; }
        return fetch("/api/health")
          .then((r) => setConnected(r.ok))
          .catch(() => setConnected(false));
      })
      .catch(() => setConnected(false));
    runSafe(async () => {
      const [templateData, projectItems] = await Promise.all([
        api<Record<string, WorkflowTemplate>>("/api/templates"),
        api<Project[]>("/api/research-projects"),
      ]);
      setTemplates(templateData);
      setProjects(projectItems);
      const preferred = window.localStorage.getItem("vibe-active-project");
      const selectedProject =
        projectItems.find((item) => item.id === preferred) || projectItems[0];
      if (selectedProject) await loadProjectContext(selectedProject);
      await Promise.all([loadDoctor(), loadModelProfiles()]);
      setAgentManifest(
        await api<Record<string, unknown>>("/api/agents/manifest"),
      );
    });
  }, []);
  useEffect(() => {
    if (
      !project ||
      !agentTasks.some((item) =>
        ["queued", "running", "cancelling"].includes(item.status),
      )
    )
      return;
    const timer = window.setInterval(
      () =>
        listAgentTasks(project.id)
          .then(setAgentTasks)
          .catch(() => {}),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [project, agentTasks]);
  useEffect(() => {
    if (!selectedId) {
      setRunCenter(undefined);
      setEditorFiles([]);
      setEditorPath("");
      setWorkflowInputs([]);
      return;
    }
    let cancelled = false;
    setRunCenter(undefined);
    setEditorFiles([]);
    setEditorPath("");
    setWorkflowInputs([]);
    void runSafe(async () => {
      const [snapshot, files, inputs] = await Promise.all([
        getWorkflowRunCenter(selectedId),
        api<{ files: string[] }>(`/api/editor/${selectedId}/files`),
        listWorkflowInputs(selectedId),
      ]);
      if (cancelled) return;
      setRunCenter(snapshot);
      setWorkflows((items) =>
        items.map((item) =>
          item.id === snapshot.workflow.id ? snapshot.workflow : item,
        ),
      );
      setEditorFiles(files.files);
      setWorkflowInputs(inputs);
      setEditorPath((current) =>
        files.files.includes(current) ? current : files.files[0] || "",
      );
    });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);
  useEffect(() => {
    if (
      !selectedId ||
      !workflowInputs.some((item) =>
        ["pending", "running"].includes(item.status),
      )
    )
      return;
    let cancelled = false;
    const timer = window.setInterval(
      () =>
        listWorkflowInputs(selectedId)
          .then((items) => {
            if (!cancelled) setWorkflowInputs(items);
          })
          .catch(() => {}),
      1000,
    );
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId, workflowInputs]);
  useEffect(() => {
    if (
      !selectedId ||
      !["running", "paused"].includes(runCenter?.workflow.status || "")
    )
      return;
    let cancelled = false;
    const timer = window.setInterval(
      () =>
        getWorkflowRunCenter(selectedId)
          .then((snapshot) => {
            if (cancelled || snapshot.workflow.id !== selectedId) return;
            setRunCenter(snapshot);
            setWorkflows((items) =>
              items.map((item) =>
                item.id === snapshot.workflow.id ? snapshot.workflow : item,
              ),
            );
          })
          .catch(() => {}),
      1500,
    );
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId, runCenter?.workflow.status]);
  const createContract = () =>
    runSafe(async () => {
      const value = await createProject(title, question, criteria);
      setProjects((items) => [value, ...items]);
      setAdversarialReviews([]);
      setAssurance(undefined);
      setInnovationCheck(undefined);
      setInnovationOverride("");
      await loadProjectContext(value);
      goToPage("智能工作流");
    });
  const selectProject = (projectId: string) =>
    runSafe(async () => {
      const value = await api<Project>(`/api/research-projects/${projectId}`);
      await loadProjectContext(value);
    });
  const search = () =>
    runSafe(async () => {
      setEvidenceNotice("");
      setRecords((await searchLiterature(provider, question)).records);
      goToPage("文献与证据");
    });
  const saveRecord = (record: LiteratureRecord) =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const saved = await saveEvidenceCard(
        project.id,
        record.provider,
        record.query_snapshot,
        record.url,
        record.snapshot_sha256,
      );
      setProject(saved);
      setProjects((items) =>
        items.map((item) => (item.id === saved.id ? saved : item)),
      );
      setEvidenceNotice(
        `已保存《${record.title}》。请在下方证据卡中完成引用与主张支持核验；核验前项目会继续显示“需要证据”。`,
      );
      await loadClaimGraph(project.id);
    });
  const reviewCard = (cardId: string, decision: "approved" | "rejected") =>
    runSafe(async () => {
      if (!project) return;
      try {
        const reviewed = await reviewEvidenceCard(
          project.id,
          cardId,
          decision,
          decision === "approved"
            ? "已核对题名、作者、年份与来源"
            : "来源信息不符合纳入标准",
        );
        setProject(reviewed);
        setProjects((items) =>
          items.map((item) => (item.id === reviewed.id ? reviewed : item)),
        );
        setEvidenceNotice(
          decision === "approved"
            ? "引用已批准；机器存在性核验已写入证据卡与 citation_checks 产物。"
            : "引用已驳回；机器存在性核验结果仍保留在证据卡中。",
        );
      } catch (error) {
        // 409 machine FAIL persists verdict/artifact before rejecting approve.
        try {
          const refreshed = await api<Project>(
            `/api/research-projects/${project.id}`,
          );
          setProject(refreshed);
          setProjects((items) =>
            items.map((item) => (item.id === refreshed.id ? refreshed : item)),
          );
          const blocked = refreshed.evidence_cards.find(
            (item) => item.id === cardId,
          );
          if (blocked?.citation_machine_verdict) {
            setEvidenceNotice(
              `机器引用核验 ${blocked.citation_machine_verdict}` +
                (blocked.citation_machine_layer
                  ? ` · ${blocked.citation_machine_layer}`
                  : "") +
                (blocked.citation_machine_detail
                  ? ` · ${blocked.citation_machine_detail}`
                  : "") +
                (blocked.citation_machine_artifact_path
                  ? ` · 产物 ${blocked.citation_machine_artifact_path}`
                  : ""),
            );
          }
        } catch {
          /* keep original error */
        }
        throw error;
      }
      await loadClaimGraph(project.id);
    });
  const reviewSupport = (cardId: string, decision: "approved" | "rejected") =>
    runSafe(async () => {
      if (!project) return;
      const updated = await reviewClaimSupport(
        project.id,
        cardId,
        decision,
        decision === "approved"
          ? "原文段落与当前主张在适用范围内一致"
          : "原文不足以支持当前主张",
      );
      setProject(updated);
      setProjects((items) =>
        items.map((item) => (item.id === updated.id ? updated : item)),
      );
    });
  const createDraft = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const value = await generateDraft(project.id);
      setDraft(value.content);
      setDraftHash(value.sha256);
    });
  const persistDraft = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const value = await saveDraft(project.id, draft);
      setDraftHash(value.sha256);
    });
  const persistWorkflow = async (
    activeProject: Project,
    template: string,
    profile = "",
    configuredParams: Record<string, unknown> = {},
    enableCheckpoints = true,
  ) =>
    api<{ id: string }>("/api/workflows", {
      method: "POST",
      body: JSON.stringify({
        project_id: activeProject.id,
        template,
        title: profile || title || question || "未命名研究任务",
        params: {
          research_question: activeProject.research_question,
          inclusion_criteria: activeProject.inclusion_criteria,
          template_profile: profile,
          ...configuredParams,
        },
        enable_checkpoints: enableCheckpoints,
      }),
    });
  const createWorkflow = (template: string, profile = "") =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const created = await persistWorkflow(project, template, profile);
      await refreshWorkflows(project.id);
      setSelectedId(created.id);
      goToPage("执行与产物");
    });
  const generateProjectFromSentence = () =>
    runSafe(async () => {
      const idea = oneSentenceIdea.trim();
      if (idea.length < 6) throw new Error("请用至少六个字符描述研究构想");
      setConfigTemplate("grad_project");
    });
  const createConfiguredWorkflow = async (draft: WorkflowDraft) =>
    runSafe(async () => {
      let activeProject = project;
      if (!activeProject) {
        activeProject = await createProject(
          draft.title.slice(0, 100),
          String(draft.params.problem_statement || draft.title),
          "纳入与任务直接相关且来源可追溯的资料；排除无法核验、重复或超出任务边界的材料",
        );
        setProjects((items) => [activeProject!, ...items]);
        await loadProjectContext(activeProject);
      }
      const created = await persistWorkflow(
        activeProject,
        draft.template,
        draft.title,
        draft.params,
        draft.enableCheckpoints,
      );
      for (const group of draft.fileGroups) {
        for (let index = 0; index < group.files.length; index += 10)
          await uploadWorkflowInputs(created.id, group.files.slice(index, index + 10), group.role);
      }
      if (draft.requirementsFile)
        await uploadWorkflowRequirements(created.id, draft.requirementsFile);
      if (draft.autoStart)
        await api(`/api/workflows/${created.id}/start`, { method: "POST" });
      await refreshWorkflows(activeProject.id);
      setSelectedId(created.id);
      setConfigTemplate("");
      goToPage("执行与产物");
    });
  const workflowAction = (
    id: string,
    action: "start" | "pause" | "resume" | "restart",
  ) =>
    runSafe(async () => {
      setSelectedId(id);
      if (action === "start") {
        const workflow = workflows.find((item) => item.id === id);
        const inputs = await listWorkflowInputs(id);
        if (workflow?.template && workflowInputRequirements[workflow.template] && !inputs.length)
          throw new Error(workflowInputRequirements[workflow.template]);
        setWorkflowInputs(inputs);
      }
      await api(`/api/workflows/${id}/${action}`, { method: "POST" });
      await refreshWorkflows();
      setRunCenter(await getWorkflowRunCenter(id));
      // Keep evidence_cards fresh: a completed workflow may have created new
      // literature snapshots in the session.
      if (project) await loadProjectContext(project);
    });
  const uploadInputs = (files: File[]) =>
    runSafe(async () => {
      if (!selectedId) throw new Error("请先选择工作流");
      if (!files.length) return;
      await uploadWorkflowInputs(selectedId, files);
      setWorkflowInputs(await listWorkflowInputs(selectedId));
      setRunCenter(await getWorkflowRunCenter(selectedId));
    });
  const resolveCheckpoint = (action: "approve" | "feedback" | "stop") =>
    runSafe(async () => {
      if (!selectedId) throw new Error("请先选择工作流");
      await resolveWorkflowCheckpoint(
        selectedId,
        action,
        action === "feedback" ? { feedback: checkpointFeedback } : {},
      );
      setCheckpointFeedback("");
      setRunCenter(await getWorkflowRunCenter(selectedId));
    });
  const removeWorkflow = (id: string) =>
    runSafe(async () => {
      if (!window.confirm("删除该工作流及其本地工作区？")) return;
      await api(`/api/workflows/${id}`, { method: "DELETE" });
      if (selectedId === id) setSelectedId("");
      await refreshWorkflows();
    });
  const syncEvidence = (workflowId: string) =>
    runSafe(async () => {
      if (!project) throw new Error("请先绑定研究合同");
      const result = await syncWorkflowEvidence(workflowId);
      // Refresh the project so evidence_cards reflects newly imported items.
      await loadProjectContext(project);
      // Surface result as a non-blocking status message rather than a native dialog.
      const notice =
        result.count > 0
          ? `已从工作流同步 ${result.count} 条文献至证据库。${result.errors.length ? `（${result.errors.length} 个来源跳过）` : ""}`
          : "未发现新文献可同步；请确认工作流已完成文献检索步骤后重试。";
      setError(notice);
    });
  const openWorkflowFromOperations = (
    projectId: string | null | undefined,
    workflowId: string,
    target: "执行与产物" | "编辑与编译",
  ) =>
    runSafe(async () => {
      if (projectId && project?.id !== projectId) {
        const targetProject = await api<Project>(`/api/research-projects/${projectId}`);
        await loadProjectContext(targetProject);
      }
      setSelectedId(workflowId);
      goToPage(target);
    });
  const openEditorFile = (file: string) =>
    runSafe(async () => {
      setEditorPath(file);
      const result = await api<{ content: string }>(
        `/api/editor/${selectedId}/file?path=${encodeURIComponent(file)}`,
      );
      setEditorContent(result.content);
    });
  const saveEditor = () =>
    runSafe(async () => {
      await api(`/api/editor/${selectedId}/file`, {
        method: "PUT",
        body: JSON.stringify({ path: editorPath, content: editorContent }),
      });
    });
  const verifiedArtifacts = useMemo(
    () => (project?.artifacts || []).filter((item) => item.status === "verified"),
    [project],
  );
  const refreshResearchRunList = async (projectId: string) => {
    const listed = await listResearchRuns(projectId);
    setResearchRuns(listed.runs || []);
    return listed;
  };
  const startRun = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const started = await startResearchRun(project.id);
      setRun(started);
      await refreshResearchRunList(project.id);
    });
  const refreshRun = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      if (run?.id) {
        setRun(await getResearchRun(run.id));
        await refreshResearchRunList(project.id);
        return;
      }
      const listed = await refreshResearchRunList(project.id);
      if (!listed.active) throw new Error("尚无研究流程可刷新");
      setRun(listed.active);
    });
  const restoreRun = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const listed = await refreshResearchRunList(project.id);
      if (!listed.active)
        throw new Error("当前项目没有可恢复的研究流程");
      setRun(listed.active);
    });
  const openResearchRun = (runId: string) =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      setRun(await getResearchRun(runId));
      await refreshResearchRunList(project.id);
    });
  const advanceRun = (gatePassed: boolean) =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      if (!run?.id) throw new Error("请先启动研究流程");
      const stepName = String(run.current_step || "");
      if (!stepName) throw new Error("当前流程没有可推进的步骤");
      if (run.status === "cancelled" || run.status === "completed")
        throw new Error("已结束的研究流程不能再推进");
      if (run.status === "blocked")
        throw new Error("流程已阻塞：请先重试阻塞步骤");
      if (gatePassed) {
        if (!verifiedArtifacts.length)
          throw new Error(
            "门禁通过需要服务器已验证产物（例如冻结假设写入的 hypothesis.manifest）；当前项目没有 verified 产物",
          );
        const artifact = verifiedArtifacts[0];
        setRun(
          await advanceResearchRunStep(run.id, stepName, {
            input: {
              step: stepName,
              project_id: project.id,
              source: "workbench",
            },
            artifacts: [{ id: artifact.id }],
            provenance: [{ source: artifact.provenance }],
            gate_passed: true,
            failure_reason: null,
          }),
        );
        return;
      }
      setRun(
        await advanceResearchRunStep(run.id, stepName, {
          input: {
            step: stepName,
            project_id: project.id,
            source: "workbench",
          },
          artifacts: [],
          provenance: [],
          gate_passed: false,
          failure_reason: "工作台诚实阻断：证据或门禁尚未满足",
        }),
      );
    });
  const retryRunStep = () =>
    runSafe(async () => {
      if (!run?.id) throw new Error("请先启动研究流程");
      const blocked = (run.steps || []).find((step) => step.status === "blocked");
      if (!blocked)
        throw new Error("没有可重试的阻塞步骤");
      setRun(await retryResearchRunStep(run.id, blocked.name));
    });
  const resumeRun = () =>
    runSafe(async () => {
      if (!run?.id) throw new Error("请先启动研究流程");
      setRun(await resumeResearchRun(run.id));
    });
  const cancelRun = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      if (!run?.id) throw new Error("请先启动研究流程");
      setRun(
        await cancelResearchRun(
          run.id,
          "用户从工作台取消研究流程",
        ),
      );
      await refreshResearchRunList(project.id);
    });
  const parseValues = (text: string) => {
    const values = text
      .split(/[\s,，;；]+/)
      .filter(Boolean)
      .map(Number);
    if (values.length < 2 || values.some((value) => !Number.isFinite(value)))
      throw new Error("每组至少需要两个有限数值");
    return values;
  };
  const runExperiment = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      if (analysisMode === "confirmatory" && !experimentHypothesisId)
        throw new Error("验证性实验必须先选择一条当前已冻结的可证伪假设");
      const value = await executeExperiment(
        project.id,
        parseValues(controlValues),
        parseValues(treatmentValues),
        seeds,
        metric,
        analysisMode,
        analysisMode === "confirmatory" ? experimentHypothesisId : undefined,
      );
      setExperiments((items) => [value, ...items]);
      await Promise.all([
        loadClaimGraph(project.id),
        loadAssurance(project.id),
        loadInnovationCheck(project.id),
      ]);
    });
  const replayRun = (id: string) =>
    runSafe(async () => {
      const value = await replayExperiment(id);
      setExperiments((items) => [value, ...items]);
    });
  const launchAgent = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const value = await startAgentTask(project.id, agentAdapter, agentPrompt);
      setAgentTasks((items) => [value, ...items]);
    });
  const cancelAgent = (id: string) =>
    runSafe(async () => {
      const value = await cancelAgentTask(id);
      setAgentTasks((items) =>
        items.map((item) => (item.id === id ? value : item)),
      );
    });
  const retryAgent = (id: string) =>
    runSafe(async () => {
      const value = await retryAgentTask(id);
      setAgentTasks((items) => [value, ...items]);
    });
  const launchCollaboration = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const value = await startAgentCollaboration(
        project.id,
        collabGoal,
        ["executor", "reviewer", "editor_ai"],
        [],
      );
      setCollaborations((items) => [value, ...items.filter((item) => item.id !== value.id)]);
    });
  const saveProfile = (role: ModelProfile["role"], value: ModelProfileUpdate) =>
    runSafe(async () => {
      const saved = await saveModelProfile(role, value);
      setModelProfiles((items) =>
        items.map((item) => (item.role === role ? saved : item)),
      );
      setModelProfileTests((items) => {
        const next = { ...items };
        delete next[role];
        return next;
      });
    });
  const testProfile = (role: ModelProfile["role"]) =>
    runSafe(async () => {
      const result = await testModelProfile(role);
      setModelProfileTests((items) => ({ ...items, [role]: result }));
    });
  const runReview = (mode: "deterministic" | "model") =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const result = await runAdversarialReview(project.id, mode);
      setAdversarialReviews((items) => [
        result,
        ...items.filter((item) => item.id !== result.id),
      ]);
      await Promise.all([
        loadAssurance(project.id),
        loadInnovationCheck(project.id),
      ]);
    });
  const runNoveltyCheck = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      const lowIds = innovationCheck?.gate?.low_novelty_claim_ids || [];
      const overrides: Record<string, string> = {};
      if (innovationOverride.trim()) {
        for (const claimId of lowIds.length ? lowIds : ["N1", "H1"]) {
          overrides[claimId] = innovationOverride.trim();
        }
      }
      const result = await runInnovationCheck(project.id, {
        overrides,
        provider: null,
      });
      setInnovationCheck(result);
      await loadAssurance(project.id);
    });
  const saveArgumentMap = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      if (!frozenHypotheses.length)
        throw new Error("先在研究项目页冻结至少一条可证伪假设，再保存论证图");
      setNarrative(
        await saveNarrativeMap(project.id, {
          ...narrative,
          question: narrative.question || question,
          hypotheses: frozenHypotheses.map((item) => item.statement),
        }),
      );
      await loadClaimGraph(project.id);
    });
  const approveArgumentMap = () =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      setNarrative(await approveNarrativeMap(project.id));
    });
  const createClaimLink = (value: {
    claim_id: string;
    evidence_card_id: string;
    relation: "supports" | "contradicts" | "context";
    passage: string;
    locator: string;
  }) =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      setClaimGraph(await createClaimEvidenceLink(project.id, value));
    });
  const reviewClaimLink = (linkId: string, decision: "approved" | "rejected") =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      setClaimGraph(
        await reviewClaimEvidenceLink(
          project.id,
          linkId,
          decision,
          decision === "approved"
            ? "该引文原句支持所述主张。"
            : "该引文原句不足以支持所述主张。",
        ),
      );
    });
  const createExperimentLink = (value: {
    claim_id: string;
    experiment_run_id: string;
    relation: "supports" | "contradicts" | "context";
    result_locator: string;
    interpretation: string;
    evidence_card_ids: string[];
  }) =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      setClaimGraph(await createClaimExperimentLink(project.id, value));
      await loadAssurance(project.id);
    });
  const reviewExperimentLink = (
    linkId: string,
    decision: "approved" | "rejected",
  ) =>
    runSafe(async () => {
      if (!project) throw new Error("请先创建研究合同");
      setClaimGraph(
        await reviewClaimExperimentLink(
          project.id,
          linkId,
          decision,
          decision === "approved"
            ? "该实验结果、统计门禁、冻结假设与证据基础均已复核。"
            : "实验结果不足以支持当前主张。",
        ),
      );
      await loadAssurance(project.id);
    });
  const pageContent = () => {
    if (page === "工作台")
      return (
        <ResearchCockpit
          connected={connected}
          project={project}
          workflows={workflows}
          researchRuns={researchRuns}
          draftText={draft}
          draftHash={draftHash}
          onNavigate={goToFeatureRoute}
        />
      );
    if (page === "设置与连接")
      return (
        <SettingsConnection
          busy={busy}
          doctor={doctor}
          agentManifest={agentManifest}
          project={project}
          agentAdapter={agentAdapter}
          agentPrompt={agentPrompt}
          agentTasks={agentTasks}
          collabGoal={collabGoal}
          collaborations={collaborations}
          modelProfiles={modelProfiles}
          modelProfileTests={modelProfileTests}
          onReloadDoctor={() => runSafe(loadDoctor)}
          onReloadAgents={() =>
            runSafe(async () =>
              setAgentManifest(
                await api<Record<string, unknown>>("/api/agents/manifest"),
              ),
            )
          }
          onAdapterChange={setAgentAdapter}
          onPromptChange={setAgentPrompt}
          onLaunchAgent={launchAgent}
          onReloadTasks={() =>
            runSafe(
              async () =>
                project && setAgentTasks(await listAgentTasks(project.id)),
            )
          }
          onCancelAgent={cancelAgent}
          onRetryAgent={retryAgent}
          onCollabGoalChange={setCollabGoal}
          onLaunchCollaboration={launchCollaboration}
          onReloadCollaborations={() =>
            runSafe(
              async () =>
                project &&
                setCollaborations(await listAgentCollaborations(project.id)),
            )
          }
          onReloadProfiles={() => runSafe(loadModelProfiles)}
          onSaveProfile={saveProfile}
          onTestProfile={testProfile}
        />
      );
    if (page === "审批与审计")
      return (
        <AuditReviewPage
          busy={busy}
          project={project}
          reviews={adversarialReviews}
          assurance={assurance}
          innovation={innovationCheck}
          overrideReason={innovationOverride}
          onOverrideReason={setInnovationOverride}
          onApprove={() =>
            runSafe(async () => {
              if (project)
                setProject(
                  await api<Project>(
                    `/api/research-projects/${project.id}/approval`,
                    {
                      method: "POST",
                      body: JSON.stringify({
                        actor: "researcher",
                        approved: true,
                        reason: "研究合同已由作者复核",
                      }),
                    },
                  ),
                );
            })
          }
          onReload={() =>
            runSafe(async () => project && loadAdversarialReviews(project.id))
          }
          onReloadAssurance={() =>
            runSafe(async () => project && loadAssurance(project.id))
          }
          onReloadInnovation={() =>
            runSafe(async () => project && loadInnovationCheck(project.id))
          }
          onRun={runReview}
          onRunInnovation={runNoveltyCheck}
          onSettings={() => goToPage("设置与连接")}
        />
      );
    if (page === "研究地图")
      return (
        <ResearchMapPage
          busy={busy}
          project={project}
          narrative={narrative}
          frozenHypotheses={frozenHypotheses}
          onNarrativeChange={setNarrative}
          onSave={saveArgumentMap}
          onApprove={approveArgumentMap}
          onOpenProjects={() => goToPage("研究项目")}
          onOpenManuscript={() => goToPage("科学写作")}
        />
      );
    if (page === "研究项目")
      return (
        <Panel
          title="研究项目"
          detail="先界定问题、证据边界与作者责任，再开始自动化工作。"
        >
          <div className="form-grid">
            <Field
              label="项目名称"
              value={title}
              set={setTitle}
              placeholder="例如：睡眠与认知控制的机制研究"
            />
            <Field
              label="研究问题"
              value={question}
              set={setQuestion}
              area
              placeholder="以可检验的问题描述研究目标"
            />
            <Field
              label="纳入与排除标准"
              value={criteria}
              set={setCriteria}
              area
              placeholder="明确检索、数据与证据筛选边界"
            />
          </div>
          <div className="actions">
            <button
              disabled={busy || !title || !question || !criteria}
              onClick={createContract}
            >
              创建研究合同
            </button>
            <button
              className="quiet"
              disabled={busy || question.length < 3}
              onClick={search}
            >
              先检索文献
            </button>
          </div>
          {project && (
            <>
              <ProjectCard project={project} />
              <HypothesisWorkbench
                project={project}
                busy={busy}
                onRun={runSafe}
                onChanged={async (updated) => {
                  setProject(updated);
                  setProjects((items) =>
                    items.map((item) => (item.id === updated.id ? updated : item)),
                  );
                  setDraft("");
                  setDraftHash("");
                  const frozen = (updated.hypotheses || []).filter(
                    (item) => item.is_current && item.status === "frozen",
                  );
                  setExperimentHypothesisId((current) =>
                    frozen.some((item) => item.id === current)
                      ? current
                      : frozen[0]?.id || "",
                  );
                  setExperiments(await listExperiments(updated.id));
                  await Promise.all([
                    loadClaimGraph(updated.id),
                    loadAdversarialReviews(updated.id),
                    loadAssurance(updated.id),
                    loadInnovationCheck(updated.id),
                  ]);
                }}
              />
            </>
          )}
        </Panel>
      );
    if (page === "智能工作流") {
      const category = templateCategories.find(
        (item) => item.id === templateCategory,
      )!;
      if (configTemplate) {
        const templateName =
          workflowNames[configTemplate] ||
          templates[configTemplate]?.name ||
          configTemplate;
        return (
          <Panel
            title="新建工作流"
            detail="逐项配置输出、素材、模板、质量门与执行参数。"
          >
            <WorkflowConfiguration
              key={configTemplate}
              template={configTemplate}
              templateName={templateName}
              initialTitle={
                oneSentenceIdea.trim() ||
                project?.research_question ||
                project?.title ||
                templateName
              }
              busy={busy}
              onBack={() => setConfigTemplate("")}
              onSubmit={createConfiguredWorkflow}
            />
          </Panel>
        );
      }
      return (
        <Panel
          title="智能工作流"
          detail="先选工作流大类，再选择具体模板。每个模板均创建真实持久化任务、执行 DAG、检查点与产物目录。"
        >
          <div
            className="workflow-template-tabs"
            role="tablist"
            aria-label="工作流大类"
          >
            {templateCategories.map((item) => (
              <button
                role="tab"
                aria-selected={templateCategory === item.id}
                className={
                  templateCategory === item.id ? "active quiet" : "quiet"
                }
                key={item.id}
                onClick={() => {
                  setTemplateCategory(item.id);
                  setConfigTemplate("");
                }}
              >
                <span className="template-tab-icon" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="template-tab-copy">
                  <strong>{item.label}</strong>
                  <small>{item.templates.length} 个模板</small>
                </span>
              </button>
            ))}
          </div>
          <section className="template-intro">
            <div>
              <p className="eyebrow">{category.label}</p>
              <h3>{category.detail}</h3>
              <span>
                {project
                  ? `当前项目：${project.title}`
                  : "尚未选择项目；提交配置时会自动建立对应研究合同。"}
              </span>
            </div>
            <button className="quiet" onClick={() => goToPage("研究项目")}>
              {project ? "切换研究项目" : "建立研究项目"}
            </button>
          </section>
          {templateCategory === "one_sentence" && (
            <section className="one-sentence-intake">
              <Field
                label="一句话研究构想"
                value={oneSentenceIdea}
                set={setOneSentenceIdea}
                placeholder="例如：研究睡眠质量是否通过执行控制影响博士生的写作效率"
              />
              <button
                disabled={busy || oneSentenceIdea.trim().length < 6}
                onClick={generateProjectFromSentence}
              >
                生成项目与工作流
              </button>
              <small>
                将真实创建研究合同、项目蓝图工作流和持久化工作区，不会直接伪造研究结论。
              </small>
            </section>
          )}
          <div className="template-grid">
            {category.templates.map((key, index) => {
              const value = templates[key];
              const templateName = workflowNames[key] || value?.name || key;
              return value ? (
                <article className="template featured-template" key={key}>
                  <div className="template-topline">
                    <span className="template-index">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="template-category">{category.label}</span>
                  </div>
                  <h3>{templateName}</h3>
                  <p>
                    {workflowDescriptions[key] ||
                      `${value.steps.length} 个可恢复步骤`}
                  </p>
                  <ul>
                    {value.steps.slice(0, 4).map((step) => (
                      <li key={step.skill_name}>
                        {step.display_name}
                        {step.has_checkpoint ? "（需确认）" : ""}
                      </li>
                    ))}
                  </ul>
                  <button
                    disabled={busy}
                    onClick={() => setConfigTemplate(key)}
                  >
                    配置“{templateName}”
                  </button>
                </article>
              ) : (
                <article className="template template-unavailable" key={key}>
                  <h3>{templateName}</h3>
                  <p>模板注册信息加载失败，未创建任务。</p>
                </article>
              );
            })}
          </div>
        </Panel>
      );
    }
    if (page === "全局运营台")
      return (
        <WorkflowOperationsPage
          projects={projects}
          activeProjectId={project?.id}
          onCreate={() => goToPage("智能工作流")}
          onOpenRun={(projectId, workflowId) =>
            void openWorkflowFromOperations(projectId, workflowId, "执行与产物")
          }
          onOpenEditor={(projectId, workflowId) =>
            void openWorkflowFromOperations(projectId, workflowId, "编辑与编译")
          }
        />
      );
    if (page === "执行与产物")
      return (
        <RunCenterPage
          project={project}
          workflows={workflows}
          selectedId={selectedId}
          snapshot={runCenter}
          inputs={workflowInputs}
          feedback={checkpointFeedback}
          busy={busy}
          onSelected={setSelectedId}
          onFeedback={setCheckpointFeedback}
          onRefresh={() =>
            runSafe(async () => {
              await refreshWorkflows();
              if (selectedId)
                setRunCenter(await getWorkflowRunCenter(selectedId));
            })
          }
          onCreate={() => goToPage("智能工作流")}
          onAction={workflowAction}
          onResolve={resolveCheckpoint}
          onUpload={uploadInputs}
          onRemove={removeWorkflow}
          onSync={syncEvidence}
          onDownload={(workflow) =>
            runSafe(() =>
              download(
                `/api/workflows/${workflow.id}/export`,
                `${workflow.title}.zip`,
              ),
            )
          }
        />
      );
    if (page === "编辑与编译")
      return (
        <>
          <EditorCompilePage
            workflows={workflows}
            selectedId={selectedId}
            onSelected={setSelectedId}
            busy={busy}
            onRun={runSafe}
          />
          <DrawioExportPanel
            workflows={workflows}
            selectedId={selectedId}
            onSelected={setSelectedId}
            busy={busy}
            onRun={runSafe}
          />
          <MermaidExportPanel
            workflows={workflows}
            selectedId={selectedId}
            onSelected={setSelectedId}
            busy={busy}
            onRun={runSafe}
          />
        </>
      );
    if (page === "筛选协议")
      return <ScreeningPage project={project} busy={busy} onRun={runSafe} />;
    if (page === "文献与证据")
      return (
        <EvidencePage
          busy={busy}
          provider={provider}
          question={question}
          records={records}
          evidenceNotice={evidenceNotice}
          project={project}
          savedRecordUrls={savedRecordUrls}
          onProviderChange={setProvider}
          onQuestionChange={setQuestion}
          onSearch={search}
          onSaveRecord={saveRecord}
          onReviewCard={reviewCard}
          onReviewSupport={reviewSupport}
        />
      );
    if (page === "实验与复现")
      return (
        <Panel
          title="实验与复现"
          detail="在本机受限工作区运行真实计算，保存输入、stdout/stderr、统计门禁、manifest 和结果 SHA256；失败结果不会显示为成功。"
        >
          <div className="form-grid">
            <label>
              分析模式
              <select
                value={analysisMode}
                onChange={(event) =>
                  setAnalysisMode(
                    event.target.value as "exploratory" | "confirmatory",
                  )
                }
              >
                <option value="confirmatory">验证性（必须绑定冻结假设）</option>
                <option value="exploratory">探索性（不可直接支持验证性主张）</option>
              </select>
            </label>
            <label>
              冻结假设版本
              <select
                value={experimentHypothesisId}
                disabled={analysisMode === "exploratory"}
                onChange={(event) => setExperimentHypothesisId(event.target.value)}
              >
                <option value="">选择当前已冻结版本</option>
                {frozenHypotheses.map((item) => (
                  <option key={item.id} value={item.id}>
                    H-{item.hypothesis_id.slice(0, 8)} v{item.version} · {item.statement}
                  </option>
                ))}
              </select>
            </label>
            <Field
              label="对照组数值"
              value={controlValues}
              set={setControlValues}
              placeholder="1, 2, 3"
            />
            <Field
              label="处理组数值"
              value={treatmentValues}
              set={setTreatmentValues}
              placeholder="2, 4, 6"
            />
            <Field
              label="指标名称"
              value={metric}
              set={setMetric}
              placeholder="结果指标"
            />
            <label>
              独立随机种子
              <input
                type="number"
                min="1"
                max="1000"
                value={seeds}
                onChange={(event) => setSeeds(Number(event.target.value))}
              />
            </label>
          </div>
          <div className="actions">
            <button
              disabled={
                busy ||
                !project ||
                (analysisMode === "confirmatory" && !experimentHypothesisId)
              }
              onClick={runExperiment}
            >
              运行可复现实验
            </button>
            <button
              className="quiet"
              disabled={busy || !project}
              onClick={() =>
                runSafe(
                  async () =>
                    project &&
                    setExperiments(await listExperiments(project.id)),
                )
              }
            >
              恢复历史运行
            </button>
            <button
              className="quiet"
              disabled={busy || !project}
              onClick={startRun}
            >
              启动研究流程
            </button>
          </div>
          <section className="graph-gate" aria-label="研究流程 Golden Path">
            <b>研究流程 · 非伪造门禁</b>
            <span>
              推进依赖服务器已验证产物（verified artifacts），客户端
              gate_passed 标志不能单独通过门禁。已验证产物{" "}
              {verifiedArtifacts.length} 个
              {verifiedArtifacts[0]
                ? ` · 将使用 ${verifiedArtifacts[0].kind || "artifact"} ${verifiedArtifacts[0].id.slice(0, 8)}`
                : " · 请先冻结假设或写入可核验产物"}
            </span>
            <div className="actions">
              <button
                className="quiet"
                disabled={busy || !project}
                onClick={startRun}
              >
                启动 / 新建
              </button>
              <button
                className="quiet"
                disabled={busy || !project}
                onClick={refreshRun}
              >
                刷新状态
              </button>
              <button
                className="quiet"
                disabled={busy || !project}
                onClick={restoreRun}
              >
                恢复流程
              </button>
              <button
                disabled={
                  busy ||
                  !run?.id ||
                  run.status === "blocked" ||
                  run.status === "cancelled" ||
                  run.status === "completed"
                }
                onClick={() => advanceRun(true)}
              >
                门禁推进
              </button>
              <button
                className="quiet"
                disabled={
                  busy ||
                  !run?.id ||
                  run.status === "blocked" ||
                  run.status === "cancelled" ||
                  run.status === "completed"
                }
                onClick={() => advanceRun(false)}
              >
                诚实阻断
              </button>
              <button
                className="quiet"
                disabled={
                  busy ||
                  !run?.id ||
                  !(run.steps || []).some((step) => step.status === "blocked")
                }
                onClick={retryRunStep}
              >
                重试阻塞步
              </button>
              <button
                className="quiet"
                disabled={busy || !run?.id || run.status !== "paused"}
                onClick={resumeRun}
              >
                恢复运行
              </button>
              <button
                className="quiet"
                disabled={
                  busy ||
                  !run?.id ||
                  run.status === "cancelled" ||
                  run.status === "completed"
                }
                onClick={cancelRun}
              >
                取消流程
              </button>
            </div>
            {researchRuns.length ? (
              <ul className="run-history" aria-label="研究流程历史">
                {researchRuns.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={
                        run?.id === item.id ? "quiet selected" : "quiet"
                      }
                      disabled={busy}
                      onClick={() => openResearchRun(item.id)}
                      title={`打开流程 ${item.id}`}
                    >
                      {item.id.slice(0, 10)} · {statusText(item.status)} ·{" "}
                      {researchStepLabel(item.current_step)}
                      {item.updated_at
                        ? ` · ${new Date(item.updated_at).toLocaleString("zh-CN", { hour12: false })}`
                        : ""}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {run ? (
              <div className="run-snapshot">
                <p>
                  流程 {run.id.slice(0, 10)} · {statusText(run.status)} · 当前{" "}
                  {researchStepLabel(run.current_step)}
                </p>
                <ol className="run-dag">
                  {(run.steps || []).map((step) => (
                    <li key={step.name}>
                      <b>
                        {researchStepLabel(step.name)}
                        {run.current_step === step.name ? " · 当前" : ""}
                      </b>
                      <span>
                        {statusText(step.status)}
                        {typeof step.attempts === "number"
                          ? ` · 尝试 ${step.attempts}`
                          : ""}
                      </span>
                      {step.failure_reason ? (
                        <small className="review-failure">
                          {step.failure_reason}
                        </small>
                      ) : null}
                      {Array.isArray(step.artifacts) && step.artifacts.length ? (
                        <small>
                          产物{" "}
                          {step.artifacts
                            .map((item) =>
                              String(
                                (item as { id?: string }).id ||
                                  JSON.stringify(item),
                              ).slice(0, 12),
                            )
                            .join(" · ")}
                        </small>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <div className="input-required">
                尚未启动研究流程。创建合同后可启动 Golden Path，并用已验证产物推进门禁。
              </div>
            )}
          </section>
          {analysisMode === "confirmatory" && !frozenHypotheses.length ? (
            <div className="input-required">
              验证性实验已阻断：请先在“研究项目”中登记并冻结一条可证伪假设。
            </div>
          ) : analysisMode === "exploratory" ? (
            <div className="graph-gate">
              <b>探索性运行</b>
              <span>结果会保留完整血缘，但不能直接成为验证性 Result-to-Claim 支持。</span>
            </div>
          ) : null}
          {experiments.length ? (
            <ol className="results">
              {experiments.map((item) => (
                <li key={item.id}>
                  <b>
                    {item.specification.metric} · {item.specification.analysis_mode === "exploratory" ? "探索性" : "验证性"} · {statusText(item.status)}
                  </b>
                  <span>
                    差值 {String(item.result.difference ?? "—")} · 95% 置信区间（CI）{" "}
                    {Array.isArray(item.result.ci95)
                      ? item.result.ci95.join(" 至 ")
                      : "—"}{" "}
                    · 统计门禁 {item.statistics.passed ? "通过" : "未通过"}
                  </span>
                  {item.statistics.issues?.map((issue) => (
                    <small key={issue}>{issue}</small>
                  ))}
                  {item.failure_reason && <small>{item.failure_reason}</small>}
                  <span>
                    结果 SHA256 {item.result_sha256 || "无"} · 运行清单（Manifest）{" "}
                    {item.manifest_sha256 || "无"}
                  </span>
                  {item.specification.hypothesis_manifests?.map((manifest) => (
                    <small key={manifest.sha256}>
                      冻结假设 H-{manifest.hypothesis_id.slice(0, 8)} v{manifest.version} · {manifest.path} · SHA256 {manifest.sha256}
                    </small>
                  ))}
                  {item.dependency_status === "stale" && (
                    <small className="review-failure">
                      上游假设已变化；本运行保留为历史，但不可继续支持当前主张。
                      {item.stale_reason ? ` ${item.stale_reason}` : ""}
                    </small>
                  )}
                  {item.integrity && !item.integrity.passed ? (
                    <small className="review-failure">
                      完整性检查失败：{item.integrity.issues.join("；")}
                    </small>
                  ) : null}
                  <button
                    className="quiet"
                    disabled={
                      busy ||
                      item.status !== "completed" ||
                      item.dependency_status === "stale"
                    }
                    onClick={() => replayRun(item.id)}
                  >
                    重放并核对哈希
                  </button>
                  {item.replay_of && (
                    <em>{item.reproduced ? "重放一致" : "重放不一致"}</em>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <Empty
              text={
                project
                  ? "尚无实验运行。输入两组数据后开始真实计算。"
                  : "请先创建研究合同。"
              }
            />
          )}
        </Panel>
      );
    if (page === "科学写作")
      return (
        <Panel
          title="科学写作"
          detail="稿件只消费人工批准的引用、论证图和通过统计门禁的实验数字。论证图主编辑已迁移到研究地图；本页聚焦批准实体生成与硬门禁稿件。"
        >
          <div className="actions">
            <button type="button" className="quiet" onClick={() => goToPage("研究地图")}>
              打开研究地图编辑论证图
            </button>
          </div>
          <div className="form-grid">
            <Field
              label="文献张力"
              value={narrative.tension}
              set={(value) =>
                setNarrative((current) => ({ ...current, tension: value }))
              }
              area
              placeholder="既有研究在哪些发现或解释上冲突？"
            />
            <Field
              label="候选机制"
              value={narrative.mechanism}
              set={(value) =>
                setNarrative((current) => ({ ...current, mechanism: value }))
              }
              area
              placeholder="提出可检验的机制"
            />
            <label className="wide">
              当前冻结假设（由注册表同步）
              <textarea
                readOnly
                value={
                  frozenHypotheses.length
                    ? frozenHypotheses
                        .map(
                          (item) =>
                            `H-${item.hypothesis_id.slice(0, 8)} v${item.version}: ${item.statement}`,
                        )
                        .join("\n")
                    : "尚无冻结假设；论证图保存与稿件生成将被阻断。"
                }
              />
            </label>
            <Field
              label="主张 ID"
              value={narrative.claims[0]}
              set={(value) =>
                setNarrative((current) => ({ ...current, claims: [value] }))
              }
              placeholder="C1"
            />
            <Field
              label="替代解释"
              value={narrative.competing_explanations[0]}
              set={(value) =>
                setNarrative((current) => ({
                  ...current,
                  competing_explanations: [value],
                }))
              }
              placeholder="至少一个竞争解释"
            />
            <Field
              label="边界条件"
              value={narrative.boundaries[0]}
              set={(value) =>
                setNarrative((current) => ({ ...current, boundaries: [value] }))
              }
              placeholder="适用范围"
            />
            <Field
              label="局限"
              value={narrative.limitations[0]}
              set={(value) =>
                setNarrative((current) => ({
                  ...current,
                  limitations: [value],
                }))
              }
              placeholder="已知局限"
            />
          </div>
          <div className="actions">
            <button
              disabled={busy || !project || !frozenHypotheses.length}
              onClick={saveArgumentMap}
            >
              保存论证图
            </button>
            <button
              disabled={busy || !project || narrative.approved}
              onClick={approveArgumentMap}
            >
              人工批准论证图
            </button>
            <button
              disabled={
                busy ||
                !project ||
                !narrative.approved ||
                !frozenHypotheses.length
              }
              onClick={createDraft}
            >
              从批准实体生成结构化初稿
            </button>
            {draft && (
              <button disabled={busy} onClick={persistDraft}>
                保存并执行硬门禁
              </button>
            )}
            {project && draft && (
              <>
                <button
                  className="quiet"
                  onClick={() =>
                    runSafe(() =>
                      download(
                        `/api/workflows/${project.id}/export-docx`,
                        "research-output.docx",
                        {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: "{}",
                        },
                      ),
                    )
                  }
                >
                  导出 DOCX
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    runSafe(() =>
                      download(
                        `/api/research-projects/${project.id}/draft/latex`,
                        "research-draft.tex",
                      ),
                    )
                  }
                >
                  导出 LaTeX
                </button>
              </>
            )}
          </div>
          {draft ? (
            <>
              <p className="file-path">paper/main.md · SHA256 {draftHash}</p>
              <textarea
                aria-label="科学稿件编辑器"
                className="code-editor"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
            </>
          ) : (
            <Empty
              text={
                project
                  ? "请先批准证据卡并完成人工论证图。"
                  : "请先建立研究合同。"
              }
            />
          )}
        </Panel>
      );
  };
  return (
    <main className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">V</span>
          <div>
            <b>Vibe Research</b>
            <small>研究证据工作台</small>
          </div>
        </div>
        <nav aria-label="主导航">
          {navGroups.map((group) => (
            <div className="nav-group" key={group.label}>
              <span className="nav-label">{group.label}</span>
              {group.items.map((item) => (
                <button
                  key={item}
                  className={page === item ? "active" : ""}
                  aria-current={page===item ? "page" : undefined}
                  onClick={() => goToPage(item)}
                >
                  <span className="nav-icon" aria-hidden="true">
                    {pageIcons[item] || "•"}
                  </span>
                  {item}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className={connected ? "dot online" : "dot"} />
          {connected ? "桌面后端已连接" : "连接检查中"}
        </div>
      </aside>
      <section className="content" id="main-content" tabIndex={-1}>
        <header className="topbar">
          <div>
            <nav className="breadcrumb" aria-label="面包屑"><button className="breadcrumb-home" onClick={() => goToFeatureRoute("dashboard")}>研究驾驶舱</button><span aria-hidden="true">/</span><span>{page}</span></nav>
            <h2>{page}</h2>
          </div>
          <div className="project-switcher">
            <label>
              <span>当前项目</span>
              <select
                aria-label="当前研究项目"
                value={project?.id || ""}
                onChange={(event) => selectProject(event.target.value)}
              >
                <option value="" disabled>
                  选择研究项目
                </option>
                {projects.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
            <span className="status" role="status">
              {project ? statusText(project.status) : "需要建立项目"}
            </span>
          </div>
        </header>
        <nav className="route-navigation" aria-label={"功能导航"}>
          <span className="route-navigation-label">{"研究路径"}</span>
          {researchJourneyRoutes.map((route) => (
            <button
              key={route}
              className={featureRouteForPage(page) === route ? "active" : ""}
              aria-current={featureRouteForPage(page) === route ? "page" : undefined}
              onClick={() => goToFeatureRoute(route)}
            >
              {ROUTE_LABELS[route]}
            </button>
          ))}
        </nav>
        {busy && (
          <div className="sr-only" role="status" aria-live="polite">
            正在处理请求
          </div>
        )}
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
        {pageContent()}
        {project && ["文献与证据", "科学写作", "审批与审计"].includes(page) && (
          <ClaimEvidenceGraph
            graph={claimGraph}
            busy={busy}
            onCreate={createClaimLink}
            onReview={reviewClaimLink}
            onCreateExperiment={createExperimentLink}
            onReviewExperiment={reviewExperimentLink}
            onGoToWriting={() => goToPage("科学写作")}
          />
        )}
      </section>
    </main>
  );
}
function LegacyClaimEvidenceGraph({
  graph,
  busy,
  onCreate,
  onReview,
}: {
  graph?: ClaimEvidenceGraph;
  busy: boolean;
  onCreate: (value: {
    claim_id: string;
    evidence_card_id: string;
    relation: "supports" | "contradicts" | "context";
    passage: string;
    locator: string;
  }) => Promise<void>;
  onReview: (
    linkId: string,
    decision: "approved" | "rejected",
  ) => Promise<void>;
}) {
  const [claimId, setClaimId] = useState(""),
    [evidenceCardId, setEvidenceCardId] = useState(""),
    [relation, setRelation] = useState<"supports" | "contradicts" | "context">(
      "supports",
    ),
    [passage, setPassage] = useState(""),
    [locator, setLocator] = useState("");
  useEffect(() => {
    if (!graph) return;
    setClaimId((current) =>
      graph.claims.some((item) => item.id === current)
        ? current
        : graph.claims[0]?.id || "",
    );
    const approved = graph.evidence_cards.filter(
      (item) => item.citation_status === "approved",
    );
    setEvidenceCardId((current) =>
      approved.some((item) => item.id === current)
        ? current
        : approved[0]?.id || "",
    );
  }, [graph]);
  if (!graph)
    return (
      <section
        className="claim-evidence-panel"
        aria-label="Claim-Evidence graph"
      >
        <header>
          <p className="eyebrow">Research quality gate</p>
          <h2>Claim-Evidence graph</h2>
          <p>Loading the persisted evidence graph.</p>
        </header>
      </section>
    );
  const approvedCards = graph.evidence_cards.filter(
    (item) => item.citation_status === "approved",
  );
  const createReady = Boolean(claimId && evidenceCardId && passage.trim());
  return (
    <section className="claim-evidence-panel" aria-label="Claim-Evidence graph">
      <header>
        <p className="eyebrow">Research quality gate</p>
        <h2>Claim-Evidence graph</h2>
        <p>
          Only approved supporting links satisfy the writing gate. The graph is
          persisted as a hash-addressed research artifact.
        </p>
      </header>
      <div className={`graph-gate ${graph.gate.passed ? "passed" : "blocked"}`}>
        <b>
          {graph.gate.passed ? "Writing gate passed" : "Writing gate blocked"}
        </b>
        <span>
          {graph.gate.supported_claims}/{graph.gate.total_claims} claims
          supported
        </span>
        <code>
          {graph.artifact.path} · {graph.artifact.sha256.slice(0, 12)}
        </code>
      </div>
      {graph.claims.length === 0 ? (
        <Empty text="Save a narrative map with at least one unique claim ID before linking evidence." />
      ) : (
        <>
          <div className="claim-node-list">
            {graph.claims.map((item) => (
              <div className={`claim-node ${item.status}`} key={item.id}>
                <b>{item.id}</b>
                <span>
                  {item.status === "supported"
                    ? `${item.supporting_link_ids.length} approved support link(s)`
                    : "Needs approved support"}
                </span>
              </div>
            ))}
          </div>
          <div className="claim-link-form">
            <label>
              Claim
              <select
                value={claimId}
                onChange={(event) => setClaimId(event.target.value)}
              >
                {graph.claims.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Evidence card
              <select
                value={evidenceCardId}
                onChange={(event) => setEvidenceCardId(event.target.value)}
              >
                <option value="">Select a citation-approved card</option>
                {approvedCards.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Relation
              <select
                value={relation}
                onChange={(event) =>
                  setRelation(event.target.value as typeof relation)
                }
              >
                <option value="supports">Supports</option>
                <option value="contradicts">Contradicts</option>
                <option value="context">Context</option>
              </select>
            </label>
            <label className="wide">
              Quoted passage or researcher rationale
              <textarea
                value={passage}
                onChange={(event) => setPassage(event.target.value)}
                placeholder="Record the specific passage that justifies this relation."
              />
            </label>
            <Field
              label="Page, section, or locator"
              value={locator}
              set={setLocator}
              placeholder="e.g. p. 4, Table 2"
            />
            <div className="claim-link-command">
              <button
                disabled={busy || !createReady}
                onClick={() =>
                  onCreate({
                    claim_id: claimId,
                    evidence_card_id: evidenceCardId,
                    relation,
                    passage: passage.trim(),
                    locator: locator.trim(),
                  })
                }
              >
                Add reviewable link
              </button>
              <small>
                {approvedCards.length
                  ? "A human review is still required."
                  : "Approve citation existence before creating a link."}
              </small>
            </div>
          </div>
          <ol className="claim-link-list">
            {graph.links.length ? (
              graph.links.map((link) => {
                const card = graph.evidence_cards.find(
                  (item) => item.id === link.evidence_card_id,
                );
                return (
                  <li key={link.id}>
                    <div>
                      <b>{link.claim_id}</b>
                      <span>
                        {link.relation} · {link.status}
                      </span>
                    </div>
                    <p>{link.passage}</p>
                    <small>
                      {card ? (
                        <a
                          href={card.canonical_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {card.title}
                        </a>
                      ) : (
                        "Evidence card unavailable"
                      )}
                      {link.locator ? ` · ${link.locator}` : ""}
                      {link.review_reason ? ` · ${link.review_reason}` : ""}
                    </small>
                    <div className="inline-actions">
                      <button
                        disabled={busy || link.status === "approved"}
                        onClick={() => onReview(link.id, "approved")}
                      >
                        Approve link
                      </button>
                      <button
                        className="danger"
                        disabled={busy || link.status === "rejected"}
                        onClick={() => onReview(link.id, "rejected")}
                      >
                        Reject link
                      </button>
                    </div>
                  </li>
                );
              })
            ) : (
              <li className="empty">
                <b>No Claim-Evidence links</b>
                <p>
                  Link a citation-approved evidence card to each narrative
                  claim.
                </p>
              </li>
            )}
          </ol>

        </>
      )}
    </section>
  );
}
function ClaimEvidenceGraph({
  graph,
  busy,
  onCreate,
  onReview,
  onCreateExperiment,
  onReviewExperiment,
  onGoToWriting,
}: {
  graph?: ClaimEvidenceGraph;
  busy: boolean;
  onCreate: (value: {
    claim_id: string;
    evidence_card_id: string;
    relation: "supports" | "contradicts" | "context";
    passage: string;
    locator: string;
  }) => Promise<void>;
  onReview: (
    linkId: string,
    decision: "approved" | "rejected",
  ) => Promise<void>;
  onCreateExperiment: (value: {
    claim_id: string;
    experiment_run_id: string;
    relation: "supports" | "contradicts" | "context";
    result_locator: string;
    interpretation: string;
    evidence_card_ids: string[];
  }) => Promise<void>;
  onReviewExperiment: (
    linkId: string,
    decision: "approved" | "rejected",
  ) => Promise<void>;
  onGoToWriting?: () => void;
}) {
  const [claimId, setClaimId] = useState(""),
    [evidenceCardId, setEvidenceCardId] = useState(""),
    [linkSource, setLinkSource] = useState<"literature" | "experiment">(
      "literature",
    ),
    [relation, setRelation] = useState<"supports" | "contradicts" | "context">(
      "supports",
    ),
    [passage, setPassage] = useState(""),
    [locator, setLocator] = useState(""),
    [experimentRunId, setExperimentRunId] = useState(""),
    [resultLocator, setResultLocator] = useState("difference"),
    [interpretation, setInterpretation] = useState(""),
    [experimentBasisIds, setExperimentBasisIds] = useState<string[]>([]);
  useEffect(() => {
    if (!graph) return;
    setClaimId((current) =>
      graph.claims.some((item) => item.id === current)
        ? current
        : graph.claims[0]?.id || "",
    );
    const approved = graph.evidence_cards.filter(
      (item) => item.citation_status === "approved",
    );
    setEvidenceCardId((current) =>
      approved.some((item) => item.id === current)
        ? current
        : approved[0]?.id || "",
    );
    const eligibleRuns = (graph.experiments || []).filter(
      (item) =>
        item.status === "completed" &&
        item.analysis_mode === "confirmatory" &&
        item.dependency_status !== "stale" &&
        item.statistics?.passed &&
        item.integrity?.passed !== false &&
        item.result_sha256 &&
        item.manifest_sha256,
    );
    setExperimentRunId((current) =>
      eligibleRuns.some((item) => item.id === current)
        ? current
        : eligibleRuns[0]?.id || "",
    );
    const approvedBasis = graph.evidence_cards.filter(
      (item) =>
        item.citation_status === "approved" &&
        item.claim_support_status === "approved",
    );
    setExperimentBasisIds((current) => {
      const retained = current.filter((id) =>
        approvedBasis.some((item) => item.id === id),
      );
      return retained.length ? retained : approvedBasis[0] ? [approvedBasis[0].id] : [];
    });
  }, [graph]);
  if (!graph)
    return (
      <section className="claim-evidence-panel" aria-label="主张-证据图">
        <header>
          <p className="eyebrow">研究质量门禁</p>
          <h2>主张-证据图</h2>
          <p>正在读取已持久化的证据图。</p>
        </header>
      </section>
    );
  const approvedCards = graph.evidence_cards.filter(
    (item) => item.citation_status === "approved",
  );
  const approvedExperimentBasis = graph.evidence_cards.filter(
    (item) =>
      item.citation_status === "approved" &&
      item.claim_support_status === "approved",
  );
  const completedExperimentRuns = (graph.experiments || []).filter(
    (item) =>
      item.status === "completed" &&
      item.analysis_mode === "confirmatory" &&
      item.dependency_status !== "stale" &&
      item.statistics?.passed &&
      item.integrity?.passed !== false &&
      item.result_sha256 &&
      item.manifest_sha256,
  );
  const relationLabels = {
    supports: "支持",
    contradicts: "反驳",
    context: "背景",
  } as const;
  const statusLabels = {
    supported: "已获支持",
    needs_evidence: "需要已批准支持",
    approved: "已批准",
    rejected: "已驳回",
  } as Record<string, string>;
  const createReady = Boolean(claimId && evidenceCardId && passage.trim());
  const experimentCreateReady = Boolean(
    claimId &&
      experimentRunId &&
      resultLocator.trim() &&
      interpretation.trim() &&
      experimentBasisIds.length,
  );
  return (
    <section className="claim-evidence-panel" aria-label="主张-证据图">
      <header>
        <p className="eyebrow">研究质量门禁</p>
        <h2>主张-证据图</h2>
        <p>
          只有经人工批准的支持链接才能通过写作门禁；图谱会持久化为可按哈希核验的研究产物。
        </p>
      </header>
      <div className={`graph-gate ${graph.gate.passed ? "passed" : "blocked"}`}>
        <b>{graph.gate.passed ? "写作门禁已通过" : "写作门禁未通过"}</b>
        <span>
          {graph.gate.supported_claims}/{graph.gate.total_claims} 条主张已获支持
        </span>
        <code>
          {graph.artifact.path} · {graph.artifact.sha256.slice(0, 12)}
        </code>
      </div>
      {graph.claims.length === 0 ? (
        <div className="claims-onboarding">
          <p className="claims-onboarding-title">还没有定义研究主张</p>
          <ol className="claims-onboarding-steps">
            <li>
              <span className="step-num">1</span>
              <div>
                <strong>前往「科学写作」</strong>
                <span>填写研究主张 ID（如 C1、C2），保存论证图</span>
              </div>
            </li>
            <li>
              <span className="step-num">2</span>
              <div>
                <strong>回到此处</strong>
                <span>将已批准的证据卡与各主张关联起来</span>
              </div>
            </li>
            <li>
              <span className="step-num">3</span>
              <div>
                <strong>全部主张获得支持后，写作门禁自动通过</strong>
                <span>可生成最终稿件</span>
              </div>
            </li>
          </ol>
          {onGoToWriting && (
            <button className="quiet" onClick={onGoToWriting}>
              前往科学写作 →
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="claim-node-list">
            {graph.claims.map((item) => (
              <div className={`claim-node ${item.status}`} key={item.id}>
                <b>{item.id}</b>
                <span>
                  {item.status === "supported"
                    ? `${item.supporting_link_ids.length} 条文献 + ${(item.supporting_experiment_link_ids || []).length} 条实验支持`
                    : "需要已批准支持"}
                </span>
              </div>
            ))}
          </div>
          <div className="evidence-source-tabs" role="tablist" aria-label="主张支持来源">
            <button
              className={linkSource === "literature" ? "active quiet" : "quiet"}
              role="tab"
              aria-selected={linkSource === "literature"}
              onClick={() => setLinkSource("literature")}
            >
              文献段落
            </button>
            <button
              className={linkSource === "experiment" ? "active quiet" : "quiet"}
              role="tab"
              aria-selected={linkSource === "experiment"}
              onClick={() => setLinkSource("experiment")}
            >
              实验结果
            </button>
          </div>
          {linkSource === "literature" ? (
            <div className="claim-link-form">
              <label>
                主张 ID
                <select value={claimId} onChange={(event) => setClaimId(event.target.value)}>
                  {graph.claims.map((item) => (
                    <option key={item.id} value={item.id}>{item.id}</option>
                  ))}
                </select>
              </label>
              <label>
                证据卡
                <select value={evidenceCardId} onChange={(event) => setEvidenceCardId(event.target.value)}>
                  <option value="">选择已核验引用的证据卡</option>
                  {approvedCards.map((item) => (
                    <option key={item.id} value={item.id}>{item.title}</option>
                  ))}
                </select>
              </label>
              <label>
                关系
                <select value={relation} onChange={(event) => setRelation(event.target.value as typeof relation)}>
                  <option value="supports">支持</option>
                  <option value="contradicts">反驳</option>
                  <option value="context">背景</option>
                </select>
              </label>
              <label className="wide">
                引文原句或研究者依据
                <textarea value={passage} onChange={(event) => setPassage(event.target.value)} placeholder="记录支撑该关系的具体原句或核验依据。" />
              </label>
              <Field label="页码、章节或定位符" value={locator} set={setLocator} placeholder="例如：第 4 页，表 2" />
              <div className="claim-link-command">
                <button
                  disabled={busy || !createReady}
                  onClick={() => onCreate({claim_id: claimId,evidence_card_id: evidenceCardId,relation,passage: passage.trim(),locator: locator.trim()})}
                >
                  添加待审文献链接
                </button>
                <small>{approvedCards.length ? "仍需由研究者人工审查。" : "请先核验引文存在性，再创建链接。"}</small>
              </div>
            </div>
          ) : (
            <div className="claim-link-form experiment-link-form">
              <label>
                主张 ID
                <select value={claimId} onChange={(event) => setClaimId(event.target.value)}>
                  {graph.claims.map((item) => (
                    <option key={item.id} value={item.id}>{item.id}</option>
                  ))}
                </select>
              </label>
              <label>
                已完成验证性实验
                <select value={experimentRunId} onChange={(event) => setExperimentRunId(event.target.value)}>
                  <option value="">选择统计门禁已通过的运行</option>
                  {completedExperimentRuns.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.id.slice(0, 12)} · 差值 {String(item.result.difference ?? "—")}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                关系
                <select value={relation} onChange={(event) => setRelation(event.target.value as typeof relation)}>
                  <option value="supports">支持</option>
                  <option value="contradicts">反驳</option>
                  <option value="context">背景</option>
                </select>
              </label>
              <Field label="结果定位符" value={resultLocator} set={setResultLocator} placeholder="例如：difference 或 ci95.0" />
              <label className="wide">
                结果解释
                <textarea value={interpretation} onChange={(event) => setInterpretation(event.target.value)} placeholder="说明该结果在冻结假设、指标方向和边界条件下为何支持或反驳主张。" />
              </label>
              <label className="wide">
                实验证据基础（可多选）
                <select
                  multiple
                  size={Math.min(Math.max(approvedExperimentBasis.length, 2), 6)}
                  value={experimentBasisIds}
                  onChange={(event) =>
                    setExperimentBasisIds(
                      Array.from(event.currentTarget.selectedOptions).map((option) => option.value),
                    )
                  }
                >
                  {approvedExperimentBasis.map((item) => (
                    <option key={item.id} value={item.id}>{item.title}</option>
                  ))}
                </select>
              </label>
              <div className="claim-link-command">
                <button
                  disabled={busy || !experimentCreateReady}
                  onClick={() => onCreateExperiment({claim_id: claimId,experiment_run_id: experimentRunId,relation,result_locator: resultLocator.trim(),interpretation: interpretation.trim(),evidence_card_ids: experimentBasisIds})}
                >
                  添加待审实验链接
                </button>
                <small>
                  {completedExperimentRuns.length && approvedExperimentBasis.length
                    ? "仍需复核结果定位、哈希血缘和解释。"
                    : "需要冻结假设下的已完成实验，以及已批准的证据基础。"}
                </small>
              </div>
            </div>
          )}
          <ol className="claim-link-list">
            {graph.links.length ? (
              graph.links.map((link) => {
                const card = graph.evidence_cards.find(
                  (item) => item.id === link.evidence_card_id,
                );
                return (
                  <li key={link.id}>
                    <div>
                      <b>{link.claim_id}</b>
                      <span>
                        {relationLabels[
                          link.relation as keyof typeof relationLabels
                        ] || link.relation}{" "}
                        · {statusLabels[link.status] || link.status}
                      </span>
                    </div>
                    <p>{link.passage}</p>
                    <small>
                      {card ? (
                        <a
                          href={card.canonical_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {card.title}
                        </a>
                      ) : (
                        "证据卡不可用"
                      )}
                      {link.locator ? ` · ${link.locator}` : ""}
                      {link.review_reason ? ` · ${link.review_reason}` : ""}
                    </small>
                    <div className="inline-actions">
                      <button
                        disabled={busy || link.status === "approved"}
                        onClick={() => onReview(link.id, "approved")}
                      >
                        批准链接
                      </button>
                      <button
                        className="danger"
                        disabled={busy || link.status === "rejected"}
                        onClick={() => onReview(link.id, "rejected")}
                      >
                        驳回链接
                      </button>
                    </div>
                  </li>
                );
              })
            ) : (
              <li className="empty">
                <b>尚无主张-证据链接</b>
                <p>为每一条叙事主张关联已核验引用的证据卡。</p>
              </li>
            )}
          </ol>
          <section className="experiment-support-ledger" aria-label="主张-实验结果链接">
            <div className="section-command">
              <div>
                <p className="eyebrow">Result-to-Claim</p>
                <h3>实验结果支持账本</h3>
              </div>
              <span>{(graph.experiment_links || []).length} 条链接</span>
            </div>
            {(graph.experiment_links || []).length ? (
              <ol className="claim-link-list experiment-link-list">
                {graph.experiment_links.map((link) => {
                  const run = (graph.experiments || []).find(
                    (item) => item.id === link.experiment_run_id,
                  );
                  const reviewable = Object.entries(link.eligibility || {})
                    .filter(([key]) => key !== "review_approved")
                    .every(([, value]) => value);
                  return (
                    <li key={link.id} className={link.eligible ? "eligible" : "blocked"}>
                      <div>
                        <b>{link.claim_id}</b>
                        <span>{relationLabels[link.relation]} · {statusLabels[link.status] || link.status}</span>
                      </div>
                      <strong className={link.eligible ? "support-pass" : "support-review"}>
                        {link.eligible ? "可用于门禁" : reviewable ? "等待人工批准" : "血缘未满足"}
                      </strong>
                      <p>{link.interpretation}</p>
                      <small>
                        运行 {link.experiment_run_id.slice(0, 12)} · {link.result_locator} = {String(link.result_value ?? "—")} · 结果 {link.result_sha256.slice(0, 12)} · Manifest {link.manifest_sha256.slice(0, 12)}
                      </small>
                      {run?.statistics?.issues?.length ? <small>{run.statistics.issues.join("；")}</small> : null}
                      <div className="eligibility-grid">
                        {Object.entries(link.eligibility || {}).map(([key, value]) => (
                          <span className={value ? "pass" : "fail"} key={key}>{value ? "✓" : "×"} {key}</span>
                        ))}
                      </div>
                      <div className="inline-actions">
                        <button disabled={busy || link.status === "approved" || !reviewable} onClick={() => onReviewExperiment(link.id, "approved")}>
                          批准实验链接
                        </button>
                        <button className="danger" disabled={busy || link.status === "rejected"} onClick={() => onReviewExperiment(link.id, "rejected")}>
                          驳回实验链接
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <Empty text="尚无主张-实验链接。验证性实验必须绑定冻结假设、通过统计门禁并保留证据基础。" />
            )}
          </section>
        </>
      )}
    </section>
  );
}
function JsonCard({ value }: { value: Record<string, unknown> }) {
  return <pre className="json-card">{JSON.stringify(value, null, 2)}</pre>;
}

type SettingsMetadata = Record<string, { value?: string; configured?: boolean }>;

createRoot(document.getElementById("root")!).render(<App />);
