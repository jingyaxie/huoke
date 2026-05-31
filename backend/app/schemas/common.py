from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ORMBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str


class DateRangeQuery(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


class PaginationQuery(BaseModel):
    page: int = 1
    page_size: int = 20

