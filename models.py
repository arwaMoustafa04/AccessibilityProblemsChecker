"""Response models matching the pod's OpenAPI contract."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Classification(str, Enum):
    AUTO_FIXABLE = "auto_fixable"
    HUMAN_REVIEW = "human_review"


class WcagLevel(str, Enum):
    A = "A"
    AA = "AA"


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["ok"]
    spec_version: str = Field(alias="specVersion")


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    check_id: str = Field(alias="checkId")
    name: str
    wcag_criterion: str = Field(alias="wcagCriterion")
    wcag_level: WcagLevel = Field(alias="wcagLevel")
    classification: Classification

