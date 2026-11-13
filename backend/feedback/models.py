"""Pydantic models for persistent per-user video feedback."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FeedbackStateRequest(BaseModel):
    """Set the current Like/Unlike state for one video."""

    model_config = ConfigDict(extra="forbid")

    is_liked: bool


class FeedbackBatchStateRequest(BaseModel):
    """Retrieve feedback states for a bounded list of videos."""

    model_config = ConfigDict(extra="forbid")

    video_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("video_ids")
    @classmethod
    def validate_video_ids(cls, values):
        for video_id in values:
            if not video_id.strip():
                raise ValueError("Video IDs cannot be blank.")

            if video_id != video_id.strip():
                raise ValueError(
                    "Video IDs cannot contain surrounding whitespace."
                )

            if len(video_id) > 128:
                raise ValueError("Video IDs cannot exceed 128 characters.")

        return values

    @model_validator(mode="after")
    def validate_unique_video_ids(self):
        if len(self.video_ids) != len(set(self.video_ids)):
            raise ValueError("Duplicate video IDs are not allowed.")

        return self


class FeedbackStateResponse(BaseModel):
    video_id: str
    is_liked: bool
    has_feedback: bool


class FeedbackBatchStateResponse(BaseModel):
    states: list[FeedbackStateResponse]
