export type ConsumerVoiceFilters = {
  options: {
    ventures: string[];
    brands: string[];
    products: { id: string; name: string; brand: string }[];
    dateRange: { min: string | null; max: string | null };
  };
};

export type ConsumerVoiceDashboard = {
  metrics: {
    averageRating: number | null;
    positiveRate: number | null;
    reviewCount: number;
    ratedReviewCount: number;
    imageReviewCount: number;
  };
  dimensions: { dimension: string; score: number | null }[];
  stars: { rating: number; count: number }[];
  tags: { label: string; count: number; sentiment: "positive" | "neutral" | "negative" }[];
  alerts: {
    productId: string;
    productName: string;
    venture: string;
    rating: number | null;
    review: string;
    reasons: string[];
    date: string | null;
  }[];
  reviews: {
    id: string;
    productId: string;
    productName: string;
    brand: string;
    venture: string;
    date: string | null;
    rating: number | null;
    sentiment: "positive" | "neutral" | "negative";
    review: string;
    upvotes: number;
    tags: string[];
    images: string[];
  }[];
  meta: { filteredCount: number; sourceCount: number };
};
