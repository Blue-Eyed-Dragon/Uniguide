"""add calendar_event_records table

Revision ID: 9c9cf84f986d
Revises: f521ae56b36c
Create Date: 2026-07-06 14:47:20.331304

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c9cf84f986d'
down_revision: Union[str, None] = 'f521ae56b36c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also proposed dropping sessions/events/user_states/
    # app_states/adk_internal_metadata — those are ADK's DatabaseSessionService
    # tables, which share this sqlite file but aren't part of our own
    # Base.metadata. Dropping them would wipe every persisted chat
    # conversation, so those commands were removed here (see f521ae56b36c).
    op.create_table(
        'calendar_event_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.String(), nullable=False),
        sa.Column('course_id', sa.String(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('calendar_event_id', sa.String(), nullable=False),
        sa.Column('start_date', sa.String(), nullable=False),
        sa.Column('end_date', sa.String(), nullable=False),
        sa.Column('day_of_week', sa.String(), nullable=True),
        sa.Column('start_time', sa.String(), nullable=True),
        sa.Column('end_time', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['student_profiles.student_id']),
        sa.ForeignKeyConstraint(['plan_id'], ['semester_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'course_id', name='uq_calendar_record_student_course'),
    )


def downgrade() -> None:
    op.drop_table('calendar_event_records')
