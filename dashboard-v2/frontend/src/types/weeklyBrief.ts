export type BriefStatus = 'leading' | 'social_momentum' | 'consumer_momentum' | 'watch_closely' | 'stable';
export type Confidence = 'High' | 'Medium' | 'Low';

export type ConsumerBrief = {
  averageRating: number | null;
  positiveRate: number | null;
  negativeRate: number | null;
  reviewCount: number;
  ratingChange: number | null;
  reviewCountChange: number;
  negativeRateChange: number | null;
  topPositiveTopics: string[];
  topRiskTopics: string[];
};

export type SocialBrief = {
  socialRating: number;
  ratingChange: number | null;
  rank: number;
  signalCount: number;
  totalLikes: number;
  totalViews: number;
  confidence: Confidence;
  topTopics: string[];
};

export type WeeklyBrandBrief = {
  brand: string;
  status: BriefStatus;
  statusLabel: string;
  confidence: Confidence;
  keySignal: string;
  consumerVoice: ConsumerBrief | null;
  socialVoice: SocialBrief | null;
};

export type WeeklyBrief = {
  country: { code: string; name: string };
  countries: { code: string; name: string }[];
  week: { start: string; end: string; comparisonStart: string; comparisonEnd: string };
  marketSummary: string;
  callouts: { strongest: string | null; momentum: string | null; watch: string | null };
  highlights: { brand: string; status: BriefStatus; statusLabel: string; text: string; confidence: Confidence }[];
  brands: WeeklyBrandBrief[];
  meta: { consumerRows: number; socialSignals: number; consumerStale?: boolean; socialStale?: boolean; cacheGeneratedAt?: string };
};
