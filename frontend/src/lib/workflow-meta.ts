/** Workflow display metadata shared across pages. */

export const workflowNames: Record<string, string> = {
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

export const workflowInputRequirements: Record<string, string> = {
  paper_from_assets: "请先上传论文素材、数据或已有文稿。",
  paper_slides: "请先上传已编译论文目录（paper/main.tex 或 main.pdf，以及 figures/）。",
  paper_poster: "请先上传已编译论文目录（paper/main.tex 或 main.pdf，以及 figures/）。",
  software_copyright: "请先上传源代码、界面截图或现有产品材料。",
};
