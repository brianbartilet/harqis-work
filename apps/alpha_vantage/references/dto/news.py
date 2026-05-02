from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DtoAlphaVantageTickerSentiment:
    ticker: Optional[str] = None
    relevance_score: Optional[str] = None
    ticker_sentiment_score: Optional[str] = None
    ticker_sentiment_label: Optional[str] = None


@dataclass
class DtoAlphaVantageTopic:
    topic: Optional[str] = None
    relevance_score: Optional[str] = None


@dataclass
class DtoAlphaVantageNewsArticle:
    """One item in function=NEWS_SENTIMENT feed."""
    title: Optional[str] = None
    url: Optional[str] = None
    time_published: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    summary: Optional[str] = None
    banner_image: Optional[str] = None
    source: Optional[str] = None
    category_within_source: Optional[str] = None
    source_domain: Optional[str] = None
    topics: List[DtoAlphaVantageTopic] = field(default_factory=list)
    overall_sentiment_score: Optional[float] = None
    overall_sentiment_label: Optional[str] = None
    ticker_sentiment: List[DtoAlphaVantageTickerSentiment] = field(default_factory=list)
