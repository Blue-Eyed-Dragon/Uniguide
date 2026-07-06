"""add start_year and start_season to student_profiles

Revision ID: a9db8ff3c0fe
Revises: 9c9cf84f986d
Create Date: 2026-07-07 00:24:34.256548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9db8ff3c0fe'
down_revision: Union[str, None] = '9c9cf84f986d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also proposed dropping sessions/events/user_states/
    # app_states/adk_internal_metadata — those are ADK's DatabaseSessionService
    # tables, which share this sqlite file but aren't part of our own
    # Base.metadata. Dropping them would wipe every persisted chat
    # conversation, so those commands were removed here (see f521ae56b36c).
    #
    # server_default matches StudentProfileORM's Python-side defaults, so
    # existing rows (created before per-student start_year/start_season
    # existed) backfill to what every date computation implicitly assumed
    # up to now, rather than failing on a NOT NULL column with no default.
    op.add_column(
        'student_profiles',
        sa.Column('start_year', sa.Integer(), nullable=False, server_default='2024'),
    )
    op.add_column(
        'student_profiles',
        sa.Column('start_season', sa.String(), nullable=False, server_default='winter'),
    )


def downgrade() -> None:
    op.drop_column('student_profiles', 'start_season')
    op.drop_column('student_profiles', 'start_year')
