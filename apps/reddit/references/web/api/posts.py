from typing import Optional

from apps.reddit.references.web.base_api_service import BaseApiServiceReddit


class ApiServiceRedditPosts(BaseApiServiceReddit):
    """
    Reddit API — post and comment write operations.

    All methods use form-encoded POST bodies as required by the Reddit write API.

    Methods:
        submit_post()       → Submit a text or link post
        submit_comment()    → Reply to a post or comment
        vote()              → Upvote, downvote, or remove vote
        save()              → Save a post or comment
        unsave()            → Unsave a post or comment
        delete()            → Delete own post or comment
        edit()              → Edit own post or comment text
        subscribe()         → Subscribe or unsubscribe from a subreddit
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceRedditPosts, self).__init__(config, **kwargs)

    def submit_post(self, subreddit: str, title: str,
                    text: str = None, url: str = None,
                    nsfw: bool = False, spoiler: bool = False,
                    send_replies: bool = True) -> dict:
        """
        Submit a new post to a subreddit.

        Requires 'submit' scope.
        Provide either text (self post) or url (link post), not both.

        Args:
            subreddit:    Target subreddit (without r/ prefix).
            title:        Post title (max 300 chars).
            text:         Body text in markdown (for self/text posts).
            url:          URL to submit (for link posts).
            nsfw:         Mark as NSFW. Default False.
            spoiler:      Mark as spoiler. Default False.
            send_replies: Send inbox replies on new comments. Default True.

        Returns:
            Dict with 'json.data' containing url, id, name (fullname) of new post.
        """
        kind = 'self' if text else 'link'
        data = {
            'sr': subreddit,
            'kind': kind,
            'title': title,
            'resubmit': 'true',
            'nsfw': 'true' if nsfw else 'false',
            'spoiler': 'true' if spoiler else 'false',
            'sendreplies': 'true' if send_replies else 'false',
            'api_type': 'json',
        }
        if text:
            data['text'] = text
        if url:
            data['url'] = url
        return self._post_form('/api/submit', data)

    def submit_comment(self, parent_fullname: str, text: str) -> dict:
        """
        Reply to a post or comment.

        Requires 'submit' scope.

        Args:
            parent_fullname: Fullname of the parent — 't3_xxx' for a post,
                             't1_xxx' for a comment.
            text:            Reply body in markdown.

        Returns:
            Dict with 'json.data.things[0].data' containing the new comment.
        """
        return self._post_form('/api/comment', {
            'parent': parent_fullname,
            'text': text,
            'api_type': 'json',
        })

    def vote(self, fullname: str, direction: int) -> dict:
        """
        Vote on a post or comment.

        Requires 'vote' scope.

        Args:
            fullname:  Fullname of the thing to vote on (e.g. 't3_abc123', 't1_xyz789').
            direction: 1 = upvote, -1 = downvote, 0 = remove vote.
        """
        return self._post_form('/api/vote', {
            'id': fullname,
            'dir': str(direction),
        })

    def save(self, fullname: str, category: str = None) -> dict:
        """
        Save a post or comment.

        Requires 'save' scope.

        Args:
            fullname: Fullname of the thing to save (t1_xxx or t3_xxx).
            category: Optional save category label.
        """
        data = {'id': fullname}
        if category:
            data['category'] = category
        return self._post_form('/api/save', data)

    def unsave(self, fullname: str) -> dict:
        """
        Unsave a previously saved post or comment.

        Args:
            fullname: Fullname of the thing to unsave.
        """
        return self._post_form('/api/unsave', {'id': fullname})

    def delete(self, fullname: str) -> dict:
        """
        Delete your own post or comment.

        Args:
            fullname: Fullname of own post (t3_xxx) or comment (t1_xxx) to delete.
        """
        return self._post_form('/api/del', {'id': fullname})

    def edit(self, fullname: str, text: str) -> dict:
        """
        Edit the text of your own post or comment.

        Requires 'edit' scope.

        Args:
            fullname: Fullname of your post (t3_xxx) or comment (t1_xxx).
            text:     New markdown text.
        """
        return self._post_form('/api/editusertext', {
            'thing_id': fullname,
            'text': text,
            'api_type': 'json',
        })

    def subscribe(self, subreddit_name: str, action: str = 'sub') -> dict:
        """
        Subscribe or unsubscribe from a subreddit.

        Requires 'subscribe' scope.

        Args:
            subreddit_name: Subreddit name (without r/ prefix).
            action:         'sub' to subscribe, 'unsub' to unsubscribe.
        """
        return self._post_form('/api/subscribe', {
            'sr_name': subreddit_name,
            'action': action,
        })
