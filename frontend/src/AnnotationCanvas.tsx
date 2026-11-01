import { useRef, useState, useEffect } from "react";
import type { Asset, Box, Category } from "./types";
import { ImageOff } from "lucide-react";
import { imageUrl } from "./api";

type Props = {
  asset: Asset | null;
  boxes: Box[];
  categories: Category[];
  category: string;
  selected: string;
  draw: boolean;
  pan: boolean;
  locked: boolean;
  zoomAction: { type: string; nonce: number };
  onSelect: (id: string) => void;
  onCommit: (boxes: Box[]) => void;
  onZoom: (value: number) => void;
  hidden?: Set<string>;
};
export default function AnnotationCanvas(p: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const gesture = useRef<any>(null);
  const [view, setView] = useState({ x: 0, y: 0, z: 1 });
  const [draft, setDraft] = useState<Box | null>(null);
  const [live, setLive] = useState<Box[] | null>(null);
  const [space, setSpace] = useState(false);
  useEffect(() => {
    setView({ x: 0, y: 0, z: 1 });
    setDraft(null);
    setLive(null);
  }, [p.asset?.id, p.asset?.active_version_id]);
  useEffect(() => {
    setLive(null);
  }, [p.boxes]);
  useEffect(() => {
    if (p.zoomAction.type === "fit") setView({ x: 0, y: 0, z: 1 });
    else if (p.zoomAction.type === "in")
      setView((v) => ({ ...v, z: Math.min(16, v.z * 1.2) }));
    else if (p.zoomAction.type === "out")
      setView((v) => ({ ...v, z: Math.max(0.1, v.z / 1.2) }));
  }, [p.zoomAction]);
  useEffect(() => {
    p.onZoom(view.z);
  }, [view.z]);
  useEffect(() => {
    function down(e: KeyboardEvent) {
      if (
        e.code === "Space" &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement) &&
        !(e.target as HTMLElement)?.closest(
          "button,select,[role=button],[role=dialog]",
        )
      ) {
        setSpace(true);
        e.preventDefault();
      }
    }
    function up() {
      setSpace(false);
    }
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", up);
    };
  }, []);
  if (!p.asset)
    return (
      <div className="empty-canvas">
        <ImageOff size={36} />
        <h3>选择一张图片，开始标注</h3>
        <p>导入动物、植物或物品图片，保留每一步修改</p>
      </div>
    );
  const asset = p.asset;
  const boxes = live || p.boxes;
  const catMap = new Map(p.categories.map((c) => [c.id, c]));
  const unit = Math.max(asset.width, asset.height) / 900 / view.z;
  function point(e: React.PointerEvent | React.WheelEvent) {
    const m = svg.current!.getScreenCTM()!;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return {
      x: Math.max(0, Math.min(asset.width, pt.x)),
      y: Math.max(0, Math.min(asset.height, pt.y)),
    };
  }
  function down(e: React.PointerEvent<SVGSVGElement>) {
    const pos = point(e);
    if (p.pan || space || e.button === 1) {
      gesture.current = { kind: "pan", pos, view };
      e.currentTarget.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    if (p.locked || e.button !== 0) return;
    const target = e.target as SVGElement;
    const id = target.dataset.box;
    const handle = target.dataset.handle;
    if (p.draw && p.category) {
      gesture.current = {
        kind: "draw",
        pos,
        start: { x: e.clientX, y: e.clientY },
      };
      setDraft({
        id: crypto.randomUUID(),
        category_id: p.category,
        x1: pos.x,
        y1: pos.y,
        x2: pos.x,
        y2: pos.y,
        source: "manual",
        score: null,
        edited: false,
      });
    } else if (id) {
      p.onSelect(id);
      gesture.current = {
        kind: handle === undefined ? "move" : "resize",
        handle: handle === undefined ? 0 : Number(handle),
        pos,
        box: { ...boxes.find((b) => b.id === id)! },
        before: boxes.map((b) => ({ ...b })),
      };
    } else p.onSelect("");
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function move(e: React.PointerEvent<SVGSVGElement>) {
    const g = gesture.current;
    if (!g) return;
    const pos = point(e);
    if (g.kind === "pan") {
      const dx = pos.x - g.pos.x,
        dy = pos.y - g.pos.y;
      setView((v) => ({ ...v, x: v.x - dx, y: v.y - dy }));
      return;
    }
    if (g.kind === "draw") {
      setDraft((d) =>
        d
          ? {
              ...d,
              x1: Math.min(g.pos.x, pos.x),
              y1: Math.min(g.pos.y, pos.y),
              x2: Math.max(g.pos.x, pos.x),
              y2: Math.max(g.pos.y, pos.y),
            }
          : null,
      );
      return;
    }
    let b = { ...g.box, edited: true };
    if (g.kind === "move") {
      let dx = pos.x - g.pos.x,
        dy = pos.y - g.pos.y;
      dx = Math.max(-b.x1, Math.min(asset.width - b.x2, dx));
      dy = Math.max(-b.y1, Math.min(asset.height - b.y2, dy));
      b = { ...b, x1: b.x1 + dx, x2: b.x2 + dx, y1: b.y1 + dy, y2: b.y2 + dy };
    } else {
      const h = g.handle;
      if ([0, 6, 7].includes(h)) b.x1 = Math.min(pos.x, b.x2 - 1);
      if ([2, 3, 4].includes(h)) b.x2 = Math.max(pos.x, b.x1 + 1);
      if ([0, 1, 2].includes(h)) b.y1 = Math.min(pos.y, b.y2 - 1);
      if ([4, 5, 6].includes(h)) b.y2 = Math.max(pos.y, b.y1 + 1);
    }
    setLive(g.before.map((old: Box) => (old.id === b.id ? b : old)));
  }
  function up(e: React.PointerEvent<SVGSVGElement>) {
    const g = gesture.current;
    gesture.current = null;
    if (!g) return;
    if (
      g.kind === "draw" &&
      draft &&
      draft.x2 - draft.x1 >= 1 &&
      draft.y2 - draft.y1 >= 1 &&
      Math.hypot(e.clientX - g.start.x, e.clientY - g.start.y) >= 3
    ) {
      p.onCommit([...p.boxes, draft]);
      p.onSelect(draft.id);
    } else if ((g.kind === "move" || g.kind === "resize") && live) {
      p.onCommit(live);
    }
    setDraft(null);
    setLive(null);
    if (e.currentTarget.hasPointerCapture(e.pointerId))
      e.currentTarget.releasePointerCapture(e.pointerId);
  }
  function render(b: Box, dashed = false) {
    if (p.hidden?.has(b.id)) return null;
    const c = catMap.get(b.category_id);
    const selected = p.selected === b.id;
    const color = c?.color || "#6366f1";
    const label = `${c?.display_name || "未知类别"}${b.score == null ? "" : ` ${(b.score * 100).toFixed(0)}%`}`;
    const h = 25 * unit;
    const labelY = b.y1 < h ? b.y1 : b.y1 - h;
    const handles = [
      [b.x1, b.y1],
      [(b.x1 + b.x2) / 2, b.y1],
      [b.x2, b.y1],
      [b.x2, (b.y1 + b.y2) / 2],
      [b.x2, b.y2],
      [(b.x1 + b.x2) / 2, b.y2],
      [b.x1, b.y2],
      [b.x1, (b.y1 + b.y2) / 2],
    ];
    return (
      <g key={b.id}>
        <rect
          data-box={b.id}
          x={b.x1}
          y={b.y1}
          width={Math.max(0, b.x2 - b.x1)}
          height={Math.max(0, b.y2 - b.y1)}
          fill={selected ? `${color}13` : "transparent"}
          stroke={color}
          strokeWidth={selected ? 2 : 1.5}
          vectorEffect="non-scaling-stroke"
          strokeDasharray={dashed ? "5 4" : undefined}
        />
        <rect
          data-box={b.id}
          x={b.x1}
          y={labelY}
          width={Math.max(72, label.length * 13) * unit}
          height={h}
          fill={color}
          rx={3 * unit}
        />
        <text
          data-box={b.id}
          x={b.x1 + 7 * unit}
          y={labelY + 17 * unit}
          fill="white"
          fontSize={14 * unit}
          fontWeight="600"
        >
          {label}
        </text>
        {selected &&
          !p.locked &&
          handles.map(([x, y], i) => (
            <rect
              key={i}
              data-box={b.id}
              data-handle={i}
              x={x - 4 * unit}
              y={y - 4 * unit}
              width={8 * unit}
              height={8 * unit}
              fill="white"
              stroke={color}
              strokeWidth="1.5"
              vectorEffect="non-scaling-stroke"
            />
          ))}
      </g>
    );
  }
  return (
    <svg
      ref={svg}
      className={`annotation-svg ${p.draw ? "drawing" : ""} ${space || p.pan ? "panning" : ""}`}
      viewBox={`${view.x} ${view.y} ${asset.width / view.z} ${asset.height / view.z}`}
      preserveAspectRatio="xMidYMid meet"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={() => {
        gesture.current = null;
        setLive(null);
        setDraft(null);
      }}
      onWheel={(e) => {
        if (e.ctrlKey || e.metaKey) e.preventDefault();
        setView((v) => ({
          ...v,
          z: Math.max(0.1, Math.min(16, v.z * (e.deltaY < 0 ? 1.1 : 1 / 1.1))),
        }));
      }}
      aria-label={`标注画布 ${asset.display_name}`}
      role="img"
    >
      <image
        href={imageUrl(asset.id, asset.sha256)}
        width={asset.width}
        height={asset.height}
      />
      {boxes.map((b) => render(b))}
      {draft && render(draft, true)}
    </svg>
  );
}
