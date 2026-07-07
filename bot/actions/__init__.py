"""Action plugins for the Reddit bot.

Action classes are imported lazily to avoid pulling in selenium
when only ActionResult or BaseAction are needed.
"""

from .base import ActionResult, BaseAction

__all__ = [
    "BaseAction",
    "ActionResult",
    "ActionRegistry",
    "VoteAction",
    "CommentAction",
    "JoinCommunityAction",
    "SaveAction",
    "HideAction",
    "PostTextAction",
    "PostLinkAction",
    "PostImageAction",
    "CrosspostAction",
    "DirectMessageAction",
    "FollowAction",
    "UnfollowAction",
    "UpdateBioAction",
]


def __getattr__(name):
    if name == "ActionRegistry":
        from .registry import ActionRegistry

        return ActionRegistry
    if name == "VoteAction":
        from .vote import VoteAction

        return VoteAction
    if name == "CommentAction":
        from .comment import CommentAction

        return CommentAction
    if name == "JoinCommunityAction":
        from .community import JoinCommunityAction

        return JoinCommunityAction
    if name in ("SaveAction", "HideAction"):
        from .save_hide import HideAction, SaveAction

        return SaveAction if name == "SaveAction" else HideAction
    if name in ("PostTextAction", "PostLinkAction", "PostImageAction", "CrosspostAction"):
        from .post import CrosspostAction, PostImageAction, PostLinkAction, PostTextAction

        return {
            "PostTextAction": PostTextAction,
            "PostLinkAction": PostLinkAction,
            "PostImageAction": PostImageAction,
            "CrosspostAction": CrosspostAction,
        }[name]
    if name == "DirectMessageAction":
        from .dm import DirectMessageAction

        return DirectMessageAction
    if name in ("FollowAction", "UnfollowAction"):
        from .follow import FollowAction, UnfollowAction

        return FollowAction if name == "FollowAction" else UnfollowAction
    if name == "UpdateBioAction":
        from .profile import UpdateBioAction

        return UpdateBioAction
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
