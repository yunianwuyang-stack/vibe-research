import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
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
import { Field, Panel, Empty, Card } from "./ui";
import {
  pageFromFeatureRoute,
  featureRouteForPage as featureRouteForShellPage,
  type ShellPage,
} from "./route-boundary";

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
const fmtTime = (iso: string | undefined | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
};

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
      .then((t) => setConnected(Boolean(t)))
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
        <nav className="route-navigation" aria-label="功能导航">
          {(["dashboard", ...FEATURE_ROUTES] as const).map((route) => (
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
          />
        )}
      </section>
    </main>
  );
}
function WorkbenchPage({
  connected,
  workflowCount,
  projectStatus,
  project,
  workflows,
  onProject,
  onWorkflow,
  onEvidence,
  onRunCenter,
  onAudit,
}: {
  connected: boolean;
  workflowCount: number;
  projectStatus: string;
  project?: Project;
  workflows: Workflow[];
  onProject: () => void;
  onWorkflow: () => void;
  onEvidence: () => void;
  onRunCenter: () => void;
  onAudit: () => void;
}) {
  const evidenceCards = project?.evidence_cards || [];
  const verifiedEvidence = evidenceCards.filter(
    (item) =>
      item.citation_status === "approved" &&
      item.claim_support_status === "approved",
  );
  const coveragePercent = evidenceCards.length
    ? Math.round((verifiedEvidence.length / evidenceCards.length) * 100)
    : 0;
  const evidenceTrend = evidenceCards.slice(-7).map((item) =>
    evidenceReview(item).percent,
  );
  return (
    <>
      <section className="hero hero-workspace">
        <div className="hero-copy">
          <p className="eyebrow">证据原生科研工作台</p>
          <h1>让每条结论，都回到它的证据。</h1>
          <p>
            从研究合同、文献检索到可恢复执行，Vibe Research 把每一步都留在同一条可审计的研究链路里。
          </p>
          <div className="actions">
            <button onClick={onProject}>建立研究合同</button>
            <button className="quiet" onClick={onWorkflow}>
              启动智能工作流 <span aria-hidden="true">→</span>
            </button>
          </div>
          <div className="hero-trust">
            <span className="live-dot" aria-hidden="true" />
            <span>{connected ? "桌面后端已连接" : "正在检查本地连接"}</span>
            <span className="trust-divider" aria-hidden="true" />
            <span>证据留在本机</span>
          </div>
        </div>
        <div className="hero-visual" aria-label="Vibe Research 工作台预览">
          <div className="visual-toolbar">
            <span className="visual-window-dots" aria-hidden="true"><i /><i /><i /></span>
            <span>研究工作台 / 项目概览</span>
            <span className="visual-secure">本地</span>
          </div>
          <img src="/vibe-research-workspace.png" alt="Vibe Research 研究工作台界面预览" />
          <div className="visual-caption">
            <span>{project?.title || "新研究项目"}</span>
            <b>{project ? statusText(project.status) : "等待研究合同"}</b>
          </div>
        </div>
      </section>
      <section className="workspace-stats" aria-label="工作台状态">
        <div>
          <span>本地会话</span>
          <b>{connected ? "在线" : "检查中"}</b>
          <small>桌面后端</small>
        </div>
        <div>
          <span>研究合同</span>
          <b>{projectStatus}</b>
          <small>当前项目状态</small>
        </div>
        <div>
          <span>可恢复工作流</span>
          <b>{workflowCount}</b>
          <small>个本地任务</small>
        </div>
      </section>
      <section className="quick-start">
        <header className="section-command">
          <div>
            <p className="eyebrow">从这里开始</p>
            <h3>研究链路</h3>
          </div>
          <button className="quiet compact-action" onClick={onAudit}>查看质量门禁 <span aria-hidden="true">→</span></button>
        </header>
        <div className="cards">
          <Card
            title="文献与证据"
            text="连接 OpenAlex、Crossref、arXiv 等真实服务商，保留来源、定位与待核验状态。"
            action={onEvidence}
            meta="01 / Evidence"
          />
          <Card
            title="可恢复执行"
            text="从选题到实验、论文和建模，任务状态、日志与产物都可暂停、恢复与导出。"
            action={onRunCenter}
            meta="02 / Workflow"
          />
          <Card
            title="研究质量门禁"
            text="合同、审批、产物血缘与独立验证共同决定一项研究是否真正完成。"
            action={onAudit}
            meta="03 / Assurance"
          />
        </div>
      </section>
      <section className="workspace-insights" aria-label="研究概览">
        <div className="coverage-panel">
          <div className="insight-heading">
            <div>
              <p className="eyebrow">Evidence coverage</p>
              <h3>证据覆盖率</h3>
            </div>
            <strong>{coveragePercent}%</strong>
          </div>
          <div className="coverage-bar" aria-label={`证据覆盖率 ${coveragePercent}%`}><i style={{ width: `${coveragePercent}%` }} /></div>
          <div className="coverage-legend"><span><i className="legend-dot verified" />已核验 {verifiedEvidence.length}</span><span><i className="legend-dot review" />待审阅 {evidenceCards.length - verifiedEvidence.length}</span><span><i className="legend-dot missing" />总计 {evidenceCards.length}</span></div>
          {evidenceTrend.length ? (
            <div className="mini-bars" aria-label="最近证据卡核验进度">
              {evidenceTrend.map((value, index) => (
                <span key={`${value}-${index}`} style={{ height: `${Math.max(value, 8)}%` }} title={`${value}%`} />
              ))}
            </div>
          ) : (
            <div className="coverage-empty">保存证据卡后显示核验趋势</div>
          )}
        </div>
        <div className="activity-panel">
          <div className="insight-heading">
            <div>
              <p className="eyebrow">Recent activity</p>
              <h3>最近活动</h3>
            </div>
            <span className="activity-date">今天</span>
          </div>
          {workflows.length ? (
            <ul className="activity-list">
              {workflows.slice(0, 3).map((workflow) => (
                <li key={workflow.id}>
                  <span className={`activity-icon ${workflow.status === "completed" ? "teal" : workflow.status === "running" ? "blue" : "amber"}`}>
                    {workflow.status === "completed" ? "✓" : workflow.status === "running" ? "▶" : "·"}
                  </span>
                  <div>
                    <b>{workflow.title}</b>
                    <small>{workflow.current_step || workflowNames[workflow.template] || "等待启动"}</small>
                  </div>
                  <em>{statusText(workflow.status)}</em>
                </li>
              ))}
            </ul>
          ) : (
            <div className="activity-empty">当前项目尚无工作流</div>
          )}
        </div>
      </section>
    </>
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
        <Empty text="保存至少包含一个唯一主张 ID 的论证图后，才能关联证据。" />
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
function LegacyRunCenterPage({
  project,
  workflows,
  selectedId,
  snapshot,
  feedback,
  busy,
  onSelected,
  onFeedback,
  onRefresh,
  onCreate,
  onAction,
  onResolve,
  onRemove,
  onDownload,
}: {
  project?: Project;
  workflows: Workflow[];
  selectedId: string;
  snapshot?: WorkflowRunCenter;
  feedback: string;
  busy: boolean;
  onSelected: (id: string) => void;
  onFeedback: (value: string) => void;
  onRefresh: () => void;
  onCreate: () => void;
  onAction: (
    id: string,
    action: "start" | "pause" | "resume" | "restart",
  ) => void;
  onResolve: (action: "approve" | "feedback" | "stop") => void;
  onRemove: (id: string) => void;
  onDownload: (workflow: Workflow) => void;
}) {
  if (!project)
    return (
      <Panel
        title="项目级运行中心"
        detail="研究项目是工作流、检查点、日志和产物的持久化边界。"
      >
        <Empty text="请先建立或选择研究合同。" />
      </Panel>
    );
  const selectedSnapshot =
    snapshot?.workflow.id === selectedId ? snapshot : undefined;
  const active = selectedSnapshot?.workflow;
  return (
    <Panel
      title="项目级运行中心"
      detail="每个工作流绑定当前 Research Contract；步骤、检查点、日志和产物都从同一持久化快照读取。"
    >
      <div className="toolbar">
        <button className="quiet" disabled={busy} onClick={onRefresh}>
          刷新运行快照
        </button>
        <button disabled={busy} onClick={onCreate}>
          新建工作流
        </button>
      </div>
      {workflows.length ? (
        <div className="run-center-layout">
          <section className="workflow-list" aria-label="项目工作流">
            {workflows.map((workflow) => (
              <article
                className={
                  selectedId === workflow.id ? "workflow selected" : "workflow"
                }
                key={workflow.id}
                onClick={() => onSelected(workflow.id)}
              >
                <div>
                  <h3>{workflow.title}</h3>
                  <p>
                    {workflowNames[workflow.template] || workflow.template} ·
                    当前：{workflow.current_step || "等待启动"}
                  </p>
                </div>
                <span className={`badge ${workflow.status}`}>
                  {statusText(workflow.status)}
                </span>
                <div className="inline-actions">
                  <button
                    disabled={
                      busy || !["pending", "paused"].includes(workflow.status)
                    }
                    onClick={(event) => {
                      event.stopPropagation();
                      onAction(
                        workflow.id,
                        workflow.status === "paused" ? "resume" : "start",
                      );
                    }}
                  >
                    {workflow.status === "paused" ? "恢复" : "启动"}
                  </button>
                  <button
                    className="quiet"
                    disabled={busy || workflow.status !== "running"}
                    onClick={(event) => {
                      event.stopPropagation();
                      onAction(workflow.id, "pause");
                    }}
                  >
                    暂停
                  </button>
                  <button
                    className="quiet"
                    disabled={busy || workflow.status === "running"}
                    onClick={(event) => {
                      event.stopPropagation();
                      onAction(workflow.id, "restart");
                    }}
                  >
                    重启
                  </button>
                  <button
                    className="quiet"
                    disabled={busy}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDownload(workflow);
                    }}
                  >
                    导出
                  </button>
                  <button
                    className="danger"
                    disabled={busy}
                    onClick={(event) => {
                      event.stopPropagation();
                      onRemove(workflow.id);
                    }}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </section>
          {active ? (
            <section className="run-snapshot" aria-label="运行快照">
              <div className="section-command">
                <div>
                  <p className="eyebrow">{active.id}</p>
                  <h3>{active.title}</h3>
                </div>
                <span className={`badge ${active.status}`}>
                  {statusText(active.status)}
                </span>
              </div>
              <section>
                <h4>执行 DAG</h4>
                <ol className="run-dag">
                  {(active.steps || []).map((step) => (
                    <li className={step.status} key={step.skill_name}>
                      <div>
                        <b>
                          {step.step_order + 1}. {step.display_name}
                        </b>
                        <span>{statusText(step.status)}</span>
                      </div>
                      {step.error_message && (
                        <small>{step.error_message}</small>
                      )}
                      {step.output_files.length ? (
                        <small>产出：{step.output_files.join("、")}</small>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </section>
              {selectedSnapshot.checkpoint && (
                <section className="checkpoint-card">
                  <div>
                    <p className="eyebrow">需要人工决策</p>
                    <h4>{selectedSnapshot.checkpoint.step_name}</h4>
                    <p>{selectedSnapshot.checkpoint.checkpoint_type}</p>
                  </div>
                  <textarea
                    aria-label="检查点反馈"
                    value={feedback}
                    onChange={(event) => onFeedback(event.target.value)}
                    placeholder="给出可审计的修改意见；反馈将与检查点响应一并持久化。"
                  />
                  <div className="inline-actions">
                    <button
                      disabled={busy}
                      onClick={() => onResolve("approve")}
                    >
                      批准继续
                    </button>
                    <button
                      className="quiet"
                      disabled={busy || !feedback.trim()}
                      onClick={() => onResolve("feedback")}
                    >
                      提交反馈
                    </button>
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() => onResolve("stop")}
                    >
                      停止工作流
                    </button>
                  </div>
                </section>
              )}
              <section>
                <h4>产物血缘快照</h4>
                {selectedSnapshot.artifacts.length ? (
                  <ol className="run-artifacts">
                    {selectedSnapshot.artifacts.map((item) => (
                      <li key={item.path}>
                        <b>{item.path}</b>
                        <span>
                          {item.size.toLocaleString()} bytes · SHA256{" "}
                          {item.sha256}
                        </span>
                        {item.producer_step && (
                          <small>生产步骤：{item.producer_step}</small>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="当前工作区还没有可交付产物。" />
                )}
              </section>
              <section>
                <h4>实时日志</h4>
                {selectedSnapshot.logs.length ? (
                  <ol className="run-logs">
                    {selectedSnapshot.logs.map((entry, index) => (
                      <li key={`${entry.created_at}-${index}`}>
                        <time dateTime={entry.created_at}>{fmtTime(entry.created_at)}</time>
                        <b>{entry.step_name || "workflow"}</b>
                        <span className={entry.level}>{entry.message}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="尚无持久化执行日志。" />
                )}
              </section>
            </section>
          ) : (
            <Empty text="选择一个工作流以查看其运行快照。" />
          )}
        </div>
      ) : (
        <Empty text="当前项目还没有工作流。请创建一个工作流后，所有执行状态和产物会自动绑定到此项目。" />
      )}
    </Panel>
  );
}
function RunCenterPage({
  project,
  workflows,
  selectedId,
  snapshot,
  inputs,
  feedback,
  busy,
  onSelected,
  onFeedback,
  onRefresh,
  onCreate,
  onAction,
  onResolve,
  onUpload,
  onRemove,
  onSync,
  onDownload,
}: {
  project?: Project;
  workflows: Workflow[];
  selectedId: string;
  snapshot?: WorkflowRunCenter;
  inputs: WorkflowInput[];
  feedback: string;
  busy: boolean;
  onSelected: (id: string) => void;
  onFeedback: (value: string) => void;
  onRefresh: () => void;
  onCreate: () => void;
  onAction: (
    id: string,
    action: "start" | "pause" | "resume" | "restart",
  ) => void;
  onResolve: (action: "approve" | "feedback" | "stop") => void;
  onUpload: (files: File[]) => void;
  onRemove: (id: string) => void;
  onSync: (id: string) => void;
  onDownload: (workflow: Workflow) => void;
}) {
  if (!project)
    return (
      <Panel
        title="项目级运行中心"
        detail="研究项目是工作流、检查点、日志和产物的持久化边界。"
      >
        <Empty text="请先建立或选择研究合同。" />
      </Panel>
    );
  const selectedSnapshot =
    snapshot?.workflow.id === selectedId ? snapshot : undefined;
  const active = selectedSnapshot?.workflow;
  const inputRequirement = active
    ? workflowInputRequirements[active.template]
    : undefined;
  return (
    <Panel
      title="项目级运行中心"
      detail="每个工作流均绑定当前研究合同；步骤、检查点、日志和产物均从同一持久化快照读取。"
    >
      <div className="toolbar">
        <button className="quiet" disabled={busy} onClick={onRefresh}>
          刷新运行快照
        </button>
        <button disabled={busy} onClick={onCreate}>
          新建工作流
        </button>
      </div>
      {workflows.length ? (
        <div className="run-center-layout">
          <section className="workflow-list" aria-label="项目工作流">
            {workflows.map((workflow) => (
              <article
                className={
                  selectedId === workflow.id ? "workflow selected" : "workflow"
                }
                key={workflow.id}
                onClick={() => onSelected(workflow.id)}
              >
                <div>
                  <h3>{workflow.title}</h3>
                  <p>
                    {workflowNames[workflow.template] || workflow.template} ·
                    当前：{workflow.current_step || "等待启动"}
                  </p>
                </div>
                <span className={`badge ${workflow.status}`}>
                  {statusText(workflow.status)}
                </span>
                <div className="inline-actions">
                  <button
                    disabled={
                      busy || !["pending", "paused"].includes(workflow.status)
                    }
                    onClick={(event) => {
                      event.stopPropagation();
                      onAction(
                        workflow.id,
                        workflow.status === "paused" ? "resume" : "start",
                      );
                    }}
                  >
                    {workflow.status === "paused" ? "恢复" : "启动"}
                  </button>
                  <button
                    className="quiet"
                    disabled={busy || workflow.status !== "running"}
                    onClick={(event) => {
                      event.stopPropagation();
                      onAction(workflow.id, "pause");
                    }}
                  >
                    暂停
                  </button>
                  <button
                    className="quiet"
                    disabled={busy || workflow.status === "running"}
                    onClick={(event) => {
                      event.stopPropagation();
                      onAction(workflow.id, "restart");
                    }}
                  >
                    重启
                  </button>
                  <button
                    className="quiet"
                    disabled={busy}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDownload(workflow);
                    }}
                  >
                    导出
                  </button>
                  <button
                    className="danger"
                    disabled={busy}
                    onClick={(event) => {
                      event.stopPropagation();
                      onRemove(workflow.id);
                    }}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </section>
          {active ? (
            <section className="run-snapshot" aria-label="运行快照">
              <div className="section-command">
                <div>
                  <p className="eyebrow">{active.id}</p>
                  <h3>{active.title}</h3>
                </div>
                <span className={`badge ${active.status}`}>
                  {statusText(active.status)}
                </span>
              </div>
              <section className="workflow-inputs">
                <div className="section-command">
                  <div>
                    <h4>输入资料</h4>
                    <p>原始文件保存在当前工作流的 user_data 目录，并记录大小、解析状态与 SHA256。</p>
                  </div>
                  <label className="button-like">
                    上传资料
                    <input
                      type="file"
                      multiple
                      disabled={busy}
                      onChange={(event) => {
                        onUpload(Array.from(event.currentTarget.files || []));
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                </div>
                {inputRequirement && !inputs.length && (
                  <div className="alert input-required" role="status">
                    {inputRequirement}上传后才能启动此工作流。
                  </div>
                )}
                {inputs.length ? (
                  <ol className="run-artifacts workflow-input-list">
                    {inputs.map((item) => (
                      <li key={item.path}>
                        <b>{item.path}</b>
                        <span>
                          {item.size.toLocaleString()} bytes · {inputStatusText(item.status)}
                        </span>
                        <small>SHA256 {item.sha256}</small>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="尚未上传输入资料；不依赖外部材料的工作流可以直接启动。" />
                )}
              </section>
              <section>
                <h4>执行 DAG</h4>
                <ol className="run-dag">
                  {(active.steps || []).map((step) => (
                    <li className={step.status} key={step.skill_name}>
                      <div>
                        <b>
                          {step.step_order + 1}. {step.display_name}
                        </b>
                        <span>{statusText(step.status)}</span>
                      </div>
                      {step.error_message && (
                        <small>{step.error_message}</small>
                      )}
                      {step.output_files.length ? (
                        <small>产出：{step.output_files.join("、")}</small>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </section>
              {selectedSnapshot.checkpoint && (
                <section className="checkpoint-card">
                  <div>
                    <p className="eyebrow">需要人工决策</p>
                    <h4>{selectedSnapshot.checkpoint.step_name}</h4>
                    <p>{selectedSnapshot.checkpoint.checkpoint_type}</p>
                  </div>
                  <textarea
                    aria-label="检查点反馈"
                    value={feedback}
                    onChange={(event) => onFeedback(event.target.value)}
                    placeholder="给出可审计的修改意见；反馈将与检查点响应一并持久化。"
                  />
                  <div className="inline-actions">
                    <button
                      disabled={busy}
                      onClick={() => onResolve("approve")}
                    >
                      批准继续
                    </button>
                    <button
                      className="quiet"
                      disabled={busy || !feedback.trim()}
                      onClick={() => onResolve("feedback")}
                    >
                      提交反馈
                    </button>
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() => onResolve("stop")}
                    >
                      停止工作流
                    </button>
                  </div>
                </section>
              )}
              <section>
                <div className="section-command">
                  <h4>产物血缘快照</h4>
                  {active.status === "completed" && (
                    <button
                      className="quiet compact-action"
                      disabled={busy}
                      title="将本工作流的文献检索结果同步至当前项目的证据库"
                      onClick={() => onSync(active.id)}
                    >
                      ⇄ 同步至证据库
                    </button>
                  )}
                </div>
                {selectedSnapshot.artifacts.length ? (
                  <ol className="run-artifacts">
                    {selectedSnapshot.artifacts.map((item) => (
                      <li key={item.path}>
                        <b>{item.path}</b>
                        <span>
                          {item.size.toLocaleString()} bytes · SHA256{" "}
                          {item.sha256}
                        </span>
                        {item.producer_step && (
                          <small>生产步骤：{item.producer_step}</small>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="当前工作区还没有可交付产物。" />
                )}
              </section>
              <section>
                <h4>实时日志</h4>
                {selectedSnapshot.logs.length ? (
                  <ol className="run-logs">
                    {selectedSnapshot.logs.map((entry, index) => (
                      <li key={`${entry.created_at}-${index}`}>
                        <time dateTime={entry.created_at}>{fmtTime(entry.created_at)}</time>
                        <b>{entry.step_name || "工作流"}</b>
                        <span className={entry.level}>{entry.message}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="尚无持久化执行日志。" />
                )}
              </section>
            </section>
          ) : (
            <Empty text="选择一个工作流以查看其运行快照。" />
          )}
        </div>
      ) : (
        <Empty text="当前项目还没有工作流。创建工作流后，所有执行状态和产物将自动绑定到此项目。" />
      )}
    </Panel>
  );
}
function ProjectCard({ project }: { project: Project }) {
  return (
    <div className="project-card">
      <div>
        <p className="eyebrow">当前研究合同</p>
        <h3>{project.title}</h3>
        <p>{project.research_question}</p>
      </div>
      <dl>
        <div>
          <dt>状态</dt>
          <dd>{statusText(project.status)}</dd>
        </div>
        <div>
          <dt>证据实体</dt>
          <dd>{project.artifacts.length}</dd>
        </div>
        <div>
          <dt>审计事件</dt>
          <dd>{project.events.length}</dd>
        </div>
        <div>
          <dt>冻结假设</dt>
          <dd>{project.hypothesis_readiness?.frozen_count || 0}</dd>
        </div>
      </dl>
    </div>
  );
}
const emptyHypothesis = (): HypothesisWrite => ({
  statement: "",
  mechanism: "",
  prediction: "",
  falsification_criteria: "",
  boundary_conditions: "",
});
function HypothesisWorkbench({
  project,
  busy,
  onRun,
  onChanged,
}: {
  project: Project;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
  onChanged: (project: Project) => Promise<void>;
}) {
  const [form, setForm] = useState<HypothesisWrite>(emptyHypothesis),
    [editingVersionId, setEditingVersionId] = useState(""),
    [changeReason, setChangeReason] = useState(""),
    [transitionReason, setTransitionReason] = useState(
      "研究者已核对机制、可观察预测、证伪标准与边界条件。",
    );
  const hypotheses = project.hypotheses || [];
  const current = hypotheses.filter((item) => item.is_current);
  const historical = hypotheses.filter((item) => !item.is_current);
  const readiness = project.hypothesis_readiness || {
    ready: false,
    current_count: current.length,
    frozen_count: current.filter((item) => item.status === "frozen").length,
    falsified_count: current.filter((item) => item.status === "falsified").length,
    rule: "验证性实验前至少冻结一条当前假设。",
  };
  useEffect(() => {
    setForm(emptyHypothesis());
    setEditingVersionId("");
    setChangeReason("");
  }, [project.id]);
  useEffect(() => {
    if (
      editingVersionId &&
      !current.some(
        (item) => item.id === editingVersionId && item.status === "draft",
      )
    ) {
      setEditingVersionId("");
      setForm(emptyHypothesis());
    }
  }, [editingVersionId, project.hypotheses]);
  const update = (key: keyof HypothesisWrite, value: string) =>
    setForm((valueBefore) => ({ ...valueBefore, [key]: value }));
  const complete = Object.values(form).every((value) => value.trim());
  const submit = () =>
    onRun(async () => {
      if (!complete || !changeReason.trim())
        throw new Error("五项假设字段和变更理由均为必填项");
      const updated = editingVersionId
        ? await reviseHypothesis(
            project.id,
            editingVersionId,
            form,
            changeReason.trim(),
          )
        : await createHypothesis(project.id, form, changeReason.trim());
      await onChanged(updated);
      setEditingVersionId("");
      setForm(emptyHypothesis());
      setChangeReason("");
    });
  const edit = (item: HypothesisVersion) => {
    setEditingVersionId(item.id);
    setForm({
      statement: item.statement,
      mechanism: item.mechanism,
      prediction: item.prediction,
      falsification_criteria: item.falsification_criteria,
      boundary_conditions: item.boundary_conditions,
    });
    setChangeReason("");
  };
  const transition = (
    item: HypothesisVersion,
    action: "freeze" | "unfreeze" | "falsify",
  ) =>
    onRun(async () => {
      if (!transitionReason.trim()) throw new Error("状态变更必须填写理由");
      const updated = await transitionHypothesis(
        project.id,
        item.id,
        action,
        transitionReason.trim(),
      );
      await onChanged(updated);
    });
  const renderVersion = (item: HypothesisVersion) => (
    <article
      className={`hypothesis-card hypothesis-${item.status}`}
      key={item.id}
    >
      <header>
        <div>
          <span>H-{item.hypothesis_id.slice(0, 8)} · v{item.version}</span>
          <h4>{item.statement}</h4>
        </div>
        <strong>{statusText(item.status)}</strong>
      </header>
      <dl className="hypothesis-fields">
        <div><dt>机制</dt><dd>{item.mechanism}</dd></div>
        <div><dt>可观察预测</dt><dd>{item.prediction}</dd></div>
        <div><dt>证伪标准</dt><dd>{item.falsification_criteria}</dd></div>
        <div><dt>边界条件</dt><dd>{item.boundary_conditions}</dd></div>
      </dl>
      <div className="hypothesis-provenance">
        <span>创建者 {item.created_by}</span>
        <span>变更理由：{item.change_reason}</span>
        {item.state_reason && <span>状态理由：{item.state_reason}</span>}
      </div>
      {item.manifest ? (
        <div className="hypothesis-manifest">
          <b>不可变假设清单</b>
          <code>{item.manifest.path}</code>
          <span>SHA256 {item.manifest.sha256}</span>
          <button
            className="quiet"
            disabled={busy}
            onClick={() =>
              onRun(() =>
                download(
                  `/api/editor/${project.id}/download?path=${encodeURIComponent(item.manifest!.path)}`,
                  `hypothesis-${item.hypothesis_id}-v${item.version}.json`,
                ),
              )
            }
          >
            下载并独立核验
          </button>
        </div>
      ) : item.status === "frozen" ? (
        <div className="review-failure">冻结状态缺少可核验清单，实验门禁将阻断。</div>
      ) : null}
      {item.events?.length ? (
        <details>
          <summary>{item.events.length} 条生命周期事件</summary>
          <ol className="hypothesis-events">
            {item.events.map((event) => (
              <li key={event.id}>
                <b>{event.event_type}</b>
                <span>{event.actor} · {event.reason}</span>
                <time dateTime={event.created_at}>{fmtTime(event.created_at)}</time>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
      {item.is_current && project.status !== "approved" && (
        <div className="inline-actions">
          {item.status === "draft" && (
            <>
              <button className="quiet" disabled={busy} onClick={() => edit(item)}>创建修订</button>
              <button disabled={busy || !transitionReason.trim()} onClick={() => transition(item, "freeze")}>冻结并锁定清单</button>
            </>
          )}
          {item.status === "frozen" && (
            <button className="quiet" disabled={busy || !transitionReason.trim()} onClick={() => transition(item, "unfreeze")}>解冻并使下游失效</button>
          )}
          {(item.status === "draft" || item.status === "frozen") && (
            <button className="danger" disabled={busy || !transitionReason.trim()} onClick={() => transition(item, "falsify")}>记录证伪</button>
          )}
        </div>
      )}
    </article>
  );
  return (
    <section className="hypothesis-workbench" aria-label="可证伪假设注册表">
      <div className="section-command">
        <div>
          <p className="eyebrow">Hypothesis lifecycle</p>
          <h3>可证伪假设注册表</h3>
          <p>登记或修订会生成不可变清单，冻结后验证性实验、稿件和独立审查才能绑定该 SHA256。解冻、修订或证伪会保留历史并使下游证据失效。</p>
        </div>
        <span className={`readiness-badge ${readiness.ready ? "ready" : "blocked"}`}>
          {readiness.ready ? "验证性工作就绪" : "验证性工作已阻断"}
        </span>
      </div>
      <div className="hypothesis-readiness">
        <span>当前 {readiness.current_count}</span>
        <span>已冻结 {readiness.frozen_count}</span>
        <span>已证伪 {readiness.falsified_count}</span>
        <small>{readiness.rule}</small>
      </div>
      <label className="wide transition-reason">
        状态变更理由
        <textarea value={transitionReason} onChange={(event) => setTransitionReason(event.target.value)} />
      </label>
      {current.length ? <div className="hypothesis-list">{current.map(renderVersion)}</div> : <Empty text="先登记一条包含机制、预测、证伪标准和边界条件的假设。" />}
      <section className="hypothesis-editor">
        <div className="section-command">
          <div>
            <p className="eyebrow">{editingVersionId ? "Version revision" : "New hypothesis"}</p>
            <h3>{editingVersionId ? "创建新版本" : "登记研究假设"}</h3>
          </div>
          {editingVersionId && <button className="quiet" onClick={() => {setEditingVersionId("");setForm(emptyHypothesis());setChangeReason("");}}>取消修订</button>}
        </div>
        <div className="form-grid hypothesis-form">
          <Field label="假设陈述" value={form.statement} set={(value) => update("statement", value)} area placeholder="明确变量、方向和可被反驳的关系" />
          <Field label="机制" value={form.mechanism} set={(value) => update("mechanism", value)} area placeholder="说明为何可能发生，而非只重复相关关系" />
          <Field label="可观察预测" value={form.prediction} set={(value) => update("prediction", value)} area placeholder="给出可由数据或实验观察的结果" />
          <Field label="证伪标准" value={form.falsification_criteria} set={(value) => update("falsification_criteria", value)} area placeholder="哪些结果出现时必须拒绝或修订假设" />
          <Field label="边界条件" value={form.boundary_conditions} set={(value) => update("boundary_conditions", value)} area placeholder="限定人群、场景、时间和适用范围" />
          <Field label="登记 / 修订理由" value={changeReason} set={setChangeReason} area placeholder="说明本版本为何产生；该理由写入审计事件" />
        </div>
        <button disabled={busy || !complete || !changeReason.trim()} onClick={submit}>
          {editingVersionId ? "保存为下一版本" : "登记草拟假设"}
        </button>
      </section>
      {historical.length ? (
        <details className="hypothesis-history">
          <summary>历史版本（{historical.length}）</summary>
          <div className="hypothesis-list">{historical.map(renderVersion)}</div>
        </details>
      ) : null}
    </section>
  );
}
function ScreeningPage({
  project,
  busy,
  onRun,
}: {
  project?: Project;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [state, setState] = useState<ScreeningState>();
  const [title, setTitle] = useState("系统综述筛选协议"),
    [inclusion, setInclusion] = useState(""),
    [exclusion, setExclusion] = useState(""),
    [strategy, setStrategy] = useState(
      "在指定 Provider 中检索；保存的证据卡逐项由研究者筛选。",
    ),
    [reason, setReason] = useState("与已激活的纳入/排除标准一致。");
  const refresh = async () => {
    if (project) setState(await getScreening(project.id));
  };
  useEffect(() => {
    if (!project) {
      setState(undefined);
      return;
    }
    void refresh();
  }, [project?.id]);
  useEffect(() => {
    if (!state?.protocol) return;
    setTitle(state.protocol.title);
    setInclusion(state.protocol.inclusion_criteria);
    setExclusion(state.protocol.exclusion_criteria);
    setStrategy(state.protocol.source_strategy);
  }, [state?.protocol?.protocol_sha256]);
  if (!project)
    return (
      <Panel
        title="筛选协议与 PRISMA"
        detail="建立研究合同后，才能固定筛选口径并记录每一张证据卡的人工决定。"
      >
        <Empty text="请先建立研究合同。" />
      </Panel>
    );
  const protocol = state?.protocol;
  const byCard = new Map(
    (state?.decisions || []).map((item) => [item.evidence_card_id, item]),
  );
  const save = () =>
    onRun(async () =>
      setState(
        await saveScreeningProtocol(project.id, {
          title,
          inclusion_criteria: inclusion || project.inclusion_criteria,
          exclusion_criteria: exclusion,
          source_strategy: strategy,
        }),
      ),
    );
  const activate = () =>
    onRun(async () => setState(await activateScreeningProtocol(project.id)));
  const decide = (
    cardId: string,
    decision: "included" | "excluded" | "uncertain",
  ) =>
    onRun(async () =>
      setState(
        await recordScreeningDecision(project.id, cardId, decision, reason),
      ),
    );
  const exportPrisma = () =>
    onRun(async () => setState(await exportScreeningPrisma(project.id)));
  return (
    <Panel
      title="筛选协议与 PRISMA"
      detail="先固定纳入、排除和检索策略；激活后的人工决定进入追加式账本，并导出可复核的 PRISMA 流程产物。"
    >
      <section className="settings-section">
        <div className="section-command">
          <h3>筛选协议</h3>
          <button
            className="icon-button quiet"
            title="刷新筛选状态"
            aria-label="刷新筛选状态"
            disabled={busy}
            onClick={() => void onRun(refresh)}
          >
            ↻
          </button>
        </div>
        <div className="form-grid">
          <Field
            label="协议名称"
            value={title}
            set={setTitle}
            placeholder="例如：开放科学可复现性系统综述"
          />
          <Field
            label="纳入标准"
            value={inclusion || project.inclusion_criteria}
            set={setInclusion}
            area
            placeholder="研究对象、年份、语言、研究设计与可获得性"
          />
          <Field
            label="排除标准"
            value={exclusion}
            set={setExclusion}
            area
            placeholder="说明应排除的研究、重复记录与无关主题"
          />
          <Field
            label="检索与去重策略"
            value={strategy}
            set={setStrategy}
            area
            placeholder="数据源、检索式、时间范围和去重规则"
          />
        </div>
        <div className="actions">
          <button
            disabled={
              busy ||
              !title.trim() ||
              !(inclusion || project.inclusion_criteria).trim() ||
              !exclusion.trim() ||
              !strategy.trim()
            }
            onClick={save}
          >
            保存协议草案
          </button>
          <button
            className="quiet"
            disabled={busy || !protocol || protocol.status === "active"}
            onClick={activate}
          >
            激活并固定版本
          </button>
          <button
            className="quiet"
            disabled={busy || protocol?.status !== "active"}
            onClick={exportPrisma}
          >
            导出 PRISMA JSON
          </button>
        </div>
        {protocol ? (
          <div
            className={`graph-gate ${protocol.active ? "passed" : "blocked"}`}
          >
            <b>{protocol.active ? "协议已激活" : "协议草案未激活"}</b>
            <span>
              v{protocol.version} · {protocol.protocol_sha256.slice(0, 16)}
            </span>
            <code>{protocol.artifact_path}</code>
          </div>
        ) : (
          <Empty text="尚未保存筛选协议。" />
        )}
      </section>
      <section className="settings-section">
        <h3>证据卡筛选决定</h3>
        <Field
          label="本次决定理由"
          value={reason}
          set={setReason}
          placeholder="必须说明为何纳入、排除或保留待定"
          area
        />
        {project.evidence_cards.length ? (
          <ol className="results">
            {project.evidence_cards.map((card) => {
              const decision = byCard.get(card.id);
              return (
                <li key={card.id}>
                  <a href={card.canonical_url} target="_blank" rel="noreferrer">
                    {card.title}
                  </a>
                  <span>
                    {decision
                      ? `${decision.decision} · ${decision.reason}`
                      : "尚未按当前协议筛选"}
                  </span>
                  <div className="inline-actions">
                    <button
                      disabled={busy || !protocol?.active || !reason.trim()}
                      onClick={() => decide(card.id, "included")}
                    >
                      纳入
                    </button>
                    <button
                      className="danger"
                      disabled={busy || !protocol?.active || !reason.trim()}
                      onClick={() => decide(card.id, "excluded")}
                    >
                      排除
                    </button>
                    <button
                      className="quiet"
                      disabled={busy || !protocol?.active || !reason.trim()}
                      onClick={() => decide(card.id, "uncertain")}
                    >
                      待定
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <Empty text="先在“文献与证据”保存数据源返回的证据卡。" />
        )}
      </section>
      {state?.prisma && (
        <section className="settings-section">
          <h3>PRISMA 流程摘要</h3>
          <dl className="metric-grid">
            <div>
              <dt>识别</dt>
              <dd>{state.prisma.flow.records_identified}</dd>
            </div>
            <div>
              <dt>已筛选</dt>
              <dd>{state.prisma.flow.records_screened}</dd>
            </div>
            <div>
              <dt>纳入</dt>
              <dd>{state.prisma.flow.studies_included}</dd>
            </div>
            <div>
              <dt>排除</dt>
              <dd>{state.prisma.flow.records_excluded}</dd>
            </div>
            <div>
              <dt>待定</dt>
              <dd>{state.prisma.flow.records_uncertain}</dd>
            </div>
          </dl>
          {state.artifact && (
            <p className="file-path">
              {state.artifact.path} · SHA256 {state.artifact.sha256}
            </p>
          )}
        </section>
      )}
    </Panel>
  );
}
type EditorWorkspaceFile = { path: string; size: number };
type EditorCompileResult = {
  status: string;
  source: { path: string; sha256: string };
  outputs: Array<{ path: string; sha256: string; bytes: number }>;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  stderr: string;
};
type EditorDocxStatus = {
  status: string;
  documents: Array<{ path: string; sha256: string; bytes: number }>;
  latest_compile?: { status: string; stderr?: string; failure_reason?: string };
};
type ImageAuditEntry = {
  source: { path: string; sha256: string; bytes: number };
  status: string;
  format?: string;
  width?: number;
  height?: number;
  mode?: string;
  frames?: number;
  warnings: string[];
  failure_reason?: string;
};
type ImageAuditResult = {
  status: string;
  scope: string;
  summary: { files_scanned: number; valid: number; failed: number };
  images: ImageAuditEntry[];
  manifest: { path: string; sha256: string };
};
type ImageDescriptionResult = ImageAuditResult & {
  image: ImageAuditEntry;
  description: string;
  description_kind: string;
};
type GeneratedImageResult = {
  status: string;
  image?: ImageAuditEntry;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  revised_prompt?: string;
};
type ProjectPreviewProcess = {
  port: number;
  url: string;
  running: boolean;
};
type ProjectPreviewStatus = {
  wf_id: string;
  frontend: ProjectPreviewProcess | null;
  backend: ProjectPreviewProcess | null;
};
type ProjectPreviewStart = {
  wf_id: string;
  servers: Array<{
    kind: "frontend" | "backend";
    status: string;
    port?: number;
    url?: string;
    note?: string;
    error?: string;
  }>;
};
type EditorAgentProposal = {
  id: string;
  path: string;
  base_hash: string;
  content: string;
  proposed_diff: string;
  status: string;
};
type EditorAgentResult = {
  status: string;
  summary?: string;
  task_id?: string;
  changed_files?: string[];
  proposals?: EditorAgentProposal[];
  has_diff?: boolean;
  proposal?: EditorAgentProposal | null;
  failure_reason?: string;
};
type EditorChatTurn = {
  id?: string;
  role?: string;
  request?: string;
  file?: string;
  content?: string;
  created_at?: string;
};
type EditorAiEditResult = {
  content: string;
  file: string;
  message: string;
  role?: string;
  status?: string;
  history?: EditorChatTurn[];
  history_path?: string;
};
type EditorScriptResult = {
  success: boolean;
  returncode: number;
  stdout: string;
  stderr: string;
  language: string;
  started_at?: string;
  finished_at?: string;
  audit?: { path: string; sha256: string };
};
function EditorCompilePage({
  workflows,
  selectedId,
  onSelected,
  busy,
  onRun,
}: {
  workflows: Workflow[];
  selectedId: string;
  onSelected: (id: string) => void;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [files, setFiles] = useState<EditorWorkspaceFile[]>([]),
    [path, setPath] = useState(""),
    [content, setContent] = useState(""),
    [compile, setCompile] = useState<EditorCompileResult>(),
    [docx, setDocx] = useState<EditorDocxStatus>(),
    [imagePath, setImagePath] = useState(""),
    [imageAudit, setImageAudit] = useState<ImageAuditResult>(),
    [imageDescription, setImageDescription] =
      useState<ImageDescriptionResult>(),
    [generationPrompt, setGenerationPrompt] = useState(""),
    [generationModel, setGenerationModel] = useState("gpt-image-1"),
    [generationSize, setGenerationSize] = useState("1024x1024"),
    [generatedImage, setGeneratedImage] = useState<GeneratedImageResult>(),
    [previewMode, setPreviewMode] = useState<"frontend" | "backend" | "both">("both"),
    [preview, setPreview] = useState<ProjectPreviewStatus>(),
    [previewMessage, setPreviewMessage] = useState(""),
    [agentPrompt, setAgentPrompt] = useState(""),
    [agentResult, setAgentResult] = useState<EditorAgentResult>(),
    [agentMessage, setAgentMessage] = useState(""),
    [editPrompt, setEditPrompt] = useState(""),
    [editResult, setEditResult] = useState<EditorAiEditResult>(),
    [editMessage, setEditMessage] = useState(""),
    [chatHistory, setChatHistory] = useState<EditorChatTurn[]>([]),
    [scriptLanguage, setScriptLanguage] = useState<"python" | "bash" | "node">("python"),
    [scriptSource, setScriptSource] = useState('print("VIBE_SCRIPT_OK")\n'),
    [scriptResult, setScriptResult] = useState<EditorScriptResult>(),
    [scriptMessage, setScriptMessage] = useState("");
  const load = async () => {
    if (!selectedId) {
      setFiles([]);
      setPath("");
      setContent("");
      setCompile(undefined);
      setDocx(undefined);
      setPreview(undefined);
      setPreviewMessage("");
      setAgentResult(undefined);
      setAgentMessage("");
      setEditResult(undefined);
      setEditMessage("");
      setChatHistory([]);
      setScriptResult(undefined);
      setScriptMessage("");
      return;
    }
    const listed = await api<{ files: EditorWorkspaceFile[] }>(
      `/api/editor/${selectedId}/files`,
    );
    setFiles(listed.files);
    const preferred =
      listed.files.find((item) => item.path === path) ||
      listed.files.find((item) => item.path === "paper/main.md") ||
      listed.files.find((item) => /\.(md|tex)$/i.test(item.path));
    if (preferred) {
      setPath(preferred.path);
      const value = await api<{ content: string }>(
        `/api/editor/${selectedId}/file?path=${encodeURIComponent(preferred.path)}`,
      );
      setContent(value.content);
    } else {
      setPath("");
      setContent("");
    }
    setDocx(
      await api<EditorDocxStatus>(`/api/editor/${selectedId}/docx-status`),
    );
    try {
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    } catch {
      setPreview(undefined);
    }
    try {
      const staged = await api<EditorAgentResult>(
        `/api/editor/${selectedId}/ai-agent-check`,
      );
      setAgentResult(staged.has_diff ? staged : undefined);
    } catch {
      /* staged proposals are optional during workspace refresh */
    }
    try {
      const history = await api<{ history: EditorChatTurn[] }>(
        `/api/editor/${selectedId}/chat-history`,
      );
      setChatHistory(history.history || []);
    } catch {
      setChatHistory([]);
    }
  };
  useEffect(() => {
    setImagePath("");
    setImageAudit(undefined);
    setImageDescription(undefined);
    setGeneratedImage(undefined);
    setAgentResult(undefined);
    setAgentMessage("");
    setEditResult(undefined);
    setEditMessage("");
    setChatHistory([]);
    setScriptResult(undefined);
    setScriptMessage("");
    void load();
  }, [selectedId]);
  const open = (next: string) =>
    onRun(async () => {
      setPath(next);
      setContent(
        (
          await api<{ content: string }>(
            `/api/editor/${selectedId}/file?path=${encodeURIComponent(next)}`,
          )
        ).content,
      );
    });
  const save = () =>
    onRun(async () => {
      if (!path) throw new Error("请选择 Markdown 或 LaTeX 源文件");
      await api(`/api/editor/${selectedId}/file`, {
        method: "PUT",
        body: JSON.stringify({ path, content }),
      });
      await load();
    });
  const runCompile = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      const result = await api<EditorCompileResult>(
        `/api/editor/${selectedId}/compile`,
        {
          method: "POST",
          body: JSON.stringify({
            source_md: path.endsWith(".md") ? content : "",
          }),
        },
      );
      setCompile(result);
      setDocx(
        await api<EditorDocxStatus>(`/api/editor/${selectedId}/docx-status`),
      );
      await load();
    });
  const runImageAudit = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      const query = imagePath ? `?path=${encodeURIComponent(imagePath)}` : "";
      setImageAudit(
        await api<ImageAuditResult>(
          `/api/editor/${selectedId}/image-check${query}`,
        ),
      );
      setImageDescription(undefined);
    });
  const describeImage = () =>
    onRun(async () => {
      if (!selectedId || !imagePath) throw new Error("请选择图像文件");
      const result = await api<ImageDescriptionResult>(
        `/api/editor/${selectedId}/describe-image?path=${encodeURIComponent(imagePath)}`,
        { method: "POST" },
      );
      setImageAudit(result);
      setImageDescription(result);
    });
  const generateImage = () =>
    onRun(async () => {
      if (!selectedId || !generationPrompt.trim())
        throw new Error("请输入图像生成提示");
      const result = await api<GeneratedImageResult>(
        `/api/editor/${selectedId}/generate-image`,
        {
          method: "POST",
          body: JSON.stringify({
            prompt: generationPrompt,
            model: generationModel,
            size: generationSize,
          }),
        },
      );
      setGeneratedImage(result);
      await load();
    });
  const refreshPreview = () =>
    onRun(async () => {
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    });
  const startPreview = () =>
    onRun(async () => {
      const started = await api<ProjectPreviewStart>(
        `/api/editor/${selectedId}/serve`,
        { method: "POST", body: JSON.stringify({ mode: previewMode }) },
      );
      const failures = started.servers.filter((item) => item.status === "error");
      setPreviewMessage(
        failures.length
          ? failures.map((item) => item.error || `${item.kind} 启动失败`).join("；")
          : started.servers.map((item) => item.note).filter(Boolean).join("；") || "项目预览已启动。",
      );
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    });
  const stopPreview = () =>
    onRun(async () => {
      await api(`/api/editor/${selectedId}/serve`, { method: "DELETE" });
      setPreviewMessage("项目预览已停止。");
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    });
  const openPreview = (url: string) => {
    window.open(url, "_blank", "noopener,noreferrer");
    setPreviewMessage(`正在系统浏览器中打开 ${url}`);
  };
  const runEditorAgent = () =>
    onRun(async () => {
      if (!selectedId || !agentPrompt.trim()) {
        throw new Error("请输入编辑代理指令");
      }
      setAgentMessage("");
      try {
        const result = await api<EditorAgentResult>(
          `/api/editor/${selectedId}/ai-agent`,
          {
            method: "POST",
            body: JSON.stringify({ message: agentPrompt.trim() }),
          },
        );
        setAgentResult(result);
        setAgentMessage(
          result.status === "staged"
            ? `已暂存 ${result.changed_files?.length || 0} 个可审阅修改`
            : result.summary || "代理未提出文件修改",
        );
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        if (detail.includes("agent_provider_unavailable") || detail.includes("501")) {
          setAgentMessage(
            "编辑代理不可用：请先在设置中配置科研编辑模型的 Base URL 与 API 密钥。",
          );
          setAgentResult(undefined);
          return;
        }
        throw error;
      }
    });
  const applyEditorAgent = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      const proposal =
        agentResult?.proposal ||
        agentResult?.proposals?.[0] ||
        null;
      const filesToApply = proposal?.path
        ? [proposal.path]
        : agentResult?.changed_files || [];
      await api(`/api/editor/${selectedId}/ai-agent-apply`, {
        method: "POST",
        body: JSON.stringify({ files: filesToApply }),
      });
      setAgentMessage(
        proposal?.path
          ? `已应用 ${proposal.path}，可撤销到备份版本。`
          : "已应用暂存提案。",
      );
      setAgentResult(undefined);
      await load();
    });
  const discardEditorAgent = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      await api(`/api/editor/${selectedId}/ai-agent-discard`, {
        method: "POST",
      });
      setAgentResult(undefined);
      setAgentMessage("已丢弃暂存提案。");
    });
  const undoEditorAgent = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      await api(`/api/editor/${selectedId}/ai-agent-undo`, { method: "POST" });
      setAgentMessage("已撤销最近一次代理应用。");
      await load();
    });
  const runAiEdit = () =>
    onRun(async () => {
      if (!selectedId || !path) throw new Error("请先选择源文件");
      if (!editPrompt.trim()) throw new Error("请输入 AI 编辑指令");
      setEditMessage("");
      try {
        const result = await api<EditorAiEditResult>(
          `/api/editor/${selectedId}/ai-edit`,
          {
            method: "POST",
            body: JSON.stringify({
              message: editPrompt.trim(),
              current_file: path,
              current_content: content,
              workspace_files: files.map((item) => item.path),
              role: path.endsWith(".tex") ? "latex" : "markdown",
              history: chatHistory,
            }),
          },
        );
        setEditResult(result);
        if (result.history) setChatHistory(result.history);
        setEditMessage(
          result.history_path
            ? `已生成建议内容，聊天记录已写入 ${result.history_path}`
            : "已生成建议内容，可审阅后写入当前文件。",
        );
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        if (
          detail.includes("agent_provider_unavailable") ||
          detail.includes("501")
        ) {
          setEditMessage(
            "AI 编辑不可用：请先在设置中配置科研编辑模型的 Base URL 与 API 密钥。",
          );
          setEditResult(undefined);
          return;
        }
        throw error;
      }
    });
  const applyAiEdit = () => {
    if (!editResult?.content) throw new Error("没有可应用的 AI 编辑结果");
    setContent(editResult.content);
    setEditMessage(`已把建议内容写入编辑器缓冲区：${editResult.file || path}`);
  };
  const clearChatHistory = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      await api(`/api/editor/${selectedId}/chat-history`, { method: "DELETE" });
      setChatHistory([]);
      setEditMessage("已清空编辑器聊天历史。");
    });
  const runWorkspaceScript = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      if (!scriptSource.trim()) throw new Error("请输入脚本内容");
      const result = await api<EditorScriptResult>(
        `/api/editor/${selectedId}/run-script`,
        {
          method: "POST",
          body: JSON.stringify({
            script: scriptSource,
            language: scriptLanguage,
          }),
        },
      );
      setScriptResult(result);
      setScriptMessage(
        result.success
          ? `脚本执行成功（exit ${result.returncode}）${
              result.audit ? ` · 审计 ${result.audit.path}` : ""
            }`
          : `脚本执行失败（exit ${result.returncode}）`,
      );
    });
  const imageFiles = files.filter((item) =>
    /\.(avif|bmp|gif|ico|jpe?g|png|tiff?|webp)$/i.test(item.path),
  );
  const hasProjectFiles = files.some((item) => item.path.startsWith("code/"));
  const stagedProposal =
    agentResult?.proposal || agentResult?.proposals?.[0] || null;
  if (!workflows.length)
    return (
      <Panel
        title="编辑与编译"
        detail="以工作区内的 Markdown 或 LaTeX 源文件生成可下载、可审计的 DOCX 和 HTML 产物。"
      >
        <Empty text="先创建一个工作流，再进入编辑与编译。" />
      </Panel>
    );
  return (
    <Panel
      title="编辑与编译"
      detail="Pandoc 在本地受限工作区运行；每次编译保存源文件、运行时、输出哈希和失败日志，不会把缺少 TeX 的情形伪装成 PDF 成功。"
    >
      <section className="settings-section">
        <div className="form-grid">
          <label>
            工作流
            <select
              value={selectedId}
              onChange={(event) => onSelected(event.target.value)}
            >
              {workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            源文件
            <select
              value={path}
              onChange={(event) => void open(event.target.value)}
            >
              <option value="">选择 Markdown 或 LaTeX</option>
              {files
                .filter((item) => /\.(md|tex)$/i.test(item.path))
                .map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.path}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button
            className="quiet"
            disabled={busy}
            onClick={() => void onRun(load)}
          >
            刷新工作区
          </button>
          <button disabled={busy || !path} onClick={save}>
            保存源文件
          </button>
          <button
            disabled={
              busy ||
              (!path && !files.some((item) => /\.(md|tex)$/i.test(item.path)))
            }
            onClick={runCompile}
          >
            编译 DOCX 与 HTML
          </button>
          {docx?.documents?.[0] && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/docx`,
                    "research-document.docx",
                  ),
                )
              }
            >
              下载 DOCX
            </button>
          )}
        </div>
        {path ? (
          <textarea
            aria-label="编辑器源文件"
            className="code-editor"
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        ) : (
          <Empty text="工作区中尚无可编译的 Markdown 或 LaTeX 文件。" />
        )}
      </section>
      <section className="settings-section">
        <h3>编辑代理</h3>
        <p>
          使用设置中的科研编辑模型生成可审阅文件提案。未配置密钥时明确提示，不会伪造成功。
        </p>
        <Field
          label="代理指令"
          value={agentPrompt}
          set={setAgentPrompt}
          placeholder="例如：收紧摘要，并统一图表编号"
          area
        />
        <div className="actions">
          <button
            disabled={busy || !selectedId || !agentPrompt.trim()}
            onClick={runEditorAgent}
          >
            生成提案
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId || !stagedProposal}
            onClick={applyEditorAgent}
          >
            应用提案
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId || !stagedProposal}
            onClick={discardEditorAgent}
          >
            丢弃提案
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId}
            onClick={undoEditorAgent}
          >
            撤销最近应用
          </button>
        </div>
        {agentMessage && <p className="file-path">{agentMessage}</p>}
        {stagedProposal && (
          <>
            <div
              className={
                "graph-gate " +
                (agentResult?.status === "staged" || stagedProposal.status === "staged"
                  ? "passed"
                  : "blocked")
              }
            >
              <b>
                {agentResult?.summary || "已暂存可审阅修改"}
              </b>
              <span>{stagedProposal.path}</span>
              <code>{stagedProposal.base_hash.slice(0, 16)}</code>
            </div>
            <textarea
              aria-label="编辑代理提案 diff"
              className="code-editor"
              readOnly
              value={stagedProposal.proposed_diff}
            />
          </>
        )}
      </section>
      <section className="settings-section">
        <h3>AI 编辑与聊天历史</h3>
        <p>
          对当前源文件发起定向改写；结果写入 `_chat_history.json`，可审阅后再覆盖编辑器内容。
        </p>
        <Field
          label="编辑指令"
          value={editPrompt}
          set={setEditPrompt}
          placeholder="例如：把摘要压缩到 150 词，并补上贡献列表"
          area
        />
        <div className="actions">
          <button
            disabled={busy || !selectedId || !path || !editPrompt.trim()}
            onClick={runAiEdit}
          >
            生成 AI 编辑
          </button>
          <button
            className="quiet"
            disabled={busy || !editResult?.content}
            onClick={applyAiEdit}
          >
            写入编辑器
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId || chatHistory.length === 0}
            onClick={clearChatHistory}
          >
            清空聊天历史
          </button>
        </div>
        {editMessage && <p className="file-path">{editMessage}</p>}
        {editResult?.content && (
          <textarea
            aria-label="AI 编辑建议内容"
            className="code-editor"
            readOnly
            value={editResult.content}
          />
        )}
        {chatHistory.length > 0 && (
          <ol className="results">
            {chatHistory
              .slice()
              .reverse()
              .slice(0, 8)
              .map((item, index) => (
                <li key={item.id || `${item.created_at || "turn"}-${index}`}>
                  <b>{item.file || path || "workspace"}</b>
                  <span>{item.request || item.role || "assistant"}</span>
                  <code>
                    {(item.content || "").slice(0, 160)}
                    {(item.content || "").length > 160 ? "…" : ""}
                  </code>
                </li>
              ))}
          </ol>
        )}
      </section>
      <section className="settings-section">
        <h3>工作区脚本执行</h3>
        <p>
          在受限监督器中运行 python / bash / node；每次执行写入 `.editor_runs/` 审计记录，不静默吞错。
        </p>
        <div className="form-grid">
          <label>
            语言
            <select
              aria-label="脚本语言"
              value={scriptLanguage}
              onChange={(event) =>
                setScriptLanguage(event.target.value as "python" | "bash" | "node")
              }
            >
              <option value="python">Python</option>
              <option value="bash">Bash</option>
              <option value="node">Node</option>
            </select>
          </label>
        </div>
        <textarea
          aria-label="工作区脚本内容"
          className="code-editor"
          value={scriptSource}
          onChange={(event) => setScriptSource(event.target.value)}
        />
        <div className="actions">
          <button
            disabled={busy || !selectedId || !scriptSource.trim()}
            onClick={runWorkspaceScript}
          >
            运行脚本
          </button>
        </div>
        {scriptMessage && <p className="file-path">{scriptMessage}</p>}
        {scriptResult && (
          <>
            <div
              className={
                "graph-gate " + (scriptResult.success ? "passed" : "blocked")
              }
            >
              <b>
                {scriptResult.success ? "执行成功" : "执行失败"} · exit{" "}
                {scriptResult.returncode}
              </b>
              <span>{scriptResult.language}</span>
              {scriptResult.audit && (
                <code>
                  {scriptResult.audit.path} ·{" "}
                  {scriptResult.audit.sha256.slice(0, 16)}
                </code>
              )}
            </div>
            {(scriptResult.stdout || scriptResult.stderr) && (
              <textarea
                aria-label="脚本执行输出"
                className="code-editor"
                readOnly
                value={[
                  scriptResult.stdout
                    ? `STDOUT\n${scriptResult.stdout}`
                    : "",
                  scriptResult.stderr
                    ? `STDERR\n${scriptResult.stderr}`
                    : "",
                ]
                  .filter(Boolean)
                  .join("\n\n")}
              />
            )}
          </>
        )}
      </section>
      {hasProjectFiles && (
        <section className="settings-section">
          <h3>项目本地预览</h3>
          <p>自动识别静态页面、Vite、FastAPI、Flask 或 Express；前后端模式通过同源 /api 代理访问。</p>
          <div className="form-grid">
            <label>
              启动模式
              <select
                aria-label="项目预览启动模式"
                value={previewMode}
                onChange={(event) => setPreviewMode(event.target.value as "frontend" | "backend" | "both")}
              >
                <option value="both">前后端一起</option>
                <option value="frontend">仅前端</option>
                <option value="backend">仅后端</option>
              </select>
            </label>
          </div>
          <div className="actions">
            <button disabled={busy} onClick={startPreview}>启动项目预览</button>
            <button className="quiet" disabled={busy} onClick={refreshPreview}>刷新预览状态</button>
            <button
              className="quiet"
              disabled={busy || (!preview?.frontend && !preview?.backend)}
              onClick={stopPreview}
            >
              停止项目预览
            </button>
            {preview?.frontend?.running && (
              <button className="quiet" disabled={busy} onClick={() => openPreview(preview.frontend!.url)}>
                打开前端预览
              </button>
            )}
            {!preview?.frontend?.running && preview?.backend?.running && (
              <button className="quiet" disabled={busy} onClick={() => openPreview(preview.backend!.url)}>
                打开后端预览
              </button>
            )}
          </div>
          {(preview?.frontend || preview?.backend) && (
            <ol className="results">
              {(["frontend", "backend"] as const).map((kind) => {
                const process = preview[kind];
                return process ? (
                  <li key={kind}>
                    <b>{kind === "frontend" ? "前端" : "后端"} · 运行中</b>
                    <span>{process.url} · 端口 {process.port}</span>
                  </li>
                ) : null;
              })}
            </ol>
          )}
          {previewMessage && <p className="file-path">{previewMessage}</p>}
        </section>
      )}
      {compile && (
        <section className="settings-section">
          <h3>最近编译</h3>
          <div
            className={`graph-gate ${compile.status === "completed" ? "passed" : "blocked"}`}
          >
            <b>{compile.status === "completed" ? "编译完成" : "编译失败"}</b>
            <span>
              {compile.source.path} · {compile.source.sha256.slice(0, 16)}
            </span>
            <code>{compile.manifest.path}</code>
          </div>
          {compile.outputs.length ? (
            <ol className="results">
              {compile.outputs.map((item) => (
                <li key={item.path}>
                  <b>{item.path}</b>
                  <span>
                    {item.bytes} bytes · SHA256 {item.sha256}
                  </span>
                </li>
              ))}
            </ol>
          ) : null}
          {compile.failure_reason && (
            <p className="review-failure">{compile.failure_reason}</p>
          )}
          {compile.stderr && <pre className="json-card">{compile.stderr}</pre>}
        </section>
      )}
      {docx && (
        <section className="settings-section">
          <h3>DOCX 产物状态</h3>
          {docx.documents.length ? (
            <ol className="results">
              {docx.documents.map((item) => (
                <li key={item.path}>
                  <b>{item.path}</b>
                  <span>
                    {item.bytes} bytes · SHA256 {item.sha256}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <Empty text="尚无 DOCX 产物。" />
          )}
        </section>
      )}
      <section className="settings-section">
        <h3>图像审计</h3>
        <div className="form-grid">
          <label>
            图像文件
            <select
              value={imagePath}
              onChange={(event) => setImagePath(event.target.value)}
            >
              <option value="">全部支持的图像</option>
              {imageFiles.map((item) => (
                <option key={item.path} value={item.path}>
                  {item.path}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button disabled={busy} onClick={runImageAudit}>
            {imagePath ? "审计所选图像" : "审计工作区图像"}
          </button>
          <button
            className="quiet"
            disabled={busy || !imagePath}
            onClick={describeImage}
          >
            读取元数据描述
          </button>
          {imageAudit && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(imageAudit.manifest.path)}`,
                    "image-audit.json",
                  ),
                )
              }
            >
              下载审计清单
            </button>
          )}
        </div>
        {imageAudit && (
          <>
            <div
              className={`graph-gate ${imageAudit.status === "completed" ? "passed" : "blocked"}`}
            >
              <b>
                {imageAudit.status === "completed"
                  ? "审计通过"
                  : imageAudit.status === "no_images"
                    ? "未发现图像"
                    : "审计发现问题"}
              </b>
              <span>
                {imageAudit.summary.files_scanned} 个文件 · 有效{" "}
                {imageAudit.summary.valid} · 失败 {imageAudit.summary.failed}
              </span>
              <code>
                {imageAudit.manifest.path} ·{" "}
                {imageAudit.manifest.sha256.slice(0, 16)}
              </code>
            </div>
            {imageAudit.images.length ? (
              <ol className="results">
                {imageAudit.images.map((item) => (
                  <li key={item.source.path}>
                    <b>{item.source.path}</b>
                    <span>
                      {item.status === "valid"
                        ? `${item.format} · ${item.width}x${item.height} · ${item.mode} · SHA256 ${item.source.sha256}`
                        : item.failure_reason}
                    </span>
                    {item.warnings.length ? (
                      <small>{item.warnings.join(", ")}</small>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : (
              <Empty text="工作区中尚无受支持的图像文件。" />
            )}
            {imageDescription && (
              <p className="file-path">{imageDescription.description}</p>
            )}
          </>
        )}
      </section>
      <section className="settings-section">
        <h3>图像生成</h3>
        <div className="form-grid">
          <Field
            label="生成提示"
            value={generationPrompt}
            set={setGenerationPrompt}
            area
            placeholder="描述研究图示的对象、关系、标注和布局"
          />
          <Field
            label="模型"
            value={generationModel}
            set={setGenerationModel}
            placeholder="gpt-image-1"
          />
          <label>
            尺寸
            <select
              value={generationSize}
              onChange={(event) => setGenerationSize(event.target.value)}
            >
              <option value="1024x1024">1024 x 1024</option>
              <option value="1536x1024">1536 x 1024</option>
              <option value="1024x1536">1024 x 1536</option>
            </select>
          </label>
        </div>
        <div className="actions">
          <button
            disabled={busy || !generationPrompt.trim()}
            onClick={generateImage}
          >
            生成图像
          </button>
          {generatedImage?.image && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    "/api/editor/" +
                      selectedId +
                      "/download?path=" +
                      encodeURIComponent(generatedImage.image!.source.path),
                    "generated-research-figure.png",
                  ),
                )
              }
            >
              下载生成图
            </button>
          )}
          {generatedImage && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    "/api/editor/" +
                      selectedId +
                      "/download?path=" +
                      encodeURIComponent(generatedImage.manifest.path),
                    "image-generation-manifest.json",
                  ),
                )
              }
            >
              下载生成清单
            </button>
          )}
        </div>
        {generatedImage && (
          <>
            <div
              className={
                "graph-gate " +
                (generatedImage.status === "completed" ? "passed" : "blocked")
              }
            >
              <b>
                {generatedImage.status === "completed"
                  ? "生成完成"
                  : "生成失败"}
              </b>
              <span>
                {generatedImage.image
                  ? [
                      generatedImage.image.format,
                      generatedImage.image.width +
                        "x" +
                        generatedImage.image.height,
                      "SHA256 " + generatedImage.image.source.sha256,
                    ].join(" · ")
                  : generatedImage.failure_reason}
              </span>
              <code>
                {generatedImage.manifest.path} ·{" "}
                {generatedImage.manifest.sha256.slice(0, 16)}
              </code>
            </div>
            {generatedImage.revised_prompt && (
              <p className="file-path">{generatedImage.revised_prompt}</p>
            )}
          </>
        )}
      </section>
    </Panel>
  );
}
type DrawioExportResult = {
  status: string;
  source: { path: string; sha256: string; bytes: number };
  outputs: Array<{
    source: { path: string; sha256: string; bytes: number };
    status?: string;
    format?: string;
    width?: number;
    height?: number;
  }>;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  stderr?: string;
};
const DRAWIO_STARTER_XML =
  '<mxfile host="app.diagrams.net"><diagram name="Research flow"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Research question" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="180" height="60" as="geometry"/></mxCell><mxCell id="3" value="Evidence" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="280" y="40" width="160" height="60" as="geometry"/></mxCell><mxCell id="4" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel></diagram></mxfile>';
function DrawioExportPanel({
  workflows,
  selectedId,
  onSelected,
  busy,
  onRun,
}: {
  workflows: Workflow[];
  selectedId: string;
  onSelected: (id: string) => void;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [source, setSource] = useState(DRAWIO_STARTER_XML),
    [format, setFormat] = useState<"png" | "pdf" | "svg">("png"),
    [result, setResult] = useState<DrawioExportResult>();
  useEffect(() => setResult(undefined), [selectedId]);
  const exportDiagram = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请先选择工作流");
      const exported = await api<DrawioExportResult>(
        `/api/editor/${selectedId}/drawio-export`,
        { method: "POST", body: JSON.stringify({ source, format }) },
      );
      setResult(exported);
    });
  if (!workflows.length) return null;
  return (
    <Panel
      title="Draw.io 导出"
      detail="使用随安装包提供的 Draw.io CLI 在本地工作区导出 PNG、PDF 或 SVG。每次导出保存 XML 源、运行时哈希、命令结果和清单。"
    >
      <section className="settings-section">
        <div className="form-grid">
          <label>
            工作流
            <select
              aria-label="Draw.io 工作流"
              value={selectedId}
              onChange={(event) => onSelected(event.target.value)}
            >
              {workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            导出格式
            <select
              aria-label="Draw.io 导出格式"
              value={format}
              onChange={(event) =>
                setFormat(event.target.value as "png" | "pdf" | "svg")
              }
            >
              <option value="png">PNG</option>
              <option value="pdf">PDF</option>
              <option value="svg">SVG</option>
            </select>
          </label>
        </div>
        <label>
          Draw.io XML
          <textarea
            aria-label="Draw.io XML"
            className="code-editor"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="actions">
          <button
            disabled={busy || !selectedId || !source.trim()}
            onClick={exportDiagram}
          >
            导出 Draw.io 图
          </button>
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.source.path)}`,
                    "research-diagram.drawio",
                  ),
                )
              }
            >
              下载 XML 源文件
            </button>
          )}
          {result?.outputs[0] && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.outputs[0].source.path)}`,
                    `research-diagram.${format}`,
                  ),
                )
              }
            >
              下载导出产物
            </button>
          )}
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.manifest.path)}`,
                    "drawio-export-manifest.json",
                  ),
                )
              }
            >
              下载导出清单
            </button>
          )}
        </div>
        {result && (
          <div
            className={`graph-gate ${result.status === "completed" ? "passed" : "blocked"}`}
          >
            <b>
              {result.status === "completed"
                ? "Draw.io 导出完成"
                : "Draw.io 导出失败"}
            </b>
            <span>
              {result.outputs[0]
                ? `${result.outputs[0].source.path} · SHA256 ${result.outputs[0].source.sha256}`
                : result.failure_reason}
            </span>
            <code>
              {result.manifest.path} · {result.manifest.sha256.slice(0, 16)}
            </code>
          </div>
        )}
        {result?.stderr && <pre className="json-card">{result.stderr}</pre>}
      </section>
    </Panel>
  );
}
type MermaidExportResult = {
  status: string;
  source: { path: string; sha256: string; bytes: number };
  outputs: Array<{
    path?: string;
    source?: { path: string; sha256: string; bytes: number };
    sha256?: string;
    bytes?: number;
    status?: string;
    format?: string;
    width?: number;
    height?: number;
  }>;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  stderr?: string;
};
const MERMAID_STARTER = `flowchart LR
  Q[Research question] --> E[Evidence card]
  E --> C[Claim]
  C --> A[Assurance gate]
`;
function MermaidExportPanel({
  workflows,
  selectedId,
  onSelected,
  busy,
  onRun,
}: {
  workflows: Workflow[];
  selectedId: string;
  onSelected: (id: string) => void;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [source, setSource] = useState(MERMAID_STARTER),
    [format, setFormat] = useState<"png" | "pdf" | "svg">("svg"),
    [result, setResult] = useState<MermaidExportResult>();
  useEffect(() => setResult(undefined), [selectedId]);
  const exportDiagram = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请先选择工作流");
      const exported = await api<MermaidExportResult>(
        `/api/editor/${selectedId}/mermaid-export`,
        { method: "POST", body: JSON.stringify({ source, format }) },
      );
      setResult(exported);
    });
  const outputPath = result?.outputs?.[0]
    ? result.outputs[0].path || result.outputs[0].source?.path || ""
    : "";
  const outputSha = result?.outputs?.[0]
    ? result.outputs[0].sha256 || result.outputs[0].source?.sha256 || ""
    : "";
  if (!workflows.length) return null;
  return (
    <Panel
      title="Mermaid 导出"
      detail="使用产品内置 offline mermaid.min.js 与本地 Chromium 浏览器渲染。无网络依赖；每次导出保存源码、HTML、运行时哈希和清单。"
    >
      <section className="settings-section">
        <div className="form-grid">
          <label>
            工作流
            <select
              aria-label="Mermaid 工作流"
              value={selectedId}
              onChange={(event) => onSelected(event.target.value)}
            >
              {workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            导出格式
            <select
              aria-label="Mermaid 导出格式"
              value={format}
              onChange={(event) =>
                setFormat(event.target.value as "png" | "pdf" | "svg")
              }
            >
              <option value="svg">SVG</option>
              <option value="png">PNG</option>
              <option value="pdf">PDF</option>
            </select>
          </label>
        </div>
        <label>
          Mermaid 源码
          <textarea
            aria-label="Mermaid 源码"
            className="code-editor"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="actions">
          <button
            disabled={busy || !selectedId || !source.trim()}
            onClick={exportDiagram}
          >
            导出 Mermaid 图
          </button>
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.source.path)}`,
                    "research-diagram.mmd",
                  ),
                )
              }
            >
              下载 Mermaid 源文件
            </button>
          )}
          {outputPath && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(outputPath)}`,
                    `research-diagram.${format}`,
                  ),
                )
              }
            >
              下载导出产物
            </button>
          )}
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.manifest.path)}`,
                    "mermaid-export-manifest.json",
                  ),
                )
              }
            >
              下载导出清单
            </button>
          )}
        </div>
        {result && (
          <div
            className={`graph-gate ${result.status === "completed" ? "passed" : "blocked"}`}
          >
            <b>
              {result.status === "completed"
                ? "Mermaid 导出完成"
                : "Mermaid 导出失败"}
            </b>
            <span>
              {outputPath
                ? `${outputPath} · SHA256 ${outputSha}`
                : result.failure_reason}
            </span>
            <code>
              {result.manifest.path} · {result.manifest.sha256.slice(0, 16)}
            </code>
          </div>
        )}
        {result?.stderr && <pre className="json-card">{result.stderr}</pre>}
      </section>
    </Panel>
  );
}
function JsonCard({ value }: { value: Record<string, unknown> }) {
  return <pre className="json-card">{JSON.stringify(value, null, 2)}</pre>;
}
function AuditReviewPage({
  busy,
  project,
  reviews,
  assurance,
  innovation,
  overrideReason,
  onOverrideReason,
  onApprove,
  onReload,
  onReloadAssurance,
  onReloadInnovation,
  onRun,
  onRunInnovation,
  onSettings,
}: {
  busy: boolean;
  project?: Project;
  reviews: AdversarialReview[];
  assurance?: AssuranceEnvelope;
  innovation?: InnovationCheck;
  overrideReason: string;
  onOverrideReason: (value: string) => void;
  onApprove: () => Promise<void>;
  onReload: () => Promise<void>;
  onReloadAssurance: () => Promise<void>;
  onReloadInnovation: () => Promise<void>;
  onRun: (mode: "deterministic" | "model") => Promise<void>;
  onRunInnovation: () => Promise<void>;
  onSettings: () => void;
}) {
  return (
    <Panel title="审批与审计" detail="">
      {project ? (
        <>
           <ProjectCard project={project} />
          <AssurancePanel
            busy={busy}
            assurance={assurance}
            onReload={onReloadAssurance}
          />
          <InnovationCheckPanel
            busy={busy}
            innovation={innovation}
            overrideReason={overrideReason}
            onOverrideReason={onOverrideReason}
            onReload={onReloadInnovation}
            onRun={onRunInnovation}
          />
          <section className="audit-review-section">
            <div className="section-command">
              <h3>独立对抗审稿</h3>
              <button
                className="icon-button quiet"
                type="button"
                title="刷新审稿历史"
                aria-label="刷新审稿历史"
                disabled={busy}
                onClick={onReload}
              >
                ↻
              </button>
            </div>
            <div className="actions">
              <button disabled={busy} onClick={() => onRun("deterministic")}>
                运行确定性审计
              </button>
              <button
                className="quiet"
                disabled={busy}
                onClick={() => onRun("model")}
              >
                运行模型独立审稿
              </button>
              <button className="quiet" disabled={busy} onClick={onApprove}>
                批准研究合同
              </button>
              <button className="quiet" onClick={onSettings}>
                查看环境诊断
              </button>
            </div>
            {reviews.length ? (
              <ol className="review-list">
                {reviews.map((review) => (
                  <li key={review.id}>
                    <header>
                      <div>
                        <b>
                          {review.mode === "model"
                            ? "模型独立审稿"
                            : "确定性对抗审计"}
                        </b>
                        <span>{fmtTime(review.created_at)}</span>
                      </div>
                      <span className={`review-verdict ${review.verdict}`}>
                        {review.status === "completed"
                          ? review.verdict
                          : review.status}
                      </span>
                    </header>
                    <div className="review-hashes">
                      <code>input {review.inputs_sha256.slice(0, 16)}</code>
                      {review.report_sha256 && (
                        <code>report {review.report_sha256.slice(0, 16)}</code>
                      )}
                    </div>
                    {review.failure_reason && (
                      <p className="review-failure">{review.failure_reason}</p>
                    )}
                    {review.findings.length ? (
                      <ul className="review-findings">
                        {review.findings.map((finding, index) => (
                          <li key={`${finding.code}-${index}`}>
                            <b className={`severity ${finding.severity}`}>
                              {finding.severity}
                            </b>
                            <span>
                              {finding.code}: {finding.message}
                              {finding.locator ? ` (${finding.locator})` : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : review.status === "completed" ? (
                      <p className="review-clear">未发现阻断性问题。</p>
                    ) : null}
                    {review.review_text && (
                      <details>
                        <summary>审稿原文</summary>
                        <pre className="json-card">{review.review_text}</pre>
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <Empty text="尚无独立审稿记录。" />
            )}
          </section>
        </>
      ) : (
        <Empty text="建立研究合同后可运行独立对抗审稿。" />
      )}
    </Panel>
  );
}
function InnovationCheckPanel({
  busy,
  innovation,
  overrideReason,
  onOverrideReason,
  onReload,
  onRun,
}: {
  busy: boolean;
  innovation?: InnovationCheck;
  overrideReason: string;
  onOverrideReason: (value: string) => void;
  onReload: () => Promise<void>;
  onRun: () => Promise<void>;
}) {
  const gatePassed = Boolean(innovation?.gate?.passed);
  return (
    <section className="assurance-panel innovation-panel" aria-label="创新性核验">
      <div className="section-command">
        <div>
          <p className="eyebrow">Novelty / Innovation</p>
          <h3>创新性核验门禁</h3>
        </div>
        <div className="inline-actions">
          <span className={`assurance-status ${gatePassed ? "pass" : "blocked"}`}>
            {innovation?.status === "missing" || !innovation
              ? "未运行"
              : gatePassed
                ? "通过"
                : "阻断"}
          </span>
          <button
            className="icon-button quiet"
            type="button"
            title="刷新创新性核验"
            aria-label="刷新创新性核验"
            disabled={busy}
            onClick={onReload}
          >
            ↻
          </button>
        </div>
      </div>
      <p className="muted">
        对当前冻结假设做确定性重叠评分；LOW 新颖性必须填写研究者 override 理由，报告以 SHA256 落盘。
      </p>
      <label className="field">
        <span>LOW 新颖性 override 理由（可选）</span>
        <textarea
          value={overrideReason}
          onChange={(event) => onOverrideReason(event.target.value)}
          placeholder="说明与最接近既有工作的差异，例如方法机制、边界条件或评价协议。"
          rows={3}
        />
      </label>
      <div className="actions">
        <button disabled={busy} onClick={onRun}>
          运行创新性核验
        </button>
      </div>
      {innovation && innovation.status !== "missing" ? (
        <>
          <div className="assurance-summary">
            <div>
              <span>主张数</span>
              <b>{innovation.gate?.total_claims ?? innovation.claims?.length ?? 0}</b>
            </div>
            <div>
              <span>LOW 未覆盖</span>
              <b>{(innovation.gate?.low_novelty_claim_ids || []).join(", ") || "无"}</b>
            </div>
            <div>
              <span>报告</span>
              <b>
                {innovation.artifact
                  ? `${innovation.artifact.sha256.slice(0, 12)}…`
                  : "无"}
              </b>
            </div>
          </div>
          {innovation.claims?.length ? (
            <ul className="review-findings">
              {innovation.claims.map((claim) => (
                <li key={claim.id}>
                  <b>{claim.id}</b>
                  <span>
                    {claim.text}
                    {claim.source ? ` · ${claim.source}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {innovation.closest_prior_art?.length ? (
            <details>
              <summary>最近既有工作</summary>
              <ul className="review-findings">
                {innovation.closest_prior_art.map((item, index) => (
                  <li key={`${item.id || "prior"}-${index}`}>
                    <b>{item.claim_id || item.id || "prior"}</b>
                    <span>
                      {item.title || "未命名"}
                      {typeof item.overlap === "number"
                        ? ` · overlap ${item.overlap}`
                        : ""}
                      {item.url ? ` · ${item.url}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {innovation.findings?.length ? (
            <ul className="review-findings">
              {innovation.findings
                .filter((finding) => finding.code !== "claim_scored")
                .map((finding, index) => (
                  <li key={`${finding.code}-${index}`}>
                    <b className={`severity ${finding.severity}`}>{finding.severity}</b>
                    <span>
                      {finding.code}: {finding.message}
                    </span>
                  </li>
                ))}
            </ul>
          ) : null}
        </>
      ) : (
        <Empty text="尚未运行创新性核验。先冻结假设后点击上方按钮。" />
      )}
    </section>
  );
}
function AssurancePanel({
  busy,
  assurance,
  onReload,
}: {
  busy: boolean;
  assurance?: AssuranceEnvelope;
  onReload: () => Promise<void>;
}) {
  if (!assurance) {
    return (
      <section className="assurance-panel">
        <div className="section-command">
          <div>
            <p className="eyebrow">质量封装</p>
            <h3>独立提交门禁</h3>
          </div>
          <button className="icon-button quiet" type="button" title="刷新质量封装" aria-label="刷新质量封装" disabled={busy} onClick={onReload}>
            ↻
          </button>
        </div>
        <Empty text="尚未生成质量封装。运行一次独立审计后刷新。" />
      </section>
    );
  }
  const statusLabel = assurance.status === "PASS" ? "可提交" : assurance.status === "WARN" ? "需复核" : "已阻断";
  return (
    <section className="assurance-panel">
      <div className="section-command">
        <div>
          <p className="eyebrow">质量封装 · {assurance.verifier_version}</p>
          <h3>独立提交门禁</h3>
        </div>
        <div className="inline-actions">
          <span className={`assurance-status ${assurance.status.toLowerCase()}`}>{statusLabel}</span>
          <button className="icon-button quiet" type="button" title="刷新质量封装" aria-label="刷新质量封装" disabled={busy} onClick={onReload}>
            ↻
          </button>
        </div>
      </div>
      <div className="assurance-summary">
        <div><span>提交就绪</span><b>{assurance.submission_ready ? "是" : "否"}</b></div>
        <div><span>独立于生成器</span><b>{assurance.independent_from_generator ? "是" : "否"}</b></div>
        <div><span>门禁</span><b>{assurance.gates.filter((gate) => gate.status === "PASS").length}/{assurance.gates.length} 通过</b></div>
      </div>
      <div className="assurance-gates">
        {assurance.gates.map((gate) => (
          <article key={gate.id} className={`assurance-gate ${gate.status.toLowerCase()}`}>
            <div><b>{gate.label}</b><span>{gate.status}</span></div>
            {gate.findings.length > 0 && <small>{gate.findings.map((finding) => `${finding.code}: ${finding.message}`).join("；")}</small>}
          </article>
        ))}
      </div>
      <div className="assurance-meta">
        <span>项目快照 <code>{assurance.input_hashes.project_snapshot_sha256.slice(0, 16)}</code></span>
        <span>审稿输入 <code>{assurance.input_hashes.latest_review_inputs_sha256?.slice(0, 16) || "无"}</code></span>
        <span>报告 <code>{assurance.input_hashes.review_report_sha256?.slice(0, 16) || "无"}</code></span>
      </div>
      {assurance.findings.length > 0 && (
        <ul className="assurance-findings">
          {assurance.findings.map((finding, index) => (
            <li key={`${finding.code}-${index}`}><b className={`severity ${finding.severity}`}>{finding.severity}</b><span>{finding.code}: {finding.message}</span></li>
          ))}
        </ul>
      )}
      {assurance.repair_actions.length > 0 && (
        <details className="assurance-repairs">
          <summary>修复动作（{assurance.repair_actions.length}）</summary>
          <ul>{assurance.repair_actions.map((repair) => <li key={`${repair.finding_code}-${repair.action}`}><b>{repair.finding_code}</b><span>{repair.action}</span></li>)}</ul>
        </details>
      )}
    </section>
  );
}
type SettingsConnectionProps = {
  busy: boolean;
  doctor?: Record<string, unknown>;
  agentManifest?: Record<string, unknown>;
  project?: Project;
  agentAdapter: string;
  agentPrompt: string;
  agentTasks: AgentTask[];
  collabGoal?: string;
  collaborations?: AgentCollaboration[];
  modelProfiles: ModelProfile[];
  modelProfileTests: Record<string, ModelProfileTest>;
  onReloadDoctor: () => Promise<void>;
  onReloadAgents: () => Promise<void>;
  onAdapterChange: (value: string) => void;
  onPromptChange: (value: string) => void;
  onLaunchAgent: () => Promise<void>;
  onReloadTasks: () => Promise<void>;
  onCancelAgent: (id: string) => Promise<void>;
  onRetryAgent: (id: string) => Promise<void>;
  onCollabGoalChange?: (value: string) => void;
  onLaunchCollaboration?: () => Promise<void>;
  onReloadCollaborations?: () => Promise<void>;
  onReloadProfiles: () => Promise<void>;
  onSaveProfile: (
    role: ModelProfile["role"],
    value: ModelProfileUpdate,
  ) => Promise<void>;
  onTestProfile: (role: ModelProfile["role"]) => Promise<void>;
};
function LegacySettingsConnection({
  busy,
  doctor,
  agentManifest,
  project,
  agentAdapter,
  agentPrompt,
  agentTasks,
  modelProfiles,
  modelProfileTests,
  onReloadDoctor,
  onReloadAgents,
  onAdapterChange,
  onPromptChange,
  onLaunchAgent,
  onReloadTasks,
  onCancelAgent,
  onRetryAgent,
  onReloadProfiles,
  onSaveProfile,
  onTestProfile,
}: SettingsConnectionProps) {
  return (
    <Panel title="设置与连接" detail="">
      <section className="settings-section">
        <div className="section-command">
          <h3>模型档案</h3>
          <button
            className="icon-button quiet"
            type="button"
            title="重新读取模型档案"
            aria-label="重新读取模型档案"
            disabled={busy}
            onClick={onReloadProfiles}
          >
            ↻
          </button>
        </div>
        <ModelProfiles
          profiles={modelProfiles}
          tests={modelProfileTests}
          busy={busy}
          onSave={onSaveProfile}
          onTest={onTestProfile}
        />
      </section>
      <section className="settings-section">
        <div className="section-command">
          <h3>环境诊断</h3>
          <button
            className="icon-button quiet"
            type="button"
            title="重新检测环境"
            aria-label="重新检测环境"
            disabled={busy}
            onClick={onReloadDoctor}
          >
            ↻
          </button>
        </div>
        <div className="diagnostics">
          <article>
            {doctor ? (
              <JsonCard value={doctor} />
            ) : (
              <Empty text="正在读取本机环境。" />
            )}
          </article>
          <article>
            <div className="section-command">
              <h3>Agent 适配器</h3>
              <button
                className="icon-button quiet"
                type="button"
                title="刷新适配器"
                aria-label="刷新适配器"
                disabled={busy}
                onClick={onReloadAgents}
              >
                ↻
              </button>
            </div>
            {agentManifest ? (
              <JsonCard value={agentManifest} />
            ) : (
              <Empty text="正在读取适配器清单。" />
            )}
          </article>
        </div>
      </section>
      <section className="settings-section">
        <h3>Agent 任务</h3>
        <div className="form-grid">
          <label>
            适配器
            <select
              value={agentAdapter}
              onChange={(event) => onAdapterChange(event.target.value)}
            >
              <option value="codex">Codex CLI</option>
              <option value="claude">Claude Code</option>
            </select>
          </label>
          <Field
            label="任务要求"
            value={agentPrompt}
            set={onPromptChange}
            area
            placeholder="描述一个只读、可审计的项目任务"
          />
        </div>
        <div className="actions">
          <button
            disabled={busy || !project || !agentPrompt.trim()}
            onClick={onLaunchAgent}
          >
            启动只读 Agent 任务
          </button>
          <button
            className="quiet"
            disabled={busy || !project}
            onClick={onReloadTasks}
          >
            恢复任务历史
          </button>
        </div>
        {agentTasks.length ? (
          <ol className="results">
            {agentTasks.map((item) => (
              <li key={item.id}>
                <b>
                  {item.adapter} · {statusText(item.status)}
                </b>
                <span>{item.prompt}</span>
                {item.result.final_text && (
                  <pre className="json-card">{item.result.final_text}</pre>
                )}
                {item.failure_reason && <small>{item.failure_reason}</small>}
                <span>
                  生命周期事件 {item.events.length} 条 · CLI 结构化事件{" "}
                  {item.result.structured_events?.length || 0} 条 · 审计文件{" "}
                  {item.audit_path || "等待生成"}
                </span>
                {item.result.artifact_sha256 && (
                  <span>
                    响应 artifact SHA256 {item.result.artifact_sha256} ·{" "}
                    {item.result.artifact_path}
                  </span>
                )}
                <div className="inline-actions">
                  <button
                    className="danger"
                    disabled={busy || !item.cancellable}
                    onClick={() => onCancelAgent(item.id)}
                  >
                    取消
                  </button>
                  <button
                    className="quiet"
                    disabled={
                      busy ||
                      !["failed", "cancelled", "interrupted"].includes(
                        item.status,
                      )
                    }
                    onClick={() => onRetryAgent(item.id)}
                  >
                    重试
                  </button>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <Empty text={project ? "尚无 Agent 任务。" : "请先创建研究合同。"} />
        )}
      </section>
    </Panel>
  );
}
function SettingsConnection({
  busy,
  doctor,
  agentManifest,
  project,
  agentAdapter,
  agentPrompt,
  agentTasks,
  collabGoal,
  collaborations,
  modelProfiles,
  modelProfileTests,
  onReloadDoctor,
  onReloadAgents,
  onAdapterChange,
  onPromptChange,
  onLaunchAgent,
  onReloadTasks,
  onCancelAgent,
  onRetryAgent,
  onCollabGoalChange = () => undefined,
  onLaunchCollaboration = async () => undefined,
  onReloadCollaborations = async () => undefined,
  onReloadProfiles,
  onSaveProfile,
  onTestProfile,
}: SettingsConnectionProps) {
  const collabGoalValue = collabGoal ?? "";
  const collaborationItems = collaborations ?? [];
  return (
    <Panel title="设置与连接" detail="">
      <section className="settings-section">
        <div className="section-command">
          <h3>模型档案</h3>
          <button
            className="icon-button quiet"
            type="button"
            title="重新读取模型档案"
            aria-label="重新读取模型档案"
            disabled={busy}
            onClick={onReloadProfiles}
          >
            ↻
          </button>
        </div>
        <ModelProfiles
          profiles={modelProfiles}
          tests={modelProfileTests}
          busy={busy}
          onSave={onSaveProfile}
          onTest={onTestProfile}
        />
      </section>
      <SettingsExtras busy={busy} />
      <section className="settings-section">
        <div className="section-command">
          <h3>环境诊断</h3>
          <button
            className="icon-button quiet"
            type="button"
            title="重新检测环境"
            aria-label="重新检测环境"
            disabled={busy}
            onClick={onReloadDoctor}
          >
            ↻
          </button>
        </div>
        <div className="diagnostics">
          <article>
            {doctor ? (
              <JsonCard value={doctor} />
            ) : (
              <Empty text="正在读取本机环境。" />
            )}
          </article>
          <article>
            <div className="section-command">
              <h3>智能体适配器</h3>
              <button
                className="icon-button quiet"
                type="button"
                title="刷新智能体适配器"
                aria-label="刷新智能体适配器"
                disabled={busy}
                onClick={onReloadAgents}
              >
                ↻
              </button>
            </div>
            {agentManifest ? (
              <JsonCard value={agentManifest} />
            ) : (
              <Empty text="正在读取智能体适配器清单。" />
            )}
          </article>
        </div>
      </section>
      <section className="settings-section">
        <h3>智能体任务</h3>
        <div className="form-grid">
          <label>
            智能体运行器
            <select
              value={agentAdapter}
              onChange={(event) => onAdapterChange(event.target.value)}
            >
              <option value="codex">Codex CLI</option>
              <option value="claude">Claude Code</option>
            </select>
          </label>
          <Field
            label="任务要求"
            value={agentPrompt}
            set={onPromptChange}
            area
            placeholder="描述一个只读、可审计的项目任务"
          />
        </div>
        <div className="actions">
          <button
            disabled={busy || !project || !agentPrompt.trim()}
            onClick={onLaunchAgent}
          >
            启动只读智能体任务
          </button>
          <button
            className="quiet"
            disabled={busy || !project}
            onClick={onReloadTasks}
          >
            恢复任务历史
          </button>
        </div>
        {agentTasks.length ? (
          <ol className="results">
            {agentTasks.map((item) => (
              <li key={item.id}>
                <b>
                  {item.adapter} · {statusText(item.status)}
                </b>
                <span>{item.prompt}</span>
                {item.result.final_text && (
                  <pre className="json-card">{item.result.final_text}</pre>
                )}
                {item.failure_reason && <small>{item.failure_reason}</small>}
                <span>
                  生命周期事件 {item.events.length} 条 · CLI 结构化事件{" "}
                  {item.result.structured_events?.length || 0} 条 · 审计文件{" "}
                  {item.audit_path || "等待生成"}
                </span>
                {item.result.artifact_sha256 && (
                  <span>
                    响应产物 SHA256 {item.result.artifact_sha256} ·{" "}
                    {item.result.artifact_path}
                  </span>
                )}
                <div className="inline-actions">
                  <button
                    className="danger"
                    disabled={busy || !item.cancellable}
                    onClick={() => onCancelAgent(item.id)}
                  >
                    取消
                  </button>
                  <button
                    className="quiet"
                    disabled={
                      busy ||
                      !["failed", "cancelled", "interrupted"].includes(
                        item.status,
                      )
                    }
                    onClick={() => onRetryAgent(item.id)}
                  >
                    重试
                  </button>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <Empty text={project ? "尚无智能体任务。" : "请先创建研究合同。"} />
        )}
      </section>
      <section className="settings-section">
        <h3>多 Agent 协作</h3>
        <p className="muted">
          按执行模型 → 独立审稿模型 → 科研编辑模型顺序真实调用已配置的 Provider/CLI；
          无密钥时诚实失败并持久化协作报告，不静默降级为成功。
        </p>
        <div className="form-grid">
          <Field
            label="协作目标"
            value={collabGoalValue}
            set={onCollabGoalChange}
            area
            placeholder="描述需要多角色协作的研究目标"
          />
        </div>
        <div className="actions">
          <button
            disabled={busy || !project || !collabGoalValue.trim()}
            onClick={onLaunchCollaboration}
          >
            启动多 Agent 协作
          </button>
          <button
            className="quiet"
            disabled={busy || !project}
            onClick={onReloadCollaborations}
          >
            刷新协作历史
          </button>
        </div>
        {collaborationItems.length ? (
          <ol className="results">
            {collaborationItems.map((item) => (
              <li key={item.id}>
                <b>
                  {statusText(item.status)} · {item.roles.join(" / ")}
                </b>
                <span>{item.goal}</span>
                {item.failure_reason && <small>{item.failure_reason}</small>}
                <span>
                  步骤 {item.steps.length} · 报告 {item.report_path || "等待生成"}
                </span>
                {item.report_sha256 && (
                  <span>报告 SHA256 {item.report_sha256}</span>
                )}
                <ul>
                  {item.steps.map((step, index) => (
                    <li key={`${item.id}-${step.role}-${index}`}>
                      {step.role}: {statusText(step.status)}
                      {step.error ? ` · ${step.error}` : ""}
                      {step.output_sha256 ? ` · out ${step.output_sha256.slice(0, 12)}` : ""}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        ) : (
          <Empty text={project ? "尚无多 Agent 协作记录。" : "请先创建研究合同。"} />
        )}
      </section>
    </Panel>
  );
}

type SettingsMetadata = Record<string, { value?: string; configured?: boolean }>;
function SettingsExtras({ busy }: { busy: boolean }) {
  const [metadata, setMetadata] = useState<SettingsMetadata>({});
  const [theme, setTheme] = useState<ThemePreset>("bright");
  const [custom, setCustom] = useState<ThemeColors>({
    background: "#c7e6c9",
    text: "#1e3524",
    accent: "#2e7d32",
  });
  const [imageKey, setImageKey] = useState("");
  const [imageBaseUrl, setImageBaseUrl] = useState("https://api.openai.com/v1");
  const [imageModel, setImageModel] = useState("gpt-image-1.5");
  const [claudeBin, setClaudeBin] = useState("");
  const [codexBin, setCodexBin] = useState("");
  const [dataDir, setDataDir] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const value = (settings: SettingsMetadata, key: string, fallback = "") =>
    typeof settings[key]?.value === "string" ? settings[key].value! : fallback;
  const load = async () => {
    const [settings, dataLocation] = await Promise.all([
      api<SettingsMetadata>("/api/settings"),
      api<{ data_dir: string; selected_data_dir?: string }>("/api/settings/data-dir"),
    ]);
    setMetadata(settings);
    const nextTheme = value(settings, "theme_preset", "bright") as ThemePreset;
    const validTheme = ["warm", "bright", "bean", "custom"].includes(nextTheme) ? nextTheme : "bright";
    const nextCustom = {
      background: safeThemeColor(value(settings, "theme_background", "#c7e6c9"), "#c7e6c9"),
      text: safeThemeColor(value(settings, "theme_text", "#1e3524"), "#1e3524"),
      accent: safeThemeColor(value(settings, "theme_accent", "#2e7d32"), "#2e7d32"),
    };
    setTheme(validTheme);
    setCustom(nextCustom);
    setImageBaseUrl(value(settings, "gpt_image_base_url", "https://api.openai.com/v1"));
    setImageModel(value(settings, "gpt_image_model_id", "gpt-image-1.5"));
    setClaudeBin(value(settings, "claude_bin"));
    setCodexBin(value(settings, "codex_bin"));
    // The stable desktop pointer is authoritative. A legacy value in a
    // previously selected SQLite database must not switch the UI back again.
    setDataDir(dataLocation.selected_data_dir || dataLocation.data_dir);
    applyTheme(validTheme, nextCustom);
  };
  useEffect(() => {
    load().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, []);

  const previewTheme = (preset: ThemePreset, colors = custom) => {
    setTheme(preset);
    applyTheme(preset, colors);
  };
  const updateCustom = (key: keyof ThemeColors, color: string) => {
    const next = { ...custom, [key]: color };
    setCustom(next);
    if (theme === "custom") applyTheme("custom", next);
  };
  const detectClaude = async () => {
    setMessage("");
    try {
      const result = await api<{ detected: boolean; path?: string }>("/api/settings/detect-claude");
      if (result.detected && result.path) {
        setClaudeBin(result.path);
        setMessage("已检测到 Claude CLI。保存配置后生效。");
      } else setMessage("未检测到 Claude CLI；使用 Responses 执行协议时不需要该路径。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };
  const detectCodex = async () => {
    setMessage("");
    try {
      const result = await api<{ detected: boolean; path?: string }>("/api/settings/detect-codex");
      if (result.detected && result.path) {
        setCodexBin(result.path);
        setMessage("已检测到 Codex CLI。保存配置后生效。");
      } else setMessage("未检测到主机 Codex CLI；安装版仍可使用内置运行时中的 Codex 适配器。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };
  const chooseDataDirectory = async () => {
    setMessage("");
    const chooser = window.electronAPI?.selectDataDirectory;
    if (!chooser) {
      setMessage("数据目录选择仅在桌面版可用。");
      return;
    }
    const selected = await chooser();
    if (!selected.canceled && selected.path) {
      setDataDir(selected.path);
      setMessage("新目录将在重启桌面应用后生效；旧工作流不会自动迁移。");
    }
  };
  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const settings: Record<string, string> = {
        theme_preset: theme,
        theme_background: custom.background,
        theme_text: custom.text,
        theme_accent: custom.accent,
        gpt_image_base_url: imageBaseUrl.trim(),
        gpt_image_model_id: imageModel.trim(),
        claude_bin: claudeBin.trim(),
        codex_bin: codexBin.trim(),
      };
      if (imageKey.trim()) settings.gpt_image_api_key = imageKey.trim();
      if (dataDir.trim())
        await api("/api/settings/data-dir", { method: "PUT", body: JSON.stringify({ data_dir: dataDir.trim() }) });
      await api<{ ok: boolean }>("/api/settings", { method: "PUT", body: JSON.stringify({ settings }) });
      window.localStorage.setItem("vibe-theme-preset", theme);
      window.localStorage.setItem("vibe-theme-custom", JSON.stringify(custom));
      applyTheme(theme, custom);
      setImageKey("");
      await load();
      setMessage("配置已安全保存。API 密钥不会回显到界面或 SQLite。" );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="settings-section settings-extras">
      <div className="section-command">
        <div>
          <p className="eyebrow">界面与本机能力</p>
          <h3>主题和其他配置</h3>
        </div>
        <button type="button" className="quiet" disabled={busy || saving} onClick={() => load().catch(() => {})}>重新读取</button>
      </div>
      <div className="settings-extra-grid">
        <article className="settings-extra-card">
          <h4>主题</h4>
          <div className="theme-options" role="radiogroup" aria-label="界面主题">
            {([['warm', '暖色'], ['bright', '亮白'], ['bean', '豆沙绿'], ['custom', '自定义']] as Array<[ThemePreset, string]>).map(([key, label]) => (
              <button key={key} type="button" role="radio" aria-checked={theme === key} className={`quiet theme-option${theme === key ? " selected" : ""}`} onClick={() => previewTheme(key)}>{label}</button>
            ))}
          </div>
          {theme === "custom" && (
            <div className="theme-color-grid">
              <label>背景色<input type="color" value={custom.background} onChange={(event) => updateCustom("background", event.target.value)} /></label>
              <label>文字色<input type="color" value={custom.text} onChange={(event) => updateCustom("text", event.target.value)} /></label>
              <label>强调色<input type="color" value={custom.accent} onChange={(event) => updateCustom("accent", event.target.value)} /></label>
            </div>
          )}
        </article>
        <article className="settings-extra-card">
          <h4>GPT Image</h4>
          <label>API Key<input type="password" autoComplete="new-password" value={imageKey} onChange={(event) => setImageKey(event.target.value)} placeholder={metadata.gpt_image_api_key?.configured ? "已配置；留空保持不变" : "sk-…"} /></label>
          <label>Base URL<input value={imageBaseUrl} onChange={(event) => setImageBaseUrl(event.target.value)} /></label>
          <label>Model ID<input value={imageModel} onChange={(event) => setImageModel(event.target.value)} /></label>
        </article>
        <article className="settings-extra-card">
          <h4>Claude CLI</h4>
          <label>可执行文件路径<input value={claudeBin} onChange={(event) => setClaudeBin(event.target.value)} placeholder="自动探测或填写 claude.exe 路径" /></label>
          <button type="button" className="quiet" disabled={busy || saving} onClick={detectClaude}>自动探测</button>
          <small>执行者使用 Anthropic 消息协议时调用；Responses 协议使用内置工作区执行器。Claude Code 始终为可选的外部安装。</small>
        </article>
        <article className="settings-extra-card">
          <h4>Codex CLI</h4>
          <label>可执行文件路径<input value={codexBin} onChange={(event) => setCodexBin(event.target.value)} placeholder="自动探测或填写 codex.exe 路径" /></label>
          <button type="button" className="quiet" disabled={busy || saving} onClick={detectCodex}>自动探测</button>
          <small>覆盖主机/PATH 探测结果。安装版优先使用经清单校验的内置 Codex；此处用于源码态与自定义路径。</small>
        </article>
        <article className="settings-extra-card">
          <h4>数据存储位置</h4>
          <label>目录<input value={dataDir} readOnly placeholder="使用桌面应用默认目录" /></label>
          <button type="button" className="quiet" disabled={busy || saving} onClick={chooseDataDirectory}>选择新位置</button>
          <small>更改后需重启；旧工作流不会自动迁移，请手动复制 workspaces。</small>
        </article>
      </div>
      {message && <p className={`settings-message${message.includes("保存") || message.includes("检测到") ? " success" : ""}`}>{message}</p>}
      <div className="workflow-config-actions settings-save-actions">
        <button type="button" disabled={busy || saving} onClick={save}>{saving ? "保存中…" : "保存配置"}</button>
      </div>
    </section>
  );
}

function ModelProfiles({
  profiles,
  tests,
  busy,
  onSave,
  onTest,
}: {
  profiles: ModelProfile[];
  tests: Record<string, ModelProfileTest>;
  busy: boolean;
  onSave: (
    role: ModelProfile["role"],
    value: ModelProfileUpdate,
  ) => Promise<void>;
  onTest: (role: ModelProfile["role"]) => Promise<void>;
}) {
  if (!profiles.length) return <Empty text="正在读取模型档案。" />;
  return (
    <div className="model-profile-grid">
      {profiles.map((profile) => (
        <LocalizedModelProfileEditor
          key={profile.role}
          profile={profile}
          test={tests[profile.role]}
          busy={busy}
          onSave={onSave}
          onTest={onTest}
        />
      ))}
    </div>
  );
}
const MODEL_ROLE_LABELS: Record<ModelProfile["role"], string> = {
  executor: "执行器",
  reviewer: "独立审稿人",
  editor_ai: "科研编辑",
};
function LegacyLocalizedModelProfileEditor({
  profile,
  test,
  busy,
  onSave,
  onTest,
}: {
  profile: ModelProfile;
  test?: ModelProfileTest;
  busy: boolean;
  onSave: (
    role: ModelProfile["role"],
    value: ModelProfileUpdate,
  ) => Promise<void>;
  onTest: (role: ModelProfile["role"]) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ModelProfileUpdate>(() => profile),
    [apiKey, setApiKey] = useState(""),
    [clearKey, setClearKey] = useState(false);
  useEffect(() => {
    setDraft(profile);
    setApiKey("");
    setClearKey(false);
  }, [profile]);
  const update = <K extends keyof ModelProfileUpdate>(
    key: K,
    value: ModelProfileUpdate[K],
  ) => setDraft((current) => ({ ...current, [key]: value }));
  const save = async () => {
    await onSave(profile.role, {
      ...draft,
      api_key: apiKey || undefined,
      clear_api_key: clearKey,
    });
    setApiKey("");
  };
  return (
    <article className="model-profile">
      <header>
        <div>
          <p className="eyebrow">{MODEL_ROLE_LABELS[profile.role]}</p>
          <h4>{profile.name}</h4>
        </div>
        <span
          className={
            profile.api_key_configured
              ? "profile-key configured"
              : "profile-key"
          }
        >
          {profile.api_key_configured ? "密钥已配置" : "未配置密钥"}
        </span>
      </header>
      <div className="profile-fields">
        <label>
          服务商与协议
          <select
            aria-label={`${MODEL_ROLE_LABELS[profile.role]}服务商与协议`}
            value={draft.provider}
            onChange={(event) =>
              update("provider", event.target.value as ModelProfile["provider"])
            }
          >
            <option value="openai_compatible">
              OpenAI 兼容（Chat Completions）
            </option>
            <option value="openai_responses">
              OpenAI Responses（响应协议）
            </option>
            <option value="anthropic_messages">Anthropic Messages 协议</option>
            <option value="gemini_generate_content">
              Gemini GenerateContent 协议
            </option>
          </select>
        </label>
        <Field
          label="服务地址（Base URL）"
          value={draft.base_url}
          set={(value) => update("base_url", value)}
          placeholder="https://share-api.com/v1 或任意 OpenAI 兼容地址"
        />
        <Field
          label="模型 ID"
          value={draft.model_id}
          set={(value) => update("model_id", value)}
          placeholder="模型 ID"
        />
        <label>
          温度
          <input
            type="number"
            min="0"
            max="2"
            step="0.05"
            value={draft.temperature}
            onChange={(event) =>
              update("temperature", Number(event.target.value))
            }
          />
        </label>
        <label>
          Top P
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={draft.top_p}
            onChange={(event) => update("top_p", Number(event.target.value))}
          />
        </label>
        <label>
          最大输出 Token
          <input
            type="number"
            min="1"
            max="32768"
            step="1"
            value={draft.max_tokens}
            onChange={(event) =>
              update("max_tokens", Number(event.target.value))
            }
          />
        </label>
        <label>
          推理强度
          <select
            value={draft.reasoning_effort}
            onChange={(event) =>
              update(
                "reasoning_effort",
                event.target.value as ModelProfile["reasoning_effort"],
              )
            }
          >
            <option value="">不启用</option>
            <option value="minimal">最低</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
          </select>
        </label>
        <label className="wide">
          API 密钥
          <input
            type="password"
            autoComplete="new-password"
            value={apiKey}
            placeholder={
              profile.api_key_configured ? "已配置；留空保留" : "未配置"
            }
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        {profile.api_key_configured && (
          <label className="check-field wide">
            <input
              type="checkbox"
              checked={clearKey}
              onChange={(event) => setClearKey(event.target.checked)}
            />
            清除已保存密钥
          </label>
        )}
      </div>
      <div className="actions">
        <button
          disabled={busy || !draft.base_url.trim() || !draft.model_id.trim()}
          onClick={save}
        >
          保存档案
        </button>
        <button
          className="quiet"
          disabled={busy}
          onClick={() => onTest(profile.role)}
        >
          测试连接
        </button>
      </div>
      {test && (
        <p
          className={`profile-test ${test.ok ? "success" : "failure"}`}
          role="status"
        >
          {test.ok ? "连接成功" : "连接失败"} · {test.message}
        </p>
      )}
    </article>
  );
}
function LocalizedModelProfileEditor({
  profile,
  test,
  busy,
  onSave,
  onTest,
}: {
  profile: ModelProfile;
  test?: ModelProfileTest;
  busy: boolean;
  onSave: (
    role: ModelProfile["role"],
    value: ModelProfileUpdate,
  ) => Promise<void>;
  onTest: (role: ModelProfile["role"]) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ModelProfileUpdate>(() => profile),
    [apiKey, setApiKey] = useState(""),
    [clearKey, setClearKey] = useState(false);
  useEffect(() => {
    setDraft(profile);
    setApiKey("");
    setClearKey(false);
  }, [profile]);
  const update = <K extends keyof ModelProfileUpdate>(
    key: K,
    value: ModelProfileUpdate[K],
  ) => setDraft((current) => ({ ...current, [key]: value }));
  const save = async () => {
    await onSave(profile.role, {
      ...draft,
      api_key: apiKey || undefined,
      clear_api_key: clearKey,
    });
    setApiKey("");
  };
  return (
    <article className="model-profile">
      <header>
        <div>
          <p className="eyebrow">{MODEL_ROLE_LABELS[profile.role]}</p>
          <h4>{profile.name}</h4>
        </div>
        <span
          className={
            profile.api_key_configured
              ? "profile-key configured"
              : "profile-key"
          }
        >
          {profile.api_key_configured ? "密钥已配置" : "未配置密钥"}
        </span>
      </header>
      <div className="profile-fields">
        <label>
          服务商与协议
          <select
            aria-label={`${MODEL_ROLE_LABELS[profile.role]}服务商与协议`}
            value={draft.provider}
            onChange={(event) =>
              update("provider", event.target.value as ModelProfile["provider"])
            }
          >
            <option value="openai_compatible">OpenAI 聊天补全</option>
            <option value="openai_responses">OpenAI 响应协议</option>
            <option value="anthropic_messages">Anthropic 消息协议</option>
            <option value="gemini_generate_content">Gemini 内容生成</option>
          </select>
        </label>
        <Field
          label="服务地址（Base URL）"
          value={draft.base_url}
          set={(value) => update("base_url", value)}
          placeholder="https://share-api.com/v1 或任意 OpenAI 兼容地址"
        />
        <Field
          label="模型 ID"
          value={draft.model_id}
          set={(value) => update("model_id", value)}
          placeholder="模型 ID"
        />
        <label>
          温度
          <input
            type="number"
            min="0"
            max="2"
            step="0.05"
            value={draft.temperature}
            onChange={(event) =>
              update("temperature", Number(event.target.value))
            }
          />
        </label>
        <label>
          Top P
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={draft.top_p}
            onChange={(event) => update("top_p", Number(event.target.value))}
          />
        </label>
        <label>
          最大输出 Token
          <input
            type="number"
            min="1"
            max="32768"
            step="1"
            value={draft.max_tokens}
            onChange={(event) =>
              update("max_tokens", Number(event.target.value))
            }
          />
        </label>
        <label>
          推理强度
          <select
            value={draft.reasoning_effort}
            onChange={(event) =>
              update(
                "reasoning_effort",
                event.target.value as ModelProfile["reasoning_effort"],
              )
            }
          >
            <option value="">不启用</option>
            <option value="minimal">最低</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
          </select>
        </label>
        <label className="wide">
          API 密钥
          <input
            type="password"
            autoComplete="new-password"
            value={apiKey}
            placeholder={
              profile.api_key_configured ? "已配置；留空保留" : "未配置"
            }
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        {profile.api_key_configured && (
          <label className="check-field wide">
            <input
              type="checkbox"
              checked={clearKey}
              onChange={(event) => setClearKey(event.target.checked)}
            />
            清除已保存密钥
          </label>
        )}
      </div>
      <div className="actions">
        <button
          disabled={busy || !draft.base_url.trim() || !draft.model_id.trim()}
          onClick={save}
        >
          保存档案
        </button>
        <button
          className="quiet"
          disabled={busy}
          onClick={() => onTest(profile.role)}
        >
          测试连接
        </button>
      </div>
      {test && (
        <p
          className={`profile-test ${test.ok ? "success" : "failure"}`}
          role="status"
        >
          {test.ok ? "连接成功" : "连接失败"} · {test.message}
        </p>
      )}
    </article>
  );
}
function ModelProfileEditor({
  profile,
  test,
  busy,
  onSave,
  onTest,
}: {
  profile: ModelProfile;
  test?: ModelProfileTest;
  busy: boolean;
  onSave: (
    role: ModelProfile["role"],
    value: ModelProfileUpdate,
  ) => Promise<void>;
  onTest: (role: ModelProfile["role"]) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ModelProfileUpdate>(() => profile),
    [apiKey, setApiKey] = useState(""),
    [clearKey, setClearKey] = useState(false);
  useEffect(() => {
    setDraft(profile);
    setApiKey("");
    setClearKey(false);
  }, [profile]);
  const update = <K extends keyof ModelProfileUpdate>(
    key: K,
    value: ModelProfileUpdate[K],
  ) => setDraft((current) => ({ ...current, [key]: value }));
  const save = async () => {
    await onSave(profile.role, {
      ...draft,
      api_key: apiKey || undefined,
      clear_api_key: clearKey,
    });
    setApiKey("");
  };
  return (
    <article className="model-profile">
      <header>
        <div>
          <p className="eyebrow">{profile.role}</p>
          <h4>{profile.name}</h4>
        </div>
        <span
          className={
            profile.api_key_configured
              ? "profile-key configured"
              : "profile-key"
          }
        >
          {profile.api_key_configured ? "密钥已配置" : "未配置密钥"}
        </span>
      </header>
      <div className="profile-fields">
        <label>
          Provider
          <select
            value={draft.provider}
            onChange={(event) =>
              update("provider", event.target.value as ModelProfile["provider"])
            }
          >
            <option value="openai_compatible">OpenAI-compatible</option>
            <option value="anthropic_messages">Anthropic Messages</option>
            <option value="gemini_generate_content">
              Gemini GenerateContent
            </option>
          </select>
        </label>
        <Field
          label="Base URL"
          value={draft.base_url}
          set={(value) => update("base_url", value)}
          placeholder="https://share-api.com/v1 或任意 OpenAI 兼容地址"
        />
        <Field
          label="模型"
          value={draft.model_id}
          set={(value) => update("model_id", value)}
          placeholder="模型 ID"
        />
        <label>
          温度
          <input
            type="number"
            min="0"
            max="2"
            step="0.05"
            value={draft.temperature}
            onChange={(event) =>
              update("temperature", Number(event.target.value))
            }
          />
        </label>
        <label>
          Top P
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={draft.top_p}
            onChange={(event) => update("top_p", Number(event.target.value))}
          />
        </label>
        <label>
          最大输出 Tokens
          <input
            type="number"
            min="1"
            max="32768"
            step="1"
            value={draft.max_tokens}
            onChange={(event) =>
              update("max_tokens", Number(event.target.value))
            }
          />
        </label>
        <label>
          推理强度
          <select
            value={draft.reasoning_effort}
            onChange={(event) =>
              update(
                "reasoning_effort",
                event.target.value as ModelProfile["reasoning_effort"],
              )
            }
          >
            <option value="">不启用</option>
            <option value="minimal">Minimal</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
        <label className="wide">
          API Key
          <input
            type="password"
            autoComplete="new-password"
            value={apiKey}
            placeholder={
              profile.api_key_configured ? "已配置；留空保留" : "未配置"
            }
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        {profile.api_key_configured && (
          <label className="check-field wide">
            <input
              type="checkbox"
              checked={clearKey}
              onChange={(event) => setClearKey(event.target.checked)}
            />
            清除已保存密钥
          </label>
        )}
      </div>
      <div className="actions">
        <button
          disabled={busy || !draft.base_url.trim() || !draft.model_id.trim()}
          onClick={save}
        >
          保存档案
        </button>
        <button
          className="quiet"
          disabled={busy}
          onClick={() => onTest(profile.role)}
        >
          测试连接
        </button>
      </div>
      {test && (
        <p
          className={`profile-test ${test.ok ? "success" : "failure"}`}
          role="status"
        >
          {test.ok ? "连接成功" : "连接失败"} · {test.message}
        </p>
      )}
    </article>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
