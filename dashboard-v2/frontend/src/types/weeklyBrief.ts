export type BriefSource = 'on_daraz' | 'off_platform' | 'market';
export type BriefPost = { summary: string; platform: string; date: string; likes: number; url: string };
export type BriefNegativeReview = { rating: number; sku: string; text: string };
export type BriefExecutiveItem = {
  key: string; label: 'RISK' | 'OPPORTUNITY' | 'WATCH'; source: string;
  title: string; detail: string; what_changed: string; evidence: string; next_step: string;
};
export type WeeklyBrandBrief = {
  key: string; name: string; reviews: number; reviews_prev: number; review_share: number;
  avg_rating: number | null; negative: number; posts: number; posts_prev: number;
  post_share: number; likes: number; top_post_likes: number; viral_flag: boolean;
  highlight: string; top_posts: BriefPost[]; negative_reviews: BriefNegativeReview[]; shown: boolean;
};
export type WeeklyBrief = {
  country: string; country_name: string;
  week: { iso: string; start: string; end: string };
  prev_week: { start: string; end: string };
  available_weeks: { iso: string }[];
  totals: { reviews: number; reviews_prev: number; avg_rating: number | null; negative: number; posts: number; posts_prev: number };
  coverage: { label: string; through: string | null; count: number; status: string; current: boolean }[];
  executive: BriefExecutiveItem[];
  priorities: BriefExecutiveItem[];
  movers: { key: string; name: string; current: number; previous: number; delta: number; material: boolean }[];
  topline: { source: BriefSource; headline: string; detail: string }[];
  daily_reviews: { date: string; count: number; peak: boolean }[];
  topics: { label: string; cur: number; prev: number; emphasis: boolean }[];
  brands: WeeklyBrandBrief[];
  market: { category: string; account: string; date: string; summary: string; url: string }[];
  display_mode: 'share' | 'count';
  meta: { consumerStale: boolean; socialStale: boolean; cacheGeneratedAt: string };
};
