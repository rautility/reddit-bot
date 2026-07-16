"""Action registry — maps action names to their implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import ActionResult, BaseAction
from .browse import HumanScrollAction
from .comment import CommentAction
from .community import JoinCommunityAction
from .dm import DirectMessageAction
from .follow import FollowAction, UnfollowAction
from .post import CrosspostAction, PostImageAction, PostLinkAction, PostTextAction
from .profile import UpdateBioAction
from .save_hide import HideAction, SaveAction
from .search import HumanSearchAction, SearchOnlyAction, SearchUpvoteAction
from .vote import VoteAction

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

    from bot.config import BotConfig


class ActionRegistry:
    """Registry that maps action names to action classes and handles dispatch."""

    _action_map: dict[str, type[BaseAction]] = {
        "upvote": VoteAction,
        "downvote": VoteAction,
        "comment": CommentAction,
        "join": JoinCommunityAction,
        "leave": JoinCommunityAction,
        "save": SaveAction,
        "hide": HideAction,
        "post_text": PostTextAction,
        "post_link": PostLinkAction,
        "post_image": PostImageAction,
        "crosspost": CrosspostAction,
        "dm": DirectMessageAction,
        "follow": FollowAction,
        "unfollow": UnfollowAction,
        "update_bio": UpdateBioAction,
        "human_scroll": HumanScrollAction,
        "human_search": HumanSearchAction,
        "search_only": SearchOnlyAction,
        "search_upvote": SearchUpvoteAction,
    }

    def __init__(self, driver: WebDriver, config: BotConfig, logger: Any = None):
        self.driver = driver
        self.config = config
        self.logger = logger

    def execute(self, action_name: str, **kwargs: Any) -> ActionResult:
        """Execute a named action with the given parameters."""
        action_cls = self._action_map.get(action_name)
        if action_cls is None:
            return ActionResult(
                success=False,
                action=action_name,
                link=kwargs.get("link", ""),
                message=f"Unknown action: {action_name}",
            )

        action = action_cls(self.driver, self.config, self.logger)

        # Map action-specific parameters
        if action_name == "upvote":
            kwargs["upvote"] = True
        elif action_name == "downvote":
            kwargs["upvote"] = False
        elif action_name == "join":
            kwargs["join"] = True
        elif action_name == "leave":
            kwargs["join"] = False

        # Rename 'comment' field to 'text' for CommentAction
        if action_name == "comment" and "comment" in kwargs:
            kwargs["text"] = kwargs.pop("comment")

        return action.execute(**kwargs)

    @classmethod
    def list_actions(cls) -> list[str]:
        """Return all registered action names."""
        return sorted(cls._action_map.keys())

    @classmethod
    def register(cls, name: str, action_cls: type[BaseAction]) -> None:
        """Register a new action type."""
        cls._action_map[name] = action_cls
