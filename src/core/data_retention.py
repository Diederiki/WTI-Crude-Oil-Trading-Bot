"""Data retention and archival management.

Handles automated data retention policies, archival, and purging
for compliance with data protection regulations.
"""

import gzip
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.core.database import get_db_session
from src.core.logging_config import get_logger

logger = get_logger("data_retention")


class RetentionPolicy:
    """Data retention policy configuration."""
    
    def __init__(
        self,
        table_name: str,
        retention_days: int,
        archive_before_delete: bool = True,
        archive_path: str | None = None,
        partition_key: str | None = None,
    ):
        """Initialize retention policy.
        
        Args:
            table_name: Database table name
            retention_days: Days to retain data
            archive_before_delete: Whether to archive before deletion
            archive_path: Path for archived data
            partition_key: Column to use for partitioning
        """
        self.table_name = table_name
        self.retention_days = retention_days
        self.archive_before_delete = archive_before_delete
        self.archive_path = archive_path or "/data/archives"
        self.partition_key = partition_key or "created_at"


class DataRetentionManager:
    """Manages data retention and archival."""
    
    DEFAULT_POLICIES = [
        RetentionPolicy("market_ticks", retention_days=7, archive_before_delete=True),
        RetentionPolicy("market_bars_1m", retention_days=90, archive_before_delete=True),
        RetentionPolicy("market_bars_5m", retention_days=180, archive_before_delete=True),
        RetentionPolicy("market_bars_1h", retention_days=365, archive_before_delete=True),
        RetentionPolicy("market_bars_1d", retention_days=1825, archive_before_delete=True),  # 5 years
        RetentionPolicy("signals", retention_days=365, archive_before_delete=True),
        RetentionPolicy("orders", retention_days=2555, archive_before_delete=True),  # 7 years
        RetentionPolicy("order_fills", retention_days=2555, archive_before_delete=True),
        RetentionPolicy("positions", retention_days=2555, archive_before_delete=True),
        RetentionPolicy("audit_log", retention_days=2555, archive_before_delete=True),
        RetentionPolicy("system_events", retention_days=90, archive_before_delete=False),
    ]
    
    def __init__(self, policies: list[RetentionPolicy] | None = None):
        """Initialize retention manager.
        
        Args:
            policies: List of retention policies
        """
        self.policies = policies or self.DEFAULT_POLICIES
        self._running = False
    
    async def enforce_all_policies(self) -> dict[str, Any]:
        """Enforce all retention policies.
        
        Returns:
            Summary of enforcement actions
        """
        results = {
            "started_at": datetime.utcnow().isoformat(),
            "policies_processed": 0,
            "records_archived": 0,
            "records_deleted": 0,
            "errors": [],
        }
        
        for policy in self.policies:
            try:
                result = await self.enforce_policy(policy)
                results["policies_processed"] += 1
                results["records_archived"] += result.get("archived", 0)
                results["records_deleted"] += result.get("deleted", 0)
            except Exception as e:
                error_msg = f"Policy {policy.table_name}: {str(e)}"
                logger.error("Retention policy enforcement failed", error=error_msg)
                results["errors"].append(error_msg)
        
        results["completed_at"] = datetime.utcnow().isoformat()
        
        logger.info(
            "Retention policy enforcement completed",
            policies=results["policies_processed"],
            archived=results["records_archived"],
            deleted=results["records_deleted"],
        )
        
        return results
    
    async def enforce_policy(self, policy: RetentionPolicy) -> dict[str, Any]:
        """Enforce a single retention policy.
        
        Args:
            policy: Retention policy to enforce
            
        Returns:
            Enforcement result
        """
        cutoff_date = datetime.utcnow() - timedelta(days=policy.retention_days)
        
        logger.info(
            "Enforcing retention policy",
            table=policy.table_name,
            cutoff=cutoff_date.isoformat(),
            retention_days=policy.retention_days,
        )
        
        result = {
            "table": policy.table_name,
            "cutoff_date": cutoff_date.isoformat(),
            "archived": 0,
            "deleted": 0,
        }
        
        async with get_db_session() as session:
            # Count records to be deleted
            count_query = text(f"""
                SELECT COUNT(*) FROM {policy.table_name}
                WHERE {policy.partition_key} < :cutoff
            """)
            count_result = await session.execute(
                count_query, {"cutoff": cutoff_date}
            )
            records_to_process = count_result.scalar() or 0
            
            if records_to_process == 0:
                logger.info(
                    "No records to process",
                    table=policy.table_name,
                )
                return result
            
            logger.info(
                "Processing records for retention",
                table=policy.table_name,
                count=records_to_process,
            )
            
            # Archive if enabled
            if policy.archive_before_delete:
                archived = await self._archive_records(
                    session, policy, cutoff_date, records_to_process
                )
                result["archived"] = archived
            
            # Delete records
            deleted = await self._delete_records(session, policy, cutoff_date)
            result["deleted"] = deleted
        
        return result
    
    async def _archive_records(
        self,
        session,
        policy: RetentionPolicy,
        cutoff_date: datetime,
        batch_size: int = 10000,
    ) -> int:
        """Archive records before deletion.
        
        Args:
            session: Database session
            policy: Retention policy
            cutoff_date: Cutoff date for records
            batch_size: Batch size for archiving
            
        Returns:
            Number of records archived
        """
        # Create archive directory
        archive_dir = Path(policy.archive_path) / policy.table_name
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Archive filename with date range
        archive_file = archive_dir / f"{policy.table_name}_{cutoff_date.strftime('%Y%m%d')}.json.gz"
        
        archived_count = 0
        
        try:
            with gzip.open(archive_file, "wt", encoding="utf-8") as f:
                # Write records in batches
                offset = 0
                while True:
                    query = text(f"""
                        SELECT * FROM {policy.table_name}
                        WHERE {policy.partition_key} < :cutoff
                        ORDER BY {policy.partition_key}
                        LIMIT :limit OFFSET :offset
                    """)
                    
                    batch = await session.execute(
                        query,
                        {
                            "cutoff": cutoff_date,
                            "limit": batch_size,
                            "offset": offset,
                        },
                    )
                    
                    rows = batch.mappings().all()
                    if not rows:
                        break
                    
                    for row in rows:
                        record = dict(row)
                        # Convert datetime objects to ISO format
                        for key, value in record.items():
                            if isinstance(value, datetime):
                                record[key] = value.isoformat()
                        
                        f.write(json.dumps(record, default=str) + "\n")
                        archived_count += 1
                    
                    offset += batch_size
                    
                    if archived_count % 100000 == 0:
                        logger.info(
                            "Archiving progress",
                            table=policy.table_name,
                            archived=archived_count,
                        )
            
            logger.info(
                "Archive created",
                table=policy.table_name,
                file=str(archive_file),
                records=archived_count,
            )
            
        except Exception as e:
            logger.error(
                "Archive creation failed",
                table=policy.table_name,
                error=str(e),
            )
            # Remove partial archive
            if archive_file.exists():
                archive_file.unlink()
            raise
        
        return archived_count
    
    async def _delete_records(
        self,
        session,
        policy: RetentionPolicy,
        cutoff_date: datetime,
    ) -> int:
        """Delete records older than cutoff.
        
        Args:
            session: Database session
            policy: Retention policy
            cutoff_date: Cutoff date
            
        Returns:
            Number of records deleted
        """
        delete_query = text(f"""
            DELETE FROM {policy.table_name}
            WHERE {policy.partition_key} < :cutoff
        """)
        
        result = await session.execute(delete_query, {"cutoff": cutoff_date})
        await session.commit()
        
        deleted = result.rowcount or 0
        
        logger.info(
            "Records deleted",
            table=policy.table_name,
            deleted=deleted,
        )
        
        return deleted
    
    async def restore_from_archive(
        self,
        table_name: str,
        archive_file: str,
    ) -> dict[str, Any]:
        """Restore data from archive.
        
        Args:
            table_name: Table to restore to
            archive_file: Path to archive file
            
        Returns:
            Restoration result
        """
        result = {
            "table": table_name,
            "archive_file": archive_file,
            "restored": 0,
            "errors": [],
        }
        
        archive_path = Path(archive_file)
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive file not found: {archive_file}")
        
        logger.info(
            "Restoring from archive",
            table=table_name,
            file=archive_file,
        )
        
        try:
            with gzip.open(archive_path, "rt", encoding="utf-8") as f:
                async with get_db_session() as session:
                    for line in f:
                        try:
                            record = json.loads(line)
                            
                            # Build insert query
                            columns = ", ".join(record.keys())
                            placeholders = ", ".join(f":{k}" for k in record.keys())
                            
                            query = text(f"""
                                INSERT INTO {table_name} ({columns})
                                VALUES ({placeholders})
                                ON CONFLICT DO NOTHING
                            """)
                            
                            await session.execute(query, record)
                            result["restored"] += 1
                            
                            # Commit every 1000 records
                            if result["restored"] % 1000 == 0:
                                await session.commit()
                                logger.info(
                                    "Restore progress",
                                    table=table_name,
                                    restored=result["restored"],
                                )
                        
                        except json.JSONDecodeError as e:
                            result["errors"].append(f"Invalid JSON: {e}")
                        except Exception as e:
                            result["errors"].append(str(e))
                    
                    await session.commit()
        
        except Exception as e:
            logger.error(
                "Restore failed",
                table=table_name,
                error=str(e),
            )
            raise
        
        logger.info(
            "Restore completed",
            table=table_name,
            restored=result["restored"],
            errors=len(result["errors"]),
        )
        
        return result
    
    async def list_archives(self, table_name: str | None = None) -> list[dict[str, Any]]:
        """List available archives.
        
        Args:
            table_name: Filter by table name
            
        Returns:
            List of archive information
        """
        archives = []
        
        base_path = Path("/data/archives")
        if not base_path.exists():
            return archives
        
        if table_name:
            paths = [base_path / table_name]
        else:
            paths = [p for p in base_path.iterdir() if p.is_dir()]
        
        for path in paths:
            if not path.exists():
                continue
            
            for archive_file in path.glob("*.json.gz"):
                stat = archive_file.stat()
                archives.append({
                    "table": path.name,
                    "file": str(archive_file),
                    "size_bytes": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        
        return sorted(archives, key=lambda x: x["modified"], reverse=True)
    
    async def cleanup_old_archives(
        self,
        max_age_days: int = 2555,  # 7 years
    ) -> dict[str, Any]:
        """Remove archives older than specified age.
        
        Args:
            max_age_days: Maximum archive age in days
            
        Returns:
            Cleanup result
        """
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        result = {
            "cutoff_date": cutoff.isoformat(),
            "deleted": [],
            "errors": [],
        }
        
        base_path = Path("/data/archives")
        if not base_path.exists():
            return result
        
        for table_dir in base_path.iterdir():
            if not table_dir.is_dir():
                continue
            
            for archive_file in table_dir.glob("*.json.gz"):
                try:
                    stat = archive_file.stat()
                    modified = datetime.fromtimestamp(stat.st_mtime)
                    
                    if modified < cutoff:
                        archive_file.unlink()
                        result["deleted"].append(str(archive_file))
                        logger.info(
                            "Old archive deleted",
                            file=str(archive_file),
                            age_days=(datetime.utcnow() - modified).days,
                        )
                
                except Exception as e:
                    result["errors"].append(f"{archive_file}: {e}")
        
        return result


class BackupManager:
    """Database backup management."""
    
    def __init__(self, backup_path: str = "/data/backups"):
        """Initialize backup manager.
        
        Args:
            backup_path: Path for backup storage
        """
        self.backup_path = Path(backup_path)
        self.backup_path.mkdir(parents=True, exist_ok=True)
    
    async def create_backup(self, database_url: str) -> dict[str, Any]:
        """Create database backup.
        
        Args:
            database_url: Database connection URL
            
        Returns:
            Backup result
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_path / f"wti_bot_backup_{timestamp}.sql.gz"
        
        logger.info("Starting database backup", file=str(backup_file))
        
        try:
            # Use pg_dump for PostgreSQL backup
            import subprocess
            
            # Parse database URL
            from urllib.parse import urlparse
            parsed = urlparse(database_url)
            
            env = os.environ.copy()
            if parsed.password:
                env["PGPASSWORD"] = parsed.password
            
            cmd = [
                "pg_dump",
                "-h", parsed.hostname or "localhost",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "postgres",
                "-d", parsed.path.lstrip("/"),
                "-F", "p",  # Plain text format
                "-v",
            ]
            
            with gzip.open(backup_file, "wb") as f:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
                
                while True:
                    chunk = process.stdout.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                
                stderr = process.stderr.read().decode()
                process.wait()
                
                if process.returncode != 0:
                    raise RuntimeError(f"pg_dump failed: {stderr}")
            
            file_size = backup_file.stat().st_size
            
            logger.info(
                "Backup completed",
                file=str(backup_file),
                size_bytes=file_size,
            )
            
            return {
                "success": True,
                "file": str(backup_file),
                "size_bytes": file_size,
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        except Exception as e:
            logger.error("Backup failed", error=str(e))
            if backup_file.exists():
                backup_file.unlink()
            raise
    
    async def restore_backup(self, backup_file: str, database_url: str) -> dict[str, Any]:
        """Restore database from backup.
        
        Args:
            backup_file: Path to backup file
            database_url: Database connection URL
            
        Returns:
            Restore result
        """
        backup_path = Path(backup_file)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_file}")
        
        logger.warning(
            "Starting database restore - this will overwrite existing data!",
            file=backup_file,
        )
        
        try:
            import subprocess
            from urllib.parse import urlparse
            
            parsed = urlparse(database_url)
            
            env = os.environ.copy()
            if parsed.password:
                env["PGPASSWORD"] = parsed.password
            
            cmd = [
                "psql",
                "-h", parsed.hostname or "localhost",
                "-p", str(parsed.port or 5432),
                "-U", parsed.username or "postgres",
                "-d", parsed.path.lstrip("/"),
                "-v",
                "ON_ERROR_STOP=1",
            ]
            
            with gzip.open(backup_path, "rb") as f:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
                
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    process.stdin.write(chunk)
                
                process.stdin.close()
                stderr = process.stderr.read().decode()
                process.wait()
                
                if process.returncode != 0:
                    raise RuntimeError(f"psql restore failed: {stderr}")
            
            logger.info("Restore completed", file=backup_file)
            
            return {
                "success": True,
                "file": backup_file,
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        except Exception as e:
            logger.error("Restore failed", error=str(e))
            raise
    
    async def list_backups(self) -> list[dict[str, Any]]:
        """List available backups.
        
        Returns:
            List of backup information
        """
        backups = []
        
        if not self.backup_path.exists():
            return backups
        
        for backup_file in self.backup_path.glob("*.sql.gz"):
            stat = backup_file.stat()
            backups.append({
                "file": str(backup_file),
                "name": backup_file.name,
                "size_bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            })
        
        return sorted(backups, key=lambda x: x["created"], reverse=True)
    
    async def cleanup_old_backups(self, keep_count: int = 10) -> dict[str, Any]:
        """Keep only specified number of recent backups.
        
        Args:
            keep_count: Number of backups to keep
            
        Returns:
            Cleanup result
        """
        backups = await self.list_backups()
        result = {"deleted": [], "kept": []}
        
        for i, backup in enumerate(backups):
            if i < keep_count:
                result["kept"].append(backup["file"])
            else:
                try:
                    Path(backup["file"]).unlink()
                    result["deleted"].append(backup["file"])
                    logger.info("Old backup deleted", file=backup["file"])
                except Exception as e:
                    logger.error(
                        "Failed to delete backup",
                        file=backup["file"],
                        error=str(e),
                    )
        
        return result
