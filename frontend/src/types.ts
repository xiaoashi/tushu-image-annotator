export type Category = {
  id: string;
  display_name: string;
  export_name: string;
  color: string;
  enabled: number;
};
export type Box = {
  id: string;
  category_id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  source: string;
  score: number | null;
  edited: boolean;
  model_id?: string | null;
  model_class?: number | null;
  run_id?: string | null;
};
export type Asset = {
  id: string;
  display_name: string;
  width: number;
  height: number;
  state: string;
  sha256: string;
  revision: number;
  active_version_id: string;
  parent_asset_id: string | null;
  group_id: string;
  split: string | null;
  box_count: number;
};
export type Job = {
  id: string;
  kind: string;
  status: string;
  done: number;
  total: number;
  current: string;
  result: any;
  error: string | null;
};
export type Bootstrap = {
  project: { id: string; name: string } | null;
  assets: Asset[];
  categories: Category[];
  counts: Record<string, number>;
  plan: any;
  job: Job | null;
  vision: { base_url: string; model: string; configured: boolean };
  projects: { id: string; name: string; created_at: string }[];
  version: string;
  client_token: string;
};
export type Detail = {
  asset: Asset;
  boxes: Box[];
  vision_result: {
    result: {
      summary: string;
      warnings: string[];
      objects: { label: string; reason: string }[];
      model: string;
      elapsed_seconds: number;
    };
  } | null;
  versions: any[];
};
export const states: Record<string, string> = {
  unlabeled: "未标注",
  predicted: "已预标注",
  pending: "待复核",
  reviewed: "已复核",
  negative: "已确认无目标",
  error: "文件异常",
  excluded: "已排除",
};
