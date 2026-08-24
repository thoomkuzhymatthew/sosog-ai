"""Client-facing reporting taxonomy for internal promotion actions."""

from __future__ import annotations

from .contracts import PromotionAction


_CLIENT_CATEGORY_BY_ACTION = {
    PromotionAction.FULL_CRYSTALLIZE: "FULLY_CRYSTALLIZABLE",
    PromotionAction.RESPONSE_CRYSTALLIZE: "FULLY_CRYSTALLIZABLE",
    PromotionAction.DECOMPOSE: "DECOMPOSABLE",
    PromotionAction.LIFT: "FULLY_AGENTIC",
    PromotionAction.RETAIN: "FULLY_AGENTIC",
    PromotionAction.DROP: "INSUFFICIENT_EVIDENCE",
}


def client_category_for(action: PromotionAction | str) -> str:
    """Return the reporting category for an internal promotion action.

    ``FULLY_MANUAL`` is intentionally absent: it comes from the separate
    client-declared manual-task registry, never from classifier output.
    """

    return _CLIENT_CATEGORY_BY_ACTION[PromotionAction(action)]
