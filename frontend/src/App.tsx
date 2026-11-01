import { useState, useEffect, useRef, useCallback } from "react";
import {
  Aperture,
  LayoutGrid,
  ScanLine,
  Layers,
  History,
  Settings,
  Upload,
  Plus,
  Search,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  MousePointer2,
  SquareDashed,
  Hand,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Undo2,
  Redo2,
  Trash2,
  Check,
  CheckCheck,
  Sparkles,
  FolderOpen,
  ArrowUpRight,
  Download,
  SlidersHorizontal,
  Loader2,
  X,
  PanelRightClose,
  ShieldCheck,
  ImagePlus,
  Info,
  AlertCircle,
  Leaf,
  Cat,
  Box as BoxIcon,
  FileCheck2,
  Command,
  Filter,
  MoreHorizontal,
  RotateCw,
  FlipHorizontal,
  RefreshCw,
  ExternalLink,
} from "lucide-react";
import { api, imageUrl, setToken } from "./api";
import type { Bootstrap, Asset, Box, Detail, Job } from "./types";
import { states } from "./types";
import AnnotationCanvas from "./AnnotationCanvas";

type Tab = "workbench" | "dataset" | "tasks";
type Modal =
  | "create"
  | "projects"
  | "import"
  | "ai"
  | "settings"
  | "process"
  | "categories"
  | null;
export default function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [current, setCurrent] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<Tab>("workbench");
  const [modal, setModal] = useState<Modal>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [category, setCategory] = useState("");
  const [selectedBox, setSelectedBox] = useState("");
  const [draw, setDraw] = useState(false);
  const [panMode, setPanMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [zoom, setZoom] = useState(1);
  const [zoomAction, setZoomAction] = useState({ type: "fit", nonce: 0 });
  const [consent, setConsent] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [name, setName] = useState("自然万物 · 图片数据集");
  const [folder, setFolder] = useState("");
  const [baseUrl, setBaseUrl] = useState(
    "https://chat.ecnu.edu.cn/open/api/v1",
  );
  const [model, setModel] = useState("ecnu-max");
  const [key, setKey] = useState("");
  const [ratio, setRatio] = useState(0.8);
  const [seed, setSeed] = useState(42);
  const [exports, setExports] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [format, setFormat] = useState("yolo");
  const [quality, setQuality] = useState<any>(null);
  const [operation, setOperation] = useState("flip_h");
  const [edge, setEdge] = useState(1280);
  const [newCat, setNewCat] = useState("");
  const [newCatExport, setNewCatExport] = useState("");
  const [hidden, setHidden] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const lastJob = useRef("");
  const detailRequest = useRef(0);
  const refresh = useCallback(async () => {
    const d = await api<Bootstrap>("/bootstrap");
    setToken(d.client_token);
    setData(d);
    setBaseUrl(d.vision.base_url);
    setModel(d.vision.model);
    return d;
  }, []);
  const loadDetail = useCallback(async (id: string) => {
    const seq = ++detailRequest.current;
    if (!id) {
      setDetail(null);
      return;
    }
    const d = await api<Detail>(`/assets/${id}`);
    if (seq === detailRequest.current) setDetail(d);
  }, []);
  function notify(text: string) {
    setToast(text);
    window.setTimeout(() => setToast(""), 4500);
  }
  async function perform(action: () => Promise<any>) {
    try {
      setError("");
      return await action();
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [refresh]);
  useEffect(() => {
    if (!data) return;
    const visible = data.assets.filter(
      (a) =>
        (!search ||
          a.display_name.toLowerCase().includes(search.toLowerCase())) &&
        (!statusFilter || a.state === statusFilter),
    );
    if (!visible.some((a) => a.id === current))
      setCurrent(visible[0]?.id || "");
    setSelection(
      (old) =>
        new Set([...old].filter((id) => visible.some((a) => a.id === id))),
    );
    if (!category || !data.categories.some((c) => c.id === category))
      setCategory(data.categories[0]?.id || "");
  }, [data?.assets, search, statusFilter, data?.categories]);
  useEffect(() => {
    setSelectedBox("");
    setHidden(false);
    loadDetail(current).catch((e) => setError(e.message));
  }, [current, loadDetail]);
  useEffect(() => {
    if (!modal) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href],textarea",
        ) || [],
      );
    focusable()[0]?.focus();
    const contain = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setModal(null);
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = focusable(),
        first = nodes[0],
        last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", contain);
    return () => {
      document.removeEventListener("keydown", contain);
      previous?.focus();
    };
  }, [modal]);
  const busy = data?.job?.status === "running";
  const job = data?.job;
  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => {
      refresh().catch((e) => setError(e.message));
    }, 650);
    return () => clearInterval(id);
  }, [busy, refresh]);
  useEffect(() => {
    if (
      !job ||
      job.status === "running" ||
      lastJob.current === job.id + job.status
    )
      return;
    lastJob.current = job.id + job.status;
    if (job.kind === "扫描文件夹" && job.status === "success")
      setModal("import");
    if (job.kind === "质量检查") setQuality(job.result);
    if (job.kind === "导出与独立校验") api<any[]>("/exports").then(setExports);
    if (current) loadDetail(current);
    if (job.error) setError(job.error);
    else if (job.status === "partial_failure" || job.status === "failed")
      setError("部分图片处理失败，请在任务记录查看详情");
    else if (job.status === "success") notify(`${job.kind}已完成`);
  }, [job?.id, job?.status]);
  useEffect(() => {
    if (tab === "dataset" && data?.project)
      api<any[]>("/exports").then(setExports);
    if (tab === "tasks" && data?.project) api<any[]>("/tasks").then(setTasks);
  }, [tab, data?.project?.id, job?.status]);
  const visible =
    data?.assets.filter(
      (a) =>
        (!search ||
          a.display_name.toLowerCase().includes(search.toLowerCase())) &&
        (!statusFilter || a.state === statusFilter),
    ) || [];
  const asset = detail?.asset.id === current ? detail.asset : null;
  const boxes = asset ? detail!.boxes : [];
  const selected = selection.size ? [...selection] : current ? [current] : [];
  const reviewed = (data?.counts.reviewed || 0) + (data?.counts.negative || 0);
  const total =
    data?.assets.filter((a) => !["excluded", "error"].includes(a.state))
      .length || 0;
  const hiddenIds = new Set(
    hidden
      ? boxes.filter((b) => b.category_id !== category).map((b) => b.id)
      : [],
  );
  async function commit(next: Box[]) {
    if (!asset || saving || busy) return;
    setSaving(true);
    await perform(async () => {
      const d = await api<Detail>(`/assets/${asset.id}/boxes`, "PUT", {
        revision: asset.revision,
        boxes: next,
      });
      setDetail(d);
      await refresh();
    });
    setSaving(false);
  }
  async function undo(redo = false) {
    if (!asset || saving || busy) return;
    await perform(async () => {
      setDetail(await api(`/assets/${asset.id}/undo?redo=${redo}`, "POST", {}));
      await refresh();
    });
  }
  async function review() {
    if (!asset) return;
    if (hiddenIds.size) {
      setError("当前有隐藏框，请先显示全部检测框再复核");
      return;
    }
    if (
      !boxes.length &&
      !window.confirm("已查看整张图片，确认没有需要标注的目标？")
    )
      return;
    await perform(async () => {
      setDetail(
        await api(
          `/assets/${asset.id}/review?negative_confirmed=${!boxes.length}`,
          "POST",
          {},
        ),
      );
      await refresh();
      notify(boxes.length ? "图片已完成复核" : "已确认无目标样本");
    });
  }
  function changeCurrent(id: string) {
    if (!saving) {
      setCurrent(id);
      setSelection(new Set());
    }
  }
  function navigate(delta: number) {
    const i = visible.findIndex((a) => a.id === current);
    const next = visible[Math.max(0, Math.min(visible.length - 1, i + delta))];
    if (next) changeCurrent(next.id);
  }
  function zoomBy(type: string) {
    setZoomAction({ type, nonce: Date.now() });
  }
  async function start(path: string, body: any) {
    await perform(async () => {
      await api(path, "POST", body);
      setModal(null);
      setConsent(false);
      await refresh();
    });
  }
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        (e.target as HTMLElement)?.closest(
          "input,textarea,select,[contenteditable=true]",
        ) ||
        modal ||
        saving ||
        busy
      )
        return;
      if (e.key.toLowerCase() === "w") {
        setDraw(true);
        setPanMode(false);
        e.preventDefault();
      }
      if (e.key === "Escape") {
        setDraw(false);
        setPanMode(false);
        setSelectedBox("");
      }
      if (e.key.toLowerCase() === "v") {
        setDraw(false);
        setPanMode(false);
      }
      if (e.key.toLowerCase() === "a") navigate(-1);
      if (e.key.toLowerCase() === "d") navigate(1);
      if (e.key.toLowerCase() === "f") zoomBy("fit");
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        review();
        e.preventDefault();
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        undo(e.shiftKey);
        e.preventDefault();
      }
      if ((e.key === "Delete" || e.key === "Backspace") && selectedBox) {
        commit(boxes.filter((b) => b.id !== selectedBox));
        setSelectedBox("");
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [asset, boxes, selectedBox, modal, saving, busy, hidden]);
  async function filesChosen(files: FileList | null) {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    await start("/import/upload", form);
    if (input.current) input.current.value = "";
  }
  async function createProject() {
    await perform(async () => {
      await api("/projects", "POST", { name });
      await api("/categories/template", "POST", {});
      setCurrent("");
      await refresh();
      setModal(null);
      notify("项目已创建，开始导入你的图片");
    });
  }
  function openModal(value: Modal) {
    setError("");
    setConsent(false);
    setModal(value);
  }
  const currentCategory = data?.categories.find((c) => c.id === category);
  const sourceName = (b: Box) =>
    b.source === "vision"
      ? "视觉建议"
      : b.source === "model"
        ? "本地检测"
        : "人工标注";
  if (!data)
    return (
      <div className="loading-page">
        <Aperture size={34} />
        <p>{error || "正在打开本地工作台…"}</p>
      </div>
    );
  return (
    <div className="app-shell">
      <nav className="rail" aria-label="主导航">
        <button
          className="brand-mark"
          title="图枢"
          onClick={() => setTab("workbench")}
        >
          <Aperture size={29} />
        </button>
        <div className="rail-main">
          {(
            [
              { id: "workbench", icon: ScanLine, label: "标注工作台" },
              { id: "dataset", icon: Layers, label: "数据集" },
              { id: "tasks", icon: History, label: "任务记录" },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? "rail-button active" : "rail-button"}
              aria-label={item.label}
              title={item.label}
              onClick={() => setTab(item.id)}
            >
              <item.icon size={22} />
              <span>
                {item.label.replace("工作台", "").replace("记录", "")}
              </span>
            </button>
          ))}
        </div>
        <button
          className="rail-button"
          title="模型与设置"
          onClick={() => openModal("settings")}
        >
          <Settings size={21} />
          <span>设置</span>
        </button>
        <div className="local-avatar" title="本地工作空间">
          本地
        </div>
      </nav>
      <div className="main-shell">
        <header className="topbar">
          <div className="product-wordmark">
            图枢<span>图像标注工作台</span>
          </div>
          <span className="top-divider" />
          <button
            className="project-switch"
            onClick={() => openModal("projects")}
          >
            <FolderOpen size={16} />
            {data.project?.name || "选择项目"}
            <ChevronDown size={14} />
          </button>
          <div className="topbar-end">
            <span className="local-indicator">
              <span />
              本地工作空间
            </span>
            <button
              className="icon-button"
              title="模型与设置"
              onClick={() => openModal("settings")}
            >
              <Settings size={17} />
            </button>
            <span className="version-tag">V1.1</span>
          </div>
        </header>
        <main className="workspace">
          <section className="page-heading">
            <div>
              <h1>
                {tab === "workbench"
                  ? "标注工作台"
                  : tab === "dataset"
                    ? "数据集管理"
                    : "任务记录"}
              </h1>
              <p>
                {tab === "workbench"
                  ? "从一张图片开始，让每个目标都有清晰的归属。"
                  : tab === "dataset"
                    ? "检查标注质量，按同源组划分并导出可追溯的数据集。"
                    : "查看每次处理的进度、结果与失败原因。"}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button"
                disabled={!data.project || busy}
                onClick={() => openModal("import")}
              >
                <Upload size={16} />
                导入图片
              </button>
              <button
                className="button primary"
                disabled={!data.project || !selected.length || busy}
                onClick={() => openModal("ai")}
              >
                <Sparkles size={16} />
                AI 视觉辅助
              </button>
            </div>
          </section>
          {error && (
            <div role="alert" className="error-banner">
              <AlertCircle size={17} />
              <span>{error}</span>
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label="关闭错误"
              >
                <X size={16} />
              </button>
            </div>
          )}
          {!data.project ? (
            <section className="welcome">
              <div className="welcome-symbol">
                <ScanLine size={42} />
              </div>
              <h2>把图片，整理成可靠的数据</h2>
              <p>
                批量处理图片，结合本地检测与视觉模型生成候选，
                <br />
                逐图复核，导出 YOLO 或 COCO 标注数据集。
              </p>
              <button
                className="button primary"
                onClick={() => openModal("create")}
              >
                <Plus size={17} />
                新建第一个项目
              </button>
              {data.projects.length > 0 && (
                <button
                  className="text-button"
                  onClick={() => openModal("projects")}
                >
                  打开已有项目 <ArrowUpRight size={15} />
                </button>
              )}
              <div className="welcome-workflow">
                <span>导入图片</span>
                <ChevronRight size={15} />
                <span>辅助标注</span>
                <ChevronRight size={15} />
                <span>人工复核</span>
                <ChevronRight size={15} />
                <span>验证导出</span>
              </div>
            </section>
          ) : (
            <>
              {tab === "workbench" && (
                <>
                  <div className="overview-strip">
                    <span>
                      <span className="dot neutral" />
                      全部图片 <strong>{data.assets.length}</strong>
                    </span>
                    <span>
                      <span className="dot purple" />
                      待复核{" "}
                      <strong>
                        {(data.counts.pending || 0) +
                          (data.counts.predicted || 0)}
                      </strong>
                    </span>
                    <span>
                      <span className="dot green" />
                      已复核 <strong>{reviewed}</strong>
                    </span>
                    <span className="overview-progress">
                      <span className="progress-track">
                        <i
                          style={{
                            width: `${total ? (reviewed / total) * 100 : 0}%`,
                          }}
                        />
                      </span>
                      <small>
                        {total ? Math.round((reviewed / total) * 100) : 0}% 完成
                      </small>
                    </span>
                    <button
                      className="text-button"
                      onClick={() => openModal("categories")}
                    >
                      管理类别 <ArrowUpRight size={14} />
                    </button>
                  </div>
                  <section className="editor-grid">
                    <aside className="asset-panel panel">
                      <div className="panel-heading">
                        <h2>
                          图片资源 <span>{visible.length}</span>
                        </h2>
                        <button
                          className="icon-button"
                          onClick={() => openModal("import")}
                          title="导入图片"
                        >
                          <Plus size={18} />
                        </button>
                      </div>
                      <label className="search-field">
                        <Search size={15} />
                        <input
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                          placeholder="搜索图片名称"
                          aria-label="搜索图片名称"
                        />
                        <kbd>⌘ K</kbd>
                      </label>
                      <div className="filter-row">
                        <select
                          aria-label="筛选图片状态"
                          value={statusFilter}
                          onChange={(e) => setStatusFilter(e.target.value)}
                        >
                          <option value="">全部状态</option>
                          {Object.entries(states).map(([id, label]) => (
                            <option key={id} value={id}>
                              {label}
                            </option>
                          ))}
                        </select>
                        <button
                          className="icon-button"
                          title="选择全部当前图片"
                          onClick={() =>
                            setSelection(new Set(visible.map((a) => a.id)))
                          }
                        >
                          <CheckCheck size={16} />
                        </button>
                        <button
                          className="icon-button"
                          title="清空多选"
                          onClick={() => setSelection(new Set())}
                        >
                          <Filter size={15} />
                        </button>
                      </div>
                      <div className="asset-list">
                        {visible.map((a, i) => (
                          <div
                            key={a.id}
                            className={`asset-row ${current === a.id ? "selected" : ""}`}
                            onClick={() => changeCurrent(a.id)}
                            role="button"
                            tabIndex={0}
                            aria-label={`选择图片 ${a.display_name}`}
                            onKeyDown={(e) => {
                              if (
                                e.target === e.currentTarget &&
                                ["Enter", " "].includes(e.key)
                              ) {
                                e.preventDefault();
                                changeCurrent(a.id);
                              }
                            }}
                          >
                            <label
                              className="asset-checkbox"
                              title="加入批量选择"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <input
                                type="checkbox"
                                checked={selection.has(a.id)}
                                aria-label={`批量选择 ${a.display_name}`}
                                onChange={(e) =>
                                  setSelection((old) => {
                                    const next = new Set(old);
                                    if (e.target.checked) next.add(a.id);
                                    else next.delete(a.id);
                                    return next;
                                  })
                                }
                              />
                            </label>
                            <img
                              src={imageUrl(a.id, a.sha256, true)}
                              alt=""
                              loading="lazy"
                            />
                            <div className="asset-info">
                              <strong title={a.display_name}>
                                {a.display_name}
                              </strong>
                              <span>
                                {a.width} × {a.height} <i /> {a.box_count}{" "}
                                个目标
                              </span>
                              <small className={`state-text ${a.state}`}>
                                <span />
                                {states[a.state]}
                              </small>
                            </div>
                            <span className="asset-number">
                              {String(i + 1).padStart(2, "0")}
                            </span>
                          </div>
                        ))}
                        {!visible.length && (
                          <div className="list-empty">
                            <ImagePlus size={27} />
                            <p>
                              {data.assets.length
                                ? "没有符合筛选的图片"
                                : "还没有图片"}
                            </p>
                            <button
                              className="text-button"
                              onClick={() => openModal("import")}
                            >
                              导入图片
                            </button>
                          </div>
                        )}
                      </div>
                      <div className="asset-panel-footer">
                        <ShieldCheck size={15} />
                        <span>
                          {selection.size
                            ? `已选 ${selection.size} 张，批量操作使用选择集`
                            : "原始图片保留，编辑自动保存"}
                        </span>
                      </div>
                    </aside>
                    <section className="canvas-panel panel">
                      <div className="canvas-heading">
                        <div>
                          <span className="file-dot" />
                          {asset?.display_name || "尚未选择图片"}
                          {asset && (
                            <span className="file-dimensions">
                              {asset.width} × {asset.height}
                            </span>
                          )}
                        </div>
                        <div className="inline-tools">
                          <button
                            className="icon-button"
                            aria-label="上一张"
                            onClick={() => navigate(-1)}
                            disabled={!asset || saving}
                          >
                            <ChevronLeft size={17} />
                          </button>
                          <span>
                            {current
                              ? visible.findIndex((a) => a.id === current) + 1
                              : 0}{" "}
                            / {visible.length}
                          </span>
                          <button
                            className="icon-button"
                            aria-label="下一张"
                            onClick={() => navigate(1)}
                            disabled={!asset || saving}
                          >
                            <ChevronRight size={17} />
                          </button>
                        </div>
                      </div>
                      <div className="canvas-stage">
                        <AnnotationCanvas
                          asset={asset}
                          boxes={boxes}
                          categories={data.categories}
                          category={category}
                          selected={selectedBox}
                          draw={draw}
                          pan={panMode}
                          locked={busy || saving || asset?.state === "excluded"}
                          zoomAction={zoomAction}
                          onSelect={setSelectedBox}
                          onCommit={commit}
                          onZoom={setZoom}
                          hidden={hiddenIds}
                        />
                        <div className="canvas-mode-tip">
                          <span className="shortcut-dot" />
                          {busy
                            ? "任务运行中，编辑已锁定"
                            : draw
                              ? "拖动创建目标框 · Esc 返回选择"
                              : "点击选择目标框 · W 开始画框"}
                        </div>
                        <div className="canvas-toolbar">
                          <div className="tool-group">
                            <button
                              className={!draw ? "selected" : ""}
                              title="选择 V"
                              aria-label="选择模式"
                              onClick={() => {
                                setDraw(false);
                                setPanMode(false);
                              }}
                            >
                              <MousePointer2 size={17} />
                            </button>
                            <button
                              className={draw ? "selected" : ""}
                              title="画框 W"
                              aria-label="画框模式"
                              disabled={!category}
                              onClick={() => {
                                setDraw(true);
                                setPanMode(false);
                              }}
                            >
                              <SquareDashed size={18} />
                            </button>
                            <span className="tool-separator" />
                            <button
                              className={panMode ? "selected" : ""}
                              title="平移模式（支持触摸拖动）"
                              aria-label="平移模式"
                              aria-pressed={panMode}
                              onClick={() => {
                                setPanMode(!panMode);
                                setDraw(false);
                              }}
                            >
                              <Hand size={17} />
                            </button>
                          </div>
                          <div className="tool-group zoom-tools">
                            <button title="缩小" onClick={() => zoomBy("out")}>
                              <ZoomOut size={16} />
                            </button>
                            <span>{Math.round(zoom * 100)}%</span>
                            <button title="放大" onClick={() => zoomBy("in")}>
                              <ZoomIn size={16} />
                            </button>
                            <span className="tool-separator" />
                            <button
                              title="适应画布 F"
                              onClick={() => zoomBy("fit")}
                            >
                              <Maximize2 size={16} />
                            </button>
                          </div>
                        </div>
                      </div>
                      <div className="canvas-status">
                        <span
                          className={`save-state ${saving ? "saving" : ""}`}
                        >
                          {saving ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Check size={14} />
                          )}{" "}
                          {saving
                            ? "正在保存"
                            : asset
                              ? `已保存 · 修订 ${asset.revision}`
                              : "等待图片"}
                        </span>
                        <div>
                          <button
                            className="icon-button"
                            title="撤销 ⌘ Z"
                            disabled={!asset || busy || saving}
                            onClick={() => undo()}
                          >
                            <Undo2 size={16} />
                          </button>
                          <button
                            className="icon-button"
                            title="重做 ⌘ ⇧ Z"
                            disabled={!asset || busy || saving}
                            onClick={() => undo(true)}
                          >
                            <Redo2 size={16} />
                          </button>
                          <span className="subtle-separator" />
                          <button
                            className="icon-button"
                            title="批量处理"
                            disabled={!selected.length || busy}
                            onClick={() => openModal("process")}
                          >
                            <SlidersHorizontal size={16} />
                          </button>
                        </div>
                      </div>
                    </section>
                    <aside className="inspector-panel panel">
                      <div className="panel-heading">
                        <h2>标注与复核</h2>
                        <span className="small-tag">{boxes.length} 个目标</span>
                      </div>
                      <div className="inspector-scroll">
                        <section className="inspector-section">
                          <div className="section-label">
                            <h3>当前类别</h3>
                            <button
                              className="text-button"
                              onClick={() => openModal("categories")}
                            >
                              编辑
                            </button>
                          </div>
                          <div className="category-options">
                            {data.categories
                              .filter((c) => c.enabled)
                              .map((c) => (
                                <button
                                  className={category === c.id ? "chosen" : ""}
                                  key={c.id}
                                  onClick={() => setCategory(c.id)}
                                >
                                  <span style={{ background: c.color }} />
                                  {c.display_name}
                                  {category === c.id && <Check size={13} />}
                                </button>
                              ))}
                          </div>
                          <label className="subtle-checkbox">
                            <input
                              type="checkbox"
                              checked={hidden}
                              onChange={(e) => setHidden(e.target.checked)}
                            />
                            只显示当前类别的框
                          </label>
                        </section>
                        <section className="assistant-note">
                          <div>
                            <Sparkles size={16} />
                            <strong>视觉辅助判断</strong>
                            <span>AI</span>
                          </div>
                          {detail?.vision_result ? (
                            <>
                              <p>{detail.vision_result.result.summary}</p>
                              <small>
                                {detail.vision_result.result.model} ·{" "}
                                {detail.vision_result.result.elapsed_seconds}s ·
                                待人工复核
                              </small>
                              {detail.vision_result.result.warnings.map(
                                (w, i) => (
                                  <p className="warning-copy" key={i}>
                                    {w}
                                  </p>
                                ),
                              )}
                            </>
                          ) : (
                            <>
                              <p>
                                结合画面内容补充目标类别与候选框，也可辅助发现本地模型未支持的植物。
                              </p>
                              <button
                                className="text-button"
                                disabled={!asset || busy}
                                onClick={() => openModal("ai")}
                              >
                                分析当前图片 <ArrowUpRight size={14} />
                              </button>
                            </>
                          )}
                        </section>
                        <section className="box-section">
                          <div className="section-label">
                            <h3>目标列表</h3>
                            <span>{boxes.length}</span>
                          </div>
                          {boxes.map((b, index) => {
                            const c = data.categories.find(
                              (c) => c.id === b.category_id,
                            );
                            return (
                              <div
                                key={b.id}
                                className={`box-row ${selectedBox === b.id ? "selected" : ""} ${hiddenIds.has(b.id) ? "muted" : ""}`}
                                onClick={() => setSelectedBox(b.id)}
                                role="button"
                                tabIndex={0}
                                aria-label={`选择目标 ${index + 1} ${c?.display_name || "未知类别"}`}
                                onKeyDown={(e) => {
                                  if (["Enter", " "].includes(e.key)) {
                                    e.preventDefault();
                                    setSelectedBox(b.id);
                                  }
                                }}
                              >
                                <span
                                  className="box-order"
                                  style={{
                                    color: c?.color,
                                    background: `${c?.color}12`,
                                  }}
                                >
                                  {String(index + 1).padStart(2, "0")}
                                </span>
                                <div>
                                  <strong>
                                    {c?.display_name || "未知类别"}
                                    <span className="source-tag">
                                      {sourceName(b)}
                                    </span>
                                  </strong>
                                  <small>
                                    {Math.round(b.x1)}, {Math.round(b.y1)}{" "}
                                    <span>→</span> {Math.round(b.x2)},{" "}
                                    {Math.round(b.y2)}
                                  </small>
                                </div>
                                {b.score !== null ? (
                                  <span className="box-score">
                                    {Math.round(b.score * 100)}
                                    <small>%</small>
                                  </span>
                                ) : (
                                  <span className="score-dash">—</span>
                                )}
                              </div>
                            );
                          })}
                          {!boxes.length && (
                            <div className="no-boxes">
                              <SquareDashed size={23} />
                              <p>尚无目标框</p>
                              <small>按 W 手工画框，或运行辅助标注</small>
                            </div>
                          )}
                          {selectedBox && (
                            <div className="selected-box-actions">
                              <button
                                className="text-button"
                                disabled={busy || saving}
                                onClick={() =>
                                  commit(
                                    boxes.map((b) =>
                                      b.id === selectedBox
                                        ? {
                                            ...b,
                                            category_id: category,
                                            edited: true,
                                          }
                                        : b,
                                    ),
                                  )
                                }
                              >
                                改为{currentCategory?.display_name}
                              </button>
                              <button
                                className="icon-button danger"
                                title="删除所选框"
                                disabled={busy || saving}
                                onClick={() => {
                                  commit(
                                    boxes.filter((b) => b.id !== selectedBox),
                                  );
                                  setSelectedBox("");
                                }}
                              >
                                <Trash2 size={15} />
                              </button>
                            </div>
                          )}
                        </section>
                      </div>
                      <div className="review-footer">
                        <p>
                          <Info size={13} />
                          模型输出仅作建议，请对照图片检查
                        </p>
                        <button
                          className="button review-button"
                          disabled={
                            !asset ||
                            busy ||
                            saving ||
                            hiddenIds.size > 0 ||
                            asset.state === "excluded"
                          }
                          onClick={review}
                        >
                          <CheckCheck size={17} />
                          {asset &&
                          ["reviewed", "negative"].includes(asset.state)
                            ? "已完成复核"
                            : "确认并完成复核"}
                          <kbd>⌘ ↵</kbd>
                        </button>
                      </div>
                    </aside>
                  </section>
                  <div className="workspace-bottom">
                    <span>
                      <span className="dot green" />{" "}
                      {data.vision.configured
                        ? "视觉服务已配置"
                        : "未配置云端模型，可离线标注"}{" "}
                      · 自动保存已开启
                    </span>
                    <span>
                      <kbd>W</kbd> 画框 <kbd>A</kbd>
                      <kbd>D</kbd> 切图 <kbd>Space</kbd> 平移 <kbd>F</kbd>{" "}
                      适应画布
                    </span>
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        start("/infer", {
                          ids: selected,
                          threshold: 0.3,
                          nms: 0.45,
                        })
                      }
                    >
                      本地 YOLOX 检测 <ArrowUpRight size={13} />
                    </button>
                  </div>
                </>
              )}
              {tab === "dataset" && (
                <section className="dataset-layout">
                  <div className="panel dataset-main">
                    <div className="panel-heading">
                      <h2>数据准备</h2>
                      <span className="small-tag">
                        {data.assets.length} 张图片
                      </span>
                    </div>
                    <div className="dataset-section">
                      <div className="section-label">
                        <h3>质量检查</h3>
                        <button
                          className="button"
                          disabled={busy}
                          onClick={() => start("/quality", {})}
                        >
                          <ShieldCheck size={16} />
                          检查全部图片
                        </button>
                      </div>
                      <p>
                        检查文件摘要、检测框、类别引用和复核状态，错误会阻止相关数据集导出。
                      </p>
                      {quality && (
                        <>
                          <div className="quality-summary">
                            <span>{quality.errors.length} 个错误</span>
                            <span>{quality.warnings.length} 个警告</span>
                            <span>{quality.assets} 张已检查</span>
                          </div>
                          <div className="issues-list">
                            {quality.issues.map((issue: any, i: number) => (
                              <button
                                key={i}
                                onClick={() => {
                                  if (issue.asset_id) {
                                    setStatusFilter("");
                                    setSearch("");
                                    setCurrent(issue.asset_id);
                                    setTab("workbench");
                                  }
                                }}
                              >
                                <span
                                  className={
                                    issue.level === "error"
                                      ? "issue-error"
                                      : "issue-warning"
                                  }
                                >
                                  {issue.level === "error" ? "错误" : "警告"}
                                </span>
                                <span>
                                  {issue.name && issue.name + " · "}
                                  {issue.message}
                                </span>
                                <ArrowUpRight size={14} />
                              </button>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                    <div className="dataset-section">
                      <h3>训练 / 验证划分</h3>
                      <p>同源、精确重复和增强图片按组划分，避免跨集合泄漏。</p>
                      <div className="split-controls">
                        <label>
                          训练比例{" "}
                          <input
                            type="number"
                            min="50"
                            max="95"
                            value={Math.round(ratio * 100)}
                            onChange={(e) =>
                              setRatio(Number(e.target.value) / 100)
                            }
                          />
                          <span>%</span>
                        </label>
                        <label>
                          随机种子
                          <input
                            type="number"
                            value={seed}
                            onChange={(e) => setSeed(Number(e.target.value))}
                          />
                        </label>
                        <button
                          className="button"
                          disabled={busy}
                          onClick={() =>
                            perform(async () => {
                              await api("/split", "POST", {
                                train_ratio: ratio,
                                seed,
                              });
                              await refresh();
                              notify("划分已锁定，请核对实际比例");
                            })
                          }
                        >
                          创建并锁定划分
                        </button>
                      </div>
                      {data.plan ? (
                        <>
                          <div className="split-visual">
                            <div
                              style={{
                                width: `${(data.plan.statistics.train.images / Math.max(1, data.plan.statistics.train.images + data.plan.statistics.val.images)) * 100}%`,
                              }}
                            >
                              Train {data.plan.statistics.train.images}
                            </div>
                            <div>Val {data.plan.statistics.val.images}</div>
                          </div>
                          <p className="small-muted">
                            计划 {data.plan.id.slice(0, 12)} ·
                            输入变更后需要重新划分
                          </p>
                        </>
                      ) : (
                        <div className="inline-notice">
                          <Info size={16} />
                          尚无有效划分，至少需要两个独立同源组
                        </div>
                      )}
                    </div>
                    <div className="dataset-section">
                      <div className="section-label">
                        <h3>导出记录</h3>
                        <button
                          className="icon-button"
                          title="刷新记录"
                          onClick={() =>
                            api<any[]>("/exports").then(setExports)
                          }
                        >
                          <RefreshCw size={15} />
                        </button>
                      </div>
                      {exports.length ? (
                        exports.map((record) => (
                          <div className="export-row" key={record.id}>
                            <FileCheck2 size={22} />
                            <div>
                              <strong>
                                {record.format.toUpperCase()} ·{" "}
                                {record.id.slice(0, 12)}
                              </strong>
                              <small>
                                {record.status === "success"
                                  ? "独立回读校验通过"
                                  : record.status}
                              </small>
                            </div>
                            {record.status === "success" && (
                              <a
                                className="button"
                                href={`/api/exports/${record.id}/download`}
                              >
                                <Download size={15} />
                                下载 ZIP
                              </a>
                            )}
                          </div>
                        ))
                      ) : (
                        <p className="small-muted">
                          还没有导出记录。校验通过后，结果会出现在这里。
                        </p>
                      )}
                    </div>
                  </div>
                  <aside className="panel export-panel">
                    <div className="panel-heading">
                      <h2>发布数据集</h2>
                      <Download size={18} />
                    </div>
                    <div className="dataset-section">
                      <p>
                        默认纳入 {reviewed} 张已复核图片，其余{" "}
                        {data.assets.length - reviewed} 张不纳入。
                      </p>
                      <label className="field-label">
                        导出格式
                        <select
                          value={format}
                          onChange={(e) => setFormat(e.target.value)}
                        >
                          <option value="yolo">YOLO 目标检测</option>
                          <option value="coco">COCO 矩形检测</option>
                        </select>
                      </label>
                      <div className="inline-notice">
                        <ShieldCheck size={18} />
                        <span>
                          先写入临时目录，再独立回读；只有校验通过的结果才会发布。
                        </span>
                      </div>
                      <label className="consent">
                        <input
                          type="checkbox"
                          checked={accepted}
                          onChange={(e) => setAccepted(e.target.checked)}
                        />
                        <span>
                          我已检查质量报告、未纳入图片和类别覆盖，接受其中的警告。
                        </span>
                      </label>
                      <button
                        className="button primary full"
                        disabled={!accepted || !data.plan || !reviewed || busy}
                        onClick={() =>
                          start("/export", {
                            format,
                            acknowledge_warnings: accepted,
                          })
                        }
                      >
                        <Download size={16} />
                        验证并导出
                      </button>
                      <small>
                        YOLO 目录迁移后请运行包内 relocate_dataset.py。
                      </small>
                    </div>
                  </aside>
                </section>
              )}
              {tab === "tasks" && (
                <section className="panel tasks-panel">
                  <div className="panel-heading">
                    <h2>处理记录</h2>
                    <span className="small-tag">最近 100 条</span>
                  </div>
                  {tasks.length ? (
                    <table>
                      <thead>
                        <tr>
                          <th>任务</th>
                          <th>状态</th>
                          <th>进度</th>
                          <th>时间</th>
                          <th>详情</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tasks.map((t) => (
                          <tr key={t.id}>
                            <td>{t.type}</td>
                            <td>
                              <span className={`task-status ${t.status}`}>
                                {(
                                  {
                                    success: "已完成",
                                    failed: "失败",
                                    partial_failure: "部分失败",
                                    cancelled: "已取消",
                                    running: "进行中",
                                    interrupted: "上次中断",
                                  } as any
                                )[t.status] || t.status}
                              </span>
                            </td>
                            <td>
                              {(() => {
                                const p = JSON.parse(t.progress_json || "{}");
                                return `${p.done || 0} / ${p.total || "—"}`;
                              })()}
                            </td>
                            <td>
                              {new Date(t.created_at).toLocaleString("zh-CN")}
                            </td>
                            <td>
                              <details>
                                <summary>查看</summary>
                                <pre>
                                  {JSON.stringify(
                                    JSON.parse(t.error_json || "[]"),
                                    null,
                                    2,
                                  )}
                                </pre>
                              </details>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="list-empty">
                      <History size={32} />
                      <p>任务执行后会在此保留结果</p>
                    </div>
                  )}
                </section>
              )}
            </>
          )}
        </main>
        <footer className="app-footer">
          <span>图枢 TUSHU</span>
          <span>图片与标注保存在本机 · 视觉辅助仅在你发起时发送所选图片</span>
          <button className="text-button" onClick={() => openModal("settings")}>
            模型设置 <ArrowUpRight size={12} />
          </button>
        </footer>
      </div>
      {busy && (
        <div className="job-toast">
          <div>
            <Loader2 size={18} className="spin" />
            <strong>{job!.kind}</strong>
            <span>
              {job!.total ? `${job!.done} / ${job!.total}` : "准备中"}
            </span>
            <button
              className="text-button"
              onClick={() => perform(() => api("/tasks/cancel", "POST", {}))}
            >
              取消
            </button>
          </div>
          <p>{job!.current || "后台处理期间可以浏览，编辑已锁定"}</p>
          <div className="progress-track">
            <i
              style={{
                width: job!.total
                  ? `${(job!.done / job!.total) * 100}%`
                  : "20%",
              }}
            />
          </div>
        </div>
      )}
      {toast && (
        <div role="status" className="notice-toast">
          <Check size={16} />
          {toast}
        </div>
      )}
      <input
        ref={input}
        type="file"
        accept=".jpg,.jpeg,.png,.webp"
        multiple
        hidden
        onChange={(e) => filesChosen(e.target.files)}
      />
      {modal && (
        <div
          className="modal-backdrop"
          onClick={() => {
            if (modal !== "ai") setModal(null);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            className={`dialog ${modal === "ai" ? "ai-dialog" : ""}`}
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <div className="dialog-icon">
                {modal === "ai" ? (
                  <Sparkles size={22} />
                ) : modal === "settings" ? (
                  <Settings size={22} />
                ) : modal === "import" ? (
                  <Upload size={22} />
                ) : (
                  <FolderOpen size={22} />
                )}
              </div>
              <div>
                <h2 id="dialog-title">
                  {
                    (
                      {
                        create: "创建项目",
                        projects: "你的项目",
                        import: "导入图片",
                        ai: "大模型视觉辅助",
                        settings: "视觉服务设置",
                        process: "批量图像处理",
                        categories: "项目类别",
                      } as any
                    )[modal]
                  }
                </h2>
                <p>
                  {modal === "ai"
                    ? "对所选图片生成类别与候选框，结果仍需人工复核。"
                    : modal === "settings"
                      ? "使用你自己的 OpenAI 兼容视觉 API。"
                      : "数据保存在本机，原始图片始终保留。"}
                </p>
              </div>
              <button
                className="icon-button"
                onClick={() => setModal(null)}
                aria-label="关闭弹窗"
              >
                <X size={19} />
              </button>
            </header>
            <div className="dialog-body">
              {error && (
                <div role="alert" className="error-banner">
                  <AlertCircle size={16} />
                  <span>{error}</span>
                </div>
              )}
              {modal === "create" && (
                <>
                  <label className="field-label">
                    项目名称
                    <input
                      maxLength={80}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      autoFocus
                    />
                  </label>
                  <div className="inline-notice">
                    <Info size={16} />
                    创建后提供动物、植物、物品三类，可随时添加或调整。
                  </div>
                  <button
                    className="button primary full"
                    onClick={createProject}
                    disabled={!name.trim()}
                  >
                    创建项目
                  </button>
                </>
              )}
              {modal === "projects" && (
                <>
                  <div className="project-list">
                    {data.projects.map((p) => (
                      <button
                        key={p.id}
                        onClick={() =>
                          perform(async () => {
                            await api("/projects/open", "POST", { id: p.id });
                            setCurrent("");
                            setSelection(new Set());
                            await refresh();
                            setModal(null);
                          })
                        }
                      >
                        <FolderOpen size={23} />
                        <span>
                          <strong>{p.name}</strong>
                          <small>
                            {new Date(p.created_at).toLocaleDateString("zh-CN")}
                          </small>
                        </span>
                        <ChevronRight size={16} />
                      </button>
                    ))}
                    {!data.projects.length && <p>尚未创建项目</p>}
                  </div>
                  <button
                    className="button primary full"
                    onClick={() => setModal("create")}
                  >
                    <Plus size={16} />
                    新建项目
                  </button>
                </>
              )}
              {modal === "import" && (
                <>
                  <button
                    className="upload-dropzone"
                    onClick={() => input.current?.click()}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      filesChosen(e.dataTransfer.files);
                    }}
                  >
                    <div>
                      <ImagePlus size={30} />
                    </div>
                    <h3>拖放图片到这里，或点击选择</h3>
                    <p>JPEG、PNG、静态 WebP · 单张最大 100 MiB</p>
                    <span className="button">选择本地图片</span>
                  </button>
                  <div className="dialog-divider">或扫描本机文件夹</div>
                  <label className="field-label">
                    文件夹绝对路径
                    <input
                      value={folder}
                      onChange={(e) => setFolder(e.target.value)}
                      placeholder="/Users/你的用户名/Pictures/样本"
                    />
                  </label>
                  <button
                    className="button full"
                    disabled={!folder || busy}
                    onClick={() =>
                      start("/import/scan", { folder, recursive: true })
                    }
                  >
                    扫描并查看清单
                  </button>
                  {job?.kind === "扫描文件夹" && job.status === "success" && (
                    <>
                      <div className="scan-summary">
                        发现 {job.result.length} 张，可导入{" "}
                        {job.result.filter((r: any) => r.accepted).length} 张
                      </div>
                      <div className="scan-results">
                        {job.result.map((r: any, i: number) => (
                          <p key={i}>
                            {r.name}
                            <span>{r.reason || "可导入"}</span>
                          </p>
                        ))}
                      </div>
                      <button
                        className="button primary full"
                        onClick={() => start("/import/confirm", {})}
                      >
                        确认导入扫描结果
                      </button>
                    </>
                  )}
                </>
              )}
              {modal === "ai" && (
                <>
                  <div className="ai-selection">
                    {selected.slice(0, 3).map((id) => {
                      const a = data.assets.find((a) => a.id === id)!;
                      return (
                        <img
                          key={id}
                          src={imageUrl(a.id, a.sha256, true)}
                          alt={a.display_name}
                        />
                      );
                    })}
                    <div>
                      <strong>分析 {selected.length} 张所选图片</strong>
                      <small>
                        {data.vision.model} ·{" "}
                        {new URL(data.vision.base_url).hostname}
                      </small>
                    </div>
                  </div>
                  <div className="capability-list">
                    <p>
                      <Check size={16} />
                      补充动物、植物和常见物品的类别建议
                    </p>
                    <p>
                      <Check size={16} />
                      给出场景说明、候选框和不确定性提示
                    </p>
                    <p>
                      <Check size={16} />
                      保留人工框和已编辑结果，生成待复核版本
                    </p>
                  </div>
                  {!data.vision.configured && (
                    <div className="inline-notice">
                      <Info size={16} />
                      尚未配置 API。
                      <button
                        className="text-button"
                        onClick={() => setModal("settings")}
                      >
                        前往设置
                      </button>
                    </div>
                  )}
                  <label className="consent">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                    />
                    <span>
                      我同意将以上所选图片的缩小副本发送到当前视觉服务；其余图片不会发送。
                    </span>
                  </label>
                  <button
                    className="button primary full"
                    disabled={!consent || !data.vision.configured || busy}
                    onClick={() =>
                      start("/vision/run", { ids: selected, consent })
                    }
                  >
                    <Sparkles size={17} />
                    开始视觉辅助
                  </button>
                  <small className="privacy-note">
                    候选位置和类别可能不准确，植物判断不替代专业物种鉴定。
                  </small>
                </>
              )}
              {modal === "settings" && (
                <>
                  <div className="model-config-state">
                    <span
                      className={`dot ${data.vision.configured ? "green" : "neutral"}`}
                    />
                    {data.vision.configured
                      ? "视觉服务已配置，密钥不会返回网页"
                      : "未配置视觉服务，人工标注和本地检测仍可使用"}
                  </div>
                  <label className="field-label">
                    Base URL
                    <input
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      placeholder="https://服务地址/v1"
                    />
                  </label>
                  <label className="field-label">
                    模型名称
                    <input
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                    />
                  </label>
                  <label className="field-label">
                    API Key
                    <input
                      type="password"
                      value={key}
                      onChange={(e) => setKey(e.target.value)}
                      autoComplete="off"
                      placeholder={
                        data.vision.configured
                          ? "已配置；留空可继续使用当前密钥"
                          : "请填写自己的 API Key"
                      }
                    />
                  </label>
                  <div className="inline-notice">
                    <ShieldCheck size={18} />
                    <span>
                      网页输入的密钥仅保存在本次服务进程中，不写入项目、导出或公开源码。重启后请重新配置，或自行设置环境变量。
                    </span>
                  </div>
                  <button
                    className="button primary full"
                    onClick={() =>
                      perform(async () => {
                        await api("/vision/config", "POST", {
                          base_url: baseUrl,
                          model,
                          api_key: key || null,
                        });
                        setKey("");
                        await refresh();
                        setModal(null);
                        notify("视觉服务设置已更新");
                      })
                    }
                  >
                    保存本次配置
                  </button>
                </>
              )}
              {modal === "process" && (
                <>
                  <p>
                    已选 {selected.length}{" "}
                    张，将生成新工作版本并同步框坐标，原版本保留。
                  </p>
                  <label className="field-label">
                    处理操作
                    <select
                      value={operation}
                      onChange={(e) => setOperation(e.target.value)}
                    >
                      <option value="flip_h">水平翻转</option>
                      <option value="flip_v">垂直翻转</option>
                      <option value="rotate">顺时针旋转 90°</option>
                      <option value="resize">按最长边等比缩放</option>
                      <option value="brightness">亮度增加 10%</option>
                      <option value="contrast">对比度增加 10%</option>
                      <option value="encode_jpeg">
                        转换 JPEG（白色背景，质量 90）
                      </option>
                      <option value="encode_webp">转换无损 WebP</option>
                    </select>
                  </label>
                  {operation === "resize" && (
                    <label className="field-label">
                      最长边像素
                      <input
                        type="number"
                        min="1"
                        max="10000"
                        value={edge}
                        onChange={(e) => setEdge(Number(e.target.value))}
                      />
                    </label>
                  )}
                  <div className="inline-notice">
                    <Info size={16} />
                    所有新版本需要重新复核；活动版本变化会使旧划分计划失效。
                  </div>
                  <button
                    className="button primary full"
                    onClick={() => {
                      const op =
                        operation === "rotate"
                          ? { op: "rotate", angle: 90 }
                          : operation === "resize"
                            ? { op: "resize", longest: edge }
                            : ["brightness", "contrast"].includes(operation)
                              ? { op: operation, factor: 1.1 }
                              : operation === "encode_jpeg"
                                ? {
                                    op: "encode",
                                    format: "JPEG",
                                    background: "#ffffff",
                                    quality: 90,
                                  }
                                : operation === "encode_webp"
                                  ? {
                                      op: "encode",
                                      format: "WEBP",
                                      lossless: true,
                                    }
                                  : { op: operation };
                      start("/process", {
                        ids: selected,
                        operations: [op],
                        augment: false,
                      });
                    }}
                  >
                    生成处理版本
                  </button>
                  <button
                    className="button full"
                    disabled={!data.plan}
                    onClick={() =>
                      start("/process", {
                        ids: selected,
                        operations: [{ op: "flip_h" }],
                        augment: true,
                        seed,
                      })
                    }
                  >
                    仅对已复核训练组生成翻转增强副本
                  </button>
                </>
              )}
              {modal === "categories" && (
                <>
                  <div className="category-list">
                    {data.categories.map((c) => (
                      <div key={c.id}>
                        <span style={{ background: c.color }} />
                        <strong>{c.display_name}</strong>
                        <small>{c.export_name}</small>
                      </div>
                    ))}
                  </div>
                  <div className="form-row">
                    <label className="field-label">
                      显示名
                      <input
                        value={newCat}
                        onChange={(e) => setNewCat(e.target.value)}
                        placeholder="例如：向日葵"
                        maxLength={50}
                      />
                    </label>
                    <label className="field-label">
                      导出名
                      <input
                        value={newCatExport}
                        onChange={(e) => setNewCatExport(e.target.value)}
                        placeholder="sunflower"
                        maxLength={50}
                      />
                    </label>
                  </div>
                  <button
                    className="button primary full"
                    disabled={!newCat.trim() || !newCatExport.trim()}
                    onClick={() =>
                      perform(async () => {
                        await api("/categories", "POST", {
                          name: newCat,
                          export_name: newCatExport,
                          color: "#6366f1",
                        });
                        setNewCat("");
                        setNewCatExport("");
                        await refresh();
                      })
                    }
                  >
                    <Plus size={16} />
                    添加类别
                  </button>
                  <p className="small-muted">
                    新增类别不会让本地 YOLOX
                    自动获得识别能力，可手工标注或由视觉辅助生成候选。
                  </p>
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
