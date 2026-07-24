import React, { useMemo, useState } from "react";

export type WorkflowFileGroup = { role: string; files: File[] };
export type WorkflowDraft = {
  template: string;
  title: string;
  params: Record<string, unknown>;
  enableCheckpoints: boolean;
  autoStart: boolean;
  fileGroups: WorkflowFileGroup[];
  requirementsFile?: File;
};

type Props = {
  template: string;
  templateName: string;
  initialTitle: string;
  busy: boolean;
  onBack: () => void;
  onSubmit: (draft: WorkflowDraft) => Promise<void>;
};

const competitions: Record<
  string,
  { label: string; lang: "zh" | "en"; pages: number }
> = {
  comp_tianfu: { label: "天府杯", lang: "zh", pages: 30 },
  comp_certcup: { label: "认证杯", lang: "zh", pages: 35 },
  comp_mathorcup: { label: "MathorCup", lang: "zh", pages: 30 },
  comp_teddy: { label: "泰迪杯", lang: "zh", pages: 40 },
  comp_huadong: { label: "华东杯", lang: "zh", pages: 30 },
  comp_huazhong: { label: "华中杯", lang: "zh", pages: 30 },
  comp_wuyi: { label: "五一杯", lang: "zh", pages: 30 },
  comp_zhongqing: { label: "中青杯", lang: "zh", pages: 30 },
  comp_yangtze: { label: "长三角", lang: "zh", pages: 30 },
  comp_stats: { label: "统计建模大赛", lang: "zh", pages: 30 },
  comp_shuwei: { label: "数维杯", lang: "zh", pages: 30 },
  comp_diangong: { label: "电工杯", lang: "zh", pages: 30 },
  comp_liaoning: { label: "辽宁省/东三省", lang: "zh", pages: 30 },
  comp_apmcm_zh: { label: "亚太赛中文 (APMCM)", lang: "zh", pages: 25 },
  comp_shenzhen: { label: "深圳杯", lang: "zh", pages: 30 },
  comp_huashu: { label: "华数杯", lang: "zh", pages: 30 },
  comp_cumcm: { label: "国赛 (CUMCM)", lang: "zh", pages: 30 },
  comp_huawei: { label: "华为杯", lang: "zh", pages: 50 },
  comp_mcm: { label: "美赛 (MCM/ICM)", lang: "en", pages: 25 },
  comp_shuwei_en: { label: "数维杯国际赛", lang: "en", pages: 25 },
  comp_apmcm: { label: "亚太 (APMCM)", lang: "en", pages: 25 },
  comp_certcup_en: { label: "小美赛 (认证杯国际)", lang: "en", pages: 25 },
};

const paperTemplates = new Set([
  "paper_writing",
  "paper_writing_zh",
  "nature_writing",
  "humanities_paper",
]);
const documentTemplates = new Set([
  ...paperTemplates,
  "full_pipeline",
  "thesis_proposal",
  "literature_review",
  "course_paper",
  "course_report",
  "paper_from_assets",
  "auto_review",
]);

const defaultParams = (template: string): Record<string, unknown> => {
  if (competitions[template]) {
    const item = competitions[template];
    return {
      output_format: "pdf",
      language: item.lang,
      max_pages: item.pages,
      validation_mode: "strict",
      flowchart_engine: "html",
      figure_style: "default",
      rich_mode: false,
      tools: "python",
      min_figures: "auto",
      min_tables: "auto",
      min_models: "auto",
      require_competition_input: template !== "comp_stats",
    };
  }
  if (template === "grad_project")
    return {
      project_type: "fullstack",
      tech_frontend: "React",
      tech_backend: "FastAPI",
      tech_db: "SQLite",
      tech_lang: "Python",
      design_style: "auto",
      feature_requirements: "",
      skip_report: true,
    };
  if (template === "auto_review")
    return { output_format: "markdown", language: "zh", max_rounds: 4, target_score: 6 };
  if (template === "paper_from_assets")
    return {
      paper_type_target: "academic_zh",
      output_format: "pdf",
      language: "zh",
      flowchart_engine: "html",
    };
  if (template === "paper_slides")
    return {
      language: "en",
      output_format: "pdf",
      talk_minutes: 12,
      aspect_ratio: "16:9",
      latex_engine: "pdflatex",
      include_speaker_notes: true,
      include_pptx: true,
    };
  if (template === "paper_poster")
    return {
      language: "en",
      output_format: "pdf",
      poster_size: "A0",
      orientation: "landscape",
      latex_engine: "pdflatex",
      include_pptx: true,
      include_svg: true,
    };
  if (template === "humanities_paper")
    return {
      output_format: "docx",
      language: "zh",
      subject_domain: "literature",
      word_count_target: 8000,
      skip_figures: true,
      skip_analysis: true,
      skip_drawio: true,
      flowchart_engine: "html",
    };
  if (template === "course_paper" || template === "course_report")
    return {
      output_format: "docx",
      language: "zh",
      subject_domain: "cs",
      word_count_target: template === "course_report" ? 10000 : 8000,
      skip_figures: true,
      skip_analysis: true,
      skip_drawio: false,
      flowchart_engine: "html",
    };
  if (template === "thesis_proposal")
    return {
      output_format: "docx",
      language: "zh",
      degree_level: "master",
      skip_drawio: false,
      flowchart_engine: "html",
    };
  if (template === "literature_review")
    return {
      output_format: "docx",
      language: "zh",
      target_paper_count: 20,
      cn_en_ratio: "1:1",
    };
  if (paperTemplates.has(template) || template === "full_pipeline")
    return {
      language: ["paper_writing", "nature_writing", "full_pipeline"].includes(template) ? "en" : "zh",
      output_format: "pdf",
      paper_type: "journal",
      column_layout: "double",
      TARGET_VENUE: "ICLR",
      max_pages: template === "paper_writing" ? 9 : 15,
      figure_style: template === "nature_writing" ? "nature" : "default",
      outline_mode: "auto",
      skip_figures: false,
      skip_analysis: false,
      skip_drawio: false,
      flowchart_engine: "html",
      ...(template === "full_pipeline" ? { paper_branch: "general" } : {}),
    };
  if (template === "copyright_material" || template === "software_copyright") {
    return { software_version: "V1.0", software_name: "" };
  }
  return {};
};

function Section({
  title,
  detail,
  children,
}: {
  title: string;
  detail?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="workflow-config-section">
      <header>
        <h3>{title}</h3>
        {detail && <p>{detail}</p>}
      </header>
      <div className="workflow-config-fields">{children}</div>
    </section>
  );
}

function InputField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  min,
  max,
  required,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "number";
  min?: number;
  max?: number;
  required?: boolean;
}) {
  return (
    <label className="workflow-config-field">
      <span>{label}</span>
      <input
        className="input"
        type={type}
        value={value}
        min={min}
        max={max}
        required={required}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <label className="workflow-config-field workflow-config-wide">
      <span>{label}</span>
      <textarea
        className="input"
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<[string, string]>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="workflow-config-field">
      <span>{label}</span>
      <select className="input" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([key, text]) => (
          <option key={key} value={key}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

function Toggle({
  label,
  detail,
  value,
  onChange,
}: {
  label: string;
  detail?: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="workflow-toggle">
      <span>
        <strong>{label}</strong>
        {detail && <small>{detail}</small>}
      </span>
      <input type="checkbox" checked={value} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

function FilePicker({
  label,
  detail,
  accept,
  files,
  multiple = true,
  directory = false,
  onChange,
}: {
  label: string;
  detail?: string;
  accept?: string;
  files: File[];
  multiple?: boolean;
  directory?: boolean;
  onChange: (files: File[]) => void;
}) {
  const [dragActive, setDragActive] = useState(false);
  const identity = (file: File) =>
    `${(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
  const add = (incoming: File[]) => {
    const next = multiple ? [...files] : [];
    for (const file of incoming) {
      if (!next.some((item) => identity(item) === identity(file))) next.push(file);
    }
    onChange(next);
  };
  const directoryProps = directory ? ({ webkitdirectory: "", directory: "" } as Record<string, string>) : {};
  return (
    <div className="workflow-file-picker">
      <div>
        <strong>{label}</strong>
        {detail && <small>{detail}</small>}
      </div>
      <div className="workflow-file-actions">
        <label
          className={`workflow-file-drop${dragActive ? " drag-active" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
            setDragActive(true);
          }}
          onDragLeave={(event) => {
            event.preventDefault();
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragActive(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragActive(false);
            add(Array.from(event.dataTransfer.files || []));
          }}
        >
          <input
            type="file"
            accept={accept}
            multiple={multiple}
            onChange={(event) => {
              add(Array.from(event.target.files || []));
              event.currentTarget.value = "";
            }}
          />
          <span>{directory ? "添加文件或拖拽到此处" : "点击选择文件或拖拽到此处"}</span>
        </label>
        {directory && (
          <label className="workflow-file-drop workflow-directory-button">
            <input
              type="file"
              multiple
              {...directoryProps}
              onChange={(event) => {
                add(Array.from(event.target.files || []));
                event.currentTarget.value = "";
              }}
            />
            <span>添加文件夹</span>
          </label>
        )}
      </div>
      {files.length > 0 && (
        <div className="workflow-file-list">
          {files.map((file, index) => (
            <span key={`${identity(file)}-${index}`}>
              {(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}
              <button type="button" onClick={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function WorkflowConfiguration({
  template,
  templateName,
  initialTitle,
  busy,
  onBack,
  onSubmit,
}: Props) {
  // 统一写作入口卡是 paper_writing；默认中文落到 paper_writing_zh，英文/Nature/人文由分支控件切换。
  const initialTemplate = template === "paper_writing" ? "paper_writing_zh" : template;
  const [resolvedTemplate, setResolvedTemplate] = useState(initialTemplate);
  const [title, setTitle] = useState(initialTitle || templateName);
  const [params, setParams] = useState<Record<string, unknown>>(() => defaultParams(initialTemplate));
  const [files, setFiles] = useState<Record<string, File[]>>({});
  const [requirementsFile, setRequirementsFile] = useState<File>();
  const [checkpoints, setCheckpoints] = useState(false);
  const [improvementLoop, setImprovementLoop] = useState(false);
  const [advancedCounts, setAdvancedCounts] = useState({ figures: false, tables: false, models: false });
  const [error, setError] = useState("");

  const competition = competitions[resolvedTemplate];
  const paperBranch = template === "full_pipeline"
    ? String(params.paper_branch || "general")
    : resolvedTemplate === "humanities_paper"
      ? "humanities"
      : resolvedTemplate === "nature_writing"
        ? "nature"
        : "general";
  const isPaper = paperTemplates.has(resolvedTemplate) || resolvedTemplate === "full_pipeline";
  const isHumanities = resolvedTemplate === "humanities_paper" || (template === "full_pipeline" && paperBranch === "humanities");
  const isNature = resolvedTemplate === "nature_writing" || (template === "full_pipeline" && paperBranch === "nature");
  const isCourse = resolvedTemplate === "course_paper" || resolvedTemplate === "course_report";
  const set = (key: string, value: unknown) => setParams((current) => ({ ...current, [key]: value }));
  const fileGroup = (role: string) => files[role] || [];
  const setFileGroup = (role: string, value: File[]) => setFiles((current) => ({ ...current, [role]: value }));
  const templateFiles = fileGroup("templates");
  const visibleImprovement =
    Boolean(competition) ||
    ["paper_writing", "paper_writing_zh", "nature_writing", "full_pipeline", "paper_from_assets"].includes(
      resolvedTemplate,
    );

  const inputSummary = useMemo(
    () =>
      Object.entries(files)
        .filter(([, value]) => value.length > 0)
        .flatMap(([role, value]) => value.map((file) => `${role}:${file.name}`)),
    [files],
  );

  // Keep the primary action disabled until the same required inputs that the
  // submit path will reject are present, and surface the exact reason in the
  // button label.
  const readiness = useMemo(() => {
    const ipTitle =
      resolvedTemplate === "copyright_material" || resolvedTemplate === "software_copyright"
        ? String(params.software_name || "").trim()
        : resolvedTemplate === "patent_disclosure"
          ? String(params.case_name || "").trim()
          : "";
    const cleanTitle = ipTitle || title.trim();
    if (
      (resolvedTemplate === "copyright_material" || resolvedTemplate === "software_copyright") &&
      !String(params.software_name || "").trim()
    ) {
      return { ok: false, reason: "请填写软件名称" };
    }
    if (resolvedTemplate === "patent_disclosure" && !String(params.case_name || "").trim()) {
      return { ok: false, reason: "请填写案件名称" };
    }
    if (resolvedTemplate === "software_copyright" && !fileGroup("source").length && !fileGroup("material").length) {
      return { ok: false, reason: "请上传源代码或产品材料" };
    }
    if (
      competition &&
      resolvedTemplate !== "comp_stats" &&
      !fileGroup("problem").length &&
      !String(params.problem_statement || "").trim()
    ) {
      return { ok: false, reason: "请上传赛题或填写内容" };
    }
    if (resolvedTemplate === "paper_from_assets" && !fileGroup("requirements").length) {
      return { ok: false, reason: "请先上传“题目 / 写作要求”文件" };
    }
    if (
      (resolvedTemplate === "paper_slides" || resolvedTemplate === "paper_poster") &&
      !fileGroup("paper").length
    ) {
      return {
        ok: false,
        reason:
          resolvedTemplate === "paper_slides"
            ? "请先上传已编译论文（paper/main.tex 或 main.pdf）"
            : "请先上传已编译论文（paper/main.tex 或 main.pdf）",
      };
    }
    if (
      !["copyright_material", "software_copyright", "patent_disclosure"].includes(resolvedTemplate) &&
      cleanTitle.length < 2
    ) {
      return { ok: false, reason: "请填写研究课题或工作流标题" };
    }
    return { ok: true, reason: "" };
  }, [competition, files, params, resolvedTemplate, title]);

  const switchPaperBranch = (branch: string) => {
    if (template === "full_pipeline") {
      setResolvedTemplate("full_pipeline");
      if (branch === "nature") {
        setParams((current) => ({
          ...current,
          paper_branch: "nature",
          language: "en",
          figure_style: "nature",
          output_format: "pdf",
        }));
      } else if (branch === "humanities") {
        setParams((current) => ({
          ...current,
          ...defaultParams("humanities_paper"),
          paper_branch: "humanities",
          custom_requirements: current.custom_requirements || "",
        }));
      } else {
        setParams((current) => ({
          ...defaultParams("full_pipeline"),
          paper_branch: "general",
          custom_requirements: current.custom_requirements || "",
        }));
      }
      return;
    }
    if (branch === "nature") {
      setResolvedTemplate("nature_writing");
      setParams((current) => ({ ...current, language: "en", figure_style: "nature", output_format: "pdf" }));
    } else if (branch === "humanities") {
      setResolvedTemplate("humanities_paper");
      setParams(defaultParams("humanities_paper"));
    } else {
      const next = template === "full_pipeline"
        ? "full_pipeline"
        : String(params.language || "zh") === "en"
          ? "paper_writing"
          : "paper_writing_zh";
      setResolvedTemplate(next);
      setParams((current) => ({ ...defaultParams(next), custom_requirements: current.custom_requirements || "" }));
    }
  };

  const changePaperLanguage = (value: string) => {
    setParams((current) => {
      const next: Record<string, unknown> = { ...current, language: value };
      if (template !== "full_pipeline" && !isHumanities && resolvedTemplate !== "nature_writing") {
        if (value === "en") {
          next.paper_type = "journal";
          next.max_pages = String(next.TARGET_VENUE || "ICLR") === "ICML" ? 8 : 9;
        } else {
          next.max_pages = next.paper_type === "master" ? 55 : next.paper_type === "bachelor" ? 25 : 15;
        }
      }
      return next;
    });
    if (!isHumanities && resolvedTemplate !== "nature_writing" && template !== "full_pipeline") {
      setResolvedTemplate(value === "zh" ? "paper_writing_zh" : "paper_writing");
      setFileGroup("templates", []);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const ipTitle =
      resolvedTemplate === "copyright_material" || resolvedTemplate === "software_copyright"
        ? String(params.software_name || "").trim()
        : resolvedTemplate === "patent_disclosure"
          ? String(params.case_name || "").trim()
          : "";
    const cleanTitle = ipTitle || title.trim();
    if (
      !["copyright_material", "software_copyright", "patent_disclosure"].includes(resolvedTemplate) &&
      cleanTitle.length < 2
    ) {
      setError("请填写工作流标题或研究课题");
      return;
    }
    if (competition && resolvedTemplate !== "comp_stats" && !fileGroup("problem").length && !String(params.problem_statement || "").trim()) {
      setError("请上传赛题文件，或在赛题补充说明中粘贴赛题内容");
      return;
    }
    if (resolvedTemplate === "paper_from_assets" && !fileGroup("requirements").length) {
      setError("请先上传“题目 / 写作要求”文件");
      return;
    }
    if (
      (resolvedTemplate === "paper_slides" || resolvedTemplate === "paper_poster") &&
      !fileGroup("paper").length
    ) {
      setError("请先上传已编译论文（paper/main.tex 或 main.pdf，以及 figures/）");
      return;
    }
    if (
      (resolvedTemplate === "copyright_material" || resolvedTemplate === "software_copyright") &&
      !String(params.software_name || "").trim()
    ) {
      setError("请填写软件名称");
      return;
    }
    if (resolvedTemplate === "patent_disclosure" && !String(params.case_name || "").trim()) {
      setError("请填写案件名称");
      return;
    }
    if (
      resolvedTemplate === "software_copyright" &&
      !fileGroup("source").length &&
      !fileGroup("material").length
    ) {
      setError("请先上传源代码、界面截图或现有产品材料");
      return;
    }

    const finalParams: Record<string, unknown> = {
      ...params,
      skip_improvement_loop: !improvementLoop,
      input_groups: inputSummary,
    };
    if (templateFiles.length) {
      finalParams.template_files = templateFiles.map((file) => `user_data/${file.name}`);
      const wordTemplate = templateFiles.find((file) => /\.(docx|dotx)$/i.test(file.name));
      if (wordTemplate) finalParams.template_file = `user_data/${wordTemplate.name}`;
    }
    if (competition) {
      finalParams.competition = resolvedTemplate.replace(/^comp_/, "");
      finalParams.language = competition.lang;
      finalParams.min_figures = advancedCounts.figures ? Number(params.min_figures || 12) : "auto";
      finalParams.min_tables = advancedCounts.tables ? Number(params.min_tables || 4) : "auto";
      finalParams.min_models = advancedCounts.models ? Number(params.min_models || 2) : "auto";
    }
    if (["copyright_material", "software_copyright", "patent_disclosure"].includes(resolvedTemplate))
      finalParams.has_uploaded_materials =
        fileGroup("source").length > 0 || fileGroup("material").length > 0;
    if (resolvedTemplate === "grad_project") {
      const projectType = String(finalParams.project_type || "fullstack");
      if (projectType === "fullstack") delete finalParams.tech_lang;
      if (projectType === "frontend") {
        delete finalParams.tech_backend;
        delete finalParams.tech_db;
        delete finalParams.tech_lang;
      }
      if (["cli", "script"].includes(projectType)) {
        delete finalParams.tech_frontend;
        delete finalParams.tech_backend;
        delete finalParams.tech_db;
        delete finalParams.design_style;
        delete finalParams.design_style_custom;
      }
      if (Boolean(finalParams.skip_report)) delete finalParams.output_format;
    }
    if (String(finalParams.outline_mode || "auto") === "input") finalParams.user_outline = true;
    if (String(finalParams.outline_mode || "auto") === "upload" && fileGroup("outline").length)
      finalParams.user_outline = true;

    await onSubmit({
      template: resolvedTemplate,
      title: cleanTitle,
      params: finalParams,
      enableCheckpoints: checkpoints,
      autoStart: true,
      fileGroups: Object.entries(files)
        .filter(([, value]) => value.length)
        .map(([role, value]) => ({ role, files: value })),
      requirementsFile,
    });
  };

  return (
    <form className="workflow-config" onSubmit={submit}>
      <div className="workflow-config-heading">
        <button type="button" className="quiet" onClick={onBack}>
          ← 返回模板
        </button>
        <div>
          <p className="eyebrow">{competition?.label || templateName}</p>
          <h2>配置并启动工作流</h2>
          <span>所有选项都会持久化到任务参数并控制实际执行步骤。</span>
        </div>
      </div>

      {!["copyright_material", "software_copyright", "patent_disclosure"].includes(resolvedTemplate) && (
        <Section title="基本信息">
          <InputField
            label={resolvedTemplate === "grad_project" ? "项目标题 / 想法" : "研究课题 / 工作流标题"}
            value={title}
            onChange={setTitle}
            required
            placeholder="请尽量具体，避免过于宽泛的主题"
          />
          {(paperTemplates.has(template) || template === "full_pipeline") && (
            <SelectField
              label="论文写作分支"
              value={paperBranch}
              options={[
                ["general", "通用学术"],
                ["nature", "Nature 顶刊"],
                ["humanities", "人文社科"],
              ]}
              onChange={switchPaperBranch}
            />
          )}
        </Section>
      )}

      {competition && (
        <>
          <Section title="竞赛参数" detail="赛事默认值已预设，可按题目要求调整。">
            <SelectField
              label="输出格式"
              value={String(params.output_format)}
              options={[
                ["pdf", "PDF（格式完整）"],
                ["docx", "Word（可二次编辑）"],
                ["latex", "LaTeX（编译为 PDF）"],
              ]}
              onChange={(value) => set("output_format", value)}
            />
            <InputField label={resolvedTemplate === "comp_stats" ? "自拟题目（可选）" : "题号"} value={String(resolvedTemplate === "comp_stats" ? params.custom_title || "" : params.problem_id || "")} placeholder={resolvedTemplate === "comp_stats" ? "输入官方主题或自拟题目" : "例如：A、B、C、D"} onChange={(value) => set(resolvedTemplate === "comp_stats" ? "custom_title" : "problem_id", value)} />
            <SelectField label="审查模式" value={String(params.validation_mode)} options={[["strict", "严格（完整审查）"], ["fast", "快速（省额度）"]]} onChange={(value) => set("validation_mode", value)} />
            <InputField label="页数限制（正文页）" type="number" min={1} max={200} value={Number(params.max_pages)} onChange={(value) => set("max_pages", Number(value))} />
            <SelectField label="流程图引擎" value={String(params.flowchart_engine)} options={[["html", "HTML（推荐）"], ["drawio", "DrawIO（可拖拽修改）"]]} onChange={(value) => set("flowchart_engine", value)} />
            <SelectField label="图表风格" value={String(params.figure_style)} options={[["default", "默认（柔和学术）"], ["nature", "Nature（高影响力期刊）"]]} onChange={(value) => set("figure_style", value)} />
            <SelectField
              label="建模工具"
              value={String(params.tools || "python")}
              options={[
                ["python", "Python（默认）"],
                ["matlab", "MATLAB"],
                ["python+matlab", "Python + MATLAB"],
              ]}
              onChange={(value) => set("tools", value)}
            />
            <Toggle label="丰满模式（华为杯标准）" detail="正文 40-60 页、30+ 图表、候选方法对比、过程式叙述" value={Boolean(params.rich_mode)} onChange={(value) => { set("rich_mode", value); if (value && Number(params.max_pages) < 40) set("max_pages", 40); }} />
          </Section>
          <Section title="高级数量选项" detail="关闭时由 AI 自动规划；开启时指定最低数量。">
            {(["figures", "tables", "models"] as const).map((kind) => {
              const labels = { figures: "图片数量", tables: "表格数量", models: "模型数量" };
                  const defaults = { figures: 12, tables: 4, models: 2 };
                  const maximums = { figures: 200, tables: 100, models: 50 };
              const field = `min_${kind}`;
              return (
                <div className="workflow-count-option" key={kind}>
                  <Toggle label={labels[kind]} value={advancedCounts[kind]} onChange={(value) => setAdvancedCounts((current) => ({ ...current, [kind]: value }))} />
                  {advancedCounts[kind] && <InputField label="至少" type="number" min={0} max={maximums[kind]} value={Number(params[field] === "auto" ? defaults[kind] : params[field] || defaults[kind])} onChange={(value) => set(field, Number(value))} />}
                </div>
              );
            })}
          </Section>
          <Section title="赛题与思路">
            <FilePicker label="上传赛题" detail="仅支持 .docx 或 PDF；系统会读取内容进行分析。" accept=".docx,.pdf" files={fileGroup("problem")} multiple={false} onChange={(value) => setFileGroup("problem", value)} />
            <FilePicker label="赛题图片（可选）" detail="示意图、地图、网络拓扑等关键图片。" accept=".png,.jpg,.jpeg,.webp" files={fileGroup("problem_images")} onChange={(value) => setFileGroup("problem_images", value)} />
            <TextAreaField label="赛题补充说明（可选）" value={String(params.problem_statement || "")} onChange={(value) => set("problem_statement", value)} placeholder="可粘贴赛题文字，或说明选择哪道题、重点关注什么。" />
            <FilePicker label="解题思路 / 大纲文档（可选）" accept=".docx,.md,.markdown,.txt" files={fileGroup("outline")} multiple={false} onChange={(value) => setFileGroup("outline", value)} />
          </Section>
        </>
      )}

      {isPaper && !competition && (
        <Section title={isHumanities ? "人文社科论文参数" : "论文参数"}>
          <SelectField
            label="输出格式"
            value={String(params.output_format)}
            options={isHumanities ? [["docx", "Word（可二次编辑）"], ["latex", "LaTeX（编译为 PDF）"]] : [["pdf", "PDF（格式完整）"], ["docx", "Word（可二次编辑）"]]}
            onChange={(value) => set("output_format", value)}
          />
          <SelectField
            label="论文语言"
            value={String(params.language)}
            options={
              isHumanities
                ? [
                    ["zh", "中文（默认，引用 GB/T 7714）"],
                    ["en", "English（APA / Chicago / MLA）"],
                  ]
                : isNature
                  ? [["en", "English"]]
                  : [
                      ["zh", "中文"],
                      ["en", "English"],
                    ]
            }
            onChange={changePaperLanguage}
          />
          {isHumanities ? (
            <>
              <SelectField label="学科领域" value={String(params.subject_domain)} options={[["literature", "文学 / 比较文学"], ["history", "历史学"], ["philosophy", "哲学"], ["sociology", "社会学"], ["communication", "传播学 / 新闻学"], ["cultural_studies", "文化研究"], ["education", "教育学"], ["law", "法学"], ["art", "艺术学 / 美学"], ["politics", "政治学 / 公共管理"]]} onChange={(value) => set("subject_domain", value)} />
              <InputField label="目标字数" type="number" min={1000} max={200000} value={Number(params.word_count_target)} onChange={(value) => set("word_count_target", Number(value))} />
              <Toggle label="数据图表" detail="默认关闭；开启后执行数据分析并生成统计图。" value={!Boolean(params.skip_figures)} onChange={(value) => { set("skip_figures", !value); set("skip_analysis", !value); }} />
              <Toggle label="理论框架图 / 示意图" detail="默认关闭；开启后生成结构示意图。" value={!Boolean(params.skip_drawio)} onChange={(value) => set("skip_drawio", !value)} />
            </>
          ) : String(params.language) === "zh" ? (
            <>
              <SelectField label="论文类型" value={String(params.paper_type)} options={[["bachelor", "本科毕业论文"], ["master", "硕士学位论文"], ["journal", "期刊论文"]]} onChange={(value) => { set("paper_type", value); set("max_pages", value === "master" ? 55 : value === "bachelor" ? 25 : 15); if (value !== "journal") set("column_layout", "single"); }} />
              <SelectField label="栏数" value={String(params.column_layout)} options={[["single", "单栏"], ["double", "双栏"]]} onChange={(value) => set("column_layout", value)} />
            </>
          ) : (
            <SelectField label="投稿会议" value={String(params.TARGET_VENUE)} options={[["ICLR", "ICLR"], ["NeurIPS", "NeurIPS"], ["ICML", "ICML"]]} onChange={(value) => { set("TARGET_VENUE", value); set("max_pages", value === "ICML" ? 8 : 9); }} />
          )}
          {!isHumanities && (
            <>
              <InputField label="页数限制" type="number" min={1} max={200} value={Number(params.max_pages)} onChange={(value) => set("max_pages", Number(value))} />
              <Toggle label="数据图表生成" detail="规划图表 → 数据分析 → 生成 PDF+PNG → 写作嵌入。" value={!Boolean(params.skip_figures)} onChange={(value) => { set("skip_figures", !value); set("skip_analysis", !value); }} />
              <Toggle label="架构图 / 流程图绘制" detail="规划 fig_arch / fig_flow 并嵌入方法章节。" value={!Boolean(params.skip_drawio)} onChange={(value) => set("skip_drawio", !value)} />
              <SelectField label="图表风格" value={String(params.figure_style)} options={[["default", "默认（柔和学术）"], ["nature", "Nature（高影响力期刊）"]]} onChange={(value) => set("figure_style", value)} />
            </>
          )}
          {!Boolean(params.skip_drawio) && <SelectField label="流程图引擎" value={String(params.flowchart_engine || "html")} options={[["html", "HTML（推荐）"], ["drawio", "DrawIO（可拖拽修改）"]]} onChange={(value) => set("flowchart_engine", value)} />}
        </Section>
      )}

      {isPaper && !isHumanities && !competition && (
        <Section title="论文大纲" detail="已有提纲请放这里，不要混在普通参考素材中。">
          <SelectField label="大纲来源" value={String(params.outline_mode || "auto")} options={[["auto", "自动生成"], ["input", "直接输入"], ["upload", "上传文件"]]} onChange={(value) => set("outline_mode", value)} />
          {params.outline_mode === "input" && <TextAreaField label="论文大纲" value={String(params.user_outline_text || "")} onChange={(value) => set("user_outline_text", value)} rows={8} />}
          {params.outline_mode === "upload" && <FilePicker label="上传大纲文件" accept=".md,.markdown,.txt,.docx,.pdf" files={fileGroup("outline")} multiple={false} onChange={(value) => setFileGroup("outline", value)} />}
        </Section>
      )}

      {(resolvedTemplate === "thesis_proposal" || resolvedTemplate === "literature_review" || isCourse) && (
        <Section title="写作参数">
          {resolvedTemplate === "thesis_proposal" && <SelectField label="学位层次" value={String(params.degree_level)} options={[["undergraduate", "本科"], ["master", "硕士"], ["doctoral", "博士"]]} onChange={(value) => set("degree_level", value)} />}
          {resolvedTemplate === "literature_review" && <><InputField label="目标文献数量" type="number" min={1} max={500} value={Number(params.target_paper_count)} onChange={(value) => set("target_paper_count", Number(value))} /><InputField label="中英文比例" value={String(params.cn_en_ratio)} onChange={(value) => set("cn_en_ratio", value)} placeholder="例如 1:1" /></>}
          {isCourse && <><SelectField label="学科领域" value={String(params.subject_domain)} options={[["cs", "计算机科学"], ["humanities", "人文社科"], ["economics", "经济管理"], ["engineering", "工程技术"]]} onChange={(value) => set("subject_domain", value)} /><InputField label="目标字数" type="number" min={1000} max={200000} value={Number(params.word_count_target)} onChange={(value) => set("word_count_target", Number(value))} /><Toggle label="数据分析与图表" detail="默认禁用，可开启。" value={!Boolean(params.skip_figures)} onChange={(value) => { set("skip_figures", !value); set("skip_analysis", !value); }} /></>}
          {resolvedTemplate !== "literature_review" && <Toggle label="架构图 / 技术路线图" value={!Boolean(params.skip_drawio)} onChange={(value) => set("skip_drawio", !value)} />}
          {!Boolean(params.skip_drawio) && resolvedTemplate !== "literature_review" && <SelectField label="流程图引擎" value={String(params.flowchart_engine || "html")} options={[["html", "HTML（推荐）"], ["drawio", "DrawIO（可拖拽修改）"]]} onChange={(value) => set("flowchart_engine", value)} />}
        </Section>
      )}

      {resolvedTemplate === "paper_from_assets" && (
        <>
          <Section title="第一步：论文类型与格式">
            <SelectField label="目标论文类型" value={String(params.paper_type_target)} options={[["academic_zh", "学术论文（中文）"], ["academic_en", "学术论文（英文）"], ["competition", "竞赛论文（数模 / 认证杯等）"], ["course", "课程论文 / 课程报告"], ["nature", "Nature / SCI 期刊风格"]]} onChange={(value) => { set("paper_type_target", value); set("language", ["academic_en", "nature"].includes(value) ? "en" : "zh"); set("figure_style", value === "nature" ? "nature" : "default"); }} />
            <SelectField label="输出格式" value={String(params.output_format)} options={[["pdf", "PDF（LaTeX）"], ["docx", "Word（docx）"]]} onChange={(value) => set("output_format", value)} />
            <SelectField label="流程图引擎" value={String(params.flowchart_engine)} options={[["html", "HTML（推荐）"], ["drawio", "DrawIO（可拖拽修改）"]]} onChange={(value) => set("flowchart_engine", value)} />
          </Section>
          <Section title="第二步：上传已有资料" detail="有什么传什么；已有内容不会覆盖或重画。">
            <FilePicker label="题目 / 写作要求 *" detail="PDF / MD / TXT / DOCX，描述要写一篇什么论文。" accept=".pdf,.md,.markdown,.txt,.docx" files={fileGroup("requirements")} onChange={(value) => setFileGroup("requirements", value)} />
            <FilePicker label="已有代码" accept=".py,.ipynb,.zip,.js,.ts,.java,.m,.r" files={fileGroup("code")} onChange={(value) => setFileGroup("code", value)} />
            <FilePicker label="数据集" accept=".csv,.xlsx,.xls,.json,.tsv" files={fileGroup("data")} onChange={(value) => setFileGroup("data", value)} />
            <FilePicker label="已画好的图" accept=".png,.jpg,.jpeg,.pdf,.svg" files={fileGroup("figures")} onChange={(value) => setFileGroup("figures", value)} />
            <FilePicker label="实验结果（强烈建议）" accept=".md,.json,.csv,.xlsx" files={fileGroup("results")} onChange={(value) => setFileGroup("results", value)} />
            <FilePicker label="论文模板" detail="可选 .tex/.cls/.docx/.dotx 学刊或赛事指定模板；不传则使用内置模板。" accept=".tex,.cls,.sty,.bst,.bib,.docx,.dotx" files={fileGroup("templates")} onChange={(value) => setFileGroup("templates", value)} />
          </Section>
        </>
      )}

      {(resolvedTemplate === "paper_slides" || resolvedTemplate === "paper_poster") && (
        <>
          <Section
            title={resolvedTemplate === "paper_slides" ? "会议幻灯片参数" : "会议海报参数"}
            detail="基于已编译论文生成报告材料；最终交付 PDF，并可导出可编辑 PPTX。"
          >
            <SelectField
              label="语言"
              value={String(params.language || "en")}
              options={[
                ["en", "English"],
                ["zh", "中文"],
              ]}
              onChange={(value) => {
                set("language", value);
                set("latex_engine", value === "zh" ? "xelatex" : "pdflatex");
              }}
            />
            <SelectField
              label="LaTeX 引擎"
              value={String(params.latex_engine || "pdflatex")}
              options={[
                ["pdflatex", "pdflatex"],
                ["xelatex", "xelatex（中文推荐）"],
              ]}
              onChange={(value) => set("latex_engine", value)}
            />
            {resolvedTemplate === "paper_slides" ? (
              <>
                <InputField
                  label="报告时长（分钟）"
                  type="number"
                  min={3}
                  max={60}
                  value={Number(params.talk_minutes || 12)}
                  onChange={(value) => set("talk_minutes", Number(value))}
                />
                <SelectField
                  label="幻灯片比例"
                  value={String(params.aspect_ratio || "16:9")}
                  options={[
                    ["16:9", "16:9 宽屏"],
                    ["4:3", "4:3 标准"],
                  ]}
                  onChange={(value) => set("aspect_ratio", value)}
                />
                <Toggle
                  label="演讲者备注"
                  detail="在 Beamer 与 PPTX 中保留 \note / notes。"
                  value={Boolean(params.include_speaker_notes)}
                  onChange={(value) => set("include_speaker_notes", value)}
                />
              </>
            ) : (
              <>
                <SelectField
                  label="海报尺寸"
                  value={String(params.poster_size || "A0")}
                  options={[
                    ["A0", "A0"],
                    ["A1", "A1"],
                  ]}
                  onChange={(value) => set("poster_size", value)}
                />
                <SelectField
                  label="方向"
                  value={String(params.orientation || "landscape")}
                  options={[
                    ["landscape", "横向"],
                    ["portrait", "纵向"],
                  ]}
                  onChange={(value) => set("orientation", value)}
                />
                <Toggle
                  label="导出 SVG"
                  detail="在 PDF 定稿后额外导出可编辑 SVG。"
                  value={Boolean(params.include_svg)}
                  onChange={(value) => set("include_svg", value)}
                />
              </>
            )}
            <Toggle
              label="导出可编辑 PPTX"
              detail="使用 python-pptx 生成可二次编辑的 PowerPoint。"
              value={Boolean(params.include_pptx)}
              onChange={(value) => set("include_pptx", value)}
            />
            <TextAreaField
              label="额外要求（可选）"
              value={String(params.custom_requirements || "")}
              onChange={(value) => set("custom_requirements", value)}
              placeholder={
                resolvedTemplate === "paper_slides"
                  ? "例如：强调方法对比、控制在 10 页、保留 Q&A 页。"
                  : "例如：突出主结果图、压缩背景文字、保留贡献列表。"
              }
              rows={4}
            />
          </Section>
          <Section
            title="上传已编译论文 *"
            detail="需要 paper/main.tex 或 paper/main.pdf，以及 figures/。可上传整个 paper 目录或压缩包。"
          >
            <FilePicker
              label="论文源文件 / 目录 / 压缩包 *"
              detail="至少包含 main.tex 或 main.pdf；建议连同 figures 一并上传。"
              accept=".tex,.pdf,.zip,.png,.jpg,.jpeg,.svg,.bib"
              files={fileGroup("paper")}
              directory
              onChange={(value) => setFileGroup("paper", value)}
            />
          </Section>
        </>
      )}

      {resolvedTemplate === "grad_project" && (
        <Section title="项目参数">
          <SelectField label="项目类型" value={String(params.project_type)} options={[["fullstack", "全栈 Web 应用"], ["frontend", "纯前端页面"], ["cli", "命令行工具"], ["script", "Python 脚本"]]} onChange={(value) => set("project_type", value)} />
          {["fullstack", "frontend"].includes(String(params.project_type)) && <SelectField label="前端框架" value={String(params.tech_frontend)} options={[["React", "React"], ["Vue", "Vue"], ["HTML", "纯 HTML + JS"]]} onChange={(value) => set("tech_frontend", value)} />}
          {params.project_type === "fullstack" && <><SelectField label="后端框架" value={String(params.tech_backend)} options={[["FastAPI", "FastAPI"], ["Flask", "Flask"], ["Node-Express", "Node-Express"]]} onChange={(value) => set("tech_backend", value)} /><SelectField label="数据库" value={String(params.tech_db)} options={[["SQLite", "SQLite"], ["MySQL", "MySQL"]]} onChange={(value) => set("tech_db", value)} /></>}
          {["cli", "script"].includes(String(params.project_type)) && <SelectField label="编程语言" value={String(params.tech_lang)} options={[["Python", "Python"], ["Node", "Node"]]} onChange={(value) => set("tech_lang", value)} />}
          {["fullstack", "frontend"].includes(String(params.project_type)) && <SelectField label="设计风格" value={String(params.design_style)} options={[["auto", "系统自动"], ["minimal", "极简专业"], ["tech", "科技感"], ["colorful", "活泼多彩"], ["elegant", "优雅留白"], ["retro", "复古"], ["custom", "自定义"]]} onChange={(value) => set("design_style", value)} />}
          {params.design_style === "custom" && <InputField label="自定义设计风格" value={String(params.design_style_custom || "")} onChange={(value) => set("design_style_custom", value)} />}
          <TextAreaField label="功能需求（可选）" value={String(params.feature_requirements || "")} onChange={(value) => set("feature_requirements", value)} placeholder="一行一个功能；留空则由 AI 根据项目想法自动拆解。" />
          <TextAreaField label="自定义要求（可选）" value={String(params.custom_requirements || "")} onChange={(value) => set("custom_requirements", value)} placeholder="额外约束、技术偏好或验收要求；可与功能清单叠加。" rows={4} />
          <Toggle label="输出项目报告" detail="额外生成含需求、设计、实现和测试的毕设 / 技术报告。" value={!Boolean(params.skip_report)} onChange={(value) => { set("skip_report", !value); if (value && !params.output_format) set("output_format", "pdf"); }} />
          {!Boolean(params.skip_report) && <SelectField label="报告格式" value={String(params.output_format || "pdf")} options={[["pdf", "PDF"], ["docx", "Word"]]} onChange={(value) => set("output_format", value)} />}
        </Section>
      )}

      {(resolvedTemplate === "copyright_material" ||
        resolvedTemplate === "software_copyright" ||
        resolvedTemplate === "patent_disclosure") && (
        <Section
          title={
            resolvedTemplate === "software_copyright"
              ? "软件著作权材料（代码清点）"
              : resolvedTemplate === "copyright_material"
                ? "软著申请资料参数"
                : "专利交底书参数"
          }
          detail={
            resolvedTemplate === "software_copyright"
              ? "扫描真实代码与截图，生成说明书、代码索引与申请清单四件套。"
              : "起草后会在检查点暂停，确认要点后再生成正式成品。"
          }
        >
          {resolvedTemplate === "copyright_material" || resolvedTemplate === "software_copyright" ? (
            <>
              <InputField
                label="软件名称 *"
                value={String(params.software_name || "")}
                onChange={(value) => set("software_name", value)}
                placeholder="完整、规范的软件名称"
                required
              />
              <InputField
                label="版本号"
                value={String(params.software_version || "V1.0")}
                onChange={(value) => set("software_version", value)}
              />
            </>
          ) : (
            <InputField
              label="案件名称 *"
              value={String(params.case_name || "")}
              onChange={(value) => set("case_name", value)}
              placeholder="一种基于……的方法及系统"
              required
            />
          )}
          <TextAreaField
            label={
              resolvedTemplate === "patent_disclosure"
                ? "技术描述 / 交底要点（可选）"
                : "软件描述 / 额外要求（可选）"
            }
            value={String(params.custom_requirements || "")}
            onChange={(value) => set("custom_requirements", value)}
            rows={7}
          />
          <FilePicker
            label={
              resolvedTemplate === "software_copyright"
                ? "上传源代码 / 界面截图 / 产品材料 *"
                : "上传真实材料（可选）"
            }
            detail="可选单文件、多文件或整个文件夹。"
            files={fileGroup("source")}
            directory
            onChange={(value) => setFileGroup("source", value)}
          />
        </Section>
      )}

      {resolvedTemplate === "auto_review" && (
        <Section title="审稿循环参数">
          <SelectField label="输出格式" value={String(params.output_format)} options={[["markdown", "Markdown"], ["docx", "Word（docx）"], ["pdf", "PDF"]]} onChange={(value) => set("output_format", value)} />
          <SelectField label="审稿 / 改写语言" value={String(params.language)} options={[["zh", "中文（默认）"], ["en", "English"]]} onChange={(value) => set("language", value)} />
          <InputField label="最大轮数" type="number" min={1} max={12} value={Number(params.max_rounds)} onChange={(value) => set("max_rounds", Number(value))} />
          <InputField label="目标分数 ≥" type="number" min={1} max={10} value={Number(params.target_score)} onChange={(value) => set("target_score", Number(value))} />
        </Section>
      )}

      {documentTemplates.has(resolvedTemplate) || competition ? (
        <Section title="格式、要求与模板">
          <TextAreaField label={resolvedTemplate === "auto_review" ? "自定义评审标准（可选）" : "自定义要求（可选）"} value={String(params.custom_requirements || "")} onChange={(value) => set("custom_requirements", value)} placeholder="作为最高优先级指令贯穿全流程。" />
          <FilePicker label="上传要求文档（可选）" detail="Word / PDF 会自动转为纯文本并写入 CUSTOM_REQUIREMENTS.md。" accept=".docx,.pdf,.md,.markdown,.txt,.tex" files={requirementsFile ? [requirementsFile] : []} multiple={false} onChange={(value) => setRequirementsFile(value[0])} />
          {(resolvedTemplate !== "auto_review" || ["docx", "pdf"].includes(String(params.output_format))) && <FilePicker label={resolvedTemplate === "auto_review" && params.output_format === "docx" ? "Word 模板（可选）" : "格式模板（可选）"} detail={resolvedTemplate === "auto_review" && params.output_format === "pdf" ? "上传 .tex/.cls/.sty 源模板；未提供时将按可用能力降级。" : "Word 实物模板或 LaTeX 模板套件，可多选。"} accept={resolvedTemplate === "auto_review" && params.output_format === "docx" ? ".docx,.dotx" : resolvedTemplate === "auto_review" && params.output_format === "pdf" ? ".tex,.cls,.sty,.bst,.bib" : ".docx,.dotx,.tex,.cls,.sty,.bst,.bib"} files={templateFiles} onChange={(value) => setFileGroup("templates", value)} />}
          <TextAreaField label="文字格式要求（可选）" value={String(params.format_text || "")} onChange={(value) => set("format_text", value)} placeholder="例如：正文小四宋体，1.5 倍行距，首行缩进 2 字符；一级标题三号黑体居中。" />
        </Section>
      ) : null}

      {!competition &&
        !["copyright_material", "software_copyright", "patent_disclosure", "paper_slides", "paper_poster"].includes(
          resolvedTemplate,
        ) && (
        <Section title="上传资料（可选）" detail="只上传必要的真实材料，避免无关文件增大上下文。">
          <FilePicker label="参考材料 / 数据 / 代码 / 图片" files={fileGroup("material")} accept=".md,.txt,.csv,.xlsx,.json,.py,.ipynb,.tex,.bib,.pdf,.docx,.png,.jpg,.jpeg,.svg,.zip" onChange={(value) => setFileGroup("material", value)} />
        </Section>
      )}
      {competition && <Section title="上传附件数据"><FilePicker label="赛题附带数据与材料" accept=".md,.txt,.csv,.xlsx,.json,.py,.tex,.bib,.pdf,.docx,.png,.jpg,.jpeg,.zip" files={fileGroup("data")} onChange={(value) => setFileGroup("data", value)} /></Section>}

      <Section title="参数设置">
        <Toggle label="人工检查点" detail={resolvedTemplate === "grad_project" ? "需求分析、系统设计后暂停，确认后再继续。" : "关键步骤完成后暂停，可预览产出并提交修改意见。"} value={checkpoints} onChange={setCheckpoints} />
        {visibleImprovement && <Toggle label="论文改进循环" detail="编译后自动审稿 → 修改 → 重编译（2 轮）。" value={improvementLoop} onChange={setImprovementLoop} />}
      </Section>

      {(error || (!readiness.ok && !busy)) && (
        <div className="workflow-config-error">{error || readiness.reason}</div>
      )}
      <div className="workflow-config-actions">
        <button type="button" className="quiet" onClick={onBack} disabled={busy}>
          取消
        </button>
        <button type="submit" disabled={busy || !readiness.ok} title={readiness.ok ? undefined : readiness.reason}>
          {busy ? "创建中…" : readiness.ok ? "创建并启动" : readiness.reason}
        </button>
      </div>
    </form>
  );
}
