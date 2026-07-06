"""add mandatory link and schedule columns to planned_courses

Revision ID: f521ae56b36c
Revises: 2c6b35423949
Create Date: 2026-07-06 01:03:07.629274

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f521ae56b36c'
down_revision: Union[str, None] = '2c6b35423949'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also proposed dropping sessions/events/user_states/
    # app_states/adk_internal_metadata — those are ADK's DatabaseSessionService
    # tables (uniguide/chat.py, api/routers/chat.py), which share this sqlite
    # file but aren't part of our own Base.metadata. Dropping them would wipe
    # every persisted chat conversation, so those commands were removed here.
    op.add_column('planned_courses', sa.Column('mandatory', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('planned_courses', sa.Column('link', sa.String(), nullable=False, server_default=''))
    op.add_column('planned_courses', sa.Column('day_of_week', sa.String(), nullable=True))
    op.add_column('planned_courses', sa.Column('start_time', sa.String(), nullable=True))
    op.add_column('planned_courses', sa.Column('end_time', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('planned_courses', 'end_time')
    op.drop_column('planned_courses', 'start_time')
    op.drop_column('planned_courses', 'day_of_week')
    op.drop_column('planned_courses', 'link')
    op.drop_column('planned_courses', 'mandatory')
