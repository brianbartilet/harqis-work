import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.youtube.config import CONFIG
from apps.youtube.references.dto.channel import DtoYouTubeChannel
from apps.youtube.references.web.api.data import ApiServiceYouTubeData


@pytest.fixture()
def given():
    return ApiServiceYouTubeData(CONFIG)


@pytest.mark.smoke
def test_get_my_channel(given):
    channel = given.get_my_channel()
    assert_that(channel, instance_of(DtoYouTubeChannel))
    assert_that(channel.id, not_none())


@pytest.mark.smoke
def test_list_channel_videos(given):
    videos = given.list_channel_videos(max_results=5)
    assert_that(videos, instance_of(list))


@pytest.mark.smoke
def test_list_all_channel_videos_is_deduplicated(given):
    videos = given.list_channel_videos(max_results=None)
    video_ids = [video.id for video in videos]
    assert_that(videos, instance_of(list))
    assert len(video_ids) == len(set(video_ids))


@pytest.mark.smoke
def test_playlist_item_maps_video_owner_and_added_timestamp():
    service = object.__new__(ApiServiceYouTubeData)
    video = service._video({
        "id": "playlist-item-id",
        "snippet": {
            "title": "External video",
            "publishedAt": "2026-06-20T09:00:00Z",
            "channelId": "playlist-owner",
            "channelTitle": "My channel",
            "videoOwnerChannelId": "video-owner",
            "videoOwnerChannelTitle": "Another creator",
        },
        "contentDetails": {
            "videoId": "video-id",
            "videoPublishedAt": "2024-01-10T00:00:00Z",
        },
    })

    assert video.channel_id == "video-owner"
    assert video.channel_title == "Another creator"
    assert video.published_at == "2024-01-10T00:00:00Z"
    assert video.added_at == "2026-06-20T09:00:00Z"
