"""multi tenant

Revision ID: 0002_multi_tenant
Revises: 0001_initial
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_multi_tenant"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("authors", sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"))
    op.add_column("videos", sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"))
    op.add_column(
        "hot_rank_snapshots",
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
    )
    op.add_column("daily_reports", sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"))

    op.create_index("ix_authors_tenant_id", "authors", ["tenant_id"], unique=False)
    op.create_index("ix_videos_tenant_id", "videos", ["tenant_id"], unique=False)
    op.create_index("ix_hot_rank_snapshots_tenant_id", "hot_rank_snapshots", ["tenant_id"], unique=False)
    op.create_index("ix_daily_reports_tenant_id", "daily_reports", ["tenant_id"], unique=False)

    op.drop_index("ix_authors_douyin_user_id", table_name="authors")
    op.create_index("ix_authors_douyin_user_id", "authors", ["douyin_user_id"], unique=False)
    op.create_index("uq_authors_tenant_douyin_user_id", "authors", ["tenant_id", "douyin_user_id"], unique=True)

    op.drop_index("ix_videos_douyin_video_id", table_name="videos")
    op.create_index("ix_videos_douyin_video_id", "videos", ["douyin_video_id"], unique=False)
    op.create_index("uq_videos_tenant_douyin_video_id", "videos", ["tenant_id", "douyin_video_id"], unique=True)

    op.drop_constraint("uq_snapshot_date_rank", "hot_rank_snapshots", type_="unique")
    op.drop_constraint("uq_snapshot_date_video", "hot_rank_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_tenant_snapshot_date_rank",
        "hot_rank_snapshots",
        ["tenant_id", "snapshot_date", "rank"],
    )
    op.create_unique_constraint(
        "uq_tenant_snapshot_date_video",
        "hot_rank_snapshots",
        ["tenant_id", "snapshot_date", "video_id"],
    )

    op.drop_index("ix_daily_reports_report_date", table_name="daily_reports")
    op.create_index("ix_daily_reports_report_date", "daily_reports", ["report_date"], unique=False)
    op.create_index("uq_daily_reports_tenant_report_date", "daily_reports", ["tenant_id", "report_date"], unique=True)

    op.create_table(
        "tenant_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("key_hash", name="uq_tenant_api_keys_key_hash"),
    )
    op.create_index("ix_tenant_api_keys_tenant_id", "tenant_api_keys", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_table("tenant_api_keys")

    op.drop_index("uq_daily_reports_tenant_report_date", table_name="daily_reports")
    op.drop_index("ix_daily_reports_report_date", table_name="daily_reports")
    op.create_index("ix_daily_reports_report_date", "daily_reports", ["report_date"], unique=True)

    op.drop_constraint("uq_tenant_snapshot_date_video", "hot_rank_snapshots", type_="unique")
    op.drop_constraint("uq_tenant_snapshot_date_rank", "hot_rank_snapshots", type_="unique")
    op.create_unique_constraint("uq_snapshot_date_rank", "hot_rank_snapshots", ["snapshot_date", "rank"])
    op.create_unique_constraint("uq_snapshot_date_video", "hot_rank_snapshots", ["snapshot_date", "video_id"])

    op.drop_index("uq_videos_tenant_douyin_video_id", table_name="videos")
    op.drop_index("ix_videos_douyin_video_id", table_name="videos")
    op.create_index("ix_videos_douyin_video_id", "videos", ["douyin_video_id"], unique=True)

    op.drop_index("uq_authors_tenant_douyin_user_id", table_name="authors")
    op.drop_index("ix_authors_douyin_user_id", table_name="authors")
    op.create_index("ix_authors_douyin_user_id", "authors", ["douyin_user_id"], unique=True)

    op.drop_index("ix_daily_reports_tenant_id", table_name="daily_reports")
    op.drop_index("ix_hot_rank_snapshots_tenant_id", table_name="hot_rank_snapshots")
    op.drop_index("ix_videos_tenant_id", table_name="videos")
    op.drop_index("ix_authors_tenant_id", table_name="authors")

    op.drop_column("daily_reports", "tenant_id")
    op.drop_column("hot_rank_snapshots", "tenant_id")
    op.drop_column("videos", "tenant_id")
    op.drop_column("authors", "tenant_id")
