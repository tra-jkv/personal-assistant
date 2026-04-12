"""
Sync State Manager

Manages incremental syncing by tracking last sync time for each source
"""

from datetime import datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from backend.models import SyncState

# Default start date for first-time sync (January 1, 2026)
DEFAULT_SYNC_START = datetime(2026, 1, 1, 0, 0, 0)


class SyncManager:
    """Manages sync state for incremental syncing"""

    def __init__(self, db: Session):
        self.db = db

    def get_last_sync_time(self, source: str) -> Optional[datetime]:
        """
        Get the last successful sync time for a source

        Args:
            source: 'github' or 'jira'

        Returns:
            DateTime of last successful sync, or None if never synced successfully

        Note:
            Returns last_sync_at even if most recent attempt failed, because
            last_sync_at is only updated on successful syncs (see update_sync_state).
            If there's a state record, it means at least one successful sync occurred.
        """
        state = self.db.query(SyncState).filter(SyncState.source == source).first()

        if state:
            # last_sync_at represents the last SUCCESSFUL sync time
            # because we only update it on success (see update_sync_state)
            return state.last_sync_at

        return None

    def get_sync_since_time(self, source: str, fallback_days: int = None) -> datetime:
        """
        Get the time to sync from (incremental)

        Args:
            source: 'github' or 'jira'
            fallback_days: Deprecated, ignored. Uses DEFAULT_SYNC_START instead.

        Returns:
            DateTime to fetch from
        """
        last_sync = self.get_last_sync_time(source)

        if last_sync:
            # Sync from last successful sync
            return last_sync
        else:
            # First time sync - fetch from default start date (Jan 1, 2026)
            return DEFAULT_SYNC_START

    def update_sync_state(self, source: str, success: bool = True, error: str = "") -> None:
        """
        Update sync state after a sync attempt

        Args:
            source: 'github' or 'jira'
            success: Whether sync was successful
            error: Error message if failed

        Note:
            On successful sync: Updates last_sync_at to current time
            On failed sync: Preserves last_sync_at from previous successful sync
                           (so next sync retries from last known good state)
        """
        state = self.db.query(SyncState).filter(SyncState.source == source).first()

        if state:
            # Update existing state
            # Only update last_sync_at on successful sync
            if success:
                state.last_sync_at = datetime.utcnow()
            state.last_sync_success = success
            state.last_sync_error = error
            state.total_syncs += 1
            state.updated_at = datetime.utcnow()
        else:
            # Create new state
            # For first sync, set last_sync_at regardless of success/failure
            state = SyncState(
                source=source,
                last_sync_at=datetime.utcnow(),
                last_sync_success=success,
                last_sync_error=error,
                total_syncs=1,
            )
            self.db.add(state)

        self.db.commit()

    def get_sync_info(self, source: str) -> Dict:
        """
        Get sync information for display

        Args:
            source: 'github' or 'jira'

        Returns:
            {
                "last_sync": "2026-04-11 14:30:00",
                "success": True,
                "error": "",
                "total_syncs": 42,
                "time_ago": "2 hours ago"
            }
        """
        state = self.db.query(SyncState).filter(SyncState.source == source).first()

        if not state:
            return {
                "last_sync": None,
                "success": None,
                "error": "",
                "total_syncs": 0,
                "time_ago": "Never",
                "status": "Never synced",
            }

        # Calculate time ago
        now = datetime.utcnow()
        diff = now - state.last_sync_at

        if diff.days > 0:
            time_ago = f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        elif diff.seconds >= 3600:
            hours = diff.seconds // 3600
            time_ago = f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.seconds >= 60:
            minutes = diff.seconds // 60
            time_ago = f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            time_ago = "Just now"

        # Status message
        if state.last_sync_success:
            status = f"✅ Synced {time_ago}"
        else:
            status = f"❌ Failed {time_ago}"

        return {
            "last_sync": state.last_sync_at.strftime("%Y-%m-%d %H:%M:%S"),
            "success": state.last_sync_success,
            "error": state.last_sync_error,
            "total_syncs": state.total_syncs,
            "time_ago": time_ago,
            "status": status,
        }

    def reset_sync_state(self, source: str) -> None:
        """
        Reset sync state (force full sync next time)

        Args:
            source: 'github' or 'jira'
        """
        state = self.db.query(SyncState).filter(SyncState.source == source).first()

        if state:
            self.db.delete(state)
            self.db.commit()
