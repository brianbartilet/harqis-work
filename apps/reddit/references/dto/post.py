from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DtoRedditPost:
    id: str = ''
    name: str = ''           # fullname e.g. t3_abc123
    title: str = ''
    selftext: str = ''
    url: str = ''
    author: str = ''
    subreddit: str = ''
    score: int = 0
    upvote_ratio: float = 0.0
    num_comments: int = 0
    created_utc: float = 0.0
    permalink: str = ''
    is_self: bool = False
    over_18: bool = False
    stickied: bool = False
    locked: bool = False
    flair_text: Optional[str] = None


@dataclass
class DtoRedditComment:
    id: str = ''
    name: str = ''           # fullname e.g. t1_xyz789
    body: str = ''
    author: str = ''
    parent_id: str = ''
    subreddit: str = ''
    score: int = 0
    created_utc: float = 0.0
    depth: int = 0
    is_submitter: bool = False
