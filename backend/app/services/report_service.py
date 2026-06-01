from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import Template
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.report_repository import ReportRepository
from app.repositories.snapshot_repository import SnapshotRepository
from app.repositories.video_repository import VideoRepository
from app.services.ai_client import AIClientFactory
from app.services.pdf_service import PdfService


REPORT_TEMPLATE = Template(
    """
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; margin: 32px; color: #111827; }
        h1, h2, h3 { margin: 0 0 12px; }
        .meta { color: #6b7280; margin-bottom: 24px; }
        table { width: 100%; border-collapse: collapse; margin: 16px 0 28px; }
        th, td { border-bottom: 1px solid #e5e7eb; padding: 10px 8px; text-align: left; font-size: 13px; }
        th { background: #f9fafb; }
        .section { margin-bottom: 28px; }
        .summary { padding: 14px 16px; background: #f8fafc; border-left: 4px solid #2563eb; }
      </style>
    </head>
    <body>
      <h1>{{ title }}</h1>
      <div class="meta">{{ report_date }} | {{ provider }}{{ " / " + model if model else "" }}</div>
      <div class="summary">{{ summary }}</div>
      <div class="section">{{ content | safe }}</div>
    </body>
    </html>
    """
)


class ReportService:
    def __init__(self, session: Session, tenant_id: str = "default", platform: str | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = get_settings()
        self.platform = platform or self.settings.default_platform
        self.report_repo = ReportRepository(session, tenant_id, self.platform)
        self.video_repo = VideoRepository(session, tenant_id, self.platform)
        self.snapshot_repo = SnapshotRepository(session, tenant_id, self.platform)
        self.ai_factory = AIClientFactory(self.settings)
        self.pdf_service = PdfService()

    def _build_prompt(self, report_date: date) -> str:
        hot_videos = self.video_repo.list_hot(limit=10)
        lines = [f"请基于以下抖音热点数据生成 {report_date} 的热点日报，输出中文 Markdown。"]
        for idx, video in enumerate(hot_videos, start=1):
            lines.append(
                f"{idx}. {video.title} | 作者:{video.author.name if video.author else '未知'} | "
                f"点赞:{video.like_count} 评论:{video.comment_count} 分享:{video.share_count}"
            )
        lines.append("请包含：今日概览、热点视频、热点作者、趋势观察、行动建议。")
        return "\n".join(lines)

    async def generate_markdown(self, report_date: date, provider: str = "template") -> tuple[str, str, str | None, str | None]:
        model = None
        summary = None
        prompt = self._build_prompt(report_date)
        client = None
        if provider == "deepseek":
            client = self.ai_factory.deepseek()
            model = self.settings.deepseek_model
        elif provider == "openai":
            client = self.ai_factory.openai()
            model = self.settings.openai_model

        if client is not None:
            completion = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是资深数据分析师，擅长热点分析与日报写作。"},
                    {"role": "user", "content": prompt},
                ],
            )
            markdown = completion.choices[0].message.content or ""
            summary = markdown.splitlines()[0][:200] if markdown else None
        else:
            hot_videos = self.video_repo.list_hot(limit=10)
            rows = "\n".join(
                [
                    f"- {i}. {video.title} / {video.author.name if video.author else '未知'} / "
                    f"赞{video.like_count} 评{video.comment_count} 转{video.share_count}"
                    for i, video in enumerate(hot_videos, start=1)
                ]
            )
            markdown = (
                f"# {report_date} 抖音热点日报\n\n"
                f"## 今日概览\n"
                f"本日报自动汇总当前热榜数据，呈现视频与作者的热度变化。\n\n"
                f"## 热点视频\n{rows or '- 暂无数据'}\n\n"
                f"## 趋势观察\n"
                f"- 建议关注排名变化明显的视频。\n"
                f"- 建议对比作者的持续入榜表现。\n"
            )
            summary = "基于当前热榜数据生成的模板日报。"
        title = f"{report_date} 抖音热点日报"
        return title, markdown, summary, model

    def build_html(self, title: str, markdown: str, summary: str | None, provider: str, model: str | None, report_date: date) -> str:
        content = markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        return REPORT_TEMPLATE.render(
            title=title,
            summary=summary or "",
            content=content,
            provider=provider,
            model=model,
            report_date=report_date.isoformat(),
        )

    async def generate_report(self, report_date: date, provider: str = "template") -> tuple[str, str | None]:
        title, markdown, summary, model = await self.generate_markdown(report_date, provider=provider)
        html = self.build_html(title, markdown, summary, provider, model, report_date)
        pdf_path = (
            self.settings.report_output_dir
            / f"hot_report_{self.platform}_{self.tenant_id}_{report_date.isoformat()}.pdf"
        )
        await self.pdf_service.html_to_pdf(html, pdf_path)
        repo = self.report_repo
        report = repo.upsert(
            report_date=report_date,
            provider=provider,
            model=model,
            title=title,
            summary=summary,
            content_markdown=markdown,
            content_html=html,
            pdf_path=str(pdf_path),
        )
        self.session.commit()
        return report.title, report.pdf_path
