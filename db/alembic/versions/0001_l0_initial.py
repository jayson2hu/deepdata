"""l0 initial schema

Revision ID: 0001_l0_initial
Revises:
Create Date: 2026-05-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_l0_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=True, unique=True),
        sa.Column("home_url", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("crawl_config", sa.JSON(), nullable=False),
        sa.Column("etiquette", sa.JSON(), nullable=False),
        sa.Column("vertical_codes", sa.JSON(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "source_health",
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), primary_key=True),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("empty_streak", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "raw_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("crawl_job_id", sa.Integer(), sa.ForeignKey("crawl_jobs.id"), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fetch_method", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("http_headers", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("raw_entry", sa.JSON(), nullable=True),
        sa.Column("raw_html_ref", sa.Text(), nullable=True),
        sa.Column("raw_html_sha256", sa.String(length=64), nullable=True),
        sa.Column("media_refs", sa.JSON(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
    )
    op.create_index("ix_raw_documents_source_fetched", "raw_documents", ["source_id", "fetched_at"])
    op.create_index("ix_raw_documents_raw_html_sha256", "raw_documents", ["raw_html_sha256"])
    op.create_table(
        "content_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=40), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("simhash", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("clean_text_ref", sa.Text(), nullable=True),
        sa.Column("lang", sa.String(length=16), nullable=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column(
            "raw_document_id",
            sa.Integer(),
            sa.ForeignKey("raw_documents.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_content_items_status_fetched", "content_items", ["status", "fetched_at"])
    op.create_index(
        "ix_content_items_source_published",
        "content_items",
        ["source_id", "published_at"],
    )
    op.create_index("ix_content_items_content_hash", "content_items", ["content_hash"])
    op.create_table(
        "content_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("content_items.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "raw_document_id",
            sa.Integer(),
            sa.ForeignKey("raw_documents.id"),
            nullable=True,
        ),
        sa.Column("clean_text_ref", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("content_id", "version"),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_unpublished", "outbox_events", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("content_versions")
    op.drop_index("ix_content_items_content_hash", table_name="content_items")
    op.drop_index("ix_content_items_source_published", table_name="content_items")
    op.drop_index("ix_content_items_status_fetched", table_name="content_items")
    op.drop_table("content_items")
    op.drop_index("ix_raw_documents_raw_html_sha256", table_name="raw_documents")
    op.drop_index("ix_raw_documents_source_fetched", table_name="raw_documents")
    op.drop_table("raw_documents")
    op.drop_table("crawl_jobs")
    op.drop_table("source_health")
    op.drop_table("sources")
