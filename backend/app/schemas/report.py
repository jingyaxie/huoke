from datetime import date, datetime

from app.schemas.common import ORMBaseModel


class DailyReportOut(ORMBaseModel):
    id: int
    report_date: date
    provider: str
    model: str | None
    title: str
    summary: str | None
    content_markdown: str
    content_html: str | None
    pdf_path: str | None
    created_at: datetime

