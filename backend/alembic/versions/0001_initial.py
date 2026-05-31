"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("douyin_user_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_authors_douyin_user_id", "authors", ["douyin_user_id"], unique=True)
    op.create_index("ix_authors_name", "authors", ["name"], unique=False)

    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("douyin_video_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("authors.id"), nullable=True),
        sa.Column("video_url", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publish_time", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=True),
    )
    op.create_index("ix_videos_douyin_video_id", "videos", ["douyin_video_id"], unique=True)
    op.create_index("ix_videos_author_id", "videos", ["author_id"], unique=False)

    op.create_table(
        "hot_rank_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("score", sa.Numeric(18, 6), nullable=True),
        sa.Column("rank_change", sa.Integer(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("snapshot_date", "rank", name="uq_snapshot_date_rank"),
        sa.UniqueConstraint("snapshot_date", "video_id", name="uq_snapshot_date_video"),
    )
    op.create_index("ix_hot_rank_snapshots_snapshot_date", "hot_rank_snapshots", ["snapshot_date"], unique=False)
    op.create_index("ix_hot_rank_snapshots_rank", "hot_rank_snapshots", ["rank"], unique=False)
    op.create_index("ix_hot_rank_snapshots_video_id", "hot_rank_snapshots", ["video_id"], unique=False)

    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_daily_reports_report_date", "daily_reports", ["report_date"], unique=True)


def downgrade() -> None:
    op.drop_table("daily_reports")
    op.drop_table("hot_rank_snapshots")
    op.drop_table("videos")
    op.drop_table("authors")

