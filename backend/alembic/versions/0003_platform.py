"""add platform dimension

Revision ID: 0003_platform
Revises: 0002_multi_tenant
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_platform"
down_revision = "0002_multi_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("authors", "videos", "hot_rank_snapshots", "daily_reports"):
        op.add_column(table, sa.Column("platform", sa.String(length=32), nullable=False, server_default="douyin"))
        op.create_index(f"ix_{table}_platform", table, ["platform"], unique=False)

    op.add_column("videos", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.create_index("ix_videos_external_id", "videos", ["external_id"], unique=False)
    op.execute("UPDATE videos SET external_id = douyin_video_id WHERE external_id IS NULL AND douyin_video_id IS NOT NULL")

    op.drop_constraint("uq_authors_tenant_douyin_user_id", "authors", type_="unique")
    op.create_index(
        "uq_authors_tenant_platform_user",
        "authors",
        ["tenant_id", "platform", "douyin_user_id"],
        unique=True,
    )

    op.drop_constraint("uq_videos_tenant_douyin_video_id", "videos", type_="unique")
    op.create_index(
        "uq_videos_tenant_platform_video",
        "videos",
        ["tenant_id", "platform", "douyin_video_id"],
        unique=True,
    )

    op.drop_constraint("uq_tenant_snapshot_date_rank", "hot_rank_snapshots", type_="unique")
    op.drop_constraint("uq_tenant_snapshot_date_video", "hot_rank_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_tenant_platform_snapshot_rank",
        "hot_rank_snapshots",
        ["tenant_id", "platform", "snapshot_date", "rank"],
    )
    op.create_unique_constraint(
        "uq_tenant_platform_snapshot_video",
        "hot_rank_snapshots",
        ["tenant_id", "platform", "snapshot_date", "video_id"],
    )

    op.drop_index("uq_daily_reports_tenant_report_date", table_name="daily_reports")
    op.create_index(
        "uq_daily_reports_tenant_platform_date",
        "daily_reports",
        ["tenant_id", "platform", "report_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_daily_reports_tenant_platform_date", table_name="daily_reports")
    op.create_index("uq_daily_reports_tenant_report_date", "daily_reports", ["tenant_id", "report_date"], unique=True)

    op.drop_constraint("uq_tenant_platform_snapshot_video", "hot_rank_snapshots", type_="unique")
    op.drop_constraint("uq_tenant_platform_snapshot_rank", "hot_rank_snapshots", type_="unique")
    op.create_unique_constraint("uq_tenant_snapshot_date_rank", "hot_rank_snapshots", ["tenant_id", "snapshot_date", "rank"])
    op.create_unique_constraint("uq_tenant_snapshot_date_video", "hot_rank_snapshots", ["tenant_id", "snapshot_date", "video_id"])

    op.drop_index("uq_videos_tenant_platform_video", table_name="videos")
    op.create_index("uq_videos_tenant_douyin_video_id", "videos", ["tenant_id", "douyin_video_id"], unique=True)

    op.drop_index("uq_authors_tenant_platform_user", table_name="authors")
    op.create_index("uq_authors_tenant_douyin_user_id", "authors", ["tenant_id", "douyin_user_id"], unique=True)

    op.drop_index("ix_videos_external_id", table_name="videos")
    op.drop_column("videos", "external_id")

    for table in ("daily_reports", "hot_rank_snapshots", "videos", "authors"):
        op.drop_index(f"ix_{table}_platform", table_name=table)
        op.drop_column(table, "platform")
