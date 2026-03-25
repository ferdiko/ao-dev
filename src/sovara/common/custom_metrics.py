import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, field_validator, model_validator


METRIC_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

MetricKind = Literal["bool", "int", "float"]
MetricValue = StrictBool | StrictInt | FiniteFloat


def get_metric_kind(value: bool | int | float) -> MetricKind:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    raise TypeError(f"Unsupported metric value type: {type(value).__name__}")


class MetricsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: dict[str, MetricValue]

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, metrics: dict[str, MetricValue]) -> dict[str, MetricValue]:
        if not metrics:
            raise ValueError("log() requires at least one metric.")

        for key in metrics:
            if not METRIC_KEY_PATTERN.fullmatch(key):
                raise ValueError(
                    f"Invalid metric key '{key}'. Metric keys must be lower_snake_case and at most 32 characters."
                )
        return metrics


class BoolMetricFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["bool"]
    values: list[StrictBool]

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: list[bool]) -> list[bool]:
        if not values:
            raise ValueError("Boolean metric filters must specify at least one value.")
        return values


class NumberMetricFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["int", "float"]
    min: StrictInt | FiniteFloat | None = None
    max: StrictInt | FiniteFloat | None = None

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.min is None and self.max is None:
            raise ValueError("Numeric metric filters must specify min or max.")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("Metric filter min cannot be greater than max.")
        return self


MetricFilter = Annotated[BoolMetricFilter | NumberMetricFilter, Field(discriminator="kind")]


class MetricColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    kind: MetricKind
    min: int | float | None = None
    max: int | float | None = None
    values: list[bool] | None = None
